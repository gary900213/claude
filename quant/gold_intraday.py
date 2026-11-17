"""黃金日內交易：15 分鐘線「突破後回踩前高／前前高區間」研究。

規則在看結果前寫死：
- 波段高點：某根 K 線最高價 ≥ 左右各 PIVOT_N 根的最高價；要等右邊 PIVOT_N 根走完才確認（不偷看未來）
- 前高 H1、前前高 H2 = 最近兩個已確認的波段高點；區間 = [min(H1,H2), max(H1,H2)]
- 區間寬度需在 0.3～3 倍 ATR(14) 之間（太窄或太寬都不算有效區間）
- 先突破：收盤價站上區間上緣 → 之後價格回到上緣時，限價做多（進場價 = 上緣；跳空低開則以開盤價成交）
- 停損：區間下緣 − 0.25 倍 ATR；停利：損益比 1:1；最多持有 32 根（8 小時）
- 進場前收盤跌破區間下緣 → 區間作廢；突破後 1 天內沒回踩 → 作廢；每個區間只做一次；同一時間只持有一筆
- 已突破、等待回踩的區間，不會被之後新確認的波段點（例如突破時的高點）取代
- 做空完全對稱（前低、前前低）
- 進場那根 K 線只檢查停損（保守）；之後同一根同時碰到停利與停損 → 算停損
- 成本（XAUUSDT 合約）：限價進場與停利各 2 bps；停損與時間到出場 5 bps＋滑價 2 bps
- 對照：同樣筆數、同樣停損距離（以 ATR 計）、1:1 停利，但隨機時點與方向，市價進場

數據：幣安現貨 PAXGUSDT 15 分鐘（2020-08 起）與幣安 XAUUSDT 永續 15 分鐘（2025-12 起）。

用法：python -m quant.gold_intraday
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from .carry import SPOT_BASE, SPOT_RAW  # noqa: E402
from .gold_range import _read_ohlc  # noqa: E402
from .history import BASE as FUT_BASE, RAW as FUT_RAW, days, fetch_many, months  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gold_intraday"
PIVOT_N, ATR_N = 5, 14
MIN_W, MAX_W, SL_BUF = 0.3, 3.0, 0.25
MAX_BARS = 32
ZONE_EXPIRE = 96  # 已突破的區間最多等 96 根（1 天）回踩
MAKER, TAKER, SLIP = 0.0002, 0.0005, 0.0002
BLUE, ORANGE, AQUA, RED, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#52514e"


def load_15m(symbol: str, market: str) -> pd.DataFrame:
    base, raw = (SPOT_BASE, SPOT_RAW) if market == "spot" else (FUT_BASE, FUT_RAW)
    today = pd.Timestamp.now(tz="UTC").date()
    this_month = date(today.year, today.month, 1)
    rels = [f"monthly/klines/{symbol}/15m/{symbol}-15m-{y}-{m:02d}.zip" for y, m in months(date(2020, 1, 1), this_month)]
    rels += [f"daily/klines/{symbol}/15m/{symbol}-15m-{d}.zip" for d in days(this_month, today - timedelta(days=1))]
    blobs = fetch_many(rels, base=base, raw=raw)
    x = pd.concat([_read_ohlc(b) for b in blobs])
    x = x[~x.index.duplicated()].sort_index()
    prev = x["close"].shift()
    tr = pd.concat([x["high"] - x["low"], (x["high"] - prev).abs(), (x["low"] - prev).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()
    return x.dropna()


def pivots(values: np.ndarray, n: int, high: bool) -> list[tuple[int, float]]:
    """回傳 (確認時點的索引, 價位)。確認時點 = 波段點之後第 n 根。"""
    s = pd.Series(values)
    win = s.rolling(2 * n + 1, center=True)
    ext = win.max() if high else win.min()
    idx = np.where((s == ext).values)[0]
    out, last = [], None
    for i in idx:
        if last is not None and i - last <= n:  # 平頂／平底只取第一個
            continue
        last = i
        out.append((i + n, float(values[i])))
    return out


def backtest(x: pd.DataFrame, pivot_n: int = PIVOT_N) -> pd.DataFrame:
    o, h, lo, c, atr = (x[k].values for k in ("open", "high", "low", "close", "atr"))
    ph = pivots(h, pivot_n, True)
    pl = pivots(lo, pivot_n, False)
    hq, lq = {i: v for i, v in ph}, {i: v for i, v in pl}
    highs, lows = [], []
    zone = {1: None, -1: None}    # 每個方向目前的區間：{"top","bot","armed","used"}
    pos, rows = None, []

    def new_zone(levels, side, t):
        if len(levels) < 2:
            return None
        a, b = levels[-1], levels[-2]
        top, bot = max(a, b), min(a, b)
        w = (top - bot) / atr[t]
        if not (MIN_W <= w <= MAX_W):
            return None
        return {"top": top, "bot": bot, "armed": False, "since": t}

    for t in range(len(o)):
        # 1) 持倉管理
        if pos is not None:
            side, entry, sl, tp, t0 = pos["side"], pos["entry"], pos["sl"], pos["tp"], pos["t0"]
            hit_sl = lo[t] <= sl if side > 0 else h[t] >= sl
            hit_tp = (h[t] >= tp if side > 0 else lo[t] <= tp) and t > t0
            exit_px = why = None
            if hit_sl:
                exit_px = min(o[t], sl) if side > 0 else max(o[t], sl)
                if t == t0:
                    exit_px = sl
                why, cost = "停損", TAKER + SLIP
            elif hit_tp:
                exit_px, why, cost = tp, "停利", MAKER
            elif t - t0 >= MAX_BARS:
                exit_px, why, cost = c[t], "時間到", TAKER + SLIP
            if exit_px is not None:
                ret = side * (exit_px / entry - 1) - MAKER - cost
                rows.append({"entry_time": x.index[t0], "exit_time": x.index[t], "side": side, "entry": entry,
                             "sl": sl, "tp": tp, "ret": ret, "risk": abs(entry - sl) / entry,
                             "risk_atr": abs(entry - sl) / atr[t0], "result": why})
                pos = None
        # 2) 更新已確認的波段點（只用到 t 為止確認的）
        # 已突破、正在等回踩的區間不被新的波段點取代（突破時的高點本身會變成新的前高）
        for side, q, levels in ((1, hq, highs), (-1, lq, lows)):
            z = zone[side]
            if z is not None and z["armed"] and t - z["since"] > ZONE_EXPIRE:
                zone[side] = z = None
            if t in q:
                levels.append(q[t])
                if z is None or not z["armed"]:
                    zone[side] = new_zone(levels, side, t)
        # 3) 進場：限價單在已突破的區間邊緣
        for side in (1, -1):
            z = zone[side]
            if z is None:
                continue
            edge, far = (z["top"], z["bot"]) if side > 0 else (z["bot"], z["top"])
            if z["armed"] and pos is None:
                touched = lo[t] <= edge if side > 0 else h[t] >= edge
                if touched:
                    entry = edge if (o[t] >= edge if side > 0 else o[t] <= edge) else o[t]
                    beyond = o[t] <= far if side > 0 else o[t] >= far
                    if not beyond:
                        sl = far - side * SL_BUF * atr[t]
                        risk = abs(entry - sl)
                        pos = {"side": side, "entry": entry, "sl": sl, "tp": entry + side * risk, "t0": t}
                        # 進場那根只檢查停損
                        if (lo[t] <= sl) if side > 0 else (h[t] >= sl):
                            rows.append({"entry_time": x.index[t], "exit_time": x.index[t], "side": side,
                                         "entry": entry, "sl": sl, "tp": pos["tp"],
                                         "ret": side * (sl / entry - 1) - MAKER - TAKER - SLIP,
                                         "risk": risk / entry, "risk_atr": risk / atr[t], "result": "停損"})
                            pos = None
                    zone[side] = None  # 每個區間只做一次
                    continue
            # 突破確認／區間作廢（以收盤判斷，下一根才生效）
            # 作廢只適用在「已突破、等回踩」的區間；突破前價格本來就在區間另一側
            if side > 0:
                if not z["armed"] and c[t] > z["top"]:
                    z["armed"], z["since"] = True, t
                elif z["armed"] and c[t] < z["bot"]:
                    zone[side] = None
            else:
                if not z["armed"] and c[t] < z["bot"]:
                    z["armed"], z["since"] = True, t
                elif z["armed"] and c[t] > z["top"]:
                    zone[side] = None
    return pd.DataFrame(rows)


def random_baseline(x: pd.DataFrame, trades: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    o, h, lo, c, atr = (x[k].values for k in ("open", "high", "low", "close", "atr"))
    starts = np.sort(rng.choice(np.arange(len(o) - MAX_BARS - 1), size=len(trades), replace=False))
    risk_atr = rng.choice(trades["risk_atr"].values, size=len(trades))
    rows, busy = [], -1
    for t0, k in zip(starts, risk_atr):
        if t0 <= busy:
            continue
        side = int(rng.choice([-1, 1]))
        entry = o[t0]
        risk = k * atr[t0]
        sl, tp = entry - side * risk, entry + side * risk
        ret, j = None, min(t0 + MAX_BARS, len(o) - 1)
        for t in range(t0, j + 1):
            if (lo[t] <= sl) if side > 0 else (h[t] >= sl):
                ret, j = side * (sl / entry - 1) - TAKER - TAKER - SLIP, t
                break
            if t > t0 and ((h[t] >= tp) if side > 0 else (lo[t] <= tp)):
                ret, j = side * (tp / entry - 1) - TAKER - MAKER, t
                break
        if ret is None:
            ret = side * (c[j] / entry - 1) - TAKER - TAKER - SLIP
        busy = j
        rows.append({"ret": ret, "risk": risk / entry})
    return pd.DataFrame(rows)


def stats(t: pd.DataFrame, years: float) -> dict:
    r = t["ret"] / t["risk"]
    cost_r = ((MAKER + (TAKER + SLIP + MAKER) / 2) / t["risk"]).mean()
    eq = (1 + 0.005 * r).cumprod()  # 每筆冒 0.5%
    return {"筆數": len(t), "每年筆數": f"{len(t) / years:.0f}", "勝率": f"{(t['ret'] > 0).mean():.1%}",
            "停利率": f"{(t['result'] == '停利').mean():.0%}" if "result" in t else "—",
            "每筆期望值（R）": f"{r.mean():+.3f}", "成本約佔（R）": f"{cost_r:.2f}",
            "停損距離中位數": f"{t['risk'].median():.2%}",
            "每筆冒 0.5% 年化": f"{eq.iloc[-1] ** (1 / years) - 1:+.1%}",
            "最大回撤": f"{(eq / eq.cummax() - 1).min():.1%}"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sets = {"PAXG 現貨（2020-08 起）": load_15m("PAXGUSDT", "spot"),
            "XAUUSDT 合約（2025-12 起）": load_15m("XAUUSDT", "futures")}
    rows, yearly, sens, sample = [], {}, [], None
    for name, x in sets.items():
        years = (x.index[-1] - x.index[0]).days / 365
        t = backtest(x)
        rows.append({"數據": name, "策略": "回踩前高／前前高區間（1:1）", **stats(t, years)})
        for side, lab in ((1, "只算做多"), (-1, "只算做空")):
            rows.append({"數據": name, "策略": f"　{lab}", **stats(t[t["side"] == side], years)})
        base = [random_baseline(x, t, s) for s in range(10)]
        rr = pd.DataFrame([stats(b, years) for b in base])
        rows.append({"數據": name, "策略": "對照：隨機進場（10 次平均）", "筆數": int(rr["筆數"].mean()),
                     "每年筆數": "—",
                     "勝率": f"{rr['勝率'].str.rstrip('%').astype(float).mean():.1f}%", "停利率": "—",
                     "每筆期望值（R）": f"{rr['每筆期望值（R）'].astype(float).mean():+.3f}",
                     "成本約佔（R）": "—", "停損距離中位數": "—",
                     "每筆冒 0.5% 年化": f"{rr['每筆冒 0.5% 年化'].str.rstrip('%').astype(float).mean():+.1f}%",
                     "最大回撤": f"{rr['最大回撤'].str.rstrip('%').astype(float).mean():.1f}%"})
        r = t["ret"] / t["risk"]
        yearly[name] = r.groupby(t["entry_time"].dt.year).agg(["size", "mean"])
        for n in (3, 5, 10):
            tn = backtest(x, n)
            sens.append({"數據": name, "波段點左右各幾根": n, "筆數": len(tn), "勝率": f"{(tn['ret'] > 0).mean():.1%}",
                         "每筆期望值（R）": f"{(tn['ret'] / tn['risk']).mean():+.3f}"})
        if name.startswith("XAU"):
            sample = (x, t)
    table = pd.DataFrame(rows)
    yr = pd.concat({k: v.rename(columns={"size": "筆數", "mean": "期望值R"}) for k, v in yearly.items()}, axis=1)
    yr = yr.round(3)
    yr.columns = [f"{a.split('（')[0]} {b}" for a, b in yr.columns]
    yr = yr.astype(object).where(yr.notna(), "—")
    yr.index.name = "年度"

    # 圖：XAUUSDT 最近 3 天的區間與交易
    x, t = sample
    end = x.index[-1]
    win = x.loc[end - pd.Timedelta(days=3):]
    tw = t[t["entry_time"] >= win.index[0]]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8), gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(win.index, win["close"], color=TEXT_2, lw=1.0, label="XAUUSDT 15 分鐘收盤")
    for _, tr in tw.iterrows():
        color = AQUA if tr["ret"] > 0 else RED
        a1.scatter(tr["entry_time"], tr["entry"], marker="^" if tr["side"] > 0 else "v", color=color, s=60, zorder=3)
        a1.hlines([tr["sl"], tr["tp"]], tr["entry_time"], tr["exit_time"], colors=[RED, AQUA], lw=1, linestyles=":")
    a1.set_title("XAUUSDT 最近 3 天的進場（▲多 ▼空；綠 = 賺、紅 = 賠；虛線 = 停損／停利）")
    a1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    a1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    a1.legend(frameon=False, loc="upper left", fontsize=8)
    for (name, xx), color in zip(sets.items(), [BLUE, ORANGE]):
        tt = backtest(xx)
        eq = (1 + 0.005 * tt["ret"] / tt["risk"]).cumprod()
        a2.plot(tt["exit_time"], eq.values, color=color, lw=1.4, label=name)
    a2.axhline(1, color=TEXT_2, lw=0.8)
    a2.set_title("淨值（每筆停損 = 總資金 0.5%，已扣成本）")
    a2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}x"))
    a2.legend(frameon=False, loc="lower left", fontsize=8)
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.tight_layout()
    fig.savefig(OUT / "gold_intraday.png", dpi=150)
    plt.close(fig)

    lines = [
        "# 黃金日內交易：15 分鐘線「突破後回踩前高／前前高區間」",
        "",
        f"規則在看結果前寫死：波段點左右各 {PIVOT_N} 根；區間寬度 {MIN_W}～{MAX_W} 倍 ATR；限價回踩進場；"
        f"停損 = 區間另一端 ∓ {SL_BUF} ATR；停利 1:1；最多 {MAX_BARS} 根（8 小時）。"
        f"成本：掛單 {MAKER:.2%}、吃單 {TAKER:.2%}＋滑價 {SLIP:.2%}。",
        "",
        "![黃金日內](gold_intraday.png)",
        "",
        "## 結果",
        "",
        "R = 停損距離。1:1 時，不算成本的損益兩平勝率是 50%；成本佔掉的 R 越多，需要的勝率越高。",
        "",
        table.to_markdown(index=False),
        "",
        "## 各年度（每筆期望值，R）",
        "",
        yr.to_markdown(),
        "",
        "## 波段點定義的敏感度（事後檢查）",
        "",
        pd.DataFrame(sens).to_markdown(index=False),
        "",
        "## 限制",
        "",
        "- 15 分鐘 K 線看不到 K 線內的先後順序；同一根同時碰到停利停損一律算停損（保守）。",
        "- 限價單假設碰到就成交；實際上價格剛好碰到時不一定輪到你，會讓結果偏樂觀。",
        "- PAXG 早期成交量小，15 分鐘的高低點可能和真正的金價不同；XAUUSDT 只有不到一年的數據。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
