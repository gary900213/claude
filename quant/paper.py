"""紙上交易：每天用固定（凍結）的策略產生建議倉位，記錄下來，之後用真實價格結算。

原則：
- 訊號紀錄 data/paper/signals.csv 只能新增、不能修改；每筆都記下產生時間。
  這樣之後看績效時，不可能用到「當時還不知道」的資訊。
- 執行時間 = 訊號產生當天的 UTC 收盤（保守假設）。幣安歷史檔約在隔天 07–09 UTC 才發布，
  所以第 D 天的訊號通常在 D+1 才產生，比回測多延遲 1 天，這個延遲會照實反映在績效裡。
- 損益：倉位 × 次日報酬 − 換手成本 7 bps − 永續資金費率（資金費率月檔還沒公布的日子先記 0，
  月底公布後重算會自動補上）。

用法：python -m quant.paper
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
from .features import add_features  # noqa: E402
from .history import load_daily  # noqa: E402
from .strategies import trend_signal, vol_scale  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "data" / "paper"
DOCS = ROOT / "docs" / "paper"

# ---------------------------------------------------------------- 凍結的策略設定
_COMMON = {
    "trend_lookbacks": [20, 60, 120],
    "target_vol": 0.40,
    "max_leverage": 1.5,
    "cost_bps": 7.0,
    "rebalance_band": 0.10,  # 執行規則：倉位變化 < 0.10 不調整（目標為 0 時一律出場）
}
STRATEGIES = {
    "v1": {**_COMMON, "version": "v1-2026-11-09",
           "filters": {"ls_z90": 1.0, "oi_z90": 1.0},  # 指標 > 門檻時倉位歸零
           "description": "趨勢（20/60/120 日）× 波動率目標 40%（上限 1.5 倍），"
                          "散戶多空比 z > 1 或持倉量水位 z > 1 時空手"},
    # v2：多幣種驗證發現兩個過濾條件無法延伸到其他幣，改為只用趨勢，與 v1 並行比較
    "v2": {**_COMMON, "version": "v2-2026-11-10", "filters": {},
           "description": "只用趨勢（20/60/120 日）× 波動率目標 40%（上限 1.5 倍），不加過濾條件"},
}
STRATEGY = STRATEGIES["v1"]  # 目前使用中的策略（main() 會依 --version 切換）


def paths(version: str, live: bool) -> tuple[Path, Path]:
    """v1 沿用原本的資料夾；其他版本加上 _v2 等後綴。"""
    name = "paper_live" if live else "paper"
    if version != "v1":
        name += f"_{version}"
    return ROOT / "data" / name, ROOT / "docs" / name

SIGNAL_COLS = ["signal_date", "generated_at_utc", "strategy", "close", "trend", "vol_scale",
               "ls_z90", "oi_z90", "filter_ls", "filter_oi", "target_pos", "source"]


def compute(d: pd.DataFrame) -> pd.DataFrame:
    """回傳每天的訊號細節（只用當天收盤已知的數據）。"""
    s = STRATEGY
    out = pd.DataFrame(index=d.index)
    out["close"] = d["close"]
    out["trend"] = trend_signal(d, tuple(s["trend_lookbacks"]))
    out["vol_scale"] = vol_scale(d, s["target_vol"], s["max_leverage"])
    out["ls_z90"] = d["ls_z90"]
    out["oi_z90"] = d["oi_z90"]
    f = s["filters"]
    no = pd.Series(False, index=d.index)
    out["filter_ls"] = (d["ls_z90"] > f["ls_z90"]).fillna(False) if "ls_z90" in f else no
    out["filter_oi"] = (d["oi_z90"] > f["oi_z90"]).fillna(False) if "oi_z90" in f else no
    pos = out["trend"].clip(lower=0) * out["vol_scale"]
    out["target_pos"] = pos.where(~(out["filter_ls"] | out["filter_oi"]), 0.0)
    return out


def latest_ready_date(d: pd.DataFrame) -> pd.Timestamp | None:
    """最新一個「價格、持倉量、多空比都齊全」的日子。"""
    ok = d[["close", "ls_z90", "oi_z90", "rv_30d"]].notna().all(axis=1)
    return ok[ok].index.max() if ok.any() else None


def load_signals() -> pd.DataFrame:
    path = PAPER / "signals.csv"
    if not path.exists():
        return pd.DataFrame(columns=SIGNAL_COLS)
    return pd.read_csv(path, parse_dates=["signal_date", "generated_at_utc"])


def append_signals(d: pd.DataFrame, now: pd.Timestamp, source: str = "archive") -> pd.DataFrame:
    sig = load_signals()
    ready = latest_ready_date(d)
    if ready is None:
        return sig
    last = sig["signal_date"].max() if len(sig) else None
    # 第一次只記最新一天；之後補上上次以來所有新的日子（錯過的日子也會記，但會帶著延遲）
    dates = [ready] if last is None else [x for x in d.loc[last:ready].index if x > last]
    if not dates:
        return sig
    c = compute(d).loc[dates].reset_index(names="signal_date")
    c["generated_at_utc"] = now
    c["strategy"] = STRATEGY["version"]
    c["source"] = source
    sig = pd.concat([sig, c[SIGNAL_COLS]], ignore_index=True)
    PAPER.mkdir(parents=True, exist_ok=True)
    sig.to_csv(PAPER / "signals.csv", index=False, float_format="%.6g")
    return sig


def executed_positions(sig: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """把訊號換成「實際持有的倉位」：在產生當天的 UTC 收盤執行。"""
    if sig.empty:
        return pd.Series(dtype=float)
    gen_day = pd.to_datetime(sig["generated_at_utc"], utc=True).dt.normalize()
    sig_day = pd.to_datetime(sig["signal_date"], utc=True)
    eff = pd.concat([gen_day, sig_day], axis=1).max(axis=1)
    s = pd.Series(sig["target_pos"].astype(float).values, index=eff).groupby(level=0).last()
    full = pd.date_range(s.index.min(), max(index.max(), s.index.max()), freq="D")
    return bt.apply_band(s.reindex(full).ffill(), STRATEGY["rebalance_band"])


def expectations(d: pd.DataFrame) -> dict:
    """同一套凍結策略在歷史上的表現：無延遲 vs 延遲 1 天（紙上交易的實際情況）。"""
    c = compute(d)
    trend_only = c["trend"].clip(lower=0) * c["vol_scale"]
    start = d.index[120]
    res = {}
    for key, pos, lag in (("凍結策略｜無延遲", c["target_pos"], 0),
                          ("凍結策略｜延遲 1 天（紙上交易實況）", c["target_pos"], 1),
                          ("對照：只用趨勢｜延遲 1 天", trend_only, 1)):
        pos = bt.apply_band(pos, STRATEGY["rebalance_band"])
        r = bt.run("", d["ret"], pos.shift(lag), STRATEGY["cost_bps"], d["funding_day"])
        res[key] = {"全期間": bt.stats(bt.Result("", r.daily.loc[start:])),
                    "2022-07 起": bt.stats(bt.Result("", r.daily.loc["2022-07-01":]))}
    return res


def order_instructions(sig: pd.DataFrame, pos: pd.Series, latest: dict, now: pd.Timestamp,
                       capital: float | None) -> list[str]:
    """依「不交易區間」後的實際倉位，說明今天要不要動、動多少。"""
    held = float(pos.iloc[-1])
    prev_pos = pos.shift(1).fillna(0.0)  # 紙上交易開始前視為空手
    changes = pos[(pos - prev_pos).abs() > 1e-9]
    if changes.empty:
        out = ["- 應持有倉位：**空手**（紙上交易開始以來尚未建倉）"]
        last_change, prev = None, 0.0
    else:
        last_change = changes.index.max()
        prev = float(prev_pos.loc[last_change])
        out = [f"- 應持有倉位：**{held:.2f} 倍**（最近一次調整：{last_change:%Y-%m-%d} UTC 收盤，"
               f"{prev:.2f} → {pos.loc[last_change]:.2f}）"]
    target = latest["target_pos"]
    if abs(target - held) > 1e-9 and target != 0.0:
        out.append(f"- 最新目標 {target:.2f} 與持有 {held:.2f} 相差不到 {STRATEGY['rebalance_band']:.2f}，"
                   "依不交易區間規則**不調整**")
    if last_change is not None and last_change == now.normalize():
        delta = pos.loc[last_change] - prev
        act = "買入" if delta > 0 else "賣出"
        line = f"- **今天要{act} {abs(delta):.2f} 倍**：UTC 00:00（台灣 08:00）收盤後立即以市價成交"
        if capital:
            notional = abs(delta) * capital
            line += f"，約 {notional:,.0f} 美元 ≈ {notional / latest['close']:.4f} BTC"
        out.append(line)
    out.append("- 執行原則（見 docs/entry/）：收盤後立刻市價成交；不要掛低價等回檔，"
               "歷史上沒成交時追單的損失大於省下的價差")
    return out


def main(live: bool = False, capital: float | None = None, version: str = "v1") -> int:
    """live=True：用幣安即時 API 補最新數據（由 quant.live 呼叫）。

    兩種模式的紀錄分開存：歷史檔模式 → data/paper、docs/paper（GitHub Actions 自動跑）；
    即時模式 → data/paper_live、docs/paper_live（在你的電腦上跑），避免兩邊同時寫同一個檔案。
    """
    global PAPER, DOCS, STRATEGY
    STRATEGY = STRATEGIES[version]
    PAPER, DOCS = paths(version, live)
    now = pd.Timestamp(datetime.now(timezone.utc))
    preview = None
    if live:
        from .live import build_live_daily
        raw, info = build_live_daily()
        print(f"[paper] 即時模式：歷史檔到 {info['archive_until']}，API 補到 {info['live_until']} UTC")
        d_all = add_features(raw)
        today = now.normalize()
        partial = d_all[d_all.index >= today]
        d = d_all[d_all.index < today]  # 今天還沒收盤，不能當正式訊號
        if not partial.empty and partial["close"].notna().any():
            preview = compute(d_all).iloc[-1]
    else:
        d = add_features(load_daily())
    d = d[d["close"].notna()]
    sig = append_signals(d, now, "live" if live else "archive")
    DOCS.mkdir(parents=True, exist_ok=True)
    if sig.empty:
        print("[paper] 數據不齊全，沒有產生訊號")
        return 1

    pos = executed_positions(sig, d.index)
    perf_lines = []
    start = pos.index.min()
    ret = d["ret"].reindex(pos.index)
    have_price = ret.loc[start:].iloc[1:].notna()
    if have_price.any():
        r = bt.run("紙上交易", ret.fillna(0.0), pos, STRATEGY["cost_bps"], d["funding_day"])
        last_px = have_price[have_price].index.max()
        daily = r.daily.loc[start:last_px]
        bh = (1 + d["ret"].loc[start:last_px].iloc[1:]).cumprod()
        eq = (1 + daily["net"].iloc[1:]).cumprod()
        perf_lines = [
            f"- 結算到：{last_px:%Y-%m-%d}（{len(eq)} 天）",
            f"- 紙上交易累計：{eq.iloc[-1] - 1:+.2%}　同期現貨持有：{bh.iloc[-1] - 1:+.2%}",
            f"- 最大回撤：{(eq / eq.cummax() - 1).min():.2%}",
        ]
        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.plot(eq.index, (eq - 1) * 100, color="#2a78d6", lw=2, label="紙上交易")
        ax.plot(bh.index, (bh - 1) * 100, color="#eb6834", lw=1.6, label="同期現貨持有")
        ax.axhline(0, color="#52514e", lw=0.8)
        ax.set_title("紙上交易累計報酬（%）")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.legend(frameon=False, loc="upper left")
        fig.tight_layout()
        fig.savefig(DOCS / "equity.png", dpi=150)
        plt.close(fig)

    last = sig.iloc[-1]
    reasons = []
    if last["trend"] <= 0:
        reasons.append("趨勢分數 ≤ 0（不做多）")
    if bool(last["filter_ls"]):
        reasons.append(f"散戶多空比 z = {last['ls_z90']:.2f} > 1（過度看多）")
    if bool(last["filter_oi"]):
        reasons.append(f"持倉量水位 z = {last['oi_z90']:.2f} > 1（槓桿偏高）")
    latest = {
        "signal_date": f"{last['signal_date']:%Y-%m-%d}",
        "generated_at_utc": f"{pd.Timestamp(last['generated_at_utc']):%Y-%m-%d %H:%M}",
        "target_pos": round(float(last["target_pos"]), 4),
        "close": float(last["close"]),
        "trend": float(last["trend"]),
        "vol_scale": round(float(last["vol_scale"]), 4),
        "ls_z90": round(float(last["ls_z90"]), 3),
        "oi_z90": round(float(last["oi_z90"]), 3),
        "reasons_flat": reasons,
        "strategy": STRATEGY,
        "source": str(last.get("source", "archive")),
    }
    if preview is not None:
        latest["preview_if_closed_now"] = {
            "as_of_utc": f"{now:%Y-%m-%d %H:%M}", "price": float(preview["close"]),
            "target_pos": round(float(preview["target_pos"]), 4), "trend": float(preview["trend"]),
            "ls_z90": round(float(preview["ls_z90"]), 3), "oi_z90": round(float(preview["oi_z90"]), 3)}
    (PAPER / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    exp = expectations(d)
    exp_rows = []
    for label, periods in exp.items():
        for period, st in periods.items():
            exp_rows.append({"版本": label, "期間": period, "年化報酬": f"{st['年化報酬']:+.1%}",
                             "夏普值": f"{st['夏普值']:.2f}", "最大回撤": f"{st['最大回撤']:.1%}",
                             "平均曝險": f"{st['平均曝險']:.2f}x"})

    recent = sig.tail(15).iloc[::-1].copy()
    recent["signal_date"] = pd.to_datetime(recent["signal_date"]).dt.strftime("%Y-%m-%d")
    recent["generated_at_utc"] = pd.to_datetime(recent["generated_at_utc"]).dt.strftime("%m-%d %H:%M")
    recent = recent[["signal_date", "generated_at_utc", "close", "trend", "vol_scale",
                     "ls_z90", "oi_z90", "target_pos"]]
    recent.columns = ["訊號日", "產生時間 UTC", "收盤價", "趨勢分數", "波動率倍數",
                      "散戶多空 z", "持倉量 z", "建議倉位"]

    pos_txt = f"{latest['target_pos']:.2f} 倍" if latest["target_pos"] > 0 else "空手（0）"
    lines = [
        f"# BTC 紙上交易 {version}" + ("（即時模式）" if live else "（歷史檔模式，延遲約 1 天）"),
        "",
        f"策略版本 `{STRATEGY['version']}`：{STRATEGY['description']}。參數已凍結，紙上交易期間不再調整。",
        "",
        "## 目前建議",
        "",
        f"- **建議倉位：{pos_txt}**（以總資金為 1；1 倍 = 全部資金買 BTC）",
        f"- 訊號日：{latest['signal_date']}（UTC 收盤），產生於 {latest['generated_at_utc']} UTC",
        f"- 收盤價 {latest['close']:,.0f}，趨勢分數 {latest['trend']:+.2f}，波動率倍數 {latest['vol_scale']:.2f}",
        f"- 散戶多空比 z = {latest['ls_z90']:.2f}，持倉量水位 z = {latest['oi_z90']:.2f}",
    ]
    if reasons:
        lines.append(f"- 空手原因：{'；'.join(reasons)}")
    src = "即時 API（零延遲）" if latest["source"] == "live" else "幣安歷史檔（延遲約 1 天）"
    lines.append(f"- 數據來源：{src}")
    if "preview_if_closed_now" in latest:
        pv = latest["preview_if_closed_now"]
        lines.append(f"- 預覽（不是正式訊號）：如果現在 {pv['as_of_utc']} UTC 就收盤，價格 {pv['price']:,.0f}，"
                     f"建議倉位會是 {pv['target_pos']:.2f}（趨勢 {pv['trend']:+.2f}，散戶 z {pv['ls_z90']:.2f}，"
                     f"持倉量 z {pv['oi_z90']:.2f}）")
    lines += ["", "## 下單指示", ""] + order_instructions(sig, pos, latest, now, capital)
    lines += ["", "## 紙上交易績效", ""]
    lines += perf_lines or ["- 還沒有可以結算的日子（下單後要等下一個交易日的收盤價）"]
    if perf_lines:
        lines += ["", "![紙上交易](equity.png)"]
    lines += [
        "", "## 預期表現（同一套凍結策略的歷史回測）", "",
        "注意：這兩個過濾條件是看過 2022-07 之後的樣本外結果才挑的，所以「2022-07 起」的數字偏樂觀；"
        "紙上交易就是用來檢驗這點。",
        "", pd.DataFrame(exp_rows).set_index("版本").to_markdown(), "",
        "## 最近的訊號紀錄", "", recent.to_markdown(index=False, floatfmt=".3f"), "",
    ]
    (DOCS / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


def cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="紙上交易（歷史檔模式）；即時模式請用 python -m quant.live")
    ap.add_argument("--capital", type=float, help="總資金（美元），用來換算下單數量")
    ap.add_argument("--version", choices=sorted(STRATEGIES), default="v1", help="凍結策略版本")
    args = ap.parse_args(argv)
    return main(capital=args.capital, version=args.version)


if __name__ == "__main__":
    sys.exit(cli())
