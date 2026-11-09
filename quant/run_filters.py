"""第三步：在「趨勢（只做多）」上逐一加入衍生品過濾條件，用滾動前推驗證。

做法：
1. 每個過濾條件 = 「指標超過門檻時，把倉位乘上一個比例（0 或 0.5）」。
   參數組合都事先定好，並包含「不使用」這個選項。
2. 滾動前推：測試期每 6 個月一段，從 2022-07 開始。
   每段只用測試期「之前」的全部數據挑出夏普值最好的參數；
   必須比「不使用」高 0.05 以上才採用，否則就不用（避免追逐雜訊）。
3. 把所有測試段接起來，就是「樣本外」績效，跟同期間的基準策略比較。
4. 區塊拆解（block bootstrap）估計「過濾後夏普值 > 基準」的機率。

用法：python -m quant.run_filters
"""
from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .features import FEATURE_LABELS, add_features  # noqa: E402
from .history import load_daily  # noqa: E402
from .strategies import trend_long_only  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "filters"
TEXT_2 = "#52514e"
MIN_IMPROVEMENT = 0.05
TEST_MONTHS = 6


@dataclass
class Filter:
    name: str
    feature: str
    direction: str            # "above"：指標高於門檻時減倉；"below"：低於門檻時減倉
    thresholds: list[float]
    scales: tuple[float, ...] = (0.0, 0.5)
    first_test: str = "2022-07-01"
    hypothesis: str = ""

    def grid(self):
        yield None  # 不使用
        yield from itertools.product(self.thresholds, self.scales)

    def apply(self, d: pd.DataFrame, base: pd.Series, params) -> pd.Series:
        if params is None:
            return base
        thr, scale = params
        x = d[self.feature]
        hit = (x > thr) if self.direction == "above" else (x < thr)
        return base * np.where(hit.fillna(False), scale, 1.0)


FILTERS = [
    Filter("資金費率過熱", "funding_z30", "above", [1.0, 1.5, 2.0],
           hypothesis="資金費率異常偏高 = 多頭擁擠，容易被洗"),
    Filter("資金費率絕對水位", "funding_7d_ann", "above", [0.15, 0.30, 0.50],
           hypothesis="年化資金費率太高時，持倉成本與擁擠風險都高"),
    Filter("持倉量水位偏高", "oi_z90", "above", [1.0, 1.5, 2.0],
           hypothesis="槓桿堆積到相對高點，之後容易去槓桿"),
    Filter("持倉量急增", "oi_chg_7d", "above", [0.10, 0.15, 0.20],
           hypothesis="一週內新增大量槓桿，追高風險大"),
    Filter("散戶過度看多", "ls_z90", "above", [1.0, 1.5, 2.0],
           hypothesis="散戶多空比異常偏多，反向指標"),
    Filter("ETF 持續流出", "etf_7d_musd", "below", [-1000.0, -500.0, 0.0], first_test="2025-01-01",
           hypothesis="機構資金連續流出時減少曝險（ETF 只有 2024 年起的數據，樣本很短）"),
]


def sharpe(net: pd.Series) -> float:
    s = net.std()
    return float(net.mean() / s * np.sqrt(bt.DAYS_PER_YEAR)) if s > 0 else float("nan")


def windows(d: pd.DataFrame, first_test: str):
    start = pd.Timestamp(first_test, tz="UTC")
    end = d.index[-1]
    while start <= end:
        stop = start + pd.DateOffset(months=TEST_MONTHS)
        yield start, min(stop - pd.Timedelta(days=1), end)
        start = stop


def walk_forward(d: pd.DataFrame, base: pd.Series, f: Filter, train_start) -> tuple[pd.Series, list]:
    """回傳樣本外的倉位序列，以及每段選到的參數。"""
    pos = pd.Series(np.nan, index=d.index)
    chosen = []
    cache = {p: bt.run("", d["ret"], f.apply(d, base, p), funding_day=d["funding_day"]).net
             for p in f.grid()}
    for ts, te in windows(d, f.first_test):
        tr = slice(train_start, ts - pd.Timedelta(days=1))
        scores = {p: sharpe(n.loc[tr]) for p, n in cache.items()}
        best = max(scores, key=lambda p: (scores[p], p is None))
        if best is not None and scores[best] < scores[None] + MIN_IMPROVEMENT:
            best = None
        chosen.append((ts, te, best, scores[best] - scores[None]))
        pos.loc[ts:te] = f.apply(d, base, best).loc[ts:te]
    return pos, chosen


