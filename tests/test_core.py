import numpy as np
import pandas as pd

from btc_daily.heatmap import estimate_heatmap
from btc_daily.main import daily_liquidations, upsert_csv
from btc_daily.sources import parse_farside

FARSIDE_HTML = """
<html><body><table class="etf">
<thead><tr><th></th><th>Blackrock</th><th>Fidelity</th><th></th></tr>
<tr><th>Date</th><th>IBIT</th><th>FBTC</th><th>Total</th></tr></thead>
<tbody>
<tr><td>05 Nov 2026</td><td>1,234.5</td><td>(12.3)</td><td>1,222.2</td></tr>
<tr><td>06 Nov 2026</td><td>-</td><td>(50.0)</td><td>(50.0)</td></tr>
<tr><td>Total</td><td>9,999</td><td>1</td><td>10,000</td></tr>
<tr><td>Average</td><td>1</td><td>1</td><td>1</td></tr>
</tbody></table></body></html>
"""


def test_parse_farside():
    df = parse_farside(FARSIDE_HTML)
    assert list(df.columns) == ["IBIT", "FBTC", "Total"]
    assert len(df) == 2
    assert df.loc["2026-11-05", "IBIT"] == 1234.5
    assert df.loc["2026-11-05", "FBTC"] == -12.3
    assert df.loc["2026-11-06", "IBIT"] == 0.0
    assert df.loc["2026-11-06", "Total"] == -50.0


def _flat_klines(n=48, price=100_000.0):
    idx = pd.date_range("2026-11-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": price, "high": price * 1.001, "low": price * 0.999,
                         "close": price, "volume": 1000.0}, index=idx)


def test_heatmap_places_levels_at_liquidation_prices():
    k = _flat_klines()
    oi = pd.Series(np.linspace(1e9, 2e9, len(k)), index=k.index)  # 持倉一路增加
    hm = estimate_heatmap(k, oi, leverage={10: 1.0}, mmr=0.005)
    assert hm.used_oi
    long_px = hm.price_bins[np.argmax(hm.long_levels)]
    short_px = hm.price_bins[np.argmax(hm.short_levels)]
    assert abs(long_px - 100_000 * (1 - 0.1 + 0.005)) < 600
    assert abs(short_px - 100_000 * (1 + 0.1 - 0.005)) < 600
    # 新增的 OI 全部分配成清算量（多空各半）
    assert abs((hm.long_levels.sum() + hm.short_levels.sum()) - 1e9) / 1e9 < 0.01


def test_heatmap_clears_levels_when_price_crosses():
    k = _flat_klines()
    oi = pd.Series(np.linspace(1e9, 2e9, len(k)), index=k.index)
    k.iloc[-1, k.columns.get_loc("low")] = 80_000  # 最後一根插針到 80k
    hm = estimate_heatmap(k, oi, leverage={10: 1.0})
    assert hm.long_levels[hm.price_bins >= 80_000].sum() == 0


def test_heatmap_falls_back_to_volume():
    hm = estimate_heatmap(_flat_klines(), None)
    assert not hm.used_oi and hm.notes
    assert hm.long_levels.sum() > 0 and hm.short_levels.sum() > 0


def test_daily_liquidations_drops_partial_days():
    t = pd.to_datetime(["2026-11-01 05:00", "2026-11-02 01:00", "2026-11-02 23:00",
                        "2026-11-03 10:00"], utc=True)
    liq = pd.DataFrame({"time": t, "side": ["long", "long", "short", "short"],
                        "price": 1.0, "usd": [1.0, 2.0, 3.0, 4.0]})
    d = daily_liquidations(liq)
    assert list(d.index) == [pd.Timestamp("2026-11-02")]  # 11/01 不完整、11/03 被丟
    assert d.loc["2026-11-02", "liq_long_usd"] == 2.0
    assert d.loc["2026-11-02", "liq_short_usd"] == 3.0


def test_upsert_keeps_history_and_prefers_new(tmp_path):
    p = tmp_path / "s.csv"
    upsert_csv(p, pd.DataFrame({"a": [1.0, 2.0]}, index=pd.to_datetime(["2026-11-01", "2026-11-02"])))
    out = upsert_csv(p, pd.DataFrame({"a": [20.0, 3.0]}, index=pd.to_datetime(["2026-11-02", "2026-11-03"])))
    assert out["a"].tolist() == [1.0, 20.0, 3.0]


def test_merge_raw_liquidations(tmp_path):
    from btc_daily.main import merge_raw_liquidations
    p = tmp_path / "raw.csv"
    a = pd.DataFrame({"time": pd.to_datetime(["2026-11-01 01:00", "2026-11-01 02:00"], utc=True),
                      "side": ["long", "short"], "price": [1.5, 2.5], "usd": [10.0, 20.0]})
    merge_raw_liquidations(p, a)
    b = pd.DataFrame({"time": pd.to_datetime(["2026-11-01 02:00", "2026-11-02 03:00"], utc=True),
                      "side": ["short", "long"], "price": [2.5, 3.5], "usd": [20.0, 30.0]})
    out = merge_raw_liquidations(p, b)
    assert len(out) == 3  # 重複的那筆被去掉
    assert merge_raw_liquidations(p, None).shape[0] == 3  # 這次抓取失敗也能沿用存檔
