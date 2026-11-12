"""BTC 波動率風險溢酬（Volatility Risk Premium）研究。

問題：選擇權是不是系統性地「太貴」？賣選擇權（尤其恐慌之後）到底穩不穩？

數據：
- 隱含波動率：Deribit DVOL 指數（BTC 30 天隱含波動率，年化 %），公開 API，2021 年起
- 實際波動率：幣安 BTCUSDT 1 小時 K 線（data/history/btcusdt_1h.csv.gz）

做法：
1. 風險溢酬 = 當天 DVOL − 接下來 30 天實際波動率（用每小時報酬算、年化）
2. 模擬每天賣出一組 30 天價平跨式（買權＋賣權，履約價 = 當天價格），以 DVOL 當隱含波動率、
   Black-Scholes 定價（利率 0），持有到期：
   - 不對沖：收權利金、到期付 |S_T − K|
   - Delta 對沖：每天用 BS delta 調整現貨部位，只賺「隱含 vs 實際」波動率的差
   報酬以「標的名目 1 倍」計（例如 1 BTC 名目、全額擔保）
3. 成本：選擇權每組來回 0.3% 名目（手續費＋買賣價差）；對沖每次調整 7 bps
4. 分情境：DVOL 處於歷史高位、7 天內暴衝、BTC 剛大跌後賣出

限制：DVOL 含價外選擇權的偏斜，通常略高於價平隱含波動率，所以溢酬可能略為高估。

用法：python -m quant.vrp
"""
from __future__ import annotations

import sys
from math import erf, sqrt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from .history import OUT as HISTORY_DIR  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "vrp"
DVOL_CSV = HISTORY_DIR / "btc_dvol.csv"
DERIBIT = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
TENOR = 30
OPTION_COST = 0.003      # 跨式來回成本（名目比例）
HEDGE_BPS = 7.0
BLUE, ORANGE, AQUA, RED, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#52514e"


# ---------------------------------------------------------------- 數據

def fetch_dvol() -> pd.Series:
    rows, end = [], 1_900_000_000_000
    while True:
        r = requests.get(DERIBIT, params={"currency": "BTC", "start_timestamp": 0, "end_timestamp": end,
                                          "resolution": "1D"}, timeout=30)
        r.raise_for_status()
        res = r.json()["result"]
        rows += res["data"]
        if not res.get("continuation") or not res["data"]:
            break
        end = res["continuation"]
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).drop_duplicates("ts")
    s = pd.Series(df["close"].values / 100, index=pd.to_datetime(df["ts"], unit="ms", utc=True))
    s = s.sort_index()
    s.index.name = "date"
    return s.rename("dvol")


def load_inputs(refresh: bool = True) -> pd.DataFrame:
    if refresh or not DVOL_CSV.exists():
        dvol = fetch_dvol()
        dvol.to_csv(DVOL_CSV, float_format="%.5f")
    dvol = pd.read_csv(DVOL_CSV, index_col=0, parse_dates=True)["dvol"]
    h = pd.read_csv(HISTORY_DIR / "btcusdt_1h.csv.gz", index_col=0, parse_dates=True)
    close_d = h["close"].resample("1D").last()
    hr = np.log(h["close"]).diff()
    rv_daily_var = hr.pow(2).resample("1D").sum()  # 每日已實現變異數
    d = pd.DataFrame({"close": close_d, "var_d": rv_daily_var}).join(dvol, how="inner")
    # dvol 的日 K「收盤」是當天結束時的值，和收盤價對齊
    # 接下來 30 天的實際波動率（不含今天）
    fwd = d["var_d"][::-1].rolling(TENOR).sum()[::-1].shift(-1)
    d["rv_fwd"] = np.sqrt(fwd * 365 / TENOR)
    past = d["var_d"].rolling(TENOR).sum()
    d["rv_past"] = np.sqrt(past * 365 / TENOR)
    d["vrp"] = d["dvol"] - d["rv_fwd"]
    return d


# ---------------------------------------------------------------- 選擇權

def _ncdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))


def bs_straddle(s: float, k: float, sigma: float, t: float) -> tuple[float, float]:
    """價格與 delta（利率 0）。t 以年計。"""
    if t <= 0 or sigma <= 0:
        return abs(s - k), (1.0 if s > k else -1.0 if s < k else 0.0)
    v = sigma * sqrt(t)
    d1 = (np.log(s / k) + 0.5 * v * v) / v
    d2 = d1 - v
    call = s * _ncdf(d1) - k * _ncdf(d2)
    put = call - (s - k)
    return call + put, 2 * _ncdf(d1) - 1


