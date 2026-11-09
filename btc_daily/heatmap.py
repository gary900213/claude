"""估算清算熱力圖（免費版近似模型）。

CoinGlass 的熱力圖是付費數據；這裡用公開的 K 線 + 持倉量自己推估：

1. 每根 1 小時 K 棒，若持倉量增加 ΔOI > 0，視為有 ΔOI 美元的新倉位
   在該 K 棒的典型價 (H+L+C)/3 開倉；依多空比拆成多單／空單。
2. 新倉位依一組假設的槓桿分佈，算出強平價：
       多單強平價 = 開倉價 × (1 − 1/槓桿 + 維持保證金率)
       空單強平價 = 開倉價 × (1 + 1/槓桿 − 維持保證金率)
   並把金額累加到對應的價格格子。
3. 若持倉量減少，依減少比例把所有未平倉的清算量等比例縮小（視為平倉）。
4. 價格一旦觸及某個格子（多單：最低價 ≤ 格子；空單：最高價 ≥ 格子），
   該格子視為已清算並歸零。
5. 每根 K 棒都記錄一次快照，疊起來就是「時間 × 價格」的熱力圖。

沒有持倉量時，退而以成交量的一個固定比例當作新開倉量。
這只是近似：交易所實際的槓桿分佈、維持保證金階梯、部位成本都拿不到。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_LEVERAGE = {5: 0.10, 10: 0.30, 25: 0.30, 50: 0.20, 100: 0.10}


@dataclass
class HeatmapResult:
    times: pd.DatetimeIndex
    price_bins: np.ndarray            # 每個格子的中心價
    matrix: np.ndarray                # shape (len(times), len(price_bins))，美元
    long_levels: np.ndarray           # 最後一刻：多單清算量（在現價下方）
    short_levels: np.ndarray          # 最後一刻：空單清算量（在現價上方）
    last_price: float
    used_oi: bool
    notes: list[str] = field(default_factory=list)


def estimate_heatmap(
    klines: pd.DataFrame,
    oi_usd: pd.Series | None = None,
    long_short_ratio: pd.Series | None = None,
    leverage: dict[int, float] | None = None,
    mmr: float = 0.005,
    range_pct: float = 0.25,
    n_bins: int = 240,
    volume_open_fraction: float = 0.05,
) -> HeatmapResult:
    leverage = leverage or DEFAULT_LEVERAGE
    lev = np.array(list(leverage.keys()), dtype=float)
    w = np.array(list(leverage.values()), dtype=float)
    w = w / w.sum()

    k = klines.sort_index()
    last_price = float(k["close"].iloc[-1])
    # 價格範圍：涵蓋整段走勢，並在現價上下至少留 range_pct
    lo = min(last_price * (1 - range_pct), float(k["low"].min()) * 0.97)
    hi = max(last_price * (1 + range_pct), float(k["high"].max()) * 1.03)
    edges = np.linspace(lo, hi, n_bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2

    notes = []
    used_oi = oi_usd is not None and len(oi_usd.dropna()) > 10
    if used_oi:
        oi = oi_usd.sort_index().reindex(k.index, method="nearest", tolerance=pd.Timedelta("90min"))
        d_oi = oi.diff()
        prev_oi = oi.shift(1)
        coverage = d_oi.notna().mean()
        if coverage < 0.5:
            notes.append(f"持倉量只覆蓋 {coverage:.0%} 的 K 棒，其餘以成交量估算")
    else:
        d_oi = prev_oi = pd.Series(np.nan, index=k.index)
        notes.append("沒有持倉量數據，以成交量的固定比例估算新開倉")

    if long_short_ratio is not None and len(long_short_ratio.dropna()):
        r = long_short_ratio.sort_index().reindex(k.index, method="nearest",
                                                  tolerance=pd.Timedelta("90min"))
        long_share = (r / (1 + r)).fillna(0.5).clip(0.2, 0.8)
    else:
        long_share = pd.Series(0.5, index=k.index)

    long_lv = np.zeros(n_bins)
    short_lv = np.zeros(n_bins)
    snaps = np.zeros((len(k), n_bins))

    def add(prices, amounts, arr):
        idx = np.searchsorted(edges, prices) - 1
        ok = (idx >= 0) & (idx < n_bins)
        np.add.at(arr, idx[ok], amounts[ok])

    for i, (t, bar) in enumerate(k.iterrows()):
        # 先處理被觸發的清算
        long_lv[centers >= bar["low"]] = 0.0
        short_lv[centers <= bar["high"]] = 0.0

        change = d_oi.iloc[i]
        if np.isnan(change):
            new_usd = bar["volume"] * bar["close"] * volume_open_fraction  # volume 單位為 BTC
        elif change >= 0:
            new_usd = change
        else:
            base = prev_oi.iloc[i]
            frac = min(1.0, -change / base) if base and base > 0 else 0.0
            long_lv *= 1 - frac
            short_lv *= 1 - frac
            new_usd = 0.0

        if new_usd > 0:
            entry = (bar["high"] + bar["low"] + bar["close"]) / 3
            ls = long_share.iloc[i]
            add(entry * (1 - 1 / lev + mmr), new_usd * ls * w, long_lv)
            add(entry * (1 + 1 / lev - mmr), new_usd * (1 - ls) * w, short_lv)
            # 開倉當根就落在區間內的部位立即被清掉
            long_lv[centers >= bar["low"]] = 0.0
            short_lv[centers <= bar["high"]] = 0.0

        snaps[i] = long_lv + short_lv

    return HeatmapResult(
        times=k.index, price_bins=centers, matrix=snaps,
        long_levels=long_lv.copy(), short_levels=short_lv.copy(),
        last_price=last_price, used_oi=used_oi, notes=notes,
    )
