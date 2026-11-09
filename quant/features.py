"""衍生品特徵：全部只用「第 D 天收盤時已知」的數據。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def zscore(s: pd.Series, window: int) -> pd.Series:
    """滾動 z 分數；允許視窗內有少量缺漏（至少 80% 有值）。"""
    r = s.rolling(window, min_periods=int(window * 0.8))
    return (s - r.mean()) / r.std()


def add_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["funding_ann"] = d["funding_day"] * 365                     # 年化資金費率
    d["funding_7d_ann"] = d["funding_day"].rolling(7).mean() * 365
    d["price_chg_7d"] = d["close"].pct_change(7)
    d["ls_z90"] = zscore(d["ls_account"], 90)                       # 散戶多空比相對 90 天
    d["top_ls_z90"] = zscore(d["top_ls_position"], 90)              # 大戶持倉多空比
    d["taker_z30"] = zscore(d["taker_buy_ratio"].rolling(7).mean(), 30)
    d["oi_z90"] = zscore(np.log(d["oi_btc"]), 90)                   # 持倉量（以 BTC 計）相對水位
    if "etf_net_musd" in d:
        first = d["etf_net_musd"].first_valid_index()
        e = d["etf_net_musd"].copy()
        if first is not None:
            e.loc[first:] = e.loc[first:].fillna(0.0)               # 週末/假日 = 0 流量
        d["etf_7d_musd"] = e.rolling(7, min_periods=7).sum()
    # 未來報酬（只用於分析，絕不能拿來產生訊號）
    d["fwd_7d"] = d["close"].shift(-7) / d["close"] - 1
    return d


FEATURE_LABELS = {
    "funding_z30": "資金費率 z 分數（30 日）",
    "funding_7d_ann": "資金費率 7 日均（年化）",
    "oi_chg_7d": "持倉量 7 日變化",
    "oi_z90": "持倉量水位 z 分數（90 日）",
    "ls_z90": "散戶多空帳戶比 z 分數（90 日）",
    "top_ls_z90": "大戶持倉多空比 z 分數（90 日）",
    "taker_z30": "主動買入比 z 分數",
    "etf_7d_musd": "ETF 7 日淨流入（百萬美元）",
    "price_chg_7d": "（對照）價格 7 日漲跌",
}
