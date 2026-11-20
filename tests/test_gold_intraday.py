import numpy as np
import pandas as pd

from quant.gold_intraday import backtest, pivots


def test_pivot_confirmed_only_after_n_bars():
    highs = np.array([1, 2, 3, 9, 3, 2, 1, 1, 1], dtype=float)
    p = pivots(highs, 2, True)
    assert p[0] == (5, 9.0)  # 第 3 根是高點，要到第 3+2=5 根才確認


def test_breakout_then_retest_long():
    # 兩個波段高點 101、100 → 區間 [100,101]；突破到 103 後回踩 101 進場，之後漲到停利
    path = [95, 96, 101, 96, 95, 94, 95, 100, 95, 94, 93, 96, 103, 104, 103, 101, 102, 104, 106, 108, 110]
    n = len(path)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    c = np.array(path, dtype=float)
    x = pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c, "atr": 2.0}, index=idx)
    t = backtest(x, pivot_n=2)
    longs = t[t["side"] == 1]
    assert len(longs) == 1
    assert np.isclose(longs["entry"].iloc[0], 101.0)
    assert longs["result"].iloc[0] == "停利"
