"""免費公開資料來源（不需 API key）。

每個函式都會依序嘗試多個來源，全部失敗才拋出例外。
注意：Binance 對美國 IP（含 GitHub Actions 主機）會回 451，
所以期貨數據會自動退回 OKX；K 線退回 data-api.binance.vision（現貨）。
"""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser

import pandas as pd
import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "*/*"})

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT_PUBLIC = "https://data-api.binance.vision"
OKX = "https://www.okx.com"
FARSIDE_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"


class SourceError(RuntimeError):
    pass


def _get(url: str, params: dict | None = None, timeout: int = 20):
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def _first_ok(*attempts):
    """依序呼叫 (名稱, 函式)，回傳 (名稱, 結果)。"""
    errors = []
    for name, fn in attempts:
        try:
            return name, fn()
        except Exception as e:  # noqa: BLE001 - 想把所有失敗原因都收集起來
            errors.append(f"{name}: {e}")
    raise SourceError("; ".join(errors))


# ---------------------------------------------------------------- K 線（1 小時）

def _binance_klines(base: str, path: str, hours: int) -> pd.DataFrame:
    rows, end = [], None
    while len(rows) < hours:
        params = {"symbol": "BTCUSDT", "interval": "1h", "limit": min(1000, hours - len(rows))}
        if end:
            params["endTime"] = end
        batch = _get(base + path, params).json()
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    return df


def _okx_klines(hours: int) -> pd.DataFrame:
    rows, after = [], None
    while len(rows) < hours:
        params = {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": 100}
        if after:
            params["after"] = after
        data = _get(OKX + "/api/v5/market/history-candles", params).json()["data"]
        if not data:
            break
        rows.extend(data)
        after = data[-1][0]
        time.sleep(0.15)
    # 欄位: ts,o,h,l,c,vol(張),volCcy(BTC),...；統一用 BTC 計的成交量
    df = pd.DataFrame(rows).iloc[:, [0, 1, 2, 3, 4, 6]]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    return df


def fetch_klines(hours: int = 24 * 30) -> tuple[str, pd.DataFrame]:
    """1 小時 K 線；volume 單位一律為 BTC。"""
    name, df = _first_ok(
        ("binance-futures", lambda: _binance_klines(BINANCE_FAPI, "/fapi/v1/klines", hours)),
        ("okx-swap", lambda: _okx_klines(hours)),
        ("binance-spot", lambda: _binance_klines(BINANCE_SPOT_PUBLIC, "/api/v3/klines", hours)),
    )
    df = df.astype(float)
    df["time"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    df = df.drop(columns="ts").drop_duplicates("time").sort_values("time")
    return name, df.set_index("time").tail(hours)


# ---------------------------------------------------------------- 持倉量（1 小時）

def _binance_oi() -> pd.DataFrame:
    # Binance 只提供最近 30 天，單次最多 500 筆
    rows, end = [], None
    for _ in range(2):
        params = {"symbol": "BTCUSDT", "period": "1h", "limit": 500}
        if end:
            params["endTime"] = end
        batch = _get(BINANCE_FAPI + "/futures/data/openInterestHist", params).json()
        if not batch:
            break
        rows = batch + rows
        end = batch[0]["timestamp"] - 1
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "time": pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True),
        "oi_usd": df["sumOpenInterestValue"].astype(float),
    })


def _okx_oi() -> pd.DataFrame:
    data = _get(OKX + "/api/v5/rubik/stat/contracts/open-interest-volume",
                {"ccy": "BTC", "period": "1H"}).json()["data"]
    return pd.DataFrame({
        "time": pd.to_datetime([int(r[0]) for r in data], unit="ms", utc=True),
        "oi_usd": [float(r[1]) for r in data],
    })


def fetch_open_interest() -> tuple[str, pd.Series]:
    name, df = _first_ok(("binance", _binance_oi), ("okx", _okx_oi))
    df = df.drop_duplicates("time").sort_values("time").set_index("time")
    return name, df["oi_usd"]


# ---------------------------------------------------------------- 資金費率

def _binance_funding() -> pd.DataFrame:
    data = _get(BINANCE_FAPI + "/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": 200}).json()
    return pd.DataFrame({
        "time": pd.to_datetime([int(r["fundingTime"]) for r in data], unit="ms", utc=True),
        "funding_rate": [float(r["fundingRate"]) for r in data],
    })


def _okx_funding() -> pd.DataFrame:
    data = _get(OKX + "/api/v5/public/funding-rate-history",
                {"instId": "BTC-USDT-SWAP", "limit": 100}).json()["data"]
    return pd.DataFrame({
        "time": pd.to_datetime([int(r["fundingTime"]) for r in data], unit="ms", utc=True),
        "funding_rate": [float(r["realizedRate"] or r["fundingRate"]) for r in data],
    })


