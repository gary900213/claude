"""用 matplotlib 輸出 PNG 圖表。"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, PowerNorm  # noqa: E402

from .heatmap import HeatmapResult  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"      # 流入 / 多單
RED = "#e34948"       # 流出
ORANGE = "#eb6834"    # 空單
SEQ_BLUE = ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
            "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "text.color": TEXT,
    "xtick.color": TEXT_2, "ytick.color": TEXT_2, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "font.sans-serif": ["Noto Sans CJK TC", "Noto Sans CJK JP", "Microsoft JhengHei",
                        "PingFang TC", "Heiti TC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})


def _usd(x: float) -> str:
    a = abs(x)
    if a >= 1e9:
        return f"{x / 1e9:.2f}B"
    if a >= 1e6:
        return f"{x / 1e6:.1f}M"
    if a >= 1e3:
        return f"{x / 1e3:.0f}K"
    return f"{x:.0f}"


def etf_flows_chart(etf: pd.DataFrame, path: str, days: int = 90) -> None:
    """上：每日淨流入（百萬美元）；下：累計淨流入。兩張圖共用時間軸、各自一個 Y 軸。"""
    total = etf["Total"].tail(days)
    cum = etf["Total"].cumsum().tail(days) / 1000  # 十億美元
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 2]})
    colors = np.where(total.values >= 0, BLUE, RED)
    a1.bar(total.index, total.values, color=colors, width=0.8)
    a1.axhline(0, color=TEXT_2, lw=0.8)
    a1.set_title(f"BTC 現貨 ETF 每日淨流入（百萬美元，近 {days} 個交易日）")
    last_d, last_v = total.index[-1], total.iloc[-1]
    a1.annotate(f"{last_d:%m/%d}  {last_v:+,.1f}M", (last_d, last_v),
                xytext=(0, 8 if last_v >= 0 else -16), textcoords="offset points",
                ha="right", color=TEXT, fontsize=9)
    a2.plot(cum.index, cum.values, color=BLUE, lw=2)
    a2.set_title("自上市以來累計淨流入（十億美元）")
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.text(0.01, 0.005, "資料來源：Farside Investors　藍=流入　紅=流出", color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def heatmap_chart(hm: HeatmapResult, klines: pd.DataFrame, path: str) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    m = hm.matrix.T
    vmax = np.percentile(m[m > 0], 99) if (m > 0).any() else 1
    cmap = LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE)
    t = mdates.date2num(hm.times.to_pydatetime())
    step = hm.price_bins[1] - hm.price_bins[0]
    ax.imshow(m, aspect="auto", origin="lower", cmap=cmap, norm=PowerNorm(0.5, 0, vmax),
              extent=[t[0], t[-1] + (t[1] - t[0]), hm.price_bins[0] - step / 2,
                      hm.price_bins[-1] + step / 2], interpolation="nearest")
    k = klines.loc[hm.times]
    ax.plot(t, k["close"].values, color=ORANGE, lw=1.5, label="BTC 收盤價")
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(False)
    ax.set_title("BTC 預估清算熱力圖（顏色越深 = 該價位累積的潛在清算量越大）")
    ax.legend(loc="upper right", facecolor=SURFACE, edgecolor=GRID, framealpha=0.9)
    src = "持倉量變化" if hm.used_oi else "成交量"
    fig.text(0.01, 0.005, f"免費近似模型：以 {src} + 多空比 + 假設槓桿分佈推估，非 CoinGlass 官方數據",
             color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def liquidation_map_chart(hm: HeatmapResult, path: str, window_pct: float = 0.12) -> None:
    """現在這一刻：各價位的潛在清算量（多單在下、空單在上）+ 累計曲線。"""
    p = hm.price_bins
    sel = np.abs(p / hm.last_price - 1) <= window_pct
    p, lg, sh = p[sel], hm.long_levels[sel], hm.short_levels[sel]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 2]})
    width = (p[1] - p[0]) * 0.85
    a1.bar(p, lg / 1e6, width=width, color=BLUE, label="多單清算（價格下跌觸發）")
    a1.bar(p, sh / 1e6, width=width, color=ORANGE, label="空單清算（價格上漲觸發）")
    a1.axvline(hm.last_price, color=TEXT, lw=1, ls="--")
    a1.annotate(f"現價 {hm.last_price:,.0f}", (hm.last_price, a1.get_ylim()[1] * 0.95),
                xytext=(4, 0), textcoords="offset points", fontsize=9)
    a1.set_title("BTC 預估清算地圖（百萬美元 / 價格格子）")
    a1.legend(loc="upper left", frameon=False)
    below = p < hm.last_price
    cum_long = np.where(below, np.cumsum(lg[::-1])[::-1], np.nan)
    cum_short = np.where(~below, np.cumsum(sh), np.nan)
    a2.plot(p, cum_long / 1e6, color=BLUE, lw=2)
    a2.plot(p, cum_short / 1e6, color=ORANGE, lw=2)
    a2.axvline(hm.last_price, color=TEXT, lw=1, ls="--")
    a2.set_title("若價格走到該處，累計會被清算的金額（百萬美元）")
    a2.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def derivatives_chart(klines: pd.DataFrame, oi: pd.Series | None, funding: pd.Series | None,
                      ls: pd.Series | None, path: str) -> None:
    panels = [("BTC 價格（USDT）", klines["close"], lambda v: f"{v:,.0f}")]
    if oi is not None and len(oi):
        panels.append(("期貨持倉量（十億美元）", oi / 1e9, lambda v: f"{v:.1f}"))
    if funding is not None and len(funding):
        panels.append(("資金費率（%／每期）", funding * 100, lambda v: f"{v:.3f}"))
    if ls is not None and len(ls):
        panels.append(("多空帳戶比", ls, lambda v: f"{v:.2f}"))
    start = klines.index[0]
    fig, axes = plt.subplots(len(panels), 1, figsize=(11, 2.2 * len(panels)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (title, s, fmt) in zip(axes, panels):
        s = s[s.index >= start]
        if "資金費率" in title:
            ax.bar(s.index, s.values, width=0.25, color=np.where(s.values >= 0, BLUE, RED))
            ax.axhline(0, color=TEXT_2, lw=0.8)
        else:
            ax.plot(s.index, s.values, color=BLUE, lw=1.6)
        if "多空" in title:
            ax.axhline(1, color=TEXT_2, lw=0.8, ls=":")
        ax.set_title(f"{title}　最新 {fmt(s.iloc[-1])}", fontsize=11)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def liquidations_daily_chart(daily: pd.DataFrame, path: str, days: int = 60) -> None:
    d = daily.dropna(subset=["liq_long_usd", "liq_short_usd"]).tail(days)
    if d.empty:
        return
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar(x - 0.2, d["liq_long_usd"] / 1e6, width=0.38, color=BLUE, label="多單被清算")
    ax.bar(x + 0.2, d["liq_short_usd"] / 1e6, width=0.38, color=ORANGE, label="空單被清算")
    ax.set_xticks(x)
    ax.set_xticklabels([pd.Timestamp(i).strftime("%m/%d") for i in d.index], rotation=45, ha="right")
    ax.set_title("OKX BTC-USDT 永續每日實際清算量（百萬美元，UTC 日）")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
