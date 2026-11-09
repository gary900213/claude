"""簡單、透明的日線回測引擎。

規則（避免前視偏差）：
- positions 的第 D 列 = 用「第 D 天收盤時已知的資訊」決定的目標倉位。
- 這個倉位賺的是第 D+1 天的報酬（引擎內部自動 shift(1)）。
- 換倉成本：|倉位變化| × cost_bps（手續費 + 滑價）。
- 資金費率：持有永續合約要付／收資金費率；多單在費率為正時付錢。
  funding_day 是當天 3 期費率合計，倉位 × 費率 從報酬中扣除。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365  # 加密貨幣全年無休


@dataclass
class Result:
    name: str
    daily: pd.DataFrame  # 欄位：pos, gross, cost, funding, net, equity, drawdown

    @property
    def net(self) -> pd.Series:
        return self.daily["net"]


def run(name: str, ret: pd.Series, positions: pd.Series, cost_bps: float = 7.0,
        funding_day: pd.Series | None = None) -> Result:
    positions = positions.reindex(ret.index).fillna(0.0)
    held = positions.shift(1).fillna(0.0)  # D 天收盤決定 → D+1 天持有
    gross = held * ret.fillna(0.0)
    turnover = positions.diff().abs().fillna(positions.abs())
    cost = turnover.shift(1).fillna(0.0) * cost_bps / 1e4  # 換倉發生在 D 收盤，計入 D+1
    fund = held * funding_day.reindex(ret.index).fillna(0.0) if funding_day is not None else 0.0 * held
    net = gross - cost - fund
    equity = (1 + net).cumprod()
    dd = equity / equity.cummax() - 1
    return Result(name, pd.DataFrame({"pos": held, "gross": gross, "cost": cost, "funding": fund,
                                      "net": net, "equity": equity, "drawdown": dd}))


def stats(r: Result, start=None, end=None) -> dict:
    d = r.daily.loc[start:end]
    n = d["net"]
    if len(n) < 2:
        return {}
    eq = (1 + n).cumprod()
    years = len(n) / DAYS_PER_YEAR
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = n.std() * np.sqrt(DAYS_PER_YEAR)
    sharpe = n.mean() / n.std() * np.sqrt(DAYS_PER_YEAR) if n.std() > 0 else np.nan
    downside = n[n < 0].std() * np.sqrt(DAYS_PER_YEAR)
    mdd = (eq / eq.cummax() - 1).min()
    return {
        "策略": r.name,
        "年化報酬": cagr,
        "年化波動": vol,
        "夏普值": sharpe,
        "索提諾": n.mean() * DAYS_PER_YEAR / downside if downside > 0 else np.nan,
        "最大回撤": mdd,
        "卡瑪比": cagr / abs(mdd) if mdd < 0 else np.nan,
        "平均曝險": d["pos"].abs().mean(),
        "年換手": d["pos"].diff().abs().sum() / years,
        "成本拖累/年": (d["cost"].sum() + d["funding"].sum()) / years,
    }


def yearly_returns(results: list[Result]) -> pd.DataFrame:
    return pd.DataFrame({r.name: (1 + r.net).groupby(r.net.index.year).prod() - 1 for r in results})


def stats_table(results: list[Result], start=None, end=None) -> pd.DataFrame:
    return pd.DataFrame([stats(r, start, end) for r in results]).set_index("策略")


def apply_band(pos: pd.Series, band: float) -> pd.Series:
    """倉位變化小於 band 就維持原倉位；目標為 0 時一律出場。"""
    out, cur = [], 0.0
    for p in pos.fillna(0.0):
        if p == 0.0 or abs(p - cur) >= band:
            cur = p
        out.append(cur)
    return pd.Series(out, index=pos.index)
