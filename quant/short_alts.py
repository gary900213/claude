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
- 組合：事件型（H1/H2/H4）資金分 10 份，每筆用當時權益 1/10、進場後不再平衡、槽位滿就略過；
  H3 每週把權益平分給當週選到的幣
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


def split_reused_symbols(p: pd.DataFrame) -> pd.DataFrame:
    """停止交易超過 3 天且價格跳動超過 50% → 視為另一個合約（代號被重新使用或重新計價）。

    例：MDTUSDT 2026-10 停 9 天後 +147,000%、BNXUSDT 2023-02 停 22 天後 −98%。
    """
    p = p.sort_values(["symbol", "date"]).copy()
    g = p.groupby("symbol")
    gap = g["date"].diff().dt.days
    jump = (p["close"] / g["close"].shift() - 1).abs()
    brk = (gap > 3) & (jump > 0.5)
    seg = brk.astype(int).groupby(p["symbol"]).cumsum()
    p["symbol"] = np.where(seg > 0, p["symbol"] + "#" + (seg + 1).astype(str), p["symbol"])
    return p


def load_panel() -> Panel:
    p = split_reused_symbols(pd.read_pickle(PANEL))
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


SLOTS = 10  # 事件型策略：資金分成 10 份，每筆訊號用當時權益的 1/10，槽位滿了就略過


def simulate(pn: Panel, entries: list, slots: int | None = SLOTS, margin: float = 1.0):
    """固定配置的部位模擬（不每天再平衡，貼近實際下單）。

    entries：(合約, 進場日, 持有天數[, 權重])。進場日收盤做空，配置 = 當時權益 × 權重
    （預設 1/slots）。部位之後不加碼也不減碼；爆倉歸零；下架以最後收盤價出場。
    margin：保證金倍數。配置的資金 = margin × 空單名目，所以名目 = 配置 / margin；
    爆倉價 ≈ 進場價 × (1 + margin × 0.9)（1 倍保證金時約 1.9 倍）。
    回傳 (純做空每日報酬, 市場中性每日報酬, 空單曝險/權益, 每筆部位明細)。
    """
    idx = pn.close.index
    by_day: dict[pd.Timestamp, list] = {}
    for e in entries:
        by_day.setdefault(e[1], []).append(e)
    C, H, F = pn.close, pn.high, pn.funding
    col = {s: k for k, s in enumerate(C.columns)}
    cv, hv, fv = C.values, H.values, F.values
    btc = pn.btc_ret.reindex(idx).fillna(0.0).values
    cash, open_pos, rows = 1.0, {}, []
    eq_prev, notional_prev = 1.0, 0.0
    r_short, r_hedged, expo = np.zeros(len(idx)), np.zeros(len(idx)), np.zeros(len(idx))
    cost = COST_BPS / 1e4
    liq_mult = 1 + margin * (LIQ_MULT - 1)

    def close_pos(sym, i, why):
        nonlocal cash
        p = open_pos.pop(sym)
        px = cv[i, col[sym]]
        exit_notional = p["alloc"] / margin * px / p["p0"] if np.isfinite(px) else 0.0
        final = max(p["eq"] - exit_notional * cost, 0.0) if why != "爆倉" else 0.0
        cash += final
        rows.append({"symbol": sym, "entry": idx[p["i0"]], "exit": idx[i], "days": i - p["i0"],
                     "return": final / p["alloc"] - 1, "reason": why})

    for i in range(len(idx)):
        # 1) 更新持有中的部位
        for sym in list(open_pos):
            p, k = open_pos[sym], col[sym]
            c, h = cv[i, k], hv[i, k]
            if not np.isfinite(c):
                close_pos(sym, i - 1, "下架")
                continue
            if np.isfinite(h) and h >= p["p0"] * liq_mult:
                p["eq"] = 0.0
                close_pos(sym, i, "爆倉")
                continue
            c_prev = cv[i - 1, k]
            p["eq"] += p["alloc"] / margin * ((c_prev - c) / p["p0"] + fv[i, k] * c_prev / p["p0"])
            if p["eq"] <= 0:
                p["eq"] = 0.0
                close_pos(sym, i, "爆倉")
            elif i - p["i0"] >= p["hold"]:
                close_pos(sym, i, "到期")
        # 2) 新進場
        equity = cash + sum(p["eq"] for p in open_pos.values())
        for e in by_day.get(idx[i], []):
            sym, hold = e[0], e[2]
            w = e[3] if len(e) > 3 else 1.0 / (slots or 1)
            if sym in open_pos or (slots and len(open_pos) >= slots):
                continue
            k = col.get(sym)
            if k is None or not np.isfinite(cv[i, k]):
                continue
            alloc = min(equity * w, cash)
            if alloc <= 1e-9:
                continue
            cash -= alloc
            open_pos[sym] = {"alloc": alloc, "eq": alloc - alloc / margin * cost, "p0": cv[i, k], "i0": i,
                             "hold": hold}
        # 3) 組合權益與報酬
        equity = cash + sum(p["eq"] for p in open_pos.values())
        notional = sum(p["alloc"] / margin * cv[i, col[s]] / p["p0"] for s, p in open_pos.items())
        r_short[i] = equity / eq_prev - 1 if eq_prev > 0 else 0.0
        r_hedged[i] = r_short[i] + (notional_prev / eq_prev * btc[i] if eq_prev > 0 else 0.0)
        expo[i] = notional / equity if equity > 0 else 0.0
        eq_prev, notional_prev = equity, notional
        if equity <= 1e-9:
            break
    s = pd.Series
    return s(r_short, idx), s(r_hedged, idx), s(expo, idx), pd.DataFrame(rows)


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
        out += [(sym, d, hold, 1.0 / len(pick)) for sym in pick.index]
    return out


