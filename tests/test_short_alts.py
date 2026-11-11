import numpy as np
import pandas as pd

from quant.short_alts import COST_BPS, Panel, simulate


def _panel(prices, highs=None, funding=0.0):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D", tz="UTC")
    close = pd.DataFrame({"X": prices}, index=idx, dtype=float)
    high = pd.DataFrame({"X": highs if highs is not None else prices}, index=idx, dtype=float)
    return Panel(close, high, close * 0 + 1e9, close * 0 + funding, pd.Series({"X": idx[0]}),
                 pd.Series({"X": idx[-1]}), pd.Series(0.0, index=idx))


def test_short_profit_with_costs():
    pn = _panel([100, 90, 50, 50])
    *_, trades = simulate(pn, [("X", pn.close.index[0], 2)])
    c = COST_BPS / 1e4
    expected = 0.50 - c - 0.5 * c  # 跌到 50：賺 50%；進場成本以名目 1、出場以名目 0.5 計
    assert np.isclose(trades["return"].iloc[0], expected)
    assert trades["reason"].iloc[0] == "到期"


def test_liquidation_on_intraday_high():
    pn = _panel([100, 110, 120, 50], highs=[100, 110, 195, 60])
    *_, trades = simulate(pn, [("X", pn.close.index[0], 3)])
    assert trades["reason"].iloc[0] == "爆倉" and trades["return"].iloc[0] == -1.0


def test_delisting_exits_at_last_close():
    pn = _panel([100, 80, np.nan, np.nan])
    *_, trades = simulate(pn, [("X", pn.close.index[0], 3)])
    assert trades["reason"].iloc[0] == "下架" and trades["return"].iloc[0] > 0.19


def test_short_receives_positive_funding():
    pn = _panel([100, 100, 100], funding=0.01)
    *_, trades = simulate(pn, [("X", pn.close.index[0], 2)])
    assert trades["return"].iloc[0] > 0.015  # 兩天各收 1%，扣掉進出成本


def test_split_reused_symbols():
    from quant.short_alts import split_reused_symbols
    d = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-12", "2026-10-13"], utc=True)
    p = pd.DataFrame({"symbol": "MDTUSDT", "date": d, "close": [0.06, 0.063, 93.3, 90.0]})
    out = split_reused_symbols(p)
    assert out["symbol"].tolist() == ["MDTUSDT", "MDTUSDT", "MDTUSDT#2", "MDTUSDT#2"]
    # 停很久但價格沒怎麼變：不拆
    p2 = p.assign(close=[1.0, 1.0, 1.1, 1.1])
    assert split_reused_symbols(p2)["symbol"].nunique() == 1


def test_slots_limit_and_fixed_allocation():
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    close = pd.DataFrame({"X": [100, 50, 50], "Y": [100, 100, 100]}, index=idx, dtype=float)
    pn = Panel(close, close, close * 0 + 1e9, close * 0, pd.Series({"X": idx[0], "Y": idx[0]}),
               pd.Series({"X": idx[-1], "Y": idx[-1]}), pd.Series([0.0, 0.10, 0.0], index=idx))
    r_short, r_hedged, expo, trades = simulate(pn, [("X", idx[0], 2), ("Y", idx[0], 2)], slots=1)
    assert trades["symbol"].tolist() == ["X"]          # 槽位滿了，Y 被略過
    assert np.isclose(r_short.iloc[1], 0.5, atol=0.01)  # 空單賺 50%
    assert r_hedged.iloc[1] > r_short.iloc[1]          # 市場中性版本多了 BTC +10%


def test_margin_halves_notional_and_moves_liquidation():
    pn = _panel([100, 150, 100], highs=[100, 195, 100])
    *_, t1 = simulate(pn, [("X", pn.close.index[0], 2)], margin=1.0)
    *_, t2 = simulate(pn, [("X", pn.close.index[0], 2)], margin=2.0)
    assert t1["reason"].iloc[0] == "爆倉"           # 1 倍：漲到 1.95 倍爆倉
    assert t2["reason"].iloc[0] == "到期"           # 2 倍：要漲到 2.8 倍才爆倉
    assert abs(t2["return"].iloc[0]) < 0.01          # 名目只有一半，最後回到原價，幾乎不賺不賠
