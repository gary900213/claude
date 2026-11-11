"""山寨幣（土狗幣）做空策略研究。

假設在看數據之前就寫死（見下方 HYPOTHESES），避免事後挑選：
- H1 新上市做空：上市第 7 天收盤做空，持有 30／90／180 天
- H2 暴漲後做空：7 日漲幅 > 100% 當天收盤做空，持有 14 天
- H3 弱勢幣做空：每週一做空過去 30 天跌最多的 20%，持有 7 天
       （對照：做空漲最多的 20%，文獻認為強者恆強、弱者常反彈）
- H4 高資金費率做空：當天資金費率年化 > 100% 時做空，持有 7 天（空頭收資金費率）

共同規則：
- 宇宙：幣安所有出現過的 USDT 永續（含已下架），排除 BTC、ETH 與穩定幣類
- 流動性：近 30 天平均成交額 ≥ 500 萬美元才交易
- 成本：進出各 20 bps；資金費率照實計（正 = 空頭收錢）
- 空單 1 倍保證金：當天最高價 ≥ 進場價 × 1.9 視為爆倉，該筆虧損 100%
- 合約下架（數據中斷）：以最後一個收盤價出場
- 組合：每天對「所有持有中的部位」等權重
- 市場中性版本：同時做多等量 BTC，扣掉大盤漲跌，看純選幣能力

用法：python -m quant.short_alts   （先跑 python -m quant.alts_data）
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from btc_daily import charts as _style  # noqa: E402,F401 - 共用圖表樣式與中文字型
from . import backtest as bt  # noqa: E402
from .alts_data import PANEL  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "short_alts"
COST_BPS = 20.0
MIN_ADV = 5e6
LIQ_MULT = 1.9
EXCLUDE = {"BTCUSDT", "ETHUSDT", "USDCUSDT", "BTCDOMUSDT", "DEFIUSDT", "FDUSDUSDT", "TUSDUSDT",
           "BUSDUSDT", "USDPUSDT", "EURUSDT", "AEURUSDT"}
BLUE, ORANGE, AQUA, YELLOW, VIOLET, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6", "#52514e"


@dataclass
class Panel:
    close: pd.DataFrame
    high: pd.DataFrame
    adv30: pd.DataFrame
    funding: pd.DataFrame
    listed: pd.Series      # 第一天
    last: pd.Series        # 最後一天
    btc_ret: pd.Series


def load_panel() -> Panel:
    p = pd.read_pickle(PANEL)
    p = p[~p["symbol"].isin(EXCLUDE - {"BTCUSDT"})]
    wide = lambda c: p.pivot_table(index="date", columns="symbol", values=c)  # noqa: E731
    close, high, qv = wide("close"), wide("high"), wide("quote_volume")
    funding = wide("funding_day").reindex_like(close).fillna(0.0)
    btc_ret = close["BTCUSDT"].pct_change()
    close, high, qv, funding = (x.drop(columns="BTCUSDT") for x in (close, high, qv, funding))
    adv30 = qv.rolling(30, min_periods=5).mean()
    listed = close.apply(lambda s: s.first_valid_index())
    last = close.apply(lambda s: s.last_valid_index())
    return Panel(close, high, adv30, funding, listed, last, btc_ret)


def simulate(pn: Panel, entries: list[tuple[str, pd.Timestamp, int]]) -> tuple[pd.Series, pd.DataFrame]:
    """entries：(合約, 進場日, 持有天數)。進場日收盤做空。

    回傳 (組合每日報酬, 每筆部位明細)。部位每日報酬以「該部位前一天的權益」計。
    """
    idx = pn.close.index
    pos_index = {d: i for i, d in enumerate(idx)}
    daily_sum = np.zeros(len(idx))
    daily_n = np.zeros(len(idx))
    rows = []
    open_until: dict[str, pd.Timestamp] = {}
    for sym, d0, hold in sorted(entries, key=lambda x: x[1]):
        if sym in open_until and d0 <= open_until[sym]:
            continue  # 同一個幣已經有部位，不重複
        i0 = pos_index[d0]
        c = pn.close[sym].values
        h = pn.high[sym].values
        f = pn.funding[sym].values
        p0 = c[i0]
        if not np.isfinite(p0):
            continue
        equity = 1.0 - COST_BPS / 1e4  # 進場成本
        daily_sum[i0] += -COST_BPS / 1e4  # 記在進場當天
        daily_n[i0] += 1
        exit_i, why = i0, "到期"
        for i in range(i0 + 1, min(i0 + hold, len(idx) - 1) + 1):
            if not np.isfinite(c[i]):
                why = "下架"
                break
            prev_eq = equity
            if np.isfinite(h[i]) and h[i] >= p0 * LIQ_MULT:
                equity, why = 0.0, "爆倉"
            else:
                # 固定數量空單：權益 = 1 + (p0 − 價格)/p0 + 累計資金費率（以名目 1 計）
                pnl_today = (c[i - 1] - c[i]) / p0 + f[i] * c[i - 1] / p0
                equity = prev_eq + pnl_today
            r = equity / prev_eq - 1 if prev_eq > 0 else 0.0
            exit_i = i
            if why == "爆倉" or equity <= 0:
                equity, r = 0.0, -1.0
                daily_sum[i] += r
                daily_n[i] += 1
                why = "爆倉"
                break
            daily_sum[i] += r
            daily_n[i] += 1
        if why != "爆倉" and equity > 0:
            equity *= 1 - COST_BPS / 1e4
            daily_sum[exit_i] += -COST_BPS / 1e4
        open_until[sym] = idx[exit_i]
        rows.append({"symbol": sym, "entry": d0, "exit": idx[exit_i], "days": exit_i - i0,
                     "return": equity - 1, "reason": why})
    port = pd.Series(np.where(daily_n > 0, daily_sum / np.maximum(daily_n, 1), 0.0), index=idx)
    port.attrs["exposure"] = pd.Series(daily_n > 0, index=idx)
    return port, pd.DataFrame(rows)


# ---------------------------------------------------------------- 假設的進場規則

def tradable(pn: Panel, d: pd.Timestamp, sym: str) -> bool:
    v = pn.adv30.at[d, sym]
    return bool(np.isfinite(v) and v >= MIN_ADV)


def h1_new_listing(pn: Panel, hold: int, day: int = 7) -> list:
    out = []
    first_data = pn.close.index[0]
    for sym, d0 in pn.listed.items():
        if d0 <= first_data + pd.Timedelta(days=31):  # 數據開頭就在的，不算新上市
            continue
        d = d0 + pd.Timedelta(days=day)
        if d in pn.close.index and tradable(pn, d, sym):
            out.append((sym, d, hold))
    return out


def h2_pump(pn: Panel, thresh: float = 1.0, hold: int = 14) -> list:
    r7 = pn.close / pn.close.shift(7) - 1
    hits = (r7 > thresh) & (pn.adv30 >= MIN_ADV)
    return [(pn.close.columns[j], pn.close.index[i], hold) for i, j in zip(*np.where(hits.values))]


def h3_rank(pn: Panel, bottom: bool, frac: float = 0.2, hold: int = 7) -> list:
    r30 = pn.close / pn.close.shift(30) - 1
    age = (pn.close.index.values[:, None] - pn.listed.reindex(pn.close.columns).values[None, :])
    old_enough = pd.DataFrame(age >= np.timedelta64(60, "D"), index=pn.close.index, columns=pn.close.columns)
    out = []
    for d in pn.close.index[pn.close.index.dayofweek == 0]:
        ok = old_enough.loc[d] & (pn.adv30.loc[d] >= MIN_ADV) & r30.loc[d].notna()
        s = r30.loc[d][ok]
        if len(s) < 10:
            continue
        n = max(1, int(len(s) * frac))
        pick = s.nsmallest(n) if bottom else s.nlargest(n)
        out += [(sym, d, hold) for sym in pick.index]
    return out


def h4_funding(pn: Panel, ann: float = 1.0, hold: int = 7) -> list:
    hits = (pn.funding * 365 > ann) & (pn.adv30 >= MIN_ADV)
    return [(pn.close.columns[j], pn.close.index[i], hold) for i, j in zip(*np.where(hits.values))]


# ---------------------------------------------------------------- 報告

def summarize(name: str, port: pd.Series, trades: pd.DataFrame, btc_ret: pd.Series) -> tuple[dict, pd.Series]:
    active = port.attrs["exposure"]
    start = active[active].index.min()
    net = port.loc[start:]
    hedged = net + active.loc[start:].astype(float) * btc_ret.reindex(net.index).fillna(0.0)

    def st(x):
        r = bt.Result("", pd.DataFrame({"net": x, "pos": active.loc[start:].astype(float)}))
        return bt.stats(r)

    s, h = st(net), st(hedged)
    years = len(net) / 365
    return {
        "策略": name, "期間": f"{start:%Y-%m} 起",
        "年化": f"{s['年化報酬']:+.0%}", "夏普": f"{s['夏普值']:.2f}", "最大回撤": f"{s['最大回撤']:.0%}",
        "中性 年化": f"{h['年化報酬']:+.0%}", "中性 夏普": f"{h['夏普值']:.2f}",
        "中性 回撤": f"{h['最大回撤']:.0%}",
        "筆數/年": f"{len(trades) / years:.0f}", "勝率": f"{(trades['return'] > 0).mean():.0%}",
        "單筆中位數": f"{trades['return'].median():+.0%}",
        "爆倉比例": f"{(trades['reason'] == '爆倉').mean():.1%}",
        "下架比例": f"{(trades['reason'] == '下架').mean():.1%}",
        "有持倉天數": f"{active.loc[start:].mean():.0%}",
    }, hedged


def main() -> int:
    pn = load_panel()
    OUT.mkdir(parents=True, exist_ok=True)
    tests = {
        "H1 新上市做空｜持有 30 天": h1_new_listing(pn, 30),
        "H1 新上市做空｜持有 90 天": h1_new_listing(pn, 90),
        "H1 新上市做空｜持有 180 天": h1_new_listing(pn, 180),
        "H2 7 日暴漲 >100% 後做空 14 天": h2_pump(pn),
        "H3 做空 30 日最弱 20%（每週）": h3_rank(pn, bottom=True),
        "H3 對照：做空 30 日最強 20%": h3_rank(pn, bottom=False),
        "H4 資金費率年化 >100% 做空 7 天": h4_funding(pn),
    }
    rows, curves, yearly, all_trades = [], {}, {}, {}
    for name, entries in tests.items():
        port, trades = simulate(pn, entries)
        if trades.empty:
            continue
        row, hedged = summarize(name, port, trades, pn.btc_ret)
        rows.append(row)
        curves[name] = (1 + port.loc[hedged.index]).cumprod(), (1 + hedged).cumprod()
        yearly[name] = (1 + hedged).groupby(hedged.index.year).prod() - 1
        all_trades[name] = trades
    table = pd.DataFrame(rows)

    # 尾部風險：H1 90 天最差的部位
    worst = all_trades["H1 新上市做空｜持有 90 天"].nsmallest(8, "return")[["symbol", "entry", "return", "reason"]]
    worst["entry"] = worst["entry"].dt.strftime("%Y-%m-%d")
    worst["return"] = worst["return"].map(lambda v: f"{v:+.0%}")

    # 新上市後的平均路徑（相對上市第 7 天，扣掉 BTC）
    paths = []
    for sym, d0 in pn.listed.items():
        if d0 <= pn.close.index[0] + pd.Timedelta(days=31):
            continue
        s = pn.close[sym].loc[d0:].dropna()
        if len(s) < 8:
            continue
        rel = s.iloc[7:7 + 181].values / s.iloc[7]
        b = (1 + pn.btc_ret.loc[s.index[7]:]).cumprod().iloc[:len(rel)].values
        b = b / b[0]
        paths.append(pd.Series(rel / b[:len(rel)], index=range(len(rel))))
    path_df = pd.concat(paths, axis=1)
    med_path = path_df.median(axis=1)

    fig, axes = plt.subplots(2, 1, figsize=(11, 8))
    colors = [BLUE, ORANGE, AQUA, YELLOW, VIOLET, "#e34948", "#008300"]
    for (name, (_, hedged_eq)), color in zip(curves.items(), colors):
        axes[0].plot(hedged_eq.index, hedged_eq, color=color, lw=1.5, label=name)
    axes[0].set_yscale("log")
    axes[0].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}x"))
    axes[0].set_title("市場中性版本淨值（做空山寨 ＋ 做多等量 BTC，已扣成本與資金費率）")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[1].plot(med_path.index, (med_path - 1) * 100, color=BLUE, lw=2, label="中位數")
    axes[1].fill_between(path_df.index, (path_df.quantile(0.25, axis=1) - 1) * 100,
                         (path_df.quantile(0.75, axis=1) - 1) * 100, color=BLUE, alpha=0.15, label="25%～75%")
    axes[1].axhline(0, color=TEXT_2, lw=0.8)
    axes[1].set_title(f"新上市合約：上市第 7 天後的價格走勢（相對 BTC，{path_df.shape[1]} 個合約）")
    axes[1].set_xlabel("上市第 7 天之後的天數")
    axes[1].set_ylabel("%")
    axes[1].legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "short_alts.png", dpi=150)
    plt.close(fig)

    yr = pd.DataFrame(yearly).map(lambda v: f"{v:+.0%}")
    yr.index.name = "年度（市場中性）"
    n_sym = pn.close.shape[1]
    n_dead = int((pn.last < pn.close.index[-1] - pd.Timedelta(days=3)).sum())
    lines = [
        "# 山寨幣做空策略研究",
        "",
        f"宇宙：幣安 {n_sym} 個 USDT 永續合約（含 {n_dead} 個已下架），"
        f"{pn.close.index[0]:%Y-%m} ~ {pn.close.index[-1]:%Y-%m}。",
        f"規則：近 30 天成交額 ≥ {MIN_ADV / 1e6:.0f}M 美元才交易；進出各 {COST_BPS:g} bps；資金費率照實計；"
        f"1 倍保證金，最高價 ≥ 進場價 × {LIQ_MULT} 視為爆倉（虧 100%）。",
        "假設在看結果前就寫死，沒有調參數。",
        "",
        "- 「年化／夏普／最大回撤」：單純做空的版本（含大盤方向）",
        "- 「中性」：同時做多等量 BTC，扣掉大盤漲跌後的純選幣能力",
        "",
        "![做空研究](short_alts.png)",
        "",
        "## 結果",
        "",
        table.to_markdown(index=False),
        "",
        "## 各年度（市場中性）",
        "",
        yr.to_markdown(),
        "",
        "## H1（持有 90 天）最慘的幾筆：做空的尾部風險",
        "",
        worst.to_markdown(index=False),
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
