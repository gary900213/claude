"""盈虧比（RR）與停利停損（TP/SL）研究：低 RR 高勝率，到底有沒有比較好賺？

用 BTCUSDT 1 小時 K 線（2020–2026），停利與停損距離以 ATR（過去 14 天平均單日波幅）為單位。
- 每筆最多持有 72 小時，到時以收盤價平倉（時間停損）
- 同一小時內同時碰到停利與停損時，一律當作先停損（保守）
- 來回成本 14 bps（手續費＋滑價）

實驗：
1. 隨機進場（每天 UTC 00:00，丟硬幣決定多空）× 各種 TP/SL：示範「沒有優勢時，改 TP/SL 只會改變勝率，
   不會改變期望值」
2. 超跌後做多（過去 24 小時跌幅 < −2 倍日波動標準差）× 低 RR：看進場條件有沒有帶來真正的優勢

用法：python -m quant.rr_study
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .history import OUT as HISTORY_DIR

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "rr"
COST = 0.0014
MAX_HOURS = 72
GRID = [(0.25, 1.0), (0.5, 1.0), (1.0, 1.0), (2.0, 1.0), (3.0, 1.0), (0.5, 2.0), (1.0, 2.0)]


def load() -> pd.DataFrame:
    h = pd.read_csv(HISTORY_DIR / "btcusdt_1h.csv.gz", index_col=0, parse_dates=True)[["open", "high", "low", "close"]]
    day = h.resample("1D").agg({"high": "max", "low": "min", "close": "last"})
    atr = (day["high"] - day["low"]).rolling(14).mean().shift(1)       # 只用前一天以前的資料
    vol = day["close"].pct_change().rolling(30).std().shift(1)
    h["atr"] = atr.reindex(h.index, method="ffill")
    h["dvol"] = vol.reindex(h.index, method="ffill")
    h["ret24"] = h["close"] / h["close"].shift(24) - 1
    return h.dropna()


def run_trade(o, hi, lo, c, i, side, tp, sl):
    """i = 進場那根的索引（以該根開盤價進場）。回傳 (報酬, 結果)。"""
    entry = o[i]
    tp_px = entry + side * tp
    sl_px = entry - side * sl
    for j in range(i, min(i + MAX_HOURS, len(o))):
        hit_sl = lo[j] <= sl_px if side > 0 else hi[j] >= sl_px
        hit_tp = hi[j] >= tp_px if side > 0 else lo[j] <= tp_px
        if hit_sl:  # 同一根兩者都碰到 → 保守算停損
            px = min(o[j], sl_px) if side > 0 else max(o[j], sl_px)  # 跳空穿過停損，以開盤價成交
            return side * (px / entry - 1) - COST, "停損", j
        if hit_tp:
            return side * (tp_px / entry - 1) - COST, "停利", j
    j = min(i + MAX_HOURS, len(o)) - 1
    return side * (c[j] / entry - 1) - COST, "時間到", j


def simulate(h: pd.DataFrame, entries: list[tuple[int, int]], tp_atr: float, sl_atr: float) -> pd.DataFrame:
    o, hi, lo, c, atr = (h[k].values for k in ("open", "high", "low", "close", "atr"))
    rows, busy_until = [], -1
    for i, side in entries:
        if i <= busy_until or i >= len(o):
            continue  # 一次只持有一筆
        r, why, j = run_trade(o, hi, lo, c, i, side, tp_atr * atr[i], sl_atr * atr[i])
        busy_until = j
        rows.append({"time": h.index[i], "ret": r, "result": why, "risk": sl_atr * atr[i] / o[i]})
    return pd.DataFrame(rows)


def summarize(name: str, t: pd.DataFrame, tp: float, sl: float) -> dict:
    rr = tp / sl
    wins = t["result"] == "停利"
    r_mult = t["ret"] / t["risk"]   # 以「停損距離」為 1R 的報酬
    years = (t["time"].iloc[-1] - t["time"].iloc[0]).days / 365
    eq = (1 + t["ret"] * 0.01 / t["risk"]).cumprod()  # 每筆冒 1% 資金的風險
    return {"情境": name, "TP": f"{tp:g} ATR", "SL": f"{sl:g} ATR", "RR": f"{rr:.2f}",
            "損益兩平勝率": f"{1 / (1 + rr):.0%}", "實際停利率": f"{wins.mean():.0%}",
            "時間到": f"{(t['result'] == '時間到').mean():.0%}",
            "每筆平均（R）": f"{r_mult.mean():+.3f}", "每筆平均（%）": f"{t['ret'].mean():+.2%}",
            "筆數": len(t), "每筆冒 1% 時年化": f"{eq.iloc[-1] ** (1 / years) - 1:+.1%}",
            "最長連虧": int(max_losing_streak(t["ret"] < 0))}


def max_losing_streak(loss: pd.Series) -> int:
    best = cur = 0
    for x in loss:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def main() -> int:
    h = load()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    daily_idx = np.where(h.index.hour == 0)[0]
    random_entries = [(i, int(rng.choice([-1, 1]))) for i in daily_idx]
    long_entries = [(i, 1) for i in daily_idx]
    oversold = np.where((h["ret24"] < -2 * h["dvol"]).values)[0]
    oversold_entries = [(i + 1, 1) for i in oversold]  # 訊號那根收盤後，下一根開盤進場
    rows = []
    for tp, sl in GRID:
        rows.append(summarize("隨機多空", simulate(h, random_entries, tp, sl), tp, sl))
    for tp, sl in GRID:
        rows.append(summarize("每天做多", simulate(h, long_entries, tp, sl), tp, sl))
    for tp, sl in GRID:
        t = simulate(h, oversold_entries, tp, sl)
        if len(t) >= 20:
            rows.append(summarize("超跌後做多", t, tp, sl))
    table = pd.DataFrame(rows)

    lines = [
        "# 盈虧比（RR）與停利停損研究",
        "",
        f"BTCUSDT 1 小時 K 線 {h.index[0]:%Y-%m-%d} ~ {h.index[-1]:%Y-%m-%d}。TP／SL 以 ATR（過去 14 天平均單日波幅）"
        f"為單位；最多持有 {MAX_HOURS} 小時；同一小時同時碰到 TP 與 SL 一律算停損；來回成本 {COST:.2%}。",
        "",
        "- RR = TP 距離 ÷ SL 距離；「損益兩平勝率」= 1 ÷ (1 + RR)，勝率要高於它才賺錢（未計成本）",
        "- R = 以停損距離為 1 單位的報酬；「每筆冒 1% 時年化」= 每筆把停損設在虧損總資金 1% 的部位大小下的複利年化",
        "",
        table.to_markdown(index=False),
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
