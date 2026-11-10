"""資金費率套利（cash-and-carry）回測。

做法：買進現貨、同時放空等量的 USDT 永續合約。價格漲跌互相抵銷，
賺的是永續合約多頭付給空頭的資金費率。

每單位名目本金的每日報酬：
    現貨報酬 − 永續報酬 + 當天收到的資金費率
（前兩項相減就是「現貨與永續價差」的變化，通常很小，但極端行情會跳動）

資金需求：現貨要全額 1；空單另外放 margin 倍的保證金（預設 1.0，也就是不加槓桿，
因為山寨幣出現過單日 +70% 的行情，保證金太少會被強平）。所以本金報酬 = 每日報酬 ÷ (1 + margin)。

開關規則（只用當天收盤前已知的資金費率）：
- 一直開著
- 過去 7 天平均資金費率（年化）> 門檻才進場，< 0 就出場（門檻 0%、5%、10%，事先定好，不做最佳化）
每次進場或出場：現貨 12 bps + 永續 7 bps = 19 bps（以名目本金計）。

最後也測「趨勢策略 v2 空手時，閒置資金拿去做套利」的組合效果。

用法：python -m quant.carry
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import date, timedelta
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
from .history import ROOT, days, fetch_many, load_daily, log, months  # noqa: E402
from .paper import STRATEGIES  # noqa: E402
from .run_multi import SYMBOLS  # noqa: E402
from .strategies import trend_signal, vol_scale  # noqa: E402

SPOT_BASE = "https://data.binance.vision/data/spot"
SPOT_RAW = ROOT / "data" / "raw" / "binance_spot"
OUT = ROOT / "docs" / "carry"
SWITCH_COST_BPS = 19.0
MARGIN = 1.0
THRESHOLDS = (0.0, 0.05, 0.10)
BLUE, ORANGE, AQUA, YELLOW, TEXT_2 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#52514e"


# ---------------------------------------------------------------- 現貨日線

def _read_spot(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), header=None).iloc[:, :5]
    if not str(df.iloc[0, 0]).isdigit():  # 有表頭
        df = df.iloc[1:]
    df.columns = ["open_time", "open", "high", "low", "close"]
    t = df["open_time"].astype("int64")
    t = np.where(t > 10**14, t // 1000, t)  # 2025 起改用微秒
    return pd.DataFrame({"close": df["close"].astype(float).values},
                        index=pd.to_datetime(t, unit="ms", utc=True))


def load_spot_daily(symbol: str, today: date) -> pd.Series:
    this_month = date(today.year, today.month, 1)
    rels = [f"monthly/klines/{symbol}/1d/{symbol}-1d-{y}-{m:02d}.zip"
            for y, m in months(date(2020, 1, 1), this_month)]
    rels += [f"daily/klines/{symbol}/1d/{symbol}-1d-{d}.zip"
             for d in days(this_month, today - timedelta(days=1))]
    blobs = fetch_many(rels, base=SPOT_BASE, raw=SPOT_RAW)
    df = pd.concat([_read_spot(b) for b in blobs])
    s = df[~df.index.duplicated()].sort_index()["close"]
    s.index.name = "date"
    return s


# ---------------------------------------------------------------- 套利報酬

def carry_daily(d: pd.DataFrame, spot: pd.Series) -> pd.DataFrame:
    """每單位名目本金的每日報酬拆解（只保留資金費率已公布的日子）。"""
    x = pd.DataFrame({"perp": d["close"], "spot": spot.reindex(d.index),
                      "funding": d["funding_day"]}).dropna()
    x["basis_ret"] = x["spot"].pct_change() - x["perp"].pct_change()
    x["basis_pct"] = x["perp"] / x["spot"] - 1
    x["funding_7d_ann"] = x["funding"].rolling(7).mean() * 365
    return x.dropna(subset=["basis_ret"])


def carry_state(f7: pd.Series, enter: float | None) -> pd.Series:
    """None = 一直開著；否則 7 日均 > enter 進場、< 0 出場（遲滯，避免頻繁進出）。"""
    if enter is None:
        return pd.Series(1.0, index=f7.index)
    out, on = [], 0.0
    for v in f7.values:
        if np.isnan(v):
            pass
        elif not on and v > enter:
            on = 1.0
        elif on and v < 0:
            on = 0.0
        out.append(on)
    return pd.Series(out, index=f7.index)


def carry_returns(x: pd.DataFrame, state: pd.Series, margin: float = MARGIN) -> pd.DataFrame:
    """以「本金」計的每日報酬：D 收盤決定的狀態，賺 D+1 的價差變化與資金費率。"""
    held = state.shift(1).fillna(0.0)
    switch = state.diff().abs().fillna(state.abs()).shift(1).fillna(0.0)
    gross = held * (x["basis_ret"] + x["funding"])
    cost = switch * SWITCH_COST_BPS / 1e4
    net = (gross - cost) / (1 + margin)
    return pd.DataFrame({"pos": held, "net": net, "cost": cost / (1 + margin),
                         "funding": -held * x["funding"] / (1 + margin),  # 負號：收到資金費率
                         "basis": held * x["basis_ret"] / (1 + margin)})


def result(name: str, df: pd.DataFrame) -> bt.Result:
    df = df.copy()
    df["equity"] = (1 + df["net"]).cumprod()
    df["drawdown"] = df["equity"] / df["equity"].cummax() - 1
    return bt.Result(name, df)


def row(name: str, r: bt.Result, extra: dict | None = None) -> dict:
    st = bt.stats(r)
    d = r.daily
    years = len(d) / bt.DAYS_PER_YEAR
    return {"策略": name, "年化報酬（本金）": f"{st['年化報酬']:+.1%}", "年化波動": f"{st['年化波動']:.1%}",
            "夏普值": f"{st['夏普值']:.2f}", "最大回撤": f"{st['最大回撤']:.1%}",
            "持有時間": f"{d['pos'].mean():.0%}",
            "資金費率貢獻/年": f"{-d['funding'].sum() / years:+.1%}",
            "價差貢獻/年": f"{d['basis'].sum() / years:+.1%}", **(extra or {})}


def main() -> int:
    today = pd.Timestamp.now(tz="UTC").date()
    OUT.mkdir(parents=True, exist_ok=True)
    per_rows, port_nets, xs, tails = [], {}, {}, []
    for sym in SYMBOLS:
        log(f"現貨日線 {sym}")
        spot = load_spot_daily(sym, today)
        d = load_daily(sym)
        x = carry_daily(d, spot)
        xs[sym] = x
        tails.append({"幣種": sym.removesuffix("USDT"),
                      "價差單日最差": f"{x['basis_ret'].min():+.2%}",
                      "價差單日最好": f"{x['basis_ret'].max():+.2%}",
                      "永續溢價中位數": f"{x['basis_pct'].median():+.3%}",
                      "資金費率為負的天數": f"{(x['funding'] < 0).mean():.0%}",
                      "年化資金費率（平均）": f"{x['funding'].mean() * 365:+.1%}"})
        for label, enter in [("一直開著", None)] + [(f"7日均 > {t:.0%} 才進場", t) for t in THRESHOLDS]:
            r = result(label, carry_returns(x, carry_state(x["funding_7d_ann"], enter)))
            per_rows.append({"幣種": sym.removesuffix("USDT"), **row(label, r)})
            port_nets.setdefault(label, {})[sym] = r.daily["net"]
    per_asset = pd.DataFrame(per_rows)

    # 等權重：7 個幣各分 1/7 本金
    port_rows, port_eq = [], {}
    for label, nets in port_nets.items():
        df = pd.DataFrame(nets).dropna()
        pos = pd.DataFrame({s: carry_state(xs[s]["funding_7d_ann"], None if label == "一直開著" else
                                           float(label.split("> ")[1].split("%")[0]) / 100).shift(1)
                            for s in nets}).reindex(df.index).fillna(0.0)
        r = result(label, pd.DataFrame({"net": df.mean(axis=1), "pos": pos.mean(axis=1),
                                        "cost": 0.0, "funding": 0.0, "basis": 0.0}))
        port_eq[label] = r.daily["equity"]
        st = bt.stats(r)
        port_rows.append({"組合（7 幣等權重）": label, "年化報酬（本金）": f"{st['年化報酬']:+.1%}",
                          "年化波動": f"{st['年化波動']:.1%}", "夏普值": f"{st['夏普值']:.2f}",
                          "最大回撤": f"{st['最大回撤']:.1%}", "期間": f"{df.index[0]:%Y-%m} ~ {df.index[-1]:%Y-%m}"})
    portfolio = pd.DataFrame(port_rows)
    yearly = pd.DataFrame({label: (1 + pd.DataFrame(n).dropna().mean(axis=1)).groupby(
        lambda t: t.year).prod() - 1 for label, n in port_nets.items()})
    yearly = yearly.map(lambda v: f"{v:+.1%}")
    yearly.index.name = "年度（7 幣組合）"

    # 趨勢 v2（BTC）＋ 閒置資金做套利
    s2 = STRATEGIES["v2"]
    d = add_features(load_daily("BTCUSDT"))
    d = d[d["close"].notna()]
    pos = bt.apply_band(trend_signal(d, tuple(s2["trend_lookbacks"])).clip(lower=0)
                        * vol_scale(d, s2["target_vol"], s2["max_leverage"]), s2["rebalance_band"])
    trend = bt.run("v2", d["ret"], pos, s2["cost_bps"], d["funding_day"]).daily
    combo_rows, combo_eq = [], {}
    carry_sources = {
        "BTC 套利（>5% 才進場）": port_nets["7日均 > 5% 才進場"]["BTCUSDT"],
        "7 幣套利組合（>5% 才進場）": pd.DataFrame(port_nets["7日均 > 5% 才進場"]).dropna().mean(axis=1),
    }
    start = max(d.index[120], *(c.index[0] for c in carry_sources.values()))
    end = min(c.index[-1] for c in carry_sources.values())
    t = trend.loc[start:end]
    zeros = {"cost": 0.0, "funding": 0.0, "basis": 0.0}
    base = result("只用趨勢 v2", pd.DataFrame({"net": t["net"], "pos": t["pos"], **zeros}))
    combo_rows.append(row("只用趨勢 v2（BTC）", base))
    combo_eq["只用趨勢 v2"] = base.daily["equity"]
    for name, c in carry_sources.items():
        idle = (1 - t["pos"]).clip(lower=0)  # 趨勢沒用到的資金比例（前一天收盤決定）
        net = t["net"] + idle * c.reindex(t.index).fillna(0.0)
        r = result(name, pd.DataFrame({"net": net, "pos": t["pos"], **zeros}))
        combo_rows.append(row(f"趨勢 v2 ＋ 閒置資金做{name}", r, {"閒置資金比例": f"{idle.mean():.0%}"}))
        combo_eq[f"＋{name}"] = r.daily["equity"]
    combo = pd.DataFrame(combo_rows).drop(columns=["資金費率貢獻/年", "價差貢獻/年"]).fillna("—")
    combo_yearly = pd.DataFrame({k: (v.pct_change().fillna(0) + 1).groupby(lambda t: t.year).prod() - 1
                                 for k, v in combo_eq.items()})
    combo_yearly["套利多賺"] = combo_yearly.iloc[:, 2] - combo_yearly.iloc[:, 0]
    combo_yearly = combo_yearly.map(lambda v: f"{v:+.1%}")
    combo_yearly.index.name = "年度"

    # 圖：上 = 套利組合淨值；下 = 趨勢 v2 與組合
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7.5))
    for (label, eq), color in zip(port_eq.items(), [BLUE, ORANGE, AQUA, YELLOW]):
        a1.plot(eq.index, eq, color=color, lw=1.7, label=label)
    a1.set_title("資金費率套利：7 幣等權重組合淨值（以本金計，已扣進出成本）")
    a1.legend(frameon=False, loc="upper left", fontsize=9)
    for (label, eq), color in zip(combo_eq.items(), [BLUE, ORANGE, AQUA]):
        a2.plot(eq.index, eq, color=color, lw=1.7, label=label)
    a2.set_yscale("log")
    a2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}x"))
    a2.yaxis.set_minor_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}x"))
    a2.set_title("趨勢 v2（BTC）＋ 空手時的閒置資金做套利（對數刻度）")
    a2.legend(frameon=False, loc="upper left", fontsize=9)
    for a in (a1, a2):
        a.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.text(0.01, 0.004, f"空單保證金 = {MARGIN:g} 倍名目本金（不加槓桿）；進出各 {SWITCH_COST_BPS:g} bps",
             color=TEXT_2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "carry.png", dpi=150)
    plt.close(fig)

    lines = [
        "# 資金費率套利（現貨多 ＋ 永續空）",
        "",
        f"- 本金需求：現貨 1 ＋ 空單保證金 {MARGIN:g} = {1 + MARGIN:g} 倍名目本金；報酬都以本金計",
        f"- 進場或出場各 {SWITCH_COST_BPS:g} bps（現貨 12 ＋ 永續 7）；兩邊部位每日再平衡的成本未計",
        "- 「7日均 > x% 才進場」：過去 7 天平均資金費率（年化）超過 x% 才進場，跌破 0 就出場；門檻事先定好，沒有最佳化",
        "- 資金費率只有月檔，所以最新一個月還沒有數據",
        "",
        "![資金費率套利](carry.png)",
        "",
        "## 1. 各幣種的資金費率與價差特性",
        "",
        pd.DataFrame(tails).to_markdown(index=False),
        "",
        "## 2. 7 幣等權重組合",
        "",
        portfolio.to_markdown(index=False),
        "",
        "各年度報酬（資金費率跟多空行情有關，牛市高、熊市低）：",
        "",
        yearly.to_markdown(),
        "",
        "## 3. 趨勢 v2 ＋ 閒置資金做套利",
        "",
        "趨勢策略沒用到的資金（1 − 倉位，倉位超過 1 倍時為 0）拿去做套利。",
        "",
        combo.to_markdown(index=False),
        "",
        combo_yearly.to_markdown(),
        "",
        "## 4. 各幣種明細",
        "",
        per_asset.to_markdown(index=False),
        "",
        "## 風險（回測看不到的）",
        "",
        "- **交易所風險**：現貨和合約都放在同一家交易所，交易所出事（例如 2022 年 FTX）會同時損失兩邊。",
        "- **空單被強平**：價格急漲時空單保證金不足會被強平，套利就變成單邊做多。需要每天把現貨利潤轉去補保證金。",
        "- **資金費率長期轉負**：熊市時空頭要付錢；遲滯規則會出場，但出場前仍會虧一段。",
        "- **容量**：小資金沒問題；大資金進出會推動價差。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
