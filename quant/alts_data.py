"""下載幣安「所有出現過」的 USDT 永續合約日線與資金費率（含已下架，避免存活者偏差）。

清單來自 data.binance.vision 的 S3 目錄（下架的合約仍保留歷史檔）。
輸出 data/raw/alts_panel.pkl（不進 git，約數十 MB）：長表格
    date, symbol, close, high, low, quote_volume, funding_day

用法：python -m quant.alts_data
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .history import RAW, ROOT, _session, fetch_many, log, read_csv_from_zip

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PANEL = ROOT / "data" / "raw" / "alts_panel.pkl"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def s3_list(prefix: str, folders: bool) -> list[str]:
    """列出 S3 前綴底下的子資料夾（folders=True）或檔案。"""
    out, marker = [], ""
    while True:
        params = {"prefix": prefix, "marker": marker}
        if folders:
            params["delimiter"] = "/"
        xml = _session.get(S3, params=params, timeout=60).text
        tag = "Prefix" if folders else "Key"
        found = [x for x in re.findall(rf"<{tag}>([^<]+)</{tag}>", xml) if x != prefix]
        out += found
        if "<IsTruncated>true</IsTruncated>" not in xml or not found:
            return out
        marker = found[-1]


def symbols() -> list[str]:
    pre = "data/futures/um/monthly/klines/"
    return sorted({p[len(pre):].rstrip("/") for p in s3_list(pre, True) if p.endswith("USDT/")})


def files_for(sym: str) -> tuple[list[str], list[str]]:
    k = [x for x in s3_list(f"data/futures/um/monthly/klines/{sym}/1d/", False) if x.endswith(".zip")]
    f = [x for x in s3_list(f"data/futures/um/monthly/fundingRate/{sym}/", False) if x.endswith(".zip")]
    strip = lambda xs: [x.removeprefix("data/futures/um/") for x in xs]  # noqa: E731
    return strip(k), strip(f)


def load_symbol(sym: str, klines: list[str], funding: list[str]) -> pd.DataFrame | None:
    blobs = fetch_many(klines, workers=4)
    if not blobs:
        return None
    k = pd.concat([read_csv_from_zip(b, KLINE_COLS) for b in blobs], ignore_index=True)
    k["date"] = pd.to_datetime(k["open_time"].astype("int64"), unit="ms", utc=True).dt.normalize()
    df = k.drop_duplicates("date").set_index("date")[["close", "high", "low", "quote_volume"]].astype(float)
    fb = fetch_many(funding, workers=4)
    if fb:
        f = pd.concat([read_csv_from_zip(b, ["calc_time", "funding_interval_hours", "last_funding_rate"])
                       for b in fb], ignore_index=True)
        t = pd.to_datetime(f["calc_time"].astype("int64"), unit="ms", utc=True).dt.normalize()
        df["funding_day"] = pd.Series(f["last_funding_rate"].astype(float).values, index=t).groupby(level=0).sum()
    else:
        df["funding_day"] = float("nan")
    df["symbol"] = sym
    return df.sort_index()


def main() -> int:
    syms = symbols()
    log(f"共 {len(syms)} 個 USDT 永續合約（含已下架）")
    with ThreadPoolExecutor(16) as ex:
        lists = dict(zip(syms, ex.map(files_for, syms)))
    log(f"檔案清單完成：K 線 {sum(len(v[0]) for v in lists.values())} 個月檔、"
        f"資金費率 {sum(len(v[1]) for v in lists.values())} 個月檔")
    frames = []
    with ThreadPoolExecutor(8) as ex:  # 8 個合約同時下載（每個再用 4 條連線）
        for i, df in enumerate(ex.map(lambda s: load_symbol(s, *lists[s]), syms), 1):
            if df is not None:
                frames.append(df)
            if i % 100 == 0:
                log(f"  {i}/{len(syms)}")
    panel = pd.concat(frames).reset_index()
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_pickle(PANEL)
    log(f"完成：{panel['symbol'].nunique()} 個合約、{len(panel)} 列 → {PANEL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