def block_bootstrap_prob(a: pd.Series, b: pd.Series, block: int = 20, reps: int = 2000,
                         seed: int = 0) -> float:
    """P(夏普(a) > 夏普(b))，以 20 天區塊重抽保留自相關。"""
    rng = np.random.default_rng(seed)
    x = np.column_stack([a.values, b.values])
    n = len(x)
    nb = int(np.ceil(n / block))
    wins = 0
    for _ in range(reps):
        starts = rng.integers(0, n - block, nb)
        idx = (starts[:, None] + np.arange(block)).ravel()[:n]
        s = x[idx]
        sa = s[:, 0].mean() / s[:, 0].std()
        sb = s[:, 1].mean() / s[:, 1].std()
        wins += sa > sb
    return wins / reps


def fmt_params(f: Filter, p) -> str:
    if p is None:
        return "不使用"
    thr, scale = p
    sign = ">" if f.direction == "above" else "<"
    thr_s = f"{thr:.0%}" if abs(thr) < 1 and f.feature.startswith(("funding_7d", "oi_chg")) else f"{thr:g}"
    return f"{sign} {thr_s} 時倉位 ×{scale:g}"


def run_slice(d: pd.DataFrame, pos: pd.Series, start) -> bt.Result:
    """整段回測後只取 start 之後；第一天的持倉來自窗口外的倉位，一併去掉。"""
    r = bt.run("", d["ret"], pos.fillna(0.0), funding_day=d["funding_day"])
    return bt.Result("", r.daily.loc[start:].iloc[1:])


