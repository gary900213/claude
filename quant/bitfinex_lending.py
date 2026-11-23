"""Bitfinex 放貸（Margin Funding）報酬研究。

數據：Bitfinex 公開 API 的每日放貸成交利率 K 線（trade:1D:fUSD / fUST，2 天期與 30 天期），
     存在 data/history/bitfinex_funding.csv.gz。利率單位是「每日」，年化 = 日利率 × 365。

做法與假設：
- 以每天的收盤成交利率代表「當天放出去拿得到的利率」（不是最高、也不是最低）
- 平台抽成：利息的 15%（隱藏掛單為 18%）；淨利率 = 毛利率 × 0.85
- 假設資金 100% 都借得出去（實際上會有閒置，掛太高利率時更明顯），所以是偏樂觀的上限
- 也比對 BTC 趨勢策略 v2 有持倉／空手時的利率：看「趨勢空手時拿去放貸」划不划算

用法：python -m quant.bitfinex_lending
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .history import OUT as HISTORY_DIR, load_daily  # noqa: E402
from .paper import STRATEGIES  # noqa: E402
from .strategies import trend_signal, vol_scale  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "bitfinex"
CSV = HISTORY_DIR / "bitfinex_funding.csv.gz"
API = "https://api-pub.bitfinex.com/v2/candles/trade:1D:{cur}:{period}/hist"
FEE = 0.15
BLUE, ORANGE, AQUA, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#52514e"


def download() -> pd.DataFrame:
    frames = {}
    for cur in ("fUSD", "fUST"):
        for p in ("p2", "p30"):
            r = requests.get(API.format(cur=cur, period=p), params={"limit": 10000, "sort": 1}, timeout=60)
            r.raise_for_status()
            df = pd.DataFrame(r.json(), columns=["t", "open", "close", "high", "low", "volume"])
            df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
            frames[f"{cur}_{p}"] = df[["open", "close", "high", "low", "volume"]]
    out = pd.concat(frames, axis=1)
    out.to_csv(CSV, float_format="%.8g")
    return out


def load(refresh: bool = True) -> pd.DataFrame:
    if refresh or not CSV.exists():
        try:
            return download()
        except requests.RequestException as e:
            print(f"[bitfinex] 下載失敗，改用存檔：{e}")
    return pd.read_csv(CSV, header=[0, 1], index_col=0, parse_dates=True)


def net_apr(daily_rate: pd.Series) -> pd.Series:
    return daily_rate * 365 * (1 - FEE)


def main(refresh: bool = True) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    f = load(refresh)
    series = {"美元 2 天期": f[("fUSD_p2", "close")], "美元 30 天期": f[("fUSD_p30", "close")],
              "USDT 2 天期": f[("fUST_p2", "close")], "USDT 30 天期": f[("fUST_p30", "close")]}
    apr = pd.DataFrame({k: net_apr(v) for k, v in series.items()})

    yearly = apr.groupby(apr.index.year).mean().map(lambda v: "—" if pd.isna(v) else f"{v:.1%}")
    yearly.index.name = "年度（扣 15% 抽成後的平均年化）"

    usd = apr["美元 2 天期"].dropna()
    dist = pd.DataFrame([{
        "幣別": k, "期間": f"{s.dropna().index[0]:%Y-%m} 起",
        "平均": f"{s.mean():.1%}", "中位數": f"{s.median():.1%}",
        "低於 4% 的天數": f"{(s < 0.04).mean():.0%}", "高於 10% 的天數": f"{(s > 0.10).mean():.0%}",
        "高於 20% 的天數": f"{(s > 0.20).mean():.0%}",
        "最近 30 天平均": f"{s.dropna().tail(30).mean():.1%}", "最近 90 天平均": f"{s.dropna().tail(90).mean():.1%}",
    } for k, s in apr.items()])

    # 和 BTC 趨勢 v2 對照：趨勢有持倉（多頭）時 vs 空手時，放貸利率差多少
    b = load_daily("BTCUSDT")
    b = b[b["close"].notna()]
    s2 = STRATEGIES["v2"]
    pos = trend_signal(b, tuple(s2["trend_lookbacks"])).clip(lower=0) * vol_scale(b, s2["target_vol"], s2["max_leverage"])
    pos = bt.apply_band(pos, s2["rebalance_band"])
    regime = (pos > 0).reindex(usd.index).dropna().astype(bool)  # 只看兩邊都有數據的期間（2020 起）
    usd = usd.reindex(regime.index)
    reg = pd.DataFrame([{"BTC 趨勢 v2": "有持倉（偏多頭）" if r else "空手（偏空頭／盤整）",
                         "天數比例": f"{(regime == r).mean():.0%}",
                         "美元放貸淨年化": f"{usd[regime == r].mean():.1%}",
                         "USDT 放貸淨年化": f"{apr['USDT 2 天期'].reindex(usd.index)[regime == r].mean():.1%}"}
                        for r in (True, False)])

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    for (k, color) in (("美元 2 天期", BLUE), ("USDT 2 天期", ORANGE)):
        s = apr[k].dropna().rolling(30).mean() * 100
        a1.plot(s.index, s, color=color, lw=1.6, label=f"{k}（30 天平均）")
    a1.axhline(4, color=TEXT_2, lw=1, ls="--")
    a1.text(apr.index[0], 4.6, "約 4%：美國短期公債利率（2023–2026）", color=TEXT_2, fontsize=8)
    a1.set_title("Bitfinex 放貸淨年化（扣 15% 抽成，%）")
    a1.set_ylim(bottom=0)
    a1.legend(frameon=False, loc="upper right")
    close = b["close"].loc[apr.index[0]:]
    a2.plot(close.index, close, color=TEXT_2, lw=1.2)
    a2.set_yscale("log")
    a2.set_title("BTC 價格（對數刻度）：利率高的時候大多是牛市")
    a2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(OUT / "lending.png", dpi=150)
    plt.close(fig)

    lines = [
        "# Bitfinex 放貸報酬研究",
        "",
        "數據：Bitfinex 公開 API 每日放貸成交利率（收盤），扣除 15% 平台抽成。"
        "假設資金 100% 借得出去，實際會有閒置，所以這是偏樂觀的上限。",
        "",
        "![放貸利率](lending.png)",
        "",
        "## 各年度平均淨年化",
        "",
        yearly.to_markdown(),
        "",
        "## 分布與近期",
        "",
        dist.to_markdown(index=False),
        "",
        "## 和 BTC 趨勢策略對照",
        "",
        "趨勢策略空手時，放貸利率通常也比較低（借錢做多的人少）。",
        "",
        reg.to_markdown(index=False),
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
