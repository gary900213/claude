"""每日更新入口：抓資料 → 存 CSV → 畫圖 → 產生 docs/index.html。

用法：
    python -m btc_daily.main               # 正常抓取
    python -m btc_daily.main --demo --out /tmp/demo   # 不連網，用模擬資料測試
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import charts, sources
from .heatmap import estimate_heatmap

ROOT = Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    print(f"[btc_daily] {msg}", flush=True)


def try_fetch(label: str, fn, status: dict):
    try:
        res = fn()
        src = res[0] if isinstance(res, tuple) else "ok"
        status[label] = f"✅ {src}"
        log(f"{label}: {src}")
        return res[1] if isinstance(res, tuple) else res
    except Exception as e:  # noqa: BLE001
        status[label] = f"❌ {str(e)[:200]}"
        log(f"{label} 失敗: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------- 模擬資料（--demo）

def demo_data():
    rng = np.random.default_rng(7)
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=24 * 30, freq="h")
    close = 95000 * np.exp(np.cumsum(rng.normal(0, 0.006, len(idx))))
    high = close * (1 + rng.uniform(0, 0.006, len(idx)))
    low = close * (1 - rng.uniform(0, 0.006, len(idx)))
    k = pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                      "volume": rng.uniform(2000, 8000, len(idx))}, index=idx)
    oi = pd.Series(30e9 + np.cumsum(rng.normal(0, 1.5e8, len(idx))), index=idx)
    funding = pd.Series(rng.normal(0.0001, 0.00008, 90),
                        index=pd.date_range(end=idx[-1], periods=90, freq="8h"))
    ls = pd.Series(1 + rng.normal(0.1, 0.15, len(idx)).cumsum() / 50, index=idx).clip(0.6, 2.5)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=400)
    etf = pd.DataFrame({"IBIT": rng.normal(150, 250, len(days)),
                        "FBTC": rng.normal(20, 80, len(days))}, index=days)
    etf["Total"] = etf.sum(axis=1)
    liq_t = idx[-24 * 3:].repeat(5) + pd.to_timedelta(rng.integers(0, 3600, 24 * 15), unit="s")
    liq = pd.DataFrame({"time": liq_t, "side": rng.choice(["long", "short"], len(liq_t)),
                        "price": 95000.0, "usd": rng.lognormal(10, 1.5, len(liq_t))})
    return k, oi, funding, ls, etf, liq


# ---------------------------------------------------------------- 存檔

def upsert_csv(path: Path, df: pd.DataFrame) -> pd.DataFrame:
    if path.exists():
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        df = df.combine_first(old) if not df.empty else old
    df = df.sort_index()
    df.to_csv(path, float_format="%.6g")
    return df


def merge_raw_liquidations(path: Path, liq: pd.DataFrame | None, keep_days: int = 10) -> pd.DataFrame | None:
    """把這次抓到的清算單和之前存的合併、去重，只保留最近 keep_days 天。

    OKX 每次只回最近一段時間的清算單，多次執行累積起來才能拼出完整的一天。
    """
    frames = [] if liq is None else [liq]
    if path.exists():
        old = pd.read_csv(path)
        old["time"] = pd.to_datetime(old["time"], utc=True, format="ISO8601")
        frames.append(old)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["time", "side", "price", "usd"]).sort_values("time")
    df = df[df["time"] >= df["time"].max() - pd.Timedelta(days=keep_days)]
    df.to_csv(path, index=False, float_format="%.8g")
    return df


def daily_liquidations(liq: pd.DataFrame) -> pd.DataFrame:
    """只保留完整覆蓋的 UTC 日。"""
    if liq is None or liq.empty:
        return pd.DataFrame(columns=["liq_long_usd", "liq_short_usd"])
    day = liq["time"].dt.tz_convert("UTC").dt.normalize().dt.tz_localize(None)
    g = liq.assign(day=day).pivot_table(index="day", columns="side", values="usd",
                                         aggfunc="sum", fill_value=0.0)
    g = g.reindex(columns=["long", "short"], fill_value=0.0)
    g.columns = ["liq_long_usd", "liq_short_usd"]
    # 抓到的最舊與最新那天都可能只有部分資料
    return g[(g.index > day.min()) & (g.index < day.max())]


# ---------------------------------------------------------------- HTML 報告

def render_html(summary: dict, status: dict, table: pd.DataFrame, images: list[tuple[str, str]],
                notes: list[str]) -> str:
    def tile(label, value, sub=""):
        return (f'<div class="tile"><div class="lbl">{html.escape(label)}</div>'
                f'<div class="val">{html.escape(value)}</div><div class="sub">{html.escape(sub)}</div></div>')

    tiles = "".join(tile(*t) for t in summary["tiles"])
    imgs = "".join(f'<figure><img src="img/{f}" alt="{html.escape(a)}" loading="lazy">'
                   f'<figcaption>{html.escape(a)}</figcaption></figure>' for f, a in images)
    stat = "".join(f"<li><b>{html.escape(k)}</b>：{html.escape(v)}</li>" for k, v in status.items())
    note = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
    tbl = table.to_html(classes="data", border=0, na_rep="—", escape=True) if not table.empty else ""
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC 每日資金與清算</title>
<style>
:root {{ --bg:#fcfcfb; --fg:#0b0b0b; --fg2:#52514e; --line:#e4e3df; --card:#ffffff; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#1a1a19; --fg:#f0efec; --fg2:#c3c2b7; --line:#383835; --card:#232322; }} }}
:root[data-theme="dark"] {{ --bg:#1a1a19; --fg:#f0efec; --fg2:#c3c2b7; --line:#383835; --card:#232322; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.6 system-ui,-apple-system,"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:1.6rem; margin:0 0 4px; }} .muted {{ color:var(--fg2); font-size:.9rem; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:20px 0; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
.lbl {{ color:var(--fg2); font-size:.85rem; }} .val {{ font-size:1.35rem; font-weight:700; font-variant-numeric:tabular-nums; }}
.sub {{ color:var(--fg2); font-size:.8rem; }}
figure {{ margin:24px 0; }} img {{ width:100%; height:auto; border-radius:8px; border:1px solid var(--line); background:#fcfcfb; }}
figcaption {{ color:var(--fg2); font-size:.85rem; margin-top:4px; }}
.scroll {{ overflow-x:auto; }} table.data {{ border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:.85rem; }}
table.data th, table.data td {{ padding:4px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
</style></head><body><main>
<h1>BTC 每日資金流與清算</h1>
<div class="muted">更新時間：{summary['updated']} UTC　·　全部使用免費公開資料</div>
<div class="tiles">{tiles}</div>
{imgs}
<h2>近期每日數據</h2><div class="scroll">{tbl}</div>
<h2>資料狀態</h2><ul class="muted">{stat}</ul>
<h2>說明</h2><ul class="muted">{note}
<li>清算熱力圖／清算地圖是以公開的持倉量、多空比與假設槓桿分佈推估的近似值，不是 CoinGlass 的官方數據，僅供參考。</li>
<li>ETF 資金流來源為 Farside Investors（單位：百萬美元），美股收盤後才會更新。</li>
</ul></main></body></html>"""


