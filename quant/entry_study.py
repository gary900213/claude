"""入場（與出場）方式研究：策略決定好倉位後，怎麼成交比較划算？

以凍結策略（quant.paper.STRATEGY）在 UTC 收盤產生的每一筆換倉為對象，
用接下來 24 小時的 1 小時 K 線，比較不同執行方式的成交價（相對收盤價，bps）：

- 收盤市價：在 UTC 收盤立刻市價成交（回測的假設）
- 分批（TWAP）4／8／24 小時：平均分散在接下來 N 小時成交
- 限價 0.5%／1%／2%：買單掛在收盤價下方 x%（賣單掛上方 x%），24 小時內觸價就成交；
  沒成交就在 24 小時後市價追單

另外測「不交易區間」：倉位變化小於門檻就不調整，減少因波動率小幅變動造成的零碎交易。

用法：python -m quant.entry_study
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from .backtest import apply_band
from .features import add_features
from .history import OUT as HISTORY_DIR, load_daily
from .paper import STRATEGY, compute

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "entry"
LIMITS = (0.005, 0.01, 0.02)
TWAPS = (4, 8, 24)


def execution_costs(h: pd.DataFrame, trades: pd.Series) -> pd.DataFrame:
    """每筆交易在各執行方式下的成本（bps，正數 = 比收盤價差）。

    trades：index = 決策日 D（UTC 日），值 = 倉位變化（正 = 買、負 = 賣）。
    """
    rows = []
    for day, dpos in trades.items():
        win = h.loc[day + pd.Timedelta(days=1): day + pd.Timedelta(days=1, hours=23)]
        ref = h["close"].get(day + pd.Timedelta(hours=23))
        if len(win) < 24 or ref is None or np.isnan(ref):
            continue
        side = 1 if dpos > 0 else -1
        r = {"date": day, "dpos": dpos, "side": "買" if side > 0 else "賣", "收盤市價": 0.0}
        for n in TWAPS:
            px = win["close"].iloc[:n].mean()
            r[f"分批 {n}h"] = side * (px / ref - 1) * 1e4
        for x in LIMITS:
            limit = ref * (1 - side * x)
            touched = (win["low"] <= limit) if side > 0 else (win["high"] >= limit)
            px = limit if touched.any() else win["close"].iloc[-1]
            r[f"限價 {x:.1%}"] = side * (px / ref - 1) * 1e4
            r[f"限價 {x:.1%} 成交率"] = float(touched.any())
        rows.append(r)
    return pd.DataFrame(rows).set_index("date")


def main() -> int:
    d = add_features(load_daily())
    d = d[d["close"].notna()]
    h = pd.read_csv(HISTORY_DIR / "btcusdt_1h.csv.gz", index_col=0, parse_dates=True)
    target = compute(d)["target_pos"]
    start = d.index[120]
    OUT.mkdir(parents=True, exist_ok=True)
    years = (d.index[-1] - start).days / 365

    # 1) 不交易區間
    band_rows = []
    for band in (0.0, 0.05, 0.10, 0.20, 0.30):
        pos = apply_band(target, band)
        r = bt.run("", d["ret"], pos, STRATEGY["cost_bps"], d["funding_day"])
        st = bt.stats(bt.Result("", r.daily.loc[start:]))
        trades = (pos.diff().abs() > 1e-9).loc[start:].sum()
        band_rows.append({"不交易區間": f"{band:.2f}", "年化報酬": f"{st['年化報酬']:+.1%}",
                          "夏普值": f"{st['夏普值']:.2f}", "最大回撤": f"{st['最大回撤']:.1%}",
                          "每年交易次數": f"{trades / years:.0f}", "年換手": f"{st['年換手']:.1f}x"})
    band_df = pd.DataFrame(band_rows).set_index("不交易區間")

    # 2) 執行方式（用 0.10 的不交易區間後的實際交易）
    pos = apply_band(target, 0.10)
    dpos = pos.diff().loc[start:]
    trades = dpos[dpos.abs() > 1e-9]
    costs = execution_costs(h, trades)
    methods = [c for c in costs.columns if c not in ("dpos", "side") and not c.endswith("成交率")]
    w = costs["dpos"].abs()
    summary = []
    for m in methods:
        rate_col = f"{m} 成交率"
        for side in ("買", "賣", "全部"):
            c = costs if side == "全部" else costs[costs["side"] == side]
            ww = c["dpos"].abs()
            summary.append({
                "執行方式": m, "方向": side,
                "平均成本 bps": f"{np.average(c[m], weights=ww):+.1f}",
                "中位數 bps": f"{c[m].median():+.1f}",
                "比收盤市價好的比例": f"{(c[m] < 0).mean():.0%}",
                "限價成交率": f"{c[rate_col].mean():.0%}" if rate_col in c else "—",
                "交易筆數": len(c),
            })
    sm = pd.DataFrame(summary)
    pivot = sm.pivot(index="執行方式", columns="方向", values="平均成本 bps")[["買", "賣", "全部"]]
    pivot = pivot.loc[methods]
    # 對策略的年化影響：Σ|Δpos| × 成本 / 年數
    impact = {m: -(w * costs[m] / 1e4).sum() / years for m in methods}
    pivot["對年化報酬的影響"] = [f"{impact[m]:+.2%}" for m in methods]
    fills = {m: f"{costs[f'{m} 成交率'].mean():.0%}" for m in methods if f"{m} 成交率" in costs}
    pivot["限價成交率"] = [fills.get(m, "—") for m in methods]
    better = {m: f"{(costs[m] < 0).mean():.0%}" for m in methods}
    pivot["比收盤市價好的比例"] = [better[m] for m in methods]

    # 3) 買單分年度穩定性（最佳幾個方式）
    buys = costs[costs["side"] == "買"]
    by_year = buys.groupby(buys.index.year)[methods].mean().round(1)
    by_year.index.name = "年度（買單平均 bps）"

    lines = [
        "# 入場與出場方式研究",
        "",
        f"對象：凍結策略 `{STRATEGY['version']}` 在 {start:%Y-%m-%d} 之後的每一筆換倉"
        f"（套用 0.10 不交易區間後共 {len(costs)} 筆）。成本以「UTC 收盤價」為基準，"
        "**正數 = 比收盤市價成交差，負數 = 比較好**。",
        "",
        "## 1. 不交易區間：倉位變化太小就不調整",
        "",
        band_df.to_markdown(),
        "",
        "## 2. 執行方式比較（平均成本 bps，依倉位變化加權）",
        "",
        pivot.to_markdown(),
        "",
        "## 3. 買單的年度穩定性",
        "",
        by_year.to_markdown(),
        "",
        "說明：限價單沒成交時，24 小時後市價追單，所以「成交率」越低、追單成本越可能吃掉好處。",
        "這裡只看成交價，沒有扣掛單／吃單手續費的差異（掛單手續費通常更低，對限價單有利）。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
