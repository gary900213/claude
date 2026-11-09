import pandas as pd

from quant import live


def _ms(t):
    t = pd.Timestamp(t)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return int(t.timestamp() * 1000)


def test_futures_data_snapshot_maps_to_previous_hour(monkeypatch):
    now = pd.Timestamp.now(tz="UTC").floor("h")
    t = now - pd.Timedelta(hours=5)
    monkeypatch.setattr(live, "_get", lambda path, params: [
        {"timestamp": _ms(t), "sumOpenInterest": "100", "sumOpenInterestValue": "7000000"}])
    df = live._futures_data("/futures/data/openInterestHist", now - pd.Timedelta(days=1),
                            {"sumOpenInterest": "oi_btc", "sumOpenInterestValue": "oi_usd"})
    # 整點 T 的快照 = 歷史檔中「T−1 小時」那一列
    assert df.index[0] == t - pd.Timedelta(hours=1)
    assert df["oi_btc"].iloc[0] == 100.0


def test_fetch_klines_drops_unfinished_candle(monkeypatch):
    now = pd.Timestamp.now(tz="UTC").floor("h")
    done, running = now - pd.Timedelta(hours=1), now

    def row(t):
        o = _ms(t)
        return [o, "1", "2", "0.5", "1.5", "10", o + 3_599_999, "15", 5, "4", "6", "0"]

    monkeypatch.setattr(live, "_get", lambda path, params: [row(done), row(running)])
    k = live.fetch_klines(done)
    assert list(k.index) == [done]
    assert k["taker_buy_volume"].iloc[0] == 4.0 and k["quote_volume"].iloc[0] == 15.0


def test_merge_live_keeps_archive_and_appends_new_hours():
    idx = pd.date_range("2026-11-01", periods=3, freq="h", tz="UTC")
    h = pd.DataFrame({"close": [1.0, 2.0, 3.0], "oi_btc": [10.0, 20.0, None]}, index=idx)
    f = pd.Series([0.0001], index=idx[:1])
    k_idx = pd.date_range(idx[1], periods=3, freq="h", tz="UTC")
    k = pd.DataFrame({"close": [99.0, 99.0, 4.0]}, index=k_idx)
    m = pd.DataFrame({"oi_btc": [99.0, 30.0, 40.0]}, index=k_idx)
    merged, _ = live.merge_live(h, f, k, m, pd.Series(dtype=float))
    assert merged["close"].tolist() == [1.0, 2.0, 3.0, 4.0]      # 歷史檔的值不被覆蓋
    assert merged["oi_btc"].tolist() == [10.0, 20.0, 30.0, 40.0]  # 歷史檔缺的欄位才補


def test_live_end_to_end_uses_last_complete_day(tmp_path, monkeypatch):
    import numpy as np
    from quant import paper

    h, f = live.load_archive()
    now = pd.Timestamp.now(tz="UTC")
    hours = pd.date_range(h.index.max() + pd.Timedelta("1h"), now.floor("h") - pd.Timedelta("1h"),
                          freq="h", tz="UTC")
    last = h.iloc[-1]
    k = pd.DataFrame({c: last[c] for c in ["open", "high", "low", "close", "volume",
                                           "quote_volume", "taker_buy_volume"]}, index=hours)
    m = pd.DataFrame({c: last[c] for c in ["oi_btc", "oi_usd", "ls_account", "top_ls_account",
                                           "top_ls_position", "taker_ls_vol"]}, index=hours)
    monkeypatch.setattr(live, "fetch_klines", lambda start: k)
    monkeypatch.setattr(live, "fetch_metrics", lambda start: m)
    monkeypatch.setattr(live, "fetch_funding", lambda start: pd.Series(dtype=float))
    monkeypatch.setattr(paper, "ROOT", tmp_path)
    orig = (paper.PAPER, paper.DOCS)
    try:
        assert paper.main(live=True) == 0
    finally:
        paper.PAPER, paper.DOCS = orig  # main(live=True) 會改全域路徑，測完還原
    sig = pd.read_csv(tmp_path / "data" / "paper_live" / "signals.csv", parse_dates=["signal_date"])
    yesterday = now.normalize() - pd.Timedelta(days=1)
    assert sig["signal_date"].iloc[-1] == yesterday
    assert sig["source"].iloc[-1] == "live"
    assert np.isfinite(sig["target_pos"].iloc[-1])
    readme = (tmp_path / "docs" / "paper_live" / "README.md").read_text(encoding="utf-8")
    assert "即時 API（零延遲）" in readme
