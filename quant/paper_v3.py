"""紙上交易 v3：BTC 趨勢 ＋ 黃金趨勢，風險平價分配資金（參數凍結）。

- BTC 腿：v2 趨勢規則（20/60/120 日 × 波動率目標 40%，上限 1.5 倍），幣安永續，資金費率照實計
- 黃金腿：同一組趨勢參數，價格用幣安現貨 PAXGUSDT；成本照期貨假設（手續費 3 bps、展期年化 4%）
- 資金分配：兩條腿過去 180 天的策略報酬波動取倒數比例（風險平價）
- 目標倉位（佔總資金倍數）= 權重 × 該腿趨勢倉位
- 執行：和 v1／v2 相同，訊號產生當天的 UTC 收盤；每條腿各自 0.10 不交易區間
- 紀錄 data/paper_v3/signals.csv 只能新增、不能修改

用法：python -m quant.paper_v3
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .gold import gold_frame  # noqa: E402
from .history import load_daily  # noqa: E402
from .strategies import trend_signal, vol_scale  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "data" / "paper_v3"
DOCS = ROOT / "docs" / "paper_v3"

STRATEGY = {
    "version": "v3-2026-11-17",
    "trend_lookbacks": [20, 60, 120],
    "target_vol": 0.40,
    "max_leverage": 1.5,
    "btc_cost_bps": 7.0,
    "gold_cost_bps": 3.0,
    "gold_carry_ann": 0.04,
    "rp_window": 180,
    "rebalance_band": 0.10,
    "description": "BTC 趨勢 ＋ 黃金趨勢（同一組參數：20/60/120 日 × 波動率目標 40%，上限 1.5 倍），"
                   "依兩條腿過去 180 天的波動做風險平價分配",
}
SIGNAL_COLS = ["signal_date", "generated_at_utc", "strategy", "btc_close", "btc_trend", "btc_pos",
               "gold_close", "gold_trend", "gold_pos", "w_btc", "w_gold", "target_btc", "target_gold"]


def leg_target(d: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    s = STRATEGY
    trend = trend_signal(d, tuple(s["trend_lookbacks"]))
    return trend, trend.clip(lower=0) * vol_scale(d, s["target_vol"], s["max_leverage"])


def compute(b: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    """每天的訊號細節（只用當天收盤已知的數據）。"""
    s = STRATEGY
    tb, pb = leg_target(b)
    tg, pg = leg_target(g)
    band = s["rebalance_band"]
    rb = bt.run("", b["ret"], bt.apply_band(pb, band), s["btc_cost_bps"], b["funding_day"]).daily["net"]
    carry = pd.Series(s["gold_carry_ann"] / 365, index=g.index)
    rg = bt.run("", g["ret"], bt.apply_band(pg, band), s["gold_cost_bps"], carry).daily["net"]
    idx = b.index.intersection(g.index)
    w = s["rp_window"]
    vb = rb.reindex(idx).rolling(w, min_periods=60).std()
    vg = rg.reindex(idx).rolling(w, min_periods=60).std()
    wb = ((1 / vb) / (1 / vb + 1 / vg)).fillna(0.5)
    out = pd.DataFrame({"btc_close": b["close"].reindex(idx), "btc_trend": tb.reindex(idx),
                        "btc_pos": pb.reindex(idx), "gold_close": g["close"].reindex(idx),
                        "gold_trend": tg.reindex(idx), "gold_pos": pg.reindex(idx),
                        "w_btc": wb, "w_gold": 1 - wb}, index=idx)
    out["target_btc"] = out["w_btc"] * out["btc_pos"]
    out["target_gold"] = out["w_gold"] * out["gold_pos"]
    return out


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    b = load_daily("BTCUSDT")
    b = b[b["close"].notna() & b["rv_30d"].notna()]
    g, _ = gold_frame()
    g = g[g["close"].notna() & g["rv_30d"].notna()]
    return b, g


def load_signals() -> pd.DataFrame:
    path = PAPER / "signals.csv"
    if not path.exists():
        return pd.DataFrame(columns=SIGNAL_COLS)
    return pd.read_csv(path, parse_dates=["signal_date", "generated_at_utc"])


def append_signals(c: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    sig = load_signals()
    ready = c.dropna().index.max()
    if pd.isna(ready):
        return sig
    last = sig["signal_date"].max() if len(sig) else None
    dates = [ready] if last is None else [x for x in c.loc[last:ready].dropna().index if x > last]
    if not dates:
        return sig
    new = c.loc[dates].reset_index(names="signal_date")
    new["generated_at_utc"] = now
    new["strategy"] = STRATEGY["version"]
    sig = pd.concat([sig, new[SIGNAL_COLS]], ignore_index=True)
    PAPER.mkdir(parents=True, exist_ok=True)
    sig.to_csv(PAPER / "signals.csv", index=False, float_format="%.6g")
    return sig


def executed(sig: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """各腿實際持有的倉位：在訊號產生當天的 UTC 收盤執行，各自套用不交易區間。"""
    if sig.empty:
        return pd.DataFrame(columns=["btc", "gold"])
    gen = pd.to_datetime(sig["generated_at_utc"], utc=True).dt.normalize()
    day = pd.to_datetime(sig["signal_date"], utc=True)
    eff = pd.concat([gen, day], axis=1).max(axis=1)
    out = {}
    for leg in ("btc", "gold"):
        s = pd.Series(sig[f"target_{leg}"].astype(float).values, index=eff).groupby(level=0).last()
        full = pd.date_range(s.index.min(), max(index.max(), s.index.max()), freq="D")
        out[leg] = bt.apply_band(s.reindex(full).ffill(), STRATEGY["rebalance_band"])
    return pd.DataFrame(out)


def settle(pos: pd.DataFrame, b: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame | None:
    s = STRATEGY
    start = pos.index.min()
    rb = b["ret"].reindex(pos.index)
    rg = g["ret"].reindex(pos.index)
    have = rb.loc[start:].iloc[1:].notna() & rg.loc[start:].iloc[1:].notna()
    if not have.any():
        return None
    last = have[have].index.max()
    nb = bt.run("", rb.fillna(0.0), pos["btc"], s["btc_cost_bps"], b["funding_day"]).daily["net"]
    carry = pd.Series(s["gold_carry_ann"] / 365, index=pos.index)
    ng = bt.run("", rg.fillna(0.0), pos["gold"], s["gold_cost_bps"], carry).daily["net"]
    return pd.DataFrame({"btc": nb, "gold": ng}).loc[start:last].iloc[1:]


def expectations(c: pd.DataFrame, b: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    s = STRATEGY
    band = s["rebalance_band"]
    rows = []
    for lag in (0, 1):
        pb = bt.apply_band(c["target_btc"], band).shift(lag)
        pg = bt.apply_band(c["target_gold"], band).shift(lag)
        nb = bt.run("", b["ret"].reindex(c.index), pb, s["btc_cost_bps"], b["funding_day"].reindex(c.index)).daily["net"]
        carry = pd.Series(s["gold_carry_ann"] / 365, index=c.index)
        ng = bt.run("", g["ret"].reindex(c.index), pg, s["gold_cost_bps"], carry).daily["net"]
        net = (nb + ng).loc[c.index[120]:]
        st = bt.stats(bt.Result("", pd.DataFrame({"net": net, "pos": (pb + pg).reindex(net.index)})))
        rows.append({"版本": "無延遲" if lag == 0 else "延遲 1 天（紙上交易實況）",
                     "年化": f"{st['年化報酬']:+.1%}", "夏普": f"{st['夏普值']:.2f}",
                     "最大回撤": f"{st['最大回撤']:.1%}", "平均總曝險": f"{st['平均曝險']:.2f}x"})
    return pd.DataFrame(rows)


def main() -> int:
    now = pd.Timestamp(datetime.now(timezone.utc))
    b, g = load_inputs()
    c = compute(b, g)
    sig = append_signals(c, now)
    DOCS.mkdir(parents=True, exist_ok=True)
    if sig.empty:
        print("[paper_v3] 數據不齊全，沒有產生訊號")
        return 1
    pos = executed(sig, c.index)
    last = sig.iloc[-1]
    latest = {k: (f"{last[k]:%Y-%m-%d}" if k == "signal_date" else
                  f"{pd.Timestamp(last[k]):%Y-%m-%d %H:%M}" if k == "generated_at_utc" else
                  last[k] if k == "strategy" else round(float(last[k]), 4)) for k in SIGNAL_COLS}
    latest["held_btc"] = round(float(pos["btc"].iloc[-1]), 4)
    latest["held_gold"] = round(float(pos["gold"].iloc[-1]), 4)
    PAPER.mkdir(parents=True, exist_ok=True)
    (PAPER / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    perf = settle(pos, b, g)
    perf_lines = ["- 還沒有可以結算的日子（下單後要等下一個交易日的收盤價）"]
    if perf is not None and len(perf):
        tot = perf.sum(axis=1)
        eq = (1 + tot).cumprod()
        bh = (1 + b["ret"].reindex(perf.index)).cumprod()
        gh = (1 + g["ret"].reindex(perf.index)).cumprod()
        perf_lines = [f"- 結算到：{perf.index[-1]:%Y-%m-%d}（{len(perf)} 天）",
                      f"- v3 累計：{eq.iloc[-1] - 1:+.2%}（BTC 腿 {(1 + perf['btc']).prod() - 1:+.2%}、"
                      f"黃金腿 {(1 + perf['gold']).prod() - 1:+.2%}）",
                      f"- 同期：BTC 現貨 {bh.iloc[-1] - 1:+.2%}、黃金 {gh.iloc[-1] - 1:+.2%}",
                      f"- 最大回撤：{(eq / eq.cummax() - 1).min():.2%}", "", "![v3](equity.png)"]
        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.plot(eq.index, (eq - 1) * 100, color="#2a78d6", lw=2, label="v3 紙上交易")
        ax.plot(bh.index, (bh - 1) * 100, color="#eb6834", lw=1.4, label="BTC 現貨持有")
        ax.plot(gh.index, (gh - 1) * 100, color="#eda100", lw=1.4, label="黃金持有")
        ax.axhline(0, color="#52514e", lw=0.8)
        ax.set_title("v3 紙上交易累計報酬（%）")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.legend(frameon=False, loc="upper left")
        fig.tight_layout()
        fig.savefig(DOCS / "equity.png", dpi=150)
        plt.close(fig)

    def why(trend, leg):
        return "趨勢向上" if trend > 0 else f"{leg}趨勢分數 {trend:+.2f} ≤ 0，空手"

    recent = sig.tail(15).iloc[::-1].copy()
    recent = pd.DataFrame({"訊號日": pd.to_datetime(recent["signal_date"]).dt.strftime("%Y-%m-%d"),
                           "BTC 趨勢": recent["btc_trend"].round(2), "BTC 權重": recent["w_btc"].round(2),
                           "BTC 目標": recent["target_btc"].round(3), "黃金趨勢": recent["gold_trend"].round(2),
                           "黃金權重": recent["w_gold"].round(2), "黃金目標": recent["target_gold"].round(3)})
    lines = [
        "# 紙上交易 v3：BTC 趨勢 ＋ 黃金趨勢（歷史檔模式，延遲約 1 天）",
        "",
        f"策略版本 `{STRATEGY['version']}`：{STRATEGY['description']}。參數已凍結。",
        "黃金價格用 PAXG；成本照期貨（例如 COMEX 小型黃金）計算。若改用幣安 XAUUSDT 永續，"
        "資金費率年化約 12.6%，實際績效會比這裡差。",
        "",
        "## 目前建議（以總資金為 1）",
        "",
        f"- 訊號日：{latest['signal_date']}（UTC 收盤），產生於 {latest['generated_at_utc']} UTC",
        f"- **BTC：目標 {latest['target_btc']:.2f} 倍**（權重 {latest['w_btc']:.0%} × 趨勢倉位 "
        f"{latest['btc_pos']:.2f}；{why(latest['btc_trend'], 'BTC ')}）；收盤 {latest['btc_close']:,.0f}",
        f"- **黃金：目標 {latest['target_gold']:.2f} 倍**（權重 {latest['w_gold']:.0%} × 趨勢倉位 "
        f"{latest['gold_pos']:.2f}；{why(latest['gold_trend'], '黃金')}）；收盤 {latest['gold_close']:,.1f}",
        f"- 目前應持有：BTC {latest['held_btc']:.2f} 倍、黃金 {latest['held_gold']:.2f} 倍"
        "（各自套用 0.10 不交易區間）",
        "",
        "## 紙上交易績效",
        "",
        *perf_lines,
        "",
        "## 預期表現（同一套凍結規則的歷史回測）",
        "",
        expectations(c, b, g).to_markdown(index=False),
        "",
        "## 最近的訊號紀錄",
        "",
        recent.to_markdown(index=False),
        "",
    ]
    (DOCS / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