def main() -> int:
    d = add_features(load_daily())
    d = d[d["close"].notna()]
    base = trend_long_only(d)
    train_start = d.index[120]

    OUT.mkdir(parents=True, exist_ok=True)
    rows, details, oos_pos = [], [], {}
    for f in FILTERS:
        pos, chosen = walk_forward(d, base, f, train_start)
        oos = pos.dropna().index
        fr, br = run_slice(d, pos, oos[0]), run_slice(d, base, oos[0])
        net, bnet = fr.net, br.net
        f_st, b_st = bt.stats(fr), bt.stats(br)
        used = sum(c[2] is not None for c in chosen)
        rows.append({
            "過濾條件": f.name,
            "樣本外期間": f"{oos[0]:%Y-%m} ~ {oos[-1]:%Y-%m}",
            "基準夏普": f"{b_st['夏普值']:.2f}",
            "過濾後夏普": f"{f_st['夏普值']:.2f}",
            "基準回撤": f"{b_st['最大回撤']:.1%}",
            "過濾後回撤": f"{f_st['最大回撤']:.1%}",
            "基準年化": f"{b_st['年化報酬']:+.1%}",
            "過濾後年化": f"{f_st['年化報酬']:+.1%}",
            "採用段數": f"{used}/{len(chosen)}",
            "勝過基準機率": "相同" if np.allclose(net, bnet) else f"{block_bootstrap_prob(net, bnet):.0%}",
            "平均曝險": f"{f_st['平均曝險']:.2f}x（基準 {b_st['平均曝險']:.2f}x）",
        })
        details.append((f, chosen))
        oos_pos[f.name] = pos

    # 組合：每段各自採用在訓練期有效的過濾條件（全部同時套用，都用 2022-07 起的過濾器）
    combo = base.copy()
    combo_pos = pd.Series(np.nan, index=d.index)
    combo_filters = [f for f in FILTERS if f.first_test == "2022-07-01"]
    choices = {f.name: {c[0]: c[2] for c in chosen} for f, chosen in details if f in combo_filters}
    for ts, te in windows(d, "2022-07-01"):
        p = base.copy()
        for f in combo_filters:
            p = f.apply(d, p, choices[f.name][ts])
        combo_pos.loc[ts:te] = p.loc[ts:te]
    oos0 = combo_pos.dropna().index[0]
    cr, br = run_slice(d, combo_pos, oos0), run_slice(d, base, oos0)
    cnet, bnet = cr.net, br.net
    c_st, b_st = bt.stats(cr), bt.stats(br)
    rows.append({
        "過濾條件": "**組合（前 5 項）**", "樣本外期間": f"{oos0:%Y-%m} ~ {d.index[-1]:%Y-%m}",
        "基準夏普": f"{b_st['夏普值']:.2f}", "過濾後夏普": f"{c_st['夏普值']:.2f}",
        "基準回撤": f"{b_st['最大回撤']:.1%}", "過濾後回撤": f"{c_st['最大回撤']:.1%}",
        "基準年化": f"{b_st['年化報酬']:+.1%}", "過濾後年化": f"{c_st['年化報酬']:+.1%}",
        "採用段數": "—", "勝過基準機率": f"{block_bootstrap_prob(cnet, bnet):.0%}",
        "平均曝險": f"{c_st['平均曝險']:.2f}x（基準 {b_st['平均曝險']:.2f}x）",
    })

    # 圖：樣本外淨值（2022-07 起），基準 vs 組合 vs 個別最佳
    fig, ax = plt.subplots(figsize=(11, 5.2))
    eq = lambda n: (1 + n).cumprod()  # noqa: E731
    ax.plot(bnet.index, eq(bnet), color="#2a78d6", lw=2, label="基準：趨勢（只做多）")
    ax.plot(cnet.index, eq(cnet), color="#eb6834", lw=2, label="加入衍生品過濾（組合）")
    ax.set_title("樣本外淨值（2022-07 起，每段參數只用過去數據挑選）")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}x"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(frameon=False, loc="upper left")
    fig.text(0.01, 0.005, "已扣 7 bps 換手成本與資金費率", color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "oos_equity.png", dpi=150)
    plt.close(fig)

    # 分組分析表
    q_rows = []
    for feat, lab in FEATURE_LABELS.items():
        x = d[[feat, "fwd_7d"]].dropna()
        q = pd.qcut(x[feat], 5, labels=False) + 1
        g = x.groupby(q)["fwd_7d"]
        q_rows.append({"指標": lab, **{f"Q{i}": f"{m:+.2%}" for i, m in g.mean().items()},
                       "Q5 上漲機率": f"{(x[q == 5]['fwd_7d'] > 0).mean():.0%}", "樣本天數": len(x)})

    lines = [
        "# 第三步：衍生品指標過濾",
        "",
        "基準 = 趨勢（只做多，20/60/120 日 + 波動率目標 40%）。每個過濾條件在指標過熱時把倉位乘以 0 或 0.5。",
        "",
        "## 1. 初步檢查：各指標分 5 組後，之後 7 天的平均報酬",
        "",
        "Q1 = 指標最低的 20% 天數，Q5 = 最高的 20%。全樣本平均 7 日報酬 "
        f"{d['fwd_7d'].mean():+.2%}。注意：7 日報酬彼此重疊，這張表只能看方向，不能當顯著性。",
        "",
        pd.DataFrame(q_rows).set_index("指標").to_markdown(),
        "",
        "## 2. 滾動前推（樣本外）結果",
        "",
        f"每 {TEST_MONTHS} 個月一段，只用之前的數據挑參數；需比「不使用」夏普高 {MIN_IMPROVEMENT} 以上才採用。"
        "「勝過基準機率」是以 20 天區塊重抽 2000 次，過濾後夏普值高於基準的比例；"
        "**低於 90% 都不能算可靠的改善**。",
        "",
        pd.DataFrame(rows).set_index("過濾條件").to_markdown(),
        "",
        "![樣本外淨值](oos_equity.png)",
        "",
        "## 3. 每段選到的參數",
        "",
    ]
    for f, chosen in details:
        lines += [f"### {f.name}（{FEATURE_LABELS.get(f.feature, f.feature)}）", "",
                  f"假設：{f.hypothesis}", ""]
        lines += [f"- {ts:%Y-%m} ~ {te:%Y-%m}：{fmt_params(f, p)}"
                  + (f"（訓練期夏普 +{imp:.2f}）" if p is not None else "")
                  for ts, te, p, imp in chosen]
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
