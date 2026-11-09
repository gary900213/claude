"""跑基準策略回測，輸出圖表與 Markdown 報告到 docs/backtest/。

用法：python -m quant.run_baseline
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 套用共用的圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .history import load_daily  # noqa: E402
from .strategies import BASELINES, buy_and_hold, trend_signal, vol_scale  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "backtest"
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"]  # 類別色，固定順序
TEXT_2 = "#52514e"

PERIODS = [("全期間", None, None), ("2020–2022", None, "2022-12-31"), ("2023 至今", "2023-01-01", None)]


def pct(x):
    return "—" if pd.isna(x) else f"{x:+.1%}"


def fmt_stats(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    for c in ["年化報酬", "最大回撤", "成本拖累/年"]:
        t[c] = t[c].map(pct)
    t["年化波動"] = t["年化波動"].map(lambda v: f"{v:.1%}")
    for c in ["夏普值", "索提諾", "卡瑪比"]:
        t[c] = t[c].map(lambda v: f"{v:.2f}")
    t["平均曝險"] = t["平均曝險"].map(lambda v: f"{v:.2f}x")
    t["年換手"] = t["年換手"].map(lambda v: f"{v:.1f}x")
    return t


def sensitivity(d: pd.DataFrame, start) -> list[str]:
    """趨勢（只做多）在不同回看週期、成本下的夏普值與最大回撤：數字穩定才代表不是碰巧。"""
    sets = [(10, 30, 60), (20, 60, 120), (30, 90, 180), (50, 100, 200), (60,), (120,), (200,)]
    rows = []
    for lbs in sets:
        pos = trend_signal(d, lbs).clip(lower=0) * vol_scale(d)
        row = {"回看週期（日）": "/".join(map(str, lbs))}
        for cost in (7, 20):
            r = bt.run("", d["ret"], pos, cost_bps=cost, funding_day=d["funding_day"])
            st = bt.stats(bt.Result("", r.daily.loc[start:]))
            row[f"夏普（{cost}bps）"] = f"{st['夏普值']:.2f}"
            row[f"最大回撤（{cost}bps）"] = pct(st["最大回撤"])
        rows.append(row)
    return ["## 參數敏感度：趨勢（只做多）", "",
            "不同回看週期、不同成本假設下的結果。數字差不多，才代表效果不是剛好挑到好參數。", "",
            pd.DataFrame(rows).set_index("回看週期（日）").to_markdown(), ""]


def main() -> int:
    d = load_daily()
    d = d[d["close"].notna()]
    # 現貨買入持有：不付資金費率，是最公平的被動基準
    results = [bt.run("現貨買入持有", d["ret"], buy_and_hold(d), cost_bps=10)]
    results += [bt.run(name, d["ret"], fn(d), funding_day=d["funding_day"])
                for name, fn in BASELINES.items()]
    results[1].name = "永續買入持有"
    # 從第一個所有策略都有訊號的日子開始比（趨勢最長回看 120 天）
    start = d.index[120]
    results = [bt.Result(r.name, r.daily.loc[start:]) for r in results]
    for r in results:  # 重新從 1 起算淨值
        r.daily["equity"] = (1 + r.daily["net"]).cumprod()
        r.daily["drawdown"] = r.daily["equity"] / r.daily["equity"].cummax() - 1

    OUT.mkdir(parents=True, exist_ok=True)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 2]})
    for r, c in zip(results, COLORS):
        a1.plot(r.daily.index, r.daily["equity"], color=c, lw=1.8, label=r.name)
        a2.plot(r.daily.index, r.daily["drawdown"] * 100, color=c, lw=1.4)
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}x"))
    a1.set_title(f"BTC 基準策略淨值（對數刻度，{start:%Y-%m-%d} 起 = 1x，已扣手續費與資金費率）")
    a1.legend(frameon=False, loc="upper left")
    a2.set_title("回撤（%）")
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.text(0.01, 0.005, "數據：Binance BTCUSDT 永續（data.binance.vision）　成本：每單位換手 7 bps",
             color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "equity.png", dpi=150)
    plt.close(fig)

    lines = [
        "# BTC 基準策略回測",
        "",
        f"- 期間：{start:%Y-%m-%d} ~ {d.index[-1]:%Y-%m-%d}（日線，UTC 收盤）",
        "- 成本：每單位換手 7 bps（taker 手續費 5 bps + 滑價 2 bps），並扣除永續合約資金費率",
        "- 波動率目標 40%／年，槓桿上限 1.5 倍；趨勢 = 20／60／120 日報酬正負號平均",
        "- 參數都是常見預設值，沒有用歷史數據調整過",
        "",
        "![淨值與回撤](equity.png)",
        "",
    ]
    for label, s, e in PERIODS:
        lines += [f"## {label}", "", fmt_stats(bt.stats_table(results, s, e)).to_markdown(), ""]
    lines += sensitivity(d, start)
    yr = bt.yearly_returns(results).map(pct)
    yr.index = [f"{y}{'（至今）' if y == d.index[-1].year else ''}" for y in yr.index]
    lines += ["## 各年度報酬", "", yr.to_markdown(), ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