def fetch_funding() -> tuple[str, pd.Series]:
    name, df = _first_ok(("binance", _binance_funding), ("okx", _okx_funding))
    return name, df.drop_duplicates("time").sort_values("time").set_index("time")["funding_rate"]


# ---------------------------------------------------------------- 多空帳戶比

def _binance_ls() -> pd.DataFrame:
    data = _get(BINANCE_FAPI + "/futures/data/globalLongShortAccountRatio",
                {"symbol": "BTCUSDT", "period": "1h", "limit": 500}).json()
    return pd.DataFrame({
        "time": pd.to_datetime([int(r["timestamp"]) for r in data], unit="ms", utc=True),
        "long_short_ratio": [float(r["longShortRatio"]) for r in data],
    })


def _okx_ls() -> pd.DataFrame:
    data = _get(OKX + "/api/v5/rubik/stat/contracts/long-short-account-ratio",
                {"ccy": "BTC", "period": "1H"}).json()["data"]
    return pd.DataFrame({
        "time": pd.to_datetime([int(r[0]) for r in data], unit="ms", utc=True),
        "long_short_ratio": [float(r[1]) for r in data],
    })


def fetch_long_short() -> tuple[str, pd.Series]:
    name, df = _first_ok(("binance", _binance_ls), ("okx", _okx_ls))
    return name, df.drop_duplicates("time").sort_values("time").set_index("time")["long_short_ratio"]


# ---------------------------------------------------------------- 實際清算單（OKX）

OKX_BTC_USDT_CT_VAL = 0.01  # BTC-USDT-SWAP 每張合約 = 0.01 BTC


def fetch_okx_liquidations(max_pages: int = 50) -> pd.DataFrame:
    """OKX 公開的 BTC-USDT 永續強平單（只保留最近幾天）。

    回傳欄位：time, side('long'/'short' 被清算的方向), price, usd
    """
    rows, after = [], None
    for _ in range(max_pages):
        params = {"instType": "SWAP", "instFamily": "BTC-USDT", "state": "filled", "limit": 100}
        if after:
            params["after"] = after
        data = _get(OKX + "/api/v5/public/liquidation-orders", params).json().get("data", [])
        details = [d for blk in data for d in blk.get("details", [])]
        if not details:
            break
        for d in details:
            px, sz = float(d["bkPx"]), float(d["sz"])
            pos = d.get("posSide")
            if pos not in ("long", "short"):  # 單向持倉模式：賣出強平 = 多單被清
                pos = "long" if d.get("side") == "sell" else "short"
            rows.append({"ts": int(d["ts"]), "side": pos, "price": px,
                         "usd": sz * OKX_BTC_USDT_CT_VAL * px})
        oldest = min(int(d["ts"]) for d in details)
        if after is not None and str(oldest) == after:
            break
        after = str(oldest)
        time.sleep(0.15)
    df = pd.DataFrame(rows, columns=["ts", "side", "price", "usd"]).drop_duplicates()
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns="ts").sort_values("time")


# ---------------------------------------------------------------- 現貨 ETF 資金流（Farside）

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


_DATE_RE = re.compile(r"^\d{1,2} [A-Z][a-z]{2} \d{4}$")


def _parse_number(s: str) -> float:
    s = s.replace(",", "").strip()
    if s in ("", "-", "–", "—"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    return -float(s.strip("()")) if neg else float(s)


def parse_farside(html: str) -> pd.DataFrame:
    """把 Farside 表格轉成 DataFrame（單位：百萬美元），index 為日期，含 Total 欄。"""
    p = _TableParser()
    p.feed(html)
    for table in p.tables:
        header = next((r for r in table if "Total" in r), None)
        if header is None:
            continue
        cols = header[1:]
        records = {}
        for row in table:
            if not row or not _DATE_RE.match(row[0]) or len(row) != len(header):
                continue
            try:
                records[pd.to_datetime(row[0], format="%d %b %Y")] = [_parse_number(v) for v in row[1:]]
            except ValueError:
                continue  # 尚未公布的欄位
        if records:
            df = pd.DataFrame.from_dict(records, orient="index", columns=cols).sort_index()
            df.index.name = "date"
            return df
    raise SourceError("找不到 ETF 資金流表格（網站改版或被 Cloudflare 擋下）")


def fetch_etf_flows() -> pd.DataFrame:
    return parse_farside(_get(FARSIDE_URL, timeout=30).text)
