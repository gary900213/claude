import numpy as np
import pandas as pd

from quant import paper_v3


def _frame(n=400, drift=0.002, vol=0.02, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    r = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(r))
    d = pd.DataFrame({"close": close}, index=idx)
    d["ret"] = d["close"].pct_change()
    d["rv_30d"] = np.sqrt(d["ret"].pow(2).rolling(30).mean() * 365)
    d["funding_day"] = 0.0
    return d.dropna()


def test_weights_and_targets():
    # 兩條腿都一路上漲（一直有持倉）；BTC 價格波動大，策略報酬波動也大 → 分到較少資金
    b, g = _frame(seed=1, vol=0.04, drift=0.01), _frame(seed=2, vol=0.01, drift=0.003)
    c = paper_v3.compute(b, g).dropna()
    assert np.allclose(c["w_btc"] + c["w_gold"], 1.0)
    assert (c["w_gold"].iloc[-50:] > c["w_btc"].iloc[-50:]).all()  # 波動小的腿分到較多資金
    assert np.allclose(c["target_btc"], c["w_btc"] * c["btc_pos"])


def test_signals_append_only_and_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_v3, "PAPER", tmp_path)
    b, g = _frame(seed=3), _frame(seed=4)
    c = paper_v3.compute(b, g)
    t1 = c.index[-2] + pd.Timedelta(days=1, hours=9)
    s1 = paper_v3.append_signals(c.iloc[:-1], t1)
    assert len(s1) == 1
    assert len(paper_v3.append_signals(c.iloc[:-1], t1)) == 1  # 沒有新數據不新增
    s2 = paper_v3.append_signals(c, t1 + pd.Timedelta(days=1))
    assert len(s2) == 2 and s2["btc_close"].iloc[0] == s1["btc_close"].iloc[0]
    pos = paper_v3.executed(s2, c.index)
    assert pos.index.min() == t1.normalize()  # 在產生當天收盤執行
