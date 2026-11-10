"""即時模式：直接用幣安期貨 API 補上歷史檔還沒發布的最近數據，訊號零延遲。

只能在幣安 API 可以連線的地方使用（例如台灣的電腦）；美國主機（含 GitHub Actions）
會被回 451，這時自動退回「歷史檔模式」（延遲約 1 天）。

做法：
- 歷史部分沿用 data/history/btcusdt_1h.csv.gz（幣安官方歷史檔）。
- 歷史檔之後缺的小時，用 API 補：1 小時 K 線、持倉量、全體多空帳戶比、大戶持倉多空比、
  主動買賣量比、資金費率。API 的持倉量／多空比只提供最近 30 天，所以歷史檔要先更新。
- 時間對齊：歷史檔每小時取「該小時最後一筆 5 分鐘快照」；API 的整點快照（時間戳 T）
  對應的是前一小時的最後狀態，所以標記為 T − 1 小時。
- 訊號用「最後一個完整的 UTC 日」計算；另外給一個「如果現在收盤」的預覽。

用法：
    python -m quant.live                    # 產生即時訊號（並寫入紙上交易紀錄）
    python -m quant.live --capital 10000    # 同上，並換算成下單數量
    python -m quant.live --check    # 檢查 API 數據與歷史檔重疊部分是否一致
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

from .history import OUT as HISTORY_DIR, build_daily

FAPI = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"

_session = requests.Session()
_session.headers["User-Agent"] = "btc-quant-research/0.1"


class LiveUnavailable(RuntimeError):
    pass


def _get(path: str, params: dict) -> list:
    try:
        r = _session.get(FAPI + path, params={"symbol": SYMBOL, **params}, timeout=20)
    except requests.RequestException as e:
        raise LiveUnavailable(f"連不上幣安 API：{e}") from e
    if r.status_code == 451:
        raise LiveUnavailable("幣安 API 回 451：這台機器所在地區被限制（例如美國），請在台灣的電腦上執行")
    r.raise_for_status()
    return r.json()


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def fetch_klines(start: pd.Timestamp) -> pd.DataFrame:
    rows, cursor = [], start
    while True:
        batch = _get("/fapi/v1/klines", {"interval": "1h", "startTime": _ms(cursor), "limit": 1500})
        if not batch:
            break
        rows += batch
        if len(batch) < 1500:
            break
        cursor = pd.Timestamp(batch[-1][0], unit="ms", tz="UTC") + pd.Timedelta("1h")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).iloc[:, [0, 1, 2, 3, 4, 5, 7, 9, 6]]
    df.columns = ["open_time", "open", "high", "low", "close", "volume", "quote_volume",
                  "taker_buy_volume", "close_time"]
    now_ms = _ms(pd.Timestamp.now(tz="UTC"))
    df = df[df["close_time"].astype("int64") < now_ms]  # 只要已經收完的 K 棒
    df.index = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_volume"]].astype(float)


def _futures_data(path: str, start: pd.Timestamp, fields: dict[str, str]) -> pd.DataFrame:
    """/futures/data/* 系列：最多 30 天、每次 500 筆，往回翻頁。"""
    start = max(start, pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=29))
    rows, end = [], None
    for _ in range(4):
        params = {"period": "1h", "limit": 500, "startTime": _ms(start)}
        if end is not None:
            params["endTime"] = end
        batch = _get(path, params)
        if not batch:
            break
        rows = batch + rows
        first = int(batch[0]["timestamp"])
        if first <= _ms(start) or len(batch) < 500:
            break
        end = first - 1
    if not rows:
        return pd.DataFrame(columns=list(fields.values()))
    df = pd.DataFrame(rows).drop_duplicates("timestamp")
    # 整點快照 T = 前一小時的最後狀態 → 標記為 T − 1h，與歷史檔一致
    idx = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True) - pd.Timedelta("1h")
    out = pd.DataFrame({new: pd.to_numeric(df[old], errors="coerce").values for old, new in fields.items()},
                       index=idx)
    return out.sort_index()


def fetch_metrics(start: pd.Timestamp) -> pd.DataFrame:
    parts = [
        _futures_data("/futures/data/openInterestHist", start,
                      {"sumOpenInterest": "oi_btc", "sumOpenInterestValue": "oi_usd"}),
        _futures_data("/futures/data/globalLongShortAccountRatio", start,
                      {"longShortRatio": "ls_account"}),
        _futures_data("/futures/data/topLongShortAccountRatio", start,
                      {"longShortRatio": "top_ls_account"}),
        _futures_data("/futures/data/topLongShortPositionRatio", start,
                      {"longShortRatio": "top_ls_position"}),
        _futures_data("/futures/data/takerlongshortRatio", start, {"buySellRatio": "taker_ls_vol"}),
    ]
    return pd.concat(parts, axis=1)


def fetch_funding(start: pd.Timestamp) -> pd.Series:
    data = _get("/fapi/v1/fundingRate", {"startTime": _ms(start), "limit": 1000})
    if not data:
        return pd.Series(dtype=float)
    t = pd.to_datetime([int(x["fundingTime"]) for x in data], unit="ms", utc=True).round("min")
    return pd.Series([float(x["fundingRate"]) for x in data], index=t).sort_index()


def load_archive() -> tuple[pd.DataFrame, pd.Series]:
    h = pd.read_csv(HISTORY_DIR / "btcusdt_1h.csv.gz", index_col=0, parse_dates=True)
    f = pd.read_csv(HISTORY_DIR / "btcusdt_funding.csv.gz", index_col=0, parse_dates=True)["funding_rate"]
    return h, f


def merge_live(h: pd.DataFrame, f: pd.Series, k: pd.DataFrame, m: pd.DataFrame,
               lf: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """歷史檔優先；只補歷史檔沒有的小時／欄位。"""
    live = k.join(m, how="left") if not k.empty else m
    live = live.reindex(columns=h.columns)
    merged = h.combine_first(live)
    funding = f.combine_first(lf) if len(lf) else f
    return merged.sort_index(), funding.sort_index()


def build_live_daily() -> tuple[pd.DataFrame, dict]:
    """回傳 (每日特徵表, 說明)。最後一列可能是今天（尚未收盤）。"""
    h, f = load_archive()
    start = h.index.max() - pd.Timedelta(days=2)  # 和歷史檔重疊兩天，方便檢查
    k = fetch_klines(start)
    m = fetch_metrics(start)
    lf = fetch_funding(f.index.max() - pd.Timedelta(days=1))
    merged, funding = merge_live(h, f, k, m, lf)
    etf_path = HISTORY_DIR.parent / "etf_flows.csv"
    etf = pd.read_csv(etf_path, index_col=0, parse_dates=True)["Total"] if etf_path.exists() else None
    daily = build_daily(merged, funding, etf)
    info = {"archive_until": f"{h.index.max():%Y-%m-%d %H:%M}",
            "live_until": f"{merged.index.max():%Y-%m-%d %H:%M}",
            "live_hours_added": int(len(merged) - len(h))}
    return daily, info


def check_overlap() -> int:
    """比較 API 與歷史檔重疊的小時，確認欄位定義一致。"""
    h, _ = load_archive()
    start = h.index.max() - pd.Timedelta(days=7)
    k, m = fetch_klines(start), fetch_metrics(start)
    live = k.join(m, how="outer")
    both = h.join(live, how="inner", rsuffix="_live")
    print(f"重疊 {len(both)} 小時（{both.index.min()} ~ {both.index.max()}）")
    for col in ["close", "volume", "oi_btc", "ls_account", "top_ls_position", "taker_ls_vol"]:
        if f"{col}_live" not in both:
            continue
        a, b = both[col], both[f"{col}_live"]
        ok = a.notna() & b.notna()
        if ok.any():
            diff = ((b[ok] - a[ok]).abs() / a[ok].abs()).median()
            print(f"  {col:16s} 中位相對差 {diff:.4%}（{ok.sum()} 筆）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="即時模式（需要能連幣安 API）")
    ap.add_argument("--check", action="store_true", help="檢查 API 與歷史檔是否一致")
    ap.add_argument("--capital", type=float, help="總資金（美元），用來換算下單數量")
    ap.add_argument("--version", default="v1", help="凍結策略版本（v1 或 v2）")
    ap.add_argument("--no-fallback", action="store_true", help="即時模式失敗時不要退回歷史檔模式")
    args = ap.parse_args(argv)
    # 用 python -m 執行時本檔會以 __main__ 與 quant.live 兩個名字載入，兩個例外類別都要接
    from quant.live import LiveUnavailable as _LU
    from . import paper
    try:
        if args.check:
            return check_overlap()
        return paper.main(live=True, capital=args.capital, version=args.version)
    except (LiveUnavailable, _LU) as e:
        print(f"[live] {e}")
        if args.check or args.no_fallback:
            return 2
        print("[live] 改用歷史檔模式（延遲約 1 天）")
        return paper.main(live=False, capital=args.capital, version=args.version)


if __name__ == "__main__":
    sys.exit(main())
