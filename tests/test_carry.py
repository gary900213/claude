import numpy as np
import pandas as pd

from quant.carry import _read_spot, carry_returns, carry_state

import io
import zipfile


def test_carry_state_hysteresis():
    f7 = pd.Series([np.nan, 0.02, 0.06, 0.03, -0.01, 0.04, 0.07])
    # >5% 進場，<0 出場；中間 0~5% 維持原狀
    assert carry_state(f7, 0.05).tolist() == [0, 0, 1, 1, 0, 0, 1]
    assert carry_state(f7, None).tolist() == [1] * 7


def test_carry_returns_timing_costs_and_margin():
    idx = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    x = pd.DataFrame({"basis_ret": [0.0, 0.001, 0.0, 0.0], "funding": 0.0003}, index=idx)
    state = pd.Series([1.0, 1.0, 0.0, 0.0], index=idx)
    r = carry_returns(x, state, margin=1.0)
    # 第 0 天收盤進場 → 第 1 天才有報酬，並扣進場成本 19 bps；本金 = 2 倍名目
    assert np.isclose(r["net"].iloc[0], 0.0)
    assert np.isclose(r["net"].iloc[1], (0.001 + 0.0003 - 0.0019) / 2)
    assert np.isclose(r["net"].iloc[2], 0.0003 / 2)
    assert np.isclose(r["net"].iloc[3], -0.0019 / 2)  # 第 2 天收盤出場的成本


def test_read_spot_handles_microseconds():
    rows = "1735603200000,1,2,0.5,1.5,10\n1735689600000000,1,2,0.5,1.6,10\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", rows)
    s = _read_spot(buf.getvalue())
    assert list(s.index.strftime("%Y-%m-%d")) == ["2024-12-31", "2025-01-01"]
