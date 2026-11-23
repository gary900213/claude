import numpy as np
import pandas as pd

from quant import lending_bot as lb


def _tape(rates, start="2026-01-01", step="1h"):
    idx = pd.date_range(start, periods=len(rates), freq=step, tz="UTC")
    return pd.DataFrame({"amount": 1000.0, "rate": rates, "period": 2}, index=idx)


def test_fill_only_when_trade_strictly_above_offer(monkeypatch):
    monkeypatch.setattr(lb, "TRANCHES", 1)
    monkeypatch.setattr(lb, "CAPITAL", 1000.0)
    t = _tape([0.0002] * 100)                      # 全部成交都剛好等於掛單利率
    q = pd.DataFrame({0.5: 0.0002}, index=pd.date_range(t.index[0], t.index[-1], freq="h"))
    res = lb.simulate(t, q, [0.5], lock=False, timeout=False)
    assert res["資金使用率"] == 0.0                  # 等於不算成交（保守）


def test_lent_for_two_days_at_offer_rate(monkeypatch):
    monkeypatch.setattr(lb, "TRANCHES", 1)
    monkeypatch.setattr(lb, "CAPITAL", 1000.0)
    rates = [0.0003] * (24 * 10)                   # 一直有人以 0.03%/日 成交
    t = _tape(rates)
    q = pd.DataFrame({0.5: 0.0002}, index=pd.date_range(t.index[0], t.index[-1], freq="h"))
    res = lb.simulate(t, q, [0.5], lock=False, timeout=False)
    assert res["資金使用率"] > 0.95                  # 幾乎一直借出去
    assert abs(res["毛年化"] - 0.0002 * 365 * res["資金使用率"]) < 0.002  # 以我的掛單利率計息