def short_straddle(closes: np.ndarray, sigma: float, cost: float = OPTION_COST,
                   hedge: bool = False) -> float:
    """closes[0] = 進場價（= 履約價），closes[TENOR] = 到期價。回傳以名目計的報酬。"""
    s0 = closes[0]
    prem, _ = bs_straddle(s0, s0, sigma, TENOR / 365)
    pnl = prem - abs(closes[-1] - s0)
    if hedge:
        pos = 0.0
        for i in range(len(closes) - 1):
            _, delta = bs_straddle(closes[i], s0, sigma, (TENOR - i) / 365)
            target = delta  # 賣出跨式的 delta = −delta，持有 +delta 的現貨來對沖
            pnl -= abs(target - pos) * closes[i] * HEDGE_BPS / 1e4
            pos = target
            pnl += pos * (closes[i + 1] - closes[i])
        pnl -= abs(pos) * closes[-1] * HEDGE_BPS / 1e4  # 到期平掉對沖
    return pnl / s0 - cost


def trades(d: pd.DataFrame, cost: float = OPTION_COST, iv_shift: float = 0.0) -> pd.DataFrame:
    """iv_shift：把 DVOL 往下調整幾個波動率點（例如 −0.02），模擬價平隱含波動率比 DVOL 低的情況。"""
    c = d["close"].values
    rows = []
    for i in range(len(d) - TENOR):
        path = c[i:i + TENOR + 1]
        if not np.isfinite(path).all() or not np.isfinite(d["dvol"].iloc[i]):
            continue
        iv = d["dvol"].iloc[i] + iv_shift
        rows.append({"date": d.index[i], "dvol": d["dvol"].iloc[i], "rv_fwd": d["rv_fwd"].iloc[i],
                     "btc_30d": path[-1] / path[0] - 1,
                     "unhedged": short_straddle(path, iv, cost),
                     "hedged": short_straddle(path, iv, cost, hedge=True)})
    return pd.DataFrame(rows).set_index("date")


def ladder_stats(t: pd.Series) -> dict:
    """每 30 天賣一組（不重疊），30 種起始日各算一次，取中位數與範圍。"""
    res = []
    for k in range(TENOR):
        r = t.iloc[k::TENOR]
        eq = (1 + r).cumprod()
        years = len(r) * TENOR / 365
        res.append({"cagr": eq.iloc[-1] ** (1 / years) - 1,
                    "sharpe": r.mean() / r.std() * sqrt(365 / TENOR),
                    "mdd": (eq / eq.cummax() - 1).min()})
    df = pd.DataFrame(res)
    return {"年化（中位數）": f"{df['cagr'].median():+.1%}",
            "年化範圍": f"{df['cagr'].min():+.1%} ~ {df['cagr'].max():+.1%}",
            "夏普（中位數）": f"{df['sharpe'].median():.2f}",
            "最大回撤（中位數）": f"{df['mdd'].median():.1%}", "最大回撤（最差）": f"{df['mdd'].min():.1%}"}


def describe(x: pd.Series) -> dict:
    return {"筆數": len(x), "平均": f"{x.mean():+.2%}", "中位數": f"{x.median():+.2%}",
            "勝率": f"{(x > 0).mean():.0%}", "最差": f"{x.min():+.1%}", "最好": f"{x.max():+.1%}",
            "最差 5% 平均": f"{x[x <= x.quantile(0.05)].mean():+.1%}"}


