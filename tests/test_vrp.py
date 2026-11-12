from math import pi, sqrt

import numpy as np

from quant.vrp import TENOR, bs_straddle, short_straddle


def test_atm_straddle_approximation():
    # 價平跨式 ≈ 2 × 0.4 × S × σ√T（= √(2/π)·σ√T·S）
    price, delta = bs_straddle(100.0, 100.0, 0.6, 30 / 365)
    assert abs(price - sqrt(2 / pi) * 0.6 * sqrt(30 / 365) * 100) < 0.05
    from math import erf
    d1 = 0.5 * 0.6 * sqrt(30 / 365)
    assert abs(delta - (2 * 0.5 * (1 + erf(d1 / sqrt(2))) - 1)) < 1e-9  # 價平 delta = 2N(σ√T/2) − 1，略大於 0


def test_short_straddle_flat_price_keeps_premium():
    path = np.full(TENOR + 1, 100.0)
    prem, _ = bs_straddle(100.0, 100.0, 0.5, TENOR / 365)
    assert np.isclose(short_straddle(path, 0.5, cost=0.0), prem / 100)


def test_short_straddle_big_move_loses_and_hedge_helps():
    path = np.linspace(100, 160, TENOR + 1)  # 一路大漲 60%
    unhedged = short_straddle(path, 0.5, cost=0.0)
    hedged = short_straddle(path, 0.5, cost=0.0, hedge=True)
    assert unhedged < -0.4
    assert hedged > unhedged  # 持續對沖會跟著加碼現貨，虧損小很多
