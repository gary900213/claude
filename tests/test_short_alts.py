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
    port, trades = simulate(pn, [("X", pn.close.index[0], 2)])
    c = COST_BPS / 1e4
    expected = ((1 - c) + 0.10 + 0.40) * (1 - c) - 1  # 跌到 50：賺 50%（以名目計）
    assert np.isclose(trades["return"].iloc[0], expected)
    assert trades["reason"].iloc[0] == "到期"


def test_liquidation_on_intraday_high():
    pn = _panel([100, 110, 120, 50], highs=[100, 110, 195, 60])
    _, trades = simulate(pn, [("X", pn.close.index[0], 3)])
    assert trades["reason"].iloc[0] == "爆倉" and trades["return"].iloc[0] == -1.0


def test_delisting_exits_at_last_close():
    pn = _panel([100, 80, np.nan, np.nan])
    _, trades = simulate(pn, [("X", pn.close.index[0], 3)])
    assert trades["reason"].iloc[0] == "下架" and trades["return"].iloc[0] > 0.19


def test_short_receives_positive_funding():
    pn = _panel([100, 100, 100], funding=0.01)
    _, trades = simulate(pn, [("X", pn.close.index[0], 2)])
    assert trades["return"].iloc[0] > 0.015  # 兩天各收 1%，扣掉進出成本
