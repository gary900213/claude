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
