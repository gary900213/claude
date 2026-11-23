"""放貸機器人能提升多少？用 Bitfinex 真實逐筆放貸成交紀錄重播模擬。

數據：Bitfinex 公開 API /v2/trades/fUSD/hist（每筆：時間、金額、日利率、天期），最近 N 天。
      存在 data/raw/bitfinex_trades_fUSD.pkl（不進 git）。

模擬（本金 1 萬美元，拆 10 份；每份「空著」時掛一張單）：
- 掛單利率 = 過去 24 小時成交利率的某個分位數（依成交量加權）
- 成交判斷（保守）：之後出現「利率嚴格高於我的掛單」的成交，才算我被借走，並以我的掛單利率計息
  （利率比我高的成交代表比我便宜的掛單已被吃完；剛好等於我的利率時可能還排在別人後面，不算）
- 借出天期：預設 2 天；「鎖長天期」版本在掛單年化 ≥ 門檻時改借 30 天
- 「逾時降價」版本：掛超過 N 小時沒借出，就改掛中位數
- 平台抽成 15%；機器人訂閱費另計（例如 Willy）

比較：
- 被動：每份都掛過去 24 小時中位數、2 天期（約等於不用機器人、掛市場一般利率）
- 階梯：10 份分別掛 50%～95% 分位
- 階梯＋鎖 30 天、階梯＋逾時降價、階梯＋兩者

用法：python -m quant.lending_bot [--days 60]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "bitfinex_trades_fUSD.pkl"
OUT = ROOT / "docs" / "lending_bot"
API = "https://api-pub.bitfinex.com/v2/trades/{sym}/hist"
FEE = 0.15
CAPITAL, TRANCHES = 10_000.0, 10
LOCK_ANN = 0.15          # 掛單年化（扣抽成前）≥ 15% 時鎖 30 天
TIMEOUT_H = 6
# Willy 年費（2026-10 比較文章所列，美元計；以官網為準）
WILLY_PLANS = [(10_000, 86), (100_000, 196), (200_000, 396)]


# ---------------------------------------------------------------- 數據

def download(days: int, sym: str = "fUSD") -> pd.DataFrame:
    end = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    start = end - days * 86_400_000
    old = pd.read_pickle(RAW) if RAW.exists() else pd.DataFrame(columns=["id", "mts", "amount", "rate", "period"])
    have_min = int(old["mts"].min()) if len(old) else None
    have_max = int(old["mts"].max()) if len(old) else None
    frames, cursor = [old], end
    while cursor > start:
        if have_min is not None and have_min <= cursor <= have_max:
            cursor = have_min - 1  # 中間已經有了，跳過
            continue
        for attempt in range(5):
            r = requests.get(API.format(sym=sym), params={"limit": 10000, "end": cursor, "sort": -1}, timeout=60)
            if r.status_code == 429:
                time.sleep(30)
                continue
            r.raise_for_status()
            break
        rows = r.json()
        if not rows:
            break
        df = pd.DataFrame(rows, columns=["id", "mts", "amount", "rate", "period"])
        frames.append(df)
        cursor = int(df["mts"].min()) - 1
        print(f"[lending_bot] 下載到 {pd.Timestamp(cursor, unit='ms'):%Y-%m-%d %H:%M}，{len(df)} 筆", flush=True)
        time.sleep(2.5)  # 公開 API 頻率限制
    out = pd.concat(frames).drop_duplicates("id").sort_values("mts")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    out.to_pickle(RAW)
    return out


# ---------------------------------------------------------------- 模擬

def rolling_quantiles(t: pd.DataFrame, qs: list[float]) -> pd.DataFrame:
    """每小時算一次「過去 24 小時」成交量加權的利率分位數（只用過去資料）。"""
    t = t.assign(vol=t["amount"].abs())
    hours = pd.date_range(t.index[0].ceil("h") + pd.Timedelta("24h"), t.index[-1].floor("h"), freq="h")
    rows = []
    for h in hours:
        w = t.loc[h - pd.Timedelta("24h"): h]
        order = np.argsort(w["rate"].values)
        r, v = w["rate"].values[order], w["vol"].values[order]
        cum = np.cumsum(v) / v.sum()
        rows.append([r[min(np.searchsorted(cum, q), len(r) - 1)] for q in qs])
    return pd.DataFrame(rows, index=hours, columns=qs)


def simulate(t: pd.DataFrame, quant: pd.DataFrame, tranche_q: list[float], lock: bool, timeout: bool) -> dict:
    """事件式模擬。t 是逐筆成交（index = 時間），quant 是每小時的分位數表。"""
    times = t.index.values.astype("datetime64[s]").astype(np.int64)
    rates = t["rate"].values
    qtimes = quant.index.values.astype("datetime64[s]").astype(np.int64)
    qvals = quant.values
    qcols = list(quant.columns)
    size = CAPITAL / TRANCHES
    start, end = qtimes[0], qtimes[-1]
    # 每份的狀態：free_at（何時空出來）、offer（掛單利率）、posted（掛單時間）
    state = [{"free_at": start, "offer": None, "posted": None, "q": q} for q in tranche_q]
    interest, lent_seconds = 0.0, 0.0
    i0 = np.searchsorted(times, start)

    def quantile_at(ts, q):
        k = max(np.searchsorted(qtimes, ts, side="right") - 1, 0)
        return qvals[k][qcols.index(q)]

    for i in range(i0, len(times)):
        ts, r = times[i], rates[i]
        if ts > end:
            break
        for s in state:
            if ts < s["free_at"]:
                continue
            if s["offer"] is None or (timeout and ts - s["posted"] > TIMEOUT_H * 3600 and s["q"] != 0.5):
                q = s["q"] if s["offer"] is None else 0.5
                s["offer"], s["posted"] = quantile_at(ts, q), ts
                if s["offer"] is not None and q == 0.5 and s["q"] != 0.5:
                    s["q_used"] = 0.5
            if r > s["offer"]:
                days = 30 if (lock and s["offer"] * 365 >= LOCK_ANN) else 2
                dur = min(days * 86400, end - ts)
                interest += size * s["offer"] * dur / 86400
                lent_seconds += size * dur
                s["free_at"] = ts + days * 86400
                s["offer"], s["posted"] = None, None
    total = CAPITAL * (end - start)
    gross = interest / CAPITAL / ((end - start) / 86400) * 365
    return {"毛年化": gross, "淨年化（扣 15%）": gross * (1 - FEE), "資金使用率": lent_seconds / total}


def term_and_baseline(t: pd.DataFrame) -> list[str]:
    """更合理的被動基準（掛低一點確保借得出去）與「直接借長天期」的比較。"""
    rows = []
    q2 = rolling_quantiles(t, [0.3])
    r = simulate(t, q2, [0.3] * TRANCHES, False, False)
    rows.append({"做法（不用機器人）": "2 天期，掛 30% 分位（幾乎都借得出去）",
                 "淨年化": f"{r['淨年化（扣 15%）']:.2%}", "資金使用率": f"{r['資金使用率']:.1%}"})
    long = t[t["period"] >= 30]
    ql = rolling_quantiles(long, [0.5])
    global LOCK_ANN
    old, LOCK_ANN = LOCK_ANN, 0.0
    try:
        r = simulate(long, ql, [0.5] * TRANCHES, True, False)
    finally:
        LOCK_ANN = old
    rows.append({"做法（不用機器人）": "30 天期，掛 30 天以上成交的中位數",
                 "淨年化": f"{r['淨年化（扣 15%）']:.2%}", "資金使用率": f"{r['資金使用率']:.1%}"})
    per = []
    for p in (2, 7, 30, 120):
        s = t[t["period"] == p]
        if len(s):
            per.append({"天期": f"{p} 天", "量加權淨年化": f"{(s['rate'] * s['amount'].abs()).sum() / s['amount'].abs().sum() * 365 * (1 - FEE):.2%}",
                        "佔成交額": f"{s['amount'].abs().sum() / t['amount'].abs().sum():.0%}"})
    return ["## 不用機器人的兩個簡單做法", "",
            "上表的「被動」掛中位數、而且要有人以更高利率成交才算借出，使用率只有約 76%，基準偏低。"
            "實際用 FRR 或掛低一點，幾乎都借得出去：", "",
            pd.DataFrame(rows).to_markdown(index=False), "",
            "各天期的成交利率（長天期明顯較高）：", "", pd.DataFrame(per).to_markdown(index=False), ""]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args(argv)
    t = pd.read_pickle(RAW) if args.no_download and RAW.exists() else download(args.days)
    t = t.assign(time=pd.to_datetime(t["mts"], unit="ms", utc=True)).set_index("time").sort_index()
    t = t[t.index >= t.index[-1] - pd.Timedelta(days=args.days)]
    qs = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
    quant = rolling_quantiles(t, qs)

    tests = {
        "被動（全部掛中位數、2 天期）": ([0.5] * TRANCHES, False, False),
        "階梯（50%～95% 分位）": (qs, False, False),
        "階梯＋高利率鎖 30 天": (qs, True, False),
        f"階梯＋逾時 {TIMEOUT_H} 小時降價": (qs, False, True),
        "階梯＋鎖 30 天＋逾時降價": (qs, True, True),
        "只掛高分位（80%～95%）": ([0.8, 0.8, 0.85, 0.85, 0.9, 0.9, 0.95, 0.95, 0.95, 0.95], False, False),
    }
    rows = []
    for name, (tq, lock, to) in tests.items():
        res = simulate(t, quant, tq, lock, to)
        rows.append({"策略": name, **res})
    df = pd.DataFrame(rows)
    base = df.loc[0, "淨年化（扣 15%）"]
    df["比被動多"] = df["淨年化（扣 15%）"] - base
    show = df.copy()
    for c in ["毛年化", "淨年化（扣 15%）", "資金使用率"]:
        show[c] = show[c].map(lambda v: f"{v:.2%}")
    show["比被動多"] = show["比被動多"].map(lambda v: f"{v:+.2%}")

    best = df["比被動多"].max()
    fees = pd.DataFrame([{"本金（美元）": f"{cap:,}", "Willy 年費（美元）": fee,
                          "年費佔本金": f"{fee / cap:.2%}",
                          "最佳策略多賺（美元／年）": f"{best * cap:,.0f}",
                          "扣年費後淨多賺": f"{best * cap - fee:+,.0f}"} for cap, fee in WILLY_PLANS])

    vwap = (t["rate"] * t["amount"].abs()).sum() / t["amount"].abs().sum()
    per = t.groupby("period")["amount"].apply(lambda a: a.abs().sum())
    lines = [
        "# 放貸機器人能提升多少？（Bitfinex 美元，逐筆成交重播）",
        "",
        f"期間 {t.index[0]:%Y-%m-%d} ~ {t.index[-1]:%Y-%m-%d}，{len(t):,} 筆成交、總額 {t['amount'].abs().sum() / 1e6:,.0f}M 美元；"
        f"全部成交的量加權年化 {vwap * 365:.2%}（扣抽成 {vwap * 365 * (1 - FEE):.2%}）；"
        f"2 天期佔成交額 {per.get(2, 0) / per.sum():.0%}。",
        "",
        f"本金 {CAPITAL:,.0f} 美元拆 {TRANCHES} 份。成交判斷：之後有利率**高於**我的掛單的成交才算借出（保守）。",
        "",
        show.to_markdown(index=False),
        "",
        *term_and_baseline(t),
        "## 扣掉 Willy 訂閱費後",
        "",
        "Willy 年費取自 2026-10 的比較文章（入門 86U／1 萬、 中階 196U／10 萬、高階 396U／20 萬），以官網為準。",
        "",
        fees.to_markdown(index=False),
        "",
        "## 限制",
        "",
        "- 只有最近幾十天的資料；利率暴衝的機會有沒有出現，對結果影響很大。",
        "- 假設本金很小，不會影響市場；資金很大時，高利率的單吃不完。",
        "- 鎖 30 天的版本在期末還沒到期的部分，只計到期末為止的利息。",
        "",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
