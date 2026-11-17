"""黃金研究：把 BTC 的趨勢策略（v2 參數，完全不調）套用到黃金，並看「BTC＋黃金」組合。

數據：幣安現貨 PAXGUSDT 日線（1 PAXG = 1 盎司實體黃金，2020-08 起）。
      和幣安 XAUUSDT 永續比對：日報酬相關 0.99、價差中位數約 −0.1%，可當金價代理。

黃金的做法（同一組趨勢訊號：20/60/120 日 × 波動率目標 40%）：
- H 買入持有：1 倍，不付持有成本
- P 永續合約：上限 1.5 倍；持有成本用幣安 XAUUSDT 實際平均資金費率（年化約 12.6%）
- S PAXG 現貨：上限 1 倍（現貨不能加槓桿）；手續費 12 bps，不付資金費率
- F 期貨（例如 COMEX 小型黃金 MGC）：上限 1.5 倍；展期成本年化約 4%（約等於美元利率）

用法：python -m quant.gold
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .alts_data import PANEL  # noqa: E402
from .carry import load_spot_daily  # noqa: E402
from .history import load_daily  # noqa: E402
from .paper import STRATEGIES  # noqa: E402
from .strategies import trend_signal, vol_scale  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gold"
FUTURES_CARRY = 0.04
BLUE, ORANGE, AQUA, YELLOW, VIOLET, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6", "#52514e"


def gold_frame() -> tuple[pd.DataFrame, dict]:
    today = pd.Timestamp.now(tz="UTC").date()
    paxg = load_spot_daily("PAXGUSDT", today)
    d = pd.DataFrame({"close": paxg})
    d["ret"] = d["close"].pct_change()
    d["rv_30d"] = np.sqrt(d["ret"].pow(2).rolling(30).mean() * 365)
    info = {"start": d.index[0], "end": d.index[-1], "vol": d["ret"].std() * np.sqrt(365)}
    # 和 XAUUSDT 永續比對，並取得實際資金費率
    p = pd.read_pickle(PANEL) if PANEL.exists() else None
    if p is not None and (p["symbol"] == "XAUUSDT").any():
        xau = p[p["symbol"] == "XAUUSDT"].set_index("date")
        both = pd.DataFrame({"paxg": d["close"], "xau": xau["close"]}).dropna()
        info.update({"overlap_days": len(both), "corr": both.pct_change().corr().iloc[0, 1],
                     "spread_median": (both["paxg"] / both["xau"] - 1).median(),
                     "xau_funding_ann": xau["funding_day"].mean() * 365,
                     "xau_funding_neg": (xau["funding_day"] < 0).mean()})
    else:
        info.update({"xau_funding_ann": 0.126})
    return d, info


def trend_positions(d: pd.DataFrame, cap: float) -> pd.Series:
    s = STRATEGIES["v2"]
    pos = trend_signal(d, tuple(s["trend_lookbacks"])).clip(lower=0) * vol_scale(d, s["target_vol"], cap)
    return bt.apply_band(pos, s["rebalance_band"])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    g, info = gold_frame()
    const = lambda ann: pd.Series(ann / 365, index=g.index)  # noqa: E731
    runs = {
        "H 黃金買入持有": bt.run("H", g["ret"], pd.Series(1.0, index=g.index), 12.0, None),
        "P 趨勢｜永續（≤1.5 倍，資金費率 12.6%）": bt.run("P", g["ret"], trend_positions(g, 1.5), 7.0,
                                              const(info["xau_funding_ann"])),
        "S 趨勢｜PAXG 現貨（≤1 倍）": bt.run("S", g["ret"], trend_positions(g, 1.0), 12.0, None),
        "F 趨勢｜期貨（≤1.5 倍，展期 4%）": bt.run("F", g["ret"], trend_positions(g, 1.5), 3.0,
                                        const(FUTURES_CARRY)),
    }
    start = g.index[120]
    rows = []
    for name, r in runs.items():
        for period, s in (("全期間", start), ("2023 起", pd.Timestamp("2023-01-01", tz="UTC"))):
            st = bt.stats(bt.Result(name, r.daily.loc[s:]))
            rows.append({"做法": name, "期間": period, "年化": f"{st['年化報酬']:+.1%}",
                         "波動": f"{st['年化波動']:.1%}", "夏普": f"{st['夏普值']:.2f}",
                         "最大回撤": f"{st['最大回撤']:.1%}", "平均曝險": f"{st['平均曝險']:.2f}x",
                         "成本拖累/年": f"{st['成本拖累/年']:+.1%}"})
    gold_table = pd.DataFrame(rows)

    # BTC v2 與組合
    b = load_daily("BTCUSDT")
    b = b[b["close"].notna()]
    btc = bt.run("BTC", b["ret"], trend_positions(b, STRATEGIES["v2"]["max_leverage"]), 7.0, b["funding_day"])
    idx = btc.daily.index.intersection(runs["F 趨勢｜期貨（≤1.5 倍，展期 4%）"].daily.index)
    idx = idx[idx >= start]
    rb = btc.daily["net"].reindex(idx).fillna(0.0)
    rg = runs["F 趨勢｜期貨（≤1.5 倍，展期 4%）"].daily["net"].reindex(idx).fillna(0.0)
    rh = runs["H 黃金買入持有"].daily["net"].reindex(idx).fillna(0.0)
    active = (btc.daily["pos"].reindex(idx) > 0) | (runs["F 趨勢｜期貨（≤1.5 倍，展期 4%）"].daily["pos"].reindex(idx) > 0)
    corr_all = np.corrcoef(rb, rg)[0, 1]
    corr_active = np.corrcoef(rb[active], rg[active])[0, 1]
    # 風險平價：用過去 180 天的實際波動決定比重（只用過去資訊）
    vb = rb.rolling(180, min_periods=60).std().shift(1)
    vg = rg.rolling(180, min_periods=60).std().shift(1)
    wb = ((1 / vb) / (1 / vb + 1 / vg)).fillna(0.5)
    combos = {
        "只做 BTC 趨勢 v2": rb,
        "只做黃金趨勢 F": rg,
        "BTC 趨勢 50% ＋ 黃金趨勢 50%": 0.5 * rb + 0.5 * rg,
        "BTC 趨勢 ＋ 黃金趨勢（風險平價）": wb * rb + (1 - wb) * rg,
        "BTC 趨勢 50% ＋ 黃金持有 50%": 0.5 * rb + 0.5 * rh,
    }
    combo_rows, combo_eq = [], {}
    for name, net in combos.items():
        r = bt.Result(name, pd.DataFrame({"net": net, "pos": 0.0}))
        st = bt.stats(r)
        combo_eq[name] = (1 + net).cumprod()
        combo_rows.append({"組合": name, "年化": f"{st['年化報酬']:+.1%}", "波動": f"{st['年化波動']:.1%}",
                           "夏普": f"{st['夏普值']:.2f}", "最大回撤": f"{st['最大回撤']:.1%}",
                           "卡瑪比": f"{st['卡瑪比']:.2f}"})
    combo_table = pd.DataFrame(combo_rows)
    yearly = pd.DataFrame({k: (1 + v).groupby(v.index.year).prod() - 1 for k, v in combos.items()})
    yearly = yearly.map(lambda x: f"{x:+.1%}")
    yearly.index.name = "年度"

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    for (name, eq), color in zip(combo_eq.items(), [BLUE, YELLOW, ORANGE, AQUA, VIOLET]):
        a1.plot(eq.index, eq, color=color, lw=1.7, label=name)
        a2.plot(eq.index, (eq / eq.cummax() - 1) * 100, color=color, lw=1.2)
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}x"))
    a1.yaxis.set_minor_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}x"))
    a1.set_title(f"BTC 與黃金的趨勢策略（同一組參數），{idx[0]:%Y-%m-%d} 起（對數刻度）")
    a1.legend(frameon=False, loc="upper left", fontsize=9)
    a2.set_title("回撤（%）")
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.text(0.01, 0.003, "黃金價格：幣安 PAXGUSDT；BTC：幣安 BTCUSDT 永續；已扣手續費與持有成本",
             color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "gold.png", dpi=150)
    plt.close(fig)

    check = ""
    if "corr" in info:
        check = (f"和幣安 XAUUSDT 永續重疊 {info['overlap_days']} 天：日報酬相關 {info['corr']:.3f}、"
                 f"價差中位數 {info['spread_median']:+.2%}；XAUUSDT 資金費率年化平均 "
                 f"{info['xau_funding_ann']:+.1%}（{info['xau_funding_neg']:.0%} 的日子為負）。")
    lines = [
        "# 黃金：趨勢策略與 BTC 組合",
        "",
        f"黃金價格用幣安現貨 PAXGUSDT（{info['start']:%Y-%m-%d} ~ {info['end']:%Y-%m-%d}，"
        f"年化波動 {info['vol']:.1%}）。{check}",
        "趨勢訊號完全沿用 BTC 的 v2 參數（20/60/120 日 × 波動率目標 40%），沒有為黃金調整。",
        "",
        "![黃金與組合](gold.png)",
        "",
        "## 1. 黃金的四種做法",
        "",
        gold_table.to_markdown(index=False),
        "",
        "## 2. BTC 趨勢 ＋ 黃金",
        "",
        f"BTC 趨勢 v2 與黃金趨勢（F）的日報酬相關係數：全部日子 {corr_all:.2f}；"
        f"至少一邊有持倉的日子 {corr_active:.2f}（越低分散效果越好）。",
        "",
        combo_table.to_markdown(index=False),
        "",
        "各年度：",
        "",
        yearly.to_markdown(),
        "",
        "## 限制",
        "",
        "- PAXG 是黃金代幣，週末也交易；真正的黃金期貨週末休市、週一可能跳空。",
        "- 永續合約的資金費率只有 XAUUSDT 上市以來（2025-12 起）的數據，用它的平均值套用到整段期間。",
        "- 期貨展期成本用固定 4%／年估計，實際隨美元利率變動（2020–2021 年接近 0%）。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
