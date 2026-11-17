"""黃金震盪區間均值回歸（布林通道）研究。

規則在看結果前寫死，都是常見預設值：
- 數據：幣安現貨 PAXGUSDT 1 小時 K 線 → 4 小時 K 線（2020-08 起；與 XAUUSDT 合約日報酬相關 0.99）
- 區間：布林通道 20 根均線 ± 2 標準差
- 進場：收盤跌破下緣 → 下一根開盤做多；收盤突破上緣 → 下一根開盤做空
- 停損：1.5 倍 ATR(14)；停利：損益比 1:1（停利距離 = 停損距離）；最多持有 30 根（5 天）
  （對照：停利設在進場當下的中線，也就是傳統布林通道回歸的做法）
- 同一根 K 線同時碰到停利與停損 → 一律算停損；跳空穿過停損以開盤價成交
- 成本：來回 0.12%（XAUUSDT 合約手續費＋滑價）；持倉期間資金費率（多單付、空單收，年化 12.6%）
- 部位：每筆停損時虧總資金 1%（槓桿上限 5 倍）

版本：
- A 不過濾
- B 只在盤整時做：ADX(14) < 20
- C B ＋ 順大趨勢：價格在 200 根均線之上只做多、之下只做空
- 對照：B 的進場次數與時間分布不變，但方向與時點隨機（同樣的停利停損）

用法：python -m quant.gold_range
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .carry import SPOT_BASE, SPOT_RAW  # noqa: E402
from .history import days, fetch_many, months  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gold_range"
BB_N, BB_K, ATR_N, ADX_N, ADX_MAX, TREND_N = 20, 2.0, 14, 14, 20.0, 200
SL_ATR, MAX_BARS = 1.5, 30
COST = 0.0012
FUNDING_ANN = 0.126
RISK = 0.01
MAX_LEV = 5.0
BLUE, ORANGE, AQUA, RED, YELLOW, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#eda100", "#52514e"


# ---------------------------------------------------------------- 數據與指標

def _read_ohlc(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), header=None).iloc[:, :6]
    if not str(df.iloc[0, 0]).isdigit():
        df = df.iloc[1:]
    df.columns = ["t", "open", "high", "low", "close", "volume"]
    t = df["t"].astype("int64")
    t = np.where(t > 10**14, t // 1000, t)  # 2025 起改用微秒
    return df.drop(columns="t").astype(float).set_index(pd.to_datetime(t, unit="ms", utc=True))


def load_4h(symbol: str = "PAXGUSDT") -> pd.DataFrame:
    today = pd.Timestamp.now(tz="UTC").date()
    this_month = date(today.year, today.month, 1)
    rels = [f"monthly/klines/{symbol}/1h/{symbol}-1h-{y}-{m:02d}.zip" for y, m in months(date(2020, 1, 1), this_month)]
    rels += [f"daily/klines/{symbol}/1h/{symbol}-1h-{d}.zip" for d in days(this_month, today - timedelta(days=1))]
    h = pd.concat([_read_ohlc(b) for b in fetch_many(rels, base=SPOT_BASE, raw=SPOT_RAW)])
    h = h[~h.index.duplicated()].sort_index()
    return h.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                 "volume": "sum"}).dropna()


def indicators(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    x["mid"] = x["close"].rolling(BB_N).mean()
    sd = x["close"].rolling(BB_N).std()
    x["upper"], x["lower"] = x["mid"] + BB_K * sd, x["mid"] - BB_K * sd
    prev = x["close"].shift()
    tr = pd.concat([x["high"] - x["low"], (x["high"] - prev).abs(), (x["low"] - prev).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()
    up, dn = x["high"].diff(), -x["low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=x.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=x.index)
    atr_w = tr.ewm(alpha=1 / ADX_N, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / ADX_N, adjust=False).mean() / atr_w
    mdi = 100 * minus.ewm(alpha=1 / ADX_N, adjust=False).mean() / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    x["adx"] = dx.ewm(alpha=1 / ADX_N, adjust=False).mean()
    x["trend_ma"] = x["close"].rolling(TREND_N).mean()
    return x.dropna()


# ---------------------------------------------------------------- 訊號與模擬

def signals(x: pd.DataFrame, version: str) -> list[tuple[int, int]]:
    """回傳 (訊號那根的索引, 方向)。進場在下一根開盤。"""
    long_ = x["close"] < x["lower"]
    short = x["close"] > x["upper"]
    if version in ("B", "C"):
        calm = x["adx"] < ADX_MAX
        long_, short = long_ & calm, short & calm
    if version == "C":
        long_ &= x["close"] > x["trend_ma"]
        short &= x["close"] < x["trend_ma"]
    out = [(i, 1) for i in np.where(long_.values)[0]] + [(i, -1) for i in np.where(short.values)[0]]
    return sorted(out)


def simulate(x: pd.DataFrame, sigs: list[tuple[int, int]], tp_mode: str = "1:1") -> pd.DataFrame:
    """tp_mode："1:1" = 停利距離等於停損距離；"mid" = 停利在進場當下的中線。"""
    o, h, lo, c = (x[k].values for k in ("open", "high", "low", "close"))
    mid, atr = x["mid"].values, x["atr"].values
    rows, busy = [], -1
    hourly_funding = FUNDING_ANN / 365 / 6  # 每根 4 小時
    for i, side in sigs:
        e = i + 1
        if e <= busy or e >= len(o):
            continue
        entry = o[e]
        sl = entry - side * SL_ATR * atr[i]
        tp = entry + side * SL_ATR * atr[i] if tp_mode == "1:1" else mid[i]
        if side * (tp - entry) <= 0:  # 開盤已經越過中線，不做
            continue
        exit_px, why, j = None, "時間到", min(e + MAX_BARS, len(o)) - 1
        for k in range(e, min(e + MAX_BARS, len(o))):
            hit_sl = lo[k] <= sl if side > 0 else h[k] >= sl
            hit_tp = h[k] >= tp if side > 0 else lo[k] <= tp
            if hit_sl:
                exit_px = min(o[k], sl) if side > 0 else max(o[k], sl)
                why, j = "停損", k
                break
            if hit_tp:
                exit_px, why, j = tp, "停利", k
                break
        if exit_px is None:
            exit_px = c[j]
        busy = j
        bars = j - e + 1
        ret = side * (exit_px / entry - 1) - COST - side * hourly_funding * bars
        risk = abs(entry - sl) / entry
        rows.append({"entry_time": x.index[e], "exit_time": x.index[j], "side": side, "ret": ret,
                     "risk": risk, "result": why, "bars": bars})
    return pd.DataFrame(rows)


def random_like(x: pd.DataFrame, sigs: list[tuple[int, int]], seed: int = 0) -> list[tuple[int, int]]:
    rng = np.random.default_rng(seed)
    idx = rng.choice(np.arange(len(x) - 2), size=len(sigs), replace=False)
    return sorted((int(i), int(rng.choice([-1, 1]))) for i in idx)


def equity(t: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    lev = np.minimum(RISK / t["risk"], MAX_LEV)
    r = pd.Series((lev * t["ret"]).values, index=t["exit_time"]).groupby(level=0).sum()
    daily = r.reindex(index, fill_value=0.0)
    return daily


def summary(name: str, t: pd.DataFrame, daily: pd.Series) -> dict:
    r_mult = t["ret"] / t["risk"]
    st = bt.stats(bt.Result(name, pd.DataFrame({"net": daily, "pos": 0.0})))
    loss = (t["ret"] < 0).astype(int).values
    streak = cur = 0
    for v in loss:
        cur = cur + 1 if v else 0
        streak = max(streak, cur)
    return {"版本": name, "筆數": len(t), "筆數/年": f"{len(t) / (len(daily) / 365):.0f}",
            "停利率": f"{(t['result'] == '停利').mean():.0%}", "勝率": f"{(t['ret'] > 0).mean():.0%}",
            "平均賺（R）": f"{r_mult[r_mult > 0].mean():+.2f}", "平均賠（R）": f"{r_mult[r_mult <= 0].mean():+.2f}",
            "每筆期望值（R）": f"{r_mult.mean():+.3f}", "年化（每筆冒 1%）": f"{st['年化報酬']:+.1%}",
            "夏普": f"{st['夏普值']:.2f}", "最大回撤": f"{st['最大回撤']:.1%}", "最長連虧": streak}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    x = indicators(load_4h())
    day_index = pd.date_range(x.index[0].normalize(), x.index[-1].normalize(), freq="D")
    results, rows = {}, []
    for v, label in (("A", "A 不過濾"), ("B", "B 只在盤整（ADX<20）"), ("C", "C 盤整＋順大趨勢")):
        sigs = signals(x, v)
        t = simulate(x, sigs)
        daily = equity(t, day_index)
        results[label] = (t, daily)
        rows.append(summary(label, t, daily))
    t_mid = simulate(x, signals(x, "B"), "mid")
    rows.append(summary("B' 同 B，但停利在中線（RR 約 0.5～0.8）", t_mid, equity(t_mid, day_index)))
    sigs_b = signals(x, "B")
    rand_rows = []
    for seed in range(20):
        t = simulate(x, random_like(x, sigs_b, seed))
        rand_rows.append(summary("對照", t, equity(t, day_index)))
    rr = pd.DataFrame(rand_rows)
    num = lambda col: rr[col].str.rstrip("%").astype(float)  # noqa: E731
    rows.append({"版本": "對照：隨機進場（20 次平均）", "筆數": int(rr["筆數"].mean()), "筆數/年": "—",
                 "停利率": f"{num('停利率').mean():.0f}%", "勝率": f"{num('勝率').mean():.0f}%",
                 "平均賺（R）": "—", "平均賠（R）": "—",
                 "每筆期望值（R）": f"{rr['每筆期望值（R）'].astype(float).mean():+.3f}",
                 "年化（每筆冒 1%）": f"{num('年化（每筆冒 1%）').mean():+.1f}%",
                 "夏普": f"{rr['夏普'].astype(float).mean():.2f}", "最大回撤": f"{num('最大回撤').mean():.1f}%",
                 "最長連虧": int(rr["最長連虧"].mean())})
    table = pd.DataFrame(rows)

    yearly = pd.DataFrame({k: (1 + d).groupby(d.index.year).prod() - 1 for k, (_, d) in results.items()})
    counts = pd.DataFrame({k: t.groupby(t["entry_time"].dt.year).size() for k, (t, _) in results.items()})
    yearly = yearly.map(lambda v: f"{v:+.1%}")
    for k in counts:
        yearly[k] = yearly[k] + counts[k].reindex(yearly.index).fillna(0).astype(int).map(lambda n: f"（{n} 筆）")
    yearly.index.name = "年度"

    # 圖：上 = 最近 90 天價格、通道與 B 的交易；下 = 三個版本的淨值
    recent = x.loc[x.index[-1] - pd.Timedelta(days=90):]
    tb = results["B 只在盤整（ADX<20）"][0]
    tb_recent = tb[tb["entry_time"] >= recent.index[0]]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 9), gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(recent.index, recent["close"], color=TEXT_2, lw=1.1, label="金價（PAXG，4 小時）")
    a1.plot(recent.index, recent["mid"], color=BLUE, lw=1.0, label="中線（20 根均線）")
    a1.fill_between(recent.index, recent["lower"], recent["upper"], color=BLUE, alpha=0.12, label="布林通道 ±2σ")
    for _, tr in tb_recent.iterrows():
        color = AQUA if tr["ret"] > 0 else RED
        a1.scatter(tr["entry_time"], x.loc[tr["entry_time"], "open"], marker="^" if tr["side"] > 0 else "v",
                   color=color, s=60, zorder=3)
    a1.set_title("最近 90 天：B 版本的進場點（▲做多 ▼做空；綠 = 賺、紅 = 賠）")
    a1.legend(frameon=False, loc="upper left", fontsize=8)
    a1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    for (k, (_, d)), color in zip(results.items(), [ORANGE, AQUA, YELLOW]):
        eq = (1 + d).cumprod()
        a2.plot(eq.index, eq, color=color, lw=1.6, label=k)
    a2.axhline(1, color=TEXT_2, lw=0.8)
    a2.set_title("淨值（每筆停損 = 總資金 1%，已扣成本與資金費率）")
    a2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}x"))
    a2.legend(frameon=False, loc="upper left", fontsize=8)
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(OUT / "gold_range.png", dpi=150)
    plt.close(fig)

    lines = [
        "# 黃金：震盪區間均值回歸（布林通道）",
        "",
        f"幣安 PAXGUSDT 4 小時 K 線 {x.index[0]:%Y-%m-%d} ~ {x.index[-1]:%Y-%m-%d}。"
        f"布林通道 {BB_N} 根 ± {BB_K:g}σ；停損 = {SL_ATR:g} 倍 ATR，停利同距離（損益比 1:1）；最多 {MAX_BARS} 根（5 天）；"
        f"來回成本 {COST:.2%}＋資金費率；每筆冒總資金 {RISK:.0%}。規則在看結果前寫死。",
        "",
        "![黃金區間交易](gold_range.png)",
        "",
        "## 結果",
        "",
        "R = 停損距離。勝率 = 扣成本後賺錢的比例；停利率 = 碰到停利出場的比例（B' 為中線，其餘為 1:1）。",
        "",
        table.to_markdown(index=False),
        "",
        "## 各年度（括號內為筆數）",
        "",
        yearly.to_markdown(),
        "",
        "## 限制",
        "",
        "- PAXG 週末也交易；黃金期貨週末休市，週一跳空會讓停損成交更差。",
        "- 早期 PAXG 成交量較小，4 小時 K 線的高低點可能比真正的金價更誇張。",
        "- 資金費率用 XAUUSDT 上市以來的平均值（年化 12.6%）套用全期間。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
