"""從幣安官方歷史數據站 data.binance.vision 建立 BTC 歷史數據庫。

下載內容（USDT 本位永續 BTCUSDT）：
- 1 小時 K 線（含主動買入量）       2020-01 起
- 資金費率                         2020-01 起（只有月檔，最新一個月要等月底）
- 每 5 分鐘指標：持倉量、大戶/全體多空比、主動買賣量比   2020-09 起

原始 zip 存在 data/raw/（不進 git），重跑只會下載缺的檔案。
整理後輸出：
- data/history/btcusdt_1h.csv.gz      每小時：K 線 + 指標
- data/history/btcusdt_funding.csv.gz 每期資金費率
- data/history/btc_daily.csv.gz       每日特徵表（回測用）

用法：python -m quant.history
"""
from __future__ import annotations

import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "binance"
OUT = ROOT / "data" / "history"
BASE = "https://data.binance.vision/data/futures/um"
SYMBOL = "BTCUSDT"

KLINE_START = date(2020, 1, 1)
METRICS_START = date(2020, 9, 1)

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]

_session = requests.Session()
_session.headers["User-Agent"] = "btc-quant-research/0.1"


def log(msg: str) -> None:
    print(f"[history] {msg}", flush=True)


# ---------------------------------------------------------------- 下載與快取