def h4_funding(pn: Panel, ann: float = 1.0, hold: int = 7) -> list:
    hits = (pn.funding * 365 > ann) & (pn.adv30 >= MIN_ADV)
    return [(pn.close.columns[j], pn.close.index[i], hold) for i, j in zip(*np.where(hits.values))]


# ---------------------------------------------------------------- 報告

def summarize(name: str, r_short: pd.Series, r_hedged: pd.Series, expo: pd.Series,
              trades: pd.DataFrame) -> dict:
    start = expo[expo > 0].index.min()

    def st(x):
        return bt.stats(bt.Result("", pd.DataFrame({"net": x.loc[start:], "pos": expo.loc[start:]})))

    s, h = st(r_short), st(r_hedged)
    years = len(r_short.loc[start:]) / 365
    return {
        "策略": name, "期間": f"{start:%Y-%m} 起",
        "年化": f"{s['年化報酬']:+.0%}", "夏普": f"{s['夏普值']:.2f}", "最大回撤": f"{s['最大回撤']:.0%}",
        "中性 年化": f"{h['年化報酬']:+.0%}", "中性 夏普": f"{h['夏普值']:.2f}",
        "中性 回撤": f"{h['最大回撤']:.0%}",
        "筆數/年": f"{len(trades) / years:.0f}", "勝率": f"{(trades['return'] > 0).mean():.0%}",
        "單筆平均": f"{trades['return'].mean():+.0%}", "單筆中位數": f"{trades['return'].median():+.0%}",
        "爆倉比例": f"{(trades['reason'] == '爆倉').mean():.1%}",
        "平均空單曝險": f"{expo.loc[start:].mean():.2f}x",
    }


def robustness(pn: Panel) -> pd.DataFrame:
    """H1（持有 30 天）的參數鄰近測試。看過主結果後才做，屬於事後探索。"""
    global COST_BPS
    rows = []
    for label, kw in [("基準：第 7 天進、持有 30 天、1 倍保證金、20 bps、10 槽", {}),
                      ("第 5 天進場", {"day": 5}), ("第 14 天進場", {"day": 14}),
                      ("持有 20 天", {"hold": 20}), ("持有 45 天", {"hold": 45}), ("持有 60 天", {"hold": 60}),
                      ("2 倍保證金（本金加倍、約漲 2.8 倍才爆倉）", {"margin": 2.0}),
                      ("成本 40 bps", {"cost": 40.0}), ("5 槽", {"slots": 5}), ("20 槽", {"slots": 20})]:
        old_cost = COST_BPS
        COST_BPS = kw.get("cost", COST_BPS)
        try:
            entries = h1_new_listing(pn, kw.get("hold", 30), kw.get("day", 7))
            _, rh, ex, tr = simulate(pn, entries, kw.get("slots", SLOTS), kw.get("margin", 1.0))
        finally:
            COST_BPS = old_cost
        start = ex[ex > 0].index.min()
        eq = (1 + rh.loc[start:]).cumprod()
        liq = f"{(tr['reason'] == '爆倉').mean():.0%}"
        if (eq <= 0.01).any():
            rows.append((label, "賠光", "—", "-100%", f"{eq[eq <= 0.01].index.min():%Y-%m}", liq))
            continue
        st = bt.stats(bt.Result("", pd.DataFrame({"net": rh.loc[start:], "pos": ex.loc[start:]})))
        dd = eq / eq.cummax() - 1
        rows.append((label, f"{st['年化報酬']:+.0%}", f"{st['夏普值']:.2f}", f"{st['最大回撤']:.0%}",
                     f"{dd.idxmin():%Y-%m}", liq))
    return pd.DataFrame(rows, columns=["設定", "中性年化", "中性夏普", "最大回撤", "最深回撤時點", "爆倉比例"])


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
        r_short, r_hedged, expo, trades = simulate(pn, entries, None if name.startswith("H3") else SLOTS)
        if trades.empty:
            continue
        rows.append(summarize(name, r_short, r_hedged, expo, trades))
        start = expo[expo > 0].index.min()
        hedged = r_hedged.loc[start:]
        curves[name] = (1 + r_short.loc[start:]).cumprod(), (1 + hedged).cumprod()
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
        "## H1（持有 30 天）參數鄰近測試（事後探索，只能當參考）",
        "",
        "看過上面結果後，才針對唯一看起來有效的 H1-30 天做的檢查：數字在鄰近參數間差很多、"
        "或最差時點集中在某段期間，都代表要小心。",
        "",
        robustness(pn).to_markdown(index=False),
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
