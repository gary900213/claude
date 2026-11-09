import io
import zipfile

import numpy as np
import pandas as pd

from quant import backtest as bt
from quant.history import KLINE_COLS, read_csv_from_zip
from quant.strategies import trend_signal


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", text)
    return buf.getvalue()


def test_read_zip_with_and_without_header():
    row = "1577836800000,1,2,0.5,1.5,10,1577840399999,15,3,4,6,0"
    a = read_csv_from_zip(_zip(row + "\n"), KLINE_COLS)
    b = read_csv_from_zip(_zip(",".join(KLINE_COLS) + "\n" + row + "\n"), KLINE_COLS)
    assert list(a.columns) == list(b.columns) == KLINE_COLS
    assert a.iloc[0]["close"] == b.iloc[0]["close"] == 1.5


def _idx(n):
    return pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")


def test_signal_on_day_d_earns_day_d_plus_1():
    idx = _idx(4)
    ret = pd.Series([0.0, 0.10, -0.05, 0.02], index=idx)
    pos = pd.Series([0.0, 1.0, 0.0, 0.0], index=idx)  # 第 1 天收盤進場，第 2 天收盤出場
    r = bt.run("t", ret, pos, cost_bps=0)
    # 只賺到第 2 天的 -5%，不能偷看到第 1 天的 +10%
    assert np.allclose(r.net.values, [0, 0, -0.05, 0])


def test_costs_and_funding():
    idx = _idx(4)
    ret = pd.Series(0.0, index=idx)
    pos = pd.Series([1.0, 1.0, 0.0, 0.0], index=idx)  # 第 0 天收盤進場、第 2 天收盤出場
    fund = pd.Series(0.001, index=idx)
    r = bt.run("t", ret, pos, cost_bps=10, funding_day=fund)
    # 第 1 天：進場成本 0.1% + 資金費 0.1%；第 2 天：資金費 0.1%；第 3 天：出場成本 0.1%（已無持倉）
    assert np.allclose(r.net.values, [0, -0.002, -0.001, -0.001])


def test_short_receives_positive_funding():
    idx = _idx(2)
    r = bt.run("t", pd.Series(0.0, index=idx), pd.Series(-1.0, index=idx), cost_bps=0,
               funding_day=pd.Series(0.001, index=idx))
    assert r.net.iloc[1] > 0


def test_trend_signal_range_and_no_lookahead():
    idx = _idx(300)
    close = pd.Series(np.linspace(100, 200, 300), index=idx)
    d = pd.DataFrame({"close": close})
    s = trend_signal(d)
    assert s.between(-1, 1).all() and s.iloc[-1] == 1.0
    # 改動未來的價格，不應影響過去的訊號
    d2 = d.copy()
    d2.iloc[200:, 0] = 1.0
    assert trend_signal(d2).iloc[:200].equals(s.iloc[:200])


def test_walk_forward_uses_only_past_data():
    from quant.run_filters import Filter, walk_forward
    rng = np.random.default_rng(1)
    idx = pd.date_range("2020-01-01", periods=1400, freq="D", tz="UTC")
    d = pd.DataFrame({"ret": rng.normal(0.001, 0.03, len(idx)),
                      "funding_day": 0.0,
                      "feat": rng.normal(0, 1, len(idx))}, index=idx)
    base = pd.Series(1.0, index=idx)
    f = Filter("t", "feat", "above", [0.0, 1.0], first_test="2022-07-01")
    _, chosen_a = walk_forward(d, base, f, idx[0])
    d2 = d.copy()
    d2.loc["2023-01-01":, "ret"] = rng.normal(0.01, 0.03, len(d2.loc["2023-01-01":]))  # 改動未來
    _, chosen_b = walk_forward(d2, base, f, idx[0])
    # 2023-01 之前開始的測試段，選到的參數必須完全一樣
    early = [(a[2], b[2]) for a, b in zip(chosen_a, chosen_b) if a[0] < pd.Timestamp("2023-01-01", tz="UTC")]
    assert early and all(x == y for x, y in early)


def _paper_frame(n=200):
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(3)
    close = 50000 * np.exp(np.cumsum(rng.normal(0.002, 0.02, n)))
    return pd.DataFrame({"close": close, "ret": pd.Series(close).pct_change().values,
                         "rv_30d": 0.5, "ls_z90": 0.0, "oi_z90": 0.0, "funding_day": 0.0}, index=idx)


def test_paper_signals_are_append_only(tmp_path, monkeypatch):
    from quant import paper
    monkeypatch.setattr(paper, "PAPER", tmp_path)
    d = _paper_frame()
    t1 = pd.Timestamp("2026-07-20 09:00", tz="UTC")
    s1 = paper.append_signals(d.loc[:"2026-07-18"], t1)
    assert len(s1) == 1 and s1["signal_date"].iloc[0] == pd.Timestamp("2026-07-18", tz="UTC")
    # 同一天再跑一次：沒有新數據就不新增
    assert len(paper.append_signals(d.loc[:"2026-07-18"], t1)) == 1
    # 之後的數據即使改動，舊紀錄也不能被改寫
    d2 = d.copy()
    d2.loc[:"2026-07-18", "close"] *= 2
    s2 = paper.append_signals(d2.loc[:"2026-07-19"], t1 + pd.Timedelta(days=1))
    assert len(s2) == 2
    assert s2["close"].iloc[0] == s1["close"].iloc[0]


def test_paper_executes_on_generation_day():
    from quant.paper import executed_positions
    sig = pd.DataFrame({
        "signal_date": pd.to_datetime(["2026-07-18", "2026-07-19"], utc=True),
        "generated_at_utc": pd.to_datetime(["2026-07-20 09:00", "2026-07-20 15:00"], utc=True),
        "target_pos": [0.5, 1.0],
    })
    idx = pd.date_range("2026-07-15", "2026-07-22", freq="D", tz="UTC")
    pos = executed_positions(sig, idx)
    # 兩筆都在 07-20 產生 → 07-20 收盤執行最後一筆；07-18、07-19 不能有倉位
    assert pos.index.min() == pd.Timestamp("2026-07-20", tz="UTC")
    assert pos.loc["2026-07-20"] == 1.0 and pos.loc["2026-07-22"] == 1.0