def fetch_zip(rel: str) -> bytes | None:
    """下載 BASE/rel；有快取就用快取。404 回傳 None（不快取，之後可能會出現）。"""
    path = RAW / rel
    if path.exists():
        return path.read_bytes()
    for attempt in range(3):
        try:
            r = _session.get(f"{BASE}/{rel}", timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.content
        except requests.RequestException as e:
            if attempt == 2:
                log(f"下載失敗 {rel}: {e}")
                return None
    return None


def read_csv_from_zip(blob: bytes, columns: list[str] | None = None) -> pd.DataFrame:
    """讀 zip 裡唯一的 CSV。舊檔沒有表頭時，用 columns 補上。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    first = raw.split(b"\n", 1)[0].split(b",")[0].strip()
    has_header = not first.replace(b".", b"").replace(b"-", b"").isdigit()
    if has_header:
        return pd.read_csv(io.BytesIO(raw))
    return pd.read_csv(io.BytesIO(raw), header=None, names=columns)


def months(start: date, end_exclusive: date):
    y, m = start.year, start.month
    while date(y, m, 1) < end_exclusive:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def days(start: date, end_inclusive: date):
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def fetch_many(rels: list[str], workers: int = 8) -> list[bytes]:
    todo = [r for r in rels if not (RAW / r).exists()]
    if todo:
        log(f"需要下載 {len(todo)} 個檔案（已快取 {len(rels) - len(todo)} 個）")
    with ThreadPoolExecutor(workers) as ex:
        return [b for b in ex.map(fetch_zip, rels) if b is not None]


# ---------------------------------------------------------------- 各資料集

def load_klines(today: date) -> pd.DataFrame:
    this_month = date(today.year, today.month, 1)
    rels = [f"monthly/klines/{SYMBOL}/1h/{SYMBOL}-1h-{y}-{m:02d}.zip"
            for y, m in months(KLINE_START, this_month)]
    rels += [f"daily/klines/{SYMBOL}/1h/{SYMBOL}-1h-{d}.zip"
             for d in days(this_month, today - timedelta(days=1))]
    df = pd.concat([read_csv_from_zip(b, KLINE_COLS) for b in fetch_many(rels)], ignore_index=True)
    df["time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    keep = ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_volume"]
    return (df.drop_duplicates("time").sort_values("time").set_index("time")[keep].astype(float))


def load_funding(today: date) -> pd.Series:
    this_month = date(today.year, today.month, 1)
    rels = [f"monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{y}-{m:02d}.zip"
            for y, m in months(KLINE_START, this_month)]
    df = pd.concat([read_csv_from_zip(b, ["calc_time", "funding_interval_hours", "last_funding_rate"])
                    for b in fetch_many(rels)], ignore_index=True)
    df["time"] = pd.to_datetime(df["calc_time"].astype("int64"), unit="ms", utc=True)
    # 整點對齊（calc_time 偶爾有幾毫秒誤差）
    df["time"] = df["time"].dt.round("min")
    return df.drop_duplicates("time").sort_values("time").set_index("time")["last_funding_rate"].astype(float)


def load_metrics(today: date) -> pd.DataFrame:
    rels = [f"daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{d}.zip"
            for d in days(METRICS_START, today - timedelta(days=1))]
    frames = []
    for b in fetch_many(rels):
        try:
            frames.append(read_csv_from_zip(b))
        except Exception as e:  # noqa: BLE001 - 個別壞檔直接跳過
            log(f"略過無法解析的檔案: {e}")
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["create_time"], utc=True)
    cols = {
        "sum_open_interest": "oi_btc",
        "sum_open_interest_value": "oi_usd",
        "count_toptrader_long_short_ratio": "top_ls_account",
        "sum_toptrader_long_short_ratio": "top_ls_position",
        "count_long_short_ratio": "ls_account",
        "sum_taker_long_short_vol_ratio": "taker_ls_vol",
    }
    df = df.drop_duplicates("time").sort_values("time").set_index("time")[list(cols)].rename(columns=cols)
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.where(df > 0)  # 幣安原始檔偶有 0 值的壞數據，持倉量與比例都不可能 ≤ 0
    # 5 分鐘 → 1 小時：持倉量與比例取該小時最後一筆（時間戳 = 小時開始，與 K 線一致）
    hourly = df.resample("1h", label="left", closed="left").last()
    hourly["taker_ls_vol"] = df["taker_ls_vol"].resample("1h").mean()
    return hourly


# ---------------------------------------------------------------- 每日特徵表

def build_daily(h: pd.DataFrame, funding: pd.Series, etf: pd.Series | None) -> pd.DataFrame:
    """每一列 = 一個 UTC 日；所有欄位都是「當天結束時已知」的資訊。

    回測時：用第 D 天的特徵決定倉位，賺第 D+1 天的報酬（backtest.py 會自動錯開一天）。
    ETF 資金流：美股 D 日的流量在台灣時間 D+1 早上才公布，所以放在 D+1 這一列。
    """
    d = pd.DataFrame({
        "open": h["open"].resample("1D").first(),
        "high": h["high"].resample("1D").max(),
        "low": h["low"].resample("1D").min(),
        "close": h["close"].resample("1D").last(),
        "quote_volume": h["quote_volume"].resample("1D").sum(),
        "taker_buy_ratio": (h["taker_buy_volume"].resample("1D").sum()
                            / h["volume"].resample("1D").sum()),
        "oi_usd": h["oi_usd"].resample("1D").last(),
        "oi_btc": h["oi_btc"].resample("1D").last(),
        "ls_account": h["ls_account"].resample("1D").last(),
        "top_ls_position": h["top_ls_position"].resample("1D").last(),
    })
    d["ret"] = d["close"].pct_change()
    # 年化已實現波動率：用 1 小時報酬算，比日報酬穩定
    hr = np.log(h["close"]).diff()
    d["rv_30d"] = (hr.pow(2).resample("1D").sum().rolling(30).mean() * 365) ** 0.5
    d["funding_day"] = funding.resample("1D").sum().reindex(d.index)  # 當天 3 期資金費率合計
    f = d["funding_day"]
    d["funding_z30"] = (f - f.rolling(30).mean()) / f.rolling(30).std()
    d["oi_chg_1d"] = d["oi_btc"].pct_change(fill_method=None)
    d["oi_chg_7d"] = d["oi_btc"].pct_change(7, fill_method=None)
    if etf is not None:
        e = etf.copy()
        e.index = pd.to_datetime(e.index).tz_localize("UTC") + pd.Timedelta(days=1)
        d["etf_net_musd"] = e.reindex(d.index)
    d.index.name = "date"
    return d


def main() -> int:
    today = pd.Timestamp.now(tz="UTC").date()
    OUT.mkdir(parents=True, exist_ok=True)
    log("K 線…")
    k = load_klines(today)
    log(f"  {len(k)} 小時，{k.index[0]:%Y-%m-%d} ~ {k.index[-1]:%Y-%m-%d %H:%M}")
    log("資金費率…")
    f = load_funding(today)
    log(f"  {len(f)} 期，{f.index[0]:%Y-%m-%d} ~ {f.index[-1]:%Y-%m-%d}")
    log("持倉量與多空比（每日檔，第一次會比較久）…")
    m = load_metrics(today)
    log(f"  {m['oi_btc'].notna().sum()} 小時，{m.index[0]:%Y-%m-%d} ~ {m.index[-1]:%Y-%m-%d}")

    h = k.join(m, how="left")
    h.to_csv(OUT / "btcusdt_1h.csv.gz", float_format="%.8g")
    f.rename("funding_rate").to_csv(OUT / "btcusdt_funding.csv.gz", float_format="%.8g")

    etf_path = ROOT / "data" / "etf_flows.csv"
    etf = pd.read_csv(etf_path, index_col=0, parse_dates=True)["Total"] if etf_path.exists() else None
    daily = build_daily(h, f, etf)
    daily.to_csv(OUT / "btc_daily.csv.gz", float_format="%.8g")
    log(f"每日特徵表 {len(daily)} 天 → {OUT / 'btc_daily.csv.gz'}")
    return 0


def load_daily() -> pd.DataFrame:
    return pd.read_csv(OUT / "btc_daily.csv.gz", index_col=0, parse_dates=True)


if __name__ == "__main__":
    sys.exit(main())
