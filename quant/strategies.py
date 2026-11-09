"""基準策略：全部只用「當天收盤已知」的數據產生目標倉位。

參數都是常見的預設值，沒有針對歷史數據調整過（避免過度擬合）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TREND_LOOKBACKS = (20, 60, 120)


def buy_and_hold(d: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=d.index)


def vol_scale(d: pd.DataFrame, target_vol: float = 0.40, max_leverage: float = 1.5) -> pd.Series:
    """波動率目標：倉位 = 目標波動 / 近 30 天已實現波動，上限 max_leverage。"""
    return (target_vol / d["rv_30d"]).clip(upper=max_leverage).fillna(0.0)


def vol_target_hold(d: pd.DataFrame, **kw) -> pd.Series:
    return vol_scale(d, **kw)


def trend_signal(d: pd.DataFrame, lookbacks=TREND_LOOKBACKS) -> pd.Series:
    """多週期趨勢分數，範圍 -1 ~ +1：各週期報酬正負號的平均。"""
    c = d["close"]
    sig = sum(np.sign(c / c.shift(lb) - 1) for lb in lookbacks) / len(lookbacks)
    return sig.fillna(0.0)


def trend_long_only(d: pd.DataFrame, **kw) -> pd.Series:
    return trend_signal(d).clip(lower=0) * vol_scale(d, **kw)


def trend_long_short(d: pd.DataFrame, **kw) -> pd.Series:
    return trend_signal(d) * vol_scale(d, **kw)


BASELINES = {
    "買入持有": buy_and_hold,
    "波動率目標持有": vol_target_hold,
    "趨勢（只做多）": trend_long_only,
    "趨勢（多空）": trend_long_short,
}
