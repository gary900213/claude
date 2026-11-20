"""多幣種驗證：把在 BTC 上凍結的策略，原封不動套用到其他主流幣。

這些幣的數據完全沒參與過參數挑選，是最乾淨的樣本外測試。
幣種挑的是「2020 年就已是主流、幣安有永續合約」的幣，避免只挑現在還紅的幣（存活者偏差）。

比較三個版本（同樣的參數、同樣 0.10 不交易區間、訊號當天收盤執行）：
- A 只用趨勢（永續）：趨勢 × 波動率目標
- B 凍結策略（永續）：A + 散戶多空比 z > 1 或持倉量水位 z > 1 時空手
- C 凍結策略（現貨）：B 改用現貨執行，不付資金費率，但現貨手續費較高（12 bps）

用法：python -m quant.run_multi   （先跑 python -m quant.history <幣種...>）
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
from .features import add_features  # noqa: E402
from .history import file_names, load_daily  # noqa: E402
from .paper import STRATEGY, compute  # noqa: E402
from .run_filters import block_bootstrap_prob  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "multi"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT", "LINKUSDT", "ADAUSDT"]
SPOT_COST_BPS = 12.0
OOS_START = "2022-07-01"
BLUE, ORANGE, AQUA, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#52514e"


def strategies(d: pd.DataFrame) -> dict[str, bt.Result]:
    c = compute(d)
    band = STRATEGY["rebalance_band"]
    trend = bt.apply_band(c["trend"].clip(lower=0) * c["vol_scale"], band)
    frozen = bt.apply_band(c["target_pos"], band)
    return {
        "A 只用趨勢": bt.run("A", d["ret"], trend, STRATEGY["cost_bps"], d["funding_day"]),
        "B 凍結策略（永續）": bt.run("B", d["ret"], frozen, STRATEGY["cost_bps"], d["funding_day"]),
        "C 凍結策略（現貨）": bt.run("C", d["ret"], frozen, SPOT_COST_BPS, None),
        "現貨買入持有": bt.run("H", d["ret"], pd.Series(1.0, index=d.index), SPOT_COST_BPS, None),
    }


def first_ready(d: pd.DataFrame) -> pd.Timestamp:
    """過濾指標與趨勢都算得出來的第一天（之前的日子過濾條件不會生效，比較不公平）。"""
    ok = d["ls_z90"].notna() & d["oi_z90"].notna() & d["rv_30d"].notna()
    return max(ok[ok].index.min(), d.index[120])


def sliced(r: bt.Result, start, end=None) -> bt.Result:
    return bt.Result(r.name, r.daily.loc[start:end])


def fmt(st: dict) -> dict:
    return {"年化報酬": f"{st['年化報酬']:+.1%}", "夏普值": f"{st['夏普值']:.2f}",
            "最大回撤": f"{st['最大回撤']:.1%}", "平均曝險": f"{st['平均曝險']:.2f}x"}


def quintiles(d: pd.DataFrame, feat: str) -> list[str]:
    x = d[[feat, "fwd_7d"]].dropna()
    q = pd.qcut(x[feat], 5, labels=False) + 1
    return [f"{m:+.1%}" for m in x.groupby(q)["fwd_7d"].mean()]


def sharpe_of(net: pd.Series) -> float:
    return float(net.mean() / net.std() * np.sqrt(bt.DAYS_PER_YEAR)) if net.std() > 0 else float("nan")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data, results, starts = {}, {}, {}
    for sym in SYMBOLS:
        if not file_names(sym)["daily"].exists():
            print(f"[multi] 略過 {sym}：沒有歷史數據（先跑 python -m quant.history {sym}）")
            continue
        d = add_features(load_daily(sym))
        d = d[d["close"].notna()]
        data[sym], results[sym], starts[sym] = d, strategies(d), first_ready(d)

    # 1) 各幣種表現
    rows = []
    for sym, res in results.items():
        st0 = starts[sym]
        for period, (s, e) in {"全期間": (st0, None), "2022-07 起": (OOS_START, None)}.items():
            row = {"幣種": sym.removesuffix("USDT"), "期間": f"{period}（{pd.Timestamp(s):%Y-%m} 起）"
                   if period == "全期間" else period}
            for name, r in res.items():
                st = bt.stats(sliced(r, s, e))
                row[f"{name[:1] if name[0] in 'ABC' else '持有'} 夏普"] = f"{st['夏普值']:.2f}"
                row[f"{name[:1] if name[0] in 'ABC' else '持有'} 回撤"] = f"{st['最大回撤']:.0%}"
            a, b = sliced(res["A 只用趨勢"], s, e).net, sliced(res["B 凍結策略（永續）"], s, e).net
            row["B 勝 A 機率"] = f"{block_bootstrap_prob(b, a):.0%}"
            rows.append(row)
    per_asset = pd.DataFrame(rows).set_index(["幣種", "期間"])

    # 2) 等權重投資組合（每個幣 1/N 資金，各自已做波動率目標）
    common = max(starts.values())
    port_rows, port_eq = [], {}
    for name in ["A 只用趨勢", "B 凍結策略（永續）", "C 凍結策略（現貨）", "現貨買入持有"]:
        nets = pd.DataFrame({sym: res[name].daily["net"] for sym, res in results.items()}).loc[common:]
        pos = pd.DataFrame({sym: res[name].daily["pos"] for sym, res in results.items()}).loc[common:]
        net = nets.mean(axis=1)
        r = bt.Result(name, pd.DataFrame({"net": net, "pos": pos.mean(axis=1), "cost": 0.0, "funding": 0.0}))
        port_eq[name] = (1 + net).cumprod()
        for period, s in {"全期間": None, "2022-07 起": OOS_START}.items():
            port_rows.append({"組合": f"{len(results)} 幣等權重｜{name}", "期間": period, **fmt(bt.stats(r, s))})
    for name in ["A 只用趨勢", "B 凍結策略（永續）"]:
        r = sliced(results["BTCUSDT"][name], common)
        for period, s in {"全期間": None, "2022-07 起": OOS_START}.items():
            port_rows.append({"組合": f"只有 BTC｜{name}", "期間": period, **fmt(bt.stats(r, s))})
    portfolio = pd.DataFrame(port_rows).set_index(["組合", "期間"])

    # 3) 策略報酬相關性（分散效果）
    b_nets = pd.DataFrame({s.removesuffix("USDT"): r["B 凍結策略（永續）"].daily["net"]
                           for s, r in results.items()}).loc[common:]
    corr = b_nets[(b_nets != 0).any(axis=1)].corr()
    avg_corr = corr.values[np.triu_indices_from(corr, 1)].mean()

    # 4) 指標分組：散戶多空比、持倉量水位越高，之後 7 天越差嗎？
    qrows = []
    for sym, d in data.items():
        for feat, lab in (("ls_z90", "散戶多空比 z"), ("oi_z90", "持倉量水位 z")):
            qrows.append({"幣種": sym.removesuffix("USDT"), "指標": lab,
                          **dict(zip([f"Q{i}" for i in range(1, 6)], quintiles(d, feat)))})
    qtab = pd.DataFrame(qrows).set_index(["指標", "幣種"]).sort_index()

    # 5) 事後檢查：兩個過濾條件拆開看（看過上面結果後才做的測試，只能當參考）
    split_rows, split_nets = [], {}
    for sym, d in data.items():
        c = compute(d)
        base = c["trend"].clip(lower=0) * c["vol_scale"]
        variants = {"A 只用趨勢": base, "B 雙過濾": c["target_pos"],
                    "D 只用散戶多空比": base.where(~c["filter_ls"], 0.0),
                    "E 只用持倉量水位": base.where(~c["filter_oi"], 0.0)}
        row = {"幣種": sym.removesuffix("USDT")}
        for k, p in variants.items():
            r = bt.run("", d["ret"], bt.apply_band(p, STRATEGY["rebalance_band"]),
                       STRATEGY["cost_bps"], d["funding_day"])
            row[k] = f"{bt.stats(sliced(r, starts[sym]))['夏普值']:.2f}"
            split_nets.setdefault(k, {})[sym] = r.daily["net"]
        split_rows.append(row)
    row = {"幣種": f"{len(data)} 幣組合"}
    for k, v in split_nets.items():
        net = pd.DataFrame(v).loc[common:].mean(axis=1)
        row[k] = f"{sharpe_of(net):.2f}"
    split_rows.append(row)
    split = pd.DataFrame(split_rows)

    # 圖 1：各幣種 A vs B（對數刻度）
    n = len(results)
    cols = 2
    rws = int(np.ceil((n + 1) / cols))
    fig, axes = plt.subplots(rws, cols, figsize=(11, 2.6 * rws), sharex=True)
    axes = axes.ravel()
    for ax, (sym, res) in zip(axes, results.items()):
        for name, color in (("A 只用趨勢", BLUE), ("B 凍結策略（永續）", ORANGE)):
            eq = (1 + sliced(res[name], starts[sym]).net).cumprod()
            ax.plot(eq.index, eq, color=color, lw=1.5, label=name)
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}x"))
        ax.yaxis.set_minor_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}x"))
        ax.set_title(sym.removesuffix("USDT"), fontsize=11)
    ax = axes[n]
    for name, color in (("A 只用趨勢", BLUE), ("B 凍結策略（永續）", ORANGE), ("C 凍結策略（現貨）", AQUA)):
        ax.plot(port_eq[name].index, port_eq[name], color=color, lw=1.8, label=name)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}x"))
    ax.yaxis.set_minor_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}x"))
    ax.set_title(f"{n} 幣等權重組合", fontsize=11)
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    for extra in axes[n + 1:]:
        extra.set_visible(False)
    for a in axes:
        a.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("凍結策略套用到其他幣種（參數完全沒看過這些幣）", x=0.01, ha="left",
                 fontsize=12, fontweight="bold")
    fig.text(0.01, 0.003, "藍 = A 只用趨勢　橙 = B 加散戶多空比與持倉量過濾　綠 = C 現貨執行；已扣成本與資金費率",
             color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "equity.png", dpi=150)
    plt.close(fig)

    lines = [
        "# 多幣種驗證",
        "",
        f"凍結策略 `{STRATEGY['version']}` 的參數只在 BTC 上挑過，這裡原封不動套用到其他幣。"
        "每個幣從「過濾指標算得出來的第一天」開始比。",
        "",
        "- A：只用趨勢（永續）　B：凍結策略（永續）　C：凍結策略（現貨，手續費 12 bps、不付資金費率）",
        "- 「B 勝 A 機率」：20 天區塊重抽 2000 次，B 夏普高於 A 的比例（90% 以上才算可靠）",
        "",
        "![各幣種淨值](equity.png)",
        "",
        "## 1. 各幣種",
        "",
        per_asset.reset_index().to_markdown(index=False),
        "",
        f"## 2. 等權重投資組合（{common:%Y-%m-%d} 起，所有幣都有數據）",
        "",
        portfolio.reset_index().to_markdown(index=False),
        "",
        f"## 3. B 策略各幣報酬的相關係數（平均 {avg_corr:.2f}，越低分散效果越好）",
        "",
        corr.round(2).to_markdown(),
        "",
        "## 4. 指標分 5 組後，之後 7 天平均報酬（Q5 = 指標最高的 20%）",
        "",
        "如果「指標越高、之後越差」在多數幣種都成立，過濾條件才比較可信。",
        "",
        qtab.reset_index().to_markdown(index=False),
        "",
        "## 5. 事後檢查：兩個過濾條件拆開（夏普值，各幣從過濾指標可用起）",
        "",
        "注意：這是看過上面結果後才做的測試，屬於事後挑選，只能當參考，不能當成新的驗證。",
        "",
        split.to_markdown(index=False),
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