def main(refresh: bool = True) -> int:
    d = load_inputs(refresh)
    OUT.mkdir(parents=True, exist_ok=True)
    t = trades(d)
    v = d.dropna(subset=["vrp"])

    # 1) 溢酬總覽與年度
    yearly = v.groupby(v.index.year).agg(隱含波動=("dvol", "mean"), 實際波動=("rv_fwd", "mean"),
                                         溢酬=("vrp", "mean"),
                                         溢酬為正的比例=("vrp", lambda x: (x > 0).mean()))
    for c in ["隱含波動", "實際波動", "溢酬"]:
        yearly[c] = yearly[c].map(lambda x: f"{x * 100:.1f}")
    yearly["溢酬為正的比例"] = yearly["溢酬為正的比例"].map(lambda x: f"{x:.0%}")
    yearly.index.name = "年度（單位：波動率點）"

    # 2) 賣跨式的結果
    strat = pd.DataFrame([{"方式": "不對沖（收租）", **describe(t["unhedged"]), **ladder_stats(t["unhedged"])},
                          {"方式": "每天 Delta 對沖", **describe(t["hedged"]), **ladder_stats(t["hedged"])}])
    cost_rows = []
    for cst in (0.0015, 0.003, 0.006):
        tt = trades(d, cst)
        cost_rows.append({"選擇權來回成本": f"{cst:.2%}", "不對沖 平均": f"{tt['unhedged'].mean():+.2%}",
                          "不對沖 年化": ladder_stats(tt["unhedged"])["年化（中位數）"],
                          "對沖 平均": f"{tt['hedged'].mean():+.2%}",
                          "對沖 年化": ladder_stats(tt["hedged"])["年化（中位數）"]})
    costs = pd.DataFrame(cost_rows)

    # 2b) 逐年（依賣出日）與價平修正
    by_year = t.groupby(t.index.year).agg(
        筆數=("hedged", "size"),
        不對沖_平均=("unhedged", "mean"), 不對沖_勝率=("unhedged", lambda x: (x > 0).mean()),
        對沖_平均=("hedged", "mean"), 對沖_勝率=("hedged", lambda x: (x > 0).mean()))
    for c in ["不對沖_平均", "對沖_平均"]:
        by_year[c] = by_year[c].map(lambda x: f"{x:+.2%}")
    for c in ["不對沖_勝率", "對沖_勝率"]:
        by_year[c] = by_year[c].map(lambda x: f"{x:.0%}")
    by_year.columns = [c.replace("_", " ") for c in by_year.columns]
    by_year.index.name = "賣出年度（每筆 30 天）"
    shift_rows = []
    for sh in (0.0, -0.02, -0.04):
        tt = trades(d, OPTION_COST, sh)
        recent = tt.loc["2025-01-01":]
        shift_rows.append({"隱含波動率": "DVOL" if sh == 0 else f"DVOL {sh * 100:+.0f} 點",
                           "對沖 平均（全期）": f"{tt['hedged'].mean():+.2%}",
                           "對沖 年化（全期）": ladder_stats(tt["hedged"])["年化（中位數）"],
                           "對沖 平均（2025 起）": f"{recent['hedged'].mean():+.2%}",
                           "不對沖 平均（2025 起）": f"{recent['unhedged'].mean():+.2%}"})
    shifts = pd.DataFrame(shift_rows)

    # 3) 情境：只用當天已知的資訊判斷
    pct = t["dvol"].expanding(180).rank(pct=True)
    jump = d["dvol"].diff(7).reindex(t.index)
    drop = (d["close"] / d["close"].shift(7) - 1).reindex(t.index)
    cases = {
        "全部日子": pd.Series(True, index=t.index),
        "DVOL 在歷史前 20% 高": pct >= 0.8,
        "DVOL 在歷史後 20% 低": pct <= 0.2,
        "恐慌：DVOL 7 天內上升 > 15 點": jump > 0.15,
        "BTC 7 天跌 > 15% 之後": drop < -0.15,
        "BTC 7 天漲 > 15% 之後": drop > 0.15,
    }
    case_rows = []
    for name, m in cases.items():
        m = m.fillna(False)
        if m.sum() < 5:
            continue
        sub = t[m]
        case_rows.append({"賣出時機": name, "天數": int(m.sum()),
                          "隱含波動（平均）": f"{sub['dvol'].mean() * 100:.0f}",
                          "之後實際波動": f"{sub['rv_fwd'].mean() * 100:.0f}",
                          "不對沖 平均": f"{sub['unhedged'].mean():+.2%}",
                          "不對沖 勝率": f"{(sub['unhedged'] > 0).mean():.0%}",
                          "不對沖 最差": f"{sub['unhedged'].min():+.1%}",
                          "對沖 平均": f"{sub['hedged'].mean():+.2%}",
                          "對沖 最差": f"{sub['hedged'].min():+.1%}"})
    case_df = pd.DataFrame(case_rows)

    # 3b) 「BTC 7 天跌 > 15% 之後賣」拆成獨立事件（相隔 10 天以上算不同事件）
    days = t.index[(drop < -0.15).fillna(False)]
    ep = (days.to_series().diff() > pd.Timedelta(days=10)).cumsum()
    episodes = pd.DataFrame([{"期間": f"{x.index[0]:%Y-%m-%d} ~ {x.index[-1]:%Y-%m-%d}", "天數": len(x),
                              "DVOL": f"{x['dvol'].mean() * 100:.0f}",
                              "不對沖 平均": f"{x['unhedged'].mean():+.1%}",
                              "對沖 平均": f"{x['hedged'].mean():+.1%}"}
                             for _, x in t.loc[days].groupby(ep.values)])

    worst = t.nsmallest(8, "unhedged").copy()
    worst = pd.DataFrame({"賣出日": worst.index.strftime("%Y-%m-%d"),
                          "當時隱含波動": (worst["dvol"] * 100).round(0),
                          "之後實際波動": (worst["rv_fwd"] * 100).round(0),
                          "BTC 30 天漲跌": worst["btc_30d"].map(lambda x: f"{x:+.0%}"),
                          "不對沖": worst["unhedged"].map(lambda x: f"{x:+.1%}"),
                          "對沖": worst["hedged"].map(lambda x: f"{x:+.1%}")})

    # 圖
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 10), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 2, 3]})
    a1.plot(v.index, v["dvol"] * 100, color=BLUE, lw=1.5, label="隱含波動率（DVOL）")
    a1.plot(v.index, v["rv_fwd"] * 100, color=ORANGE, lw=1.3, label="之後 30 天實際波動率")
    a1.set_title("BTC：選擇權隱含的波動率 vs 事後實際的波動率（年化 %）")
    a1.legend(frameon=False, loc="upper right")
    a2.fill_between(v.index, v["vrp"] * 100, 0, where=v["vrp"] >= 0, color=BLUE, alpha=0.5, lw=0)
    a2.fill_between(v.index, v["vrp"] * 100, 0, where=v["vrp"] < 0, color=RED, alpha=0.6, lw=0)
    a2.axhline(0, color=TEXT_2, lw=0.8)
    a2.set_title("風險溢酬 = 隱含 − 實際（藍 = 賣方賺、紅 = 賣方虧）")
    for col, color, label in (("unhedged", ORANGE, "不對沖"), ("hedged", AQUA, "每天 Delta 對沖")):
        r = t[col].iloc[::TENOR]
        eq = (1 + r).cumprod()
        a3.plot(eq.index, eq, color=color, lw=1.8, label=label)
    a3.set_title("每 30 天賣一組價平跨式的累積淨值（名目 1 倍、已扣成本）")
    a3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.2f}x"))
    a3.legend(frameon=False, loc="upper left")
    a3.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.text(0.01, 0.003, "數據：Deribit DVOL、幣安 BTCUSDT；跨式以 DVOL 用 Black-Scholes 定價，來回成本 0.3%",
             color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "vrp.png", dpi=150)
    plt.close(fig)

    lines = [
        "# BTC 波動率風險溢酬",
        "",
        f"期間：{v.index[0]:%Y-%m-%d} ~ {v.index[-1]:%Y-%m-%d}（{len(v)} 天）。"
        "隱含波動率 = Deribit DVOL；實際波動率 = 接下來 30 天每小時報酬年化。",
        "",
        "![波動率風險溢酬](vrp.png)",
        "",
        "## 1. 隱含 vs 實際（各年度平均）",
        "",
        yearly.to_markdown(),
        "",
        "## 2. 每天賣一組 30 天價平跨式（以名目計、已扣成本）",
        "",
        "「年化」是每 30 天賣一組、不重疊；30 種起始日各算一次後取中位數與範圍，看結果對起始日敏不敏感。",
        "",
        strat.to_markdown(index=False),
        "",
        "成本敏感度：",
        "",
        costs.to_markdown(index=False),
        "",
        "逐年（依賣出日分組，每筆是 30 天的報酬）：",
        "",
        by_year.to_markdown(),
        "",
        "價平修正：DVOL 包含偏斜，通常比價平隱含波動率高；把它往下調幾點，看溢酬還剩多少：",
        "",
        shifts.to_markdown(index=False),
        "",
        "## 3. 什麼時候賣比較好？（只用當天已知的資訊判斷）",
        "",
        case_df.to_markdown(index=False),
        "",
        "「BTC 7 天跌 > 15% 之後賣」拆成獨立事件（樣本很少，結論要保守看）：",
        "",
        episodes.to_markdown(index=False),
        "",
        "## 4. 最慘的幾筆（不對沖）",
        "",
        worst.to_markdown(index=False),
        "",
        "## 限制",
        "",
        "- DVOL 含價外選擇權的偏斜，通常略高於價平隱含波動率，所以權利金與溢酬可能略為高估。",
        "- 實際賣選擇權需要保證金；不對沖的賣方在急漲急跌時可能被要求追繳或強平，回測以全額擔保計。",
        "- 只用日線模擬對沖；盤中跳空時，實際對沖效果會更差。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