# ---------------------------------------------------------------- 主流程

def run(demo: bool = False, out: str | None = None) -> int:
    base = Path(out) if out else ROOT
    DATA, DOCS = base / "data", base / "docs"
    IMG = DOCS / "img"
    DATA.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}

    if demo:
        k, oi, funding, ls, etf, liq = demo_data()
        status = {k_: "🧪 demo" for k_ in ["K 線", "持倉量", "資金費率", "多空比", "ETF 資金流", "OKX 清算單"]}
    else:
        k = try_fetch("K 線", lambda: sources.fetch_klines(24 * 30), status)
        oi = try_fetch("持倉量", sources.fetch_open_interest, status)
        funding = try_fetch("資金費率", sources.fetch_funding, status)
        ls = try_fetch("多空比", sources.fetch_long_short, status)
        etf = try_fetch("ETF 資金流", sources.fetch_etf_flows, status)
        liq = try_fetch("OKX 清算單", sources.fetch_okx_liquidations, status)

    if etf is not None:
        etf.to_csv(DATA / "etf_flows.csv", float_format="%.1f")
    elif (DATA / "etf_flows.csv").exists():
        etf = pd.read_csv(DATA / "etf_flows.csv", index_col=0, parse_dates=True)
        status["ETF 資金流"] += "（沿用上次存檔）"

    # 每日摘要（UTC 日）
    rows = {}
    if k is not None:
        rows["close"] = k["close"].resample("1D").last()
    if oi is not None:
        rows["oi_usd"] = oi.resample("1D").last()
    if funding is not None:
        rows["funding_avg"] = funding.resample("1D").mean()
    if ls is not None:
        rows["long_short_ratio"] = ls.resample("1D").last()
    today_df = pd.DataFrame(rows)
    if not today_df.empty:
        today_df.index = today_df.index.tz_localize(None)
    liq = merge_raw_liquidations(DATA / "liquidations_raw.csv", liq)
    liq_daily = daily_liquidations(liq)
    today_df = today_df.join(liq_daily, how="outer") if not today_df.empty else liq_daily
    if etf is not None:
        today_df = today_df.join(etf[["Total"]].rename(columns={"Total": "etf_net_musd"}), how="outer")
    summary_df = upsert_csv(DATA / "daily_summary.csv", today_df)

    # 持倉量／資金費率／多空比只來自單一交易所，標示清楚
    venue = "OKX " if "okx" in status.get("持倉量", "") else ("Binance " if "binance" in status.get("持倉量", "") else "")
    images, notes = [], []
    if etf is not None and len(etf):
        charts.etf_flows_chart(etf, str(IMG / "etf_flows.png"))
        images.append(("etf_flows.png", "BTC 現貨 ETF 每日淨流入與累計淨流入"))
    hm = None
    if k is not None:
        hm = estimate_heatmap(k.tail(24 * 14), oi, ls)
        notes += hm.notes
        charts.heatmap_chart(hm, k, str(IMG / "liq_heatmap.png"))
        charts.liquidation_map_chart(hm, str(IMG / "liq_map.png"))
        charts.derivatives_chart(k.tail(24 * 14), oi, funding, ls, str(IMG / "derivatives.png"),
                                 venue=venue)
        images += [("liq_heatmap.png", "預估清算熱力圖（近 14 天）"),
                   ("liq_map.png", "預估清算地圖（現價 ±12%）"),
                   ("derivatives.png", "價格、持倉量、資金費率、多空比（近 14 天）")]
    if "liq_long_usd" in summary_df and summary_df["liq_long_usd"].notna().any():
        charts.liquidations_daily_chart(summary_df, str(IMG / "liquidations_daily.png"))
        images.append(("liquidations_daily.png", "OKX 每日實際清算量（每天累積，歷史會越來越長）"))

    # 摘要數字
    tiles = []
    for ver, folder in (("v1", "paper"), ("v2", "paper_v2")):
        paper_json = ROOT / "data" / folder / "latest.json"
        if not paper_json.exists():
            continue
        try:
            p = json.loads(paper_json.read_text(encoding="utf-8"))
            pos = p["target_pos"]
            tiles.append((f"紙上交易 {ver} 建議倉位", f"{pos:.2f}x" if pos > 0 else "空手",
                          f"訊號日 {p['signal_date']}　詳見 {folder}/"))
        except (ValueError, KeyError):
            pass
    if k is not None:
        c = k["close"]
        chg = c.iloc[-1] / c[c.index <= c.index[-1] - pd.Timedelta("24h")].iloc[-1] - 1
        tiles.append(("BTC 價格", f"{c.iloc[-1]:,.0f}", f"24h {chg:+.2%}"))
    if etf is not None and len(etf):
        t = etf["Total"]
        tiles.append(("ETF 淨流入（最近交易日）", f"{t.iloc[-1]:+,.1f}M",
                      f"{t.index[-1]:%Y-%m-%d}　5 日合計 {t.tail(5).sum():+,.0f}M"))
    if oi is not None:
        d = oi.iloc[-1] / oi[oi.index <= oi.index[-1] - pd.Timedelta("24h")].iloc[-1] - 1 \
            if (oi.index <= oi.index[-1] - pd.Timedelta("24h")).any() else float("nan")
        tiles.append((f"{venue}期貨持倉量", f"${oi.iloc[-1] / 1e9:,.2f}B", f"24h {d:+.2%}"))
    if funding is not None:
        tiles.append(("資金費率（最新一期）", f"{funding.iloc[-1] * 100:.4f}%", ""))
    if hm is not None:
        lp = hm.last_price
        below = hm.price_bins < lp
        if hm.long_levels[below].any():
            i = np.argmax(np.where(below, hm.long_levels, 0))
            tiles.append(("下方最大清算區（多單）", f"{hm.price_bins[i]:,.0f}",
                          f"約 ${charts._usd(hm.long_levels[i])}"))
        if hm.short_levels[~below].any():
            i = np.argmax(np.where(~below, hm.short_levels, 0))
            tiles.append(("上方最大清算區（空單）", f"{hm.price_bins[i]:,.0f}",
                          f"約 ${charts._usd(hm.short_levels[i])}"))

    table = summary_df.tail(14).iloc[::-1].copy()
    fmt = {"close": "{:,.0f}", "oi_usd": lambda v: f"{v / 1e9:,.2f}B",
           "funding_avg": lambda v: f"{v * 100:.4f}%", "long_short_ratio": "{:.2f}",
           "liq_long_usd": lambda v: charts._usd(v), "liq_short_usd": lambda v: charts._usd(v),
           "etf_net_musd": "{:+,.1f}M"}
    for col, f in fmt.items():
        if col in table:
            table[col] = table[col].map(lambda v, f=f: "—" if pd.isna(v) else (f(v) if callable(f) else f.format(v)))
    table = table.rename(columns={"close": "收盤價", "oi_usd": "持倉量", "funding_avg": "平均資金費率",
                                  "long_short_ratio": "多空比", "liq_long_usd": "多單清算",
                                  "liq_short_usd": "空單清算", "etf_net_musd": "ETF 淨流入"})
    table.index = [pd.Timestamp(i).strftime("%Y-%m-%d") for i in table.index]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    (DOCS / "index.html").write_text(
        render_html({"updated": now, "tiles": tiles}, status, table, images, notes), encoding="utf-8")
    (DATA / "last_run.json").write_text(json.dumps({"updated_utc": now, "status": status},
                                                   ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"完成，輸出 {DOCS / 'index.html'}")
    return 0 if k is not None else 1  # 連 K 線都抓不到才算失敗


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BTC 每日資金流與清算報告（免費資料）")
    ap.add_argument("--demo", action="store_true", help="用模擬資料跑完整流程（不連網）")
    ap.add_argument("--out", help="輸出根目錄（預設為 repo 根目錄，會寫入 data/ 與 docs/）")
    return run(**vars(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
