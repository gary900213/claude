"""檢查紙上交易（v1／v2：BTC；v3：BTC＋黃金）最近有沒有換倉，給每日聊天通知用。

只讀 GitHub Actions 寫好的紀錄，不會產生或修改任何訊號。

用法：python -m quant.check_changes [--days 2]
輸出一段 JSON：各版本最新訊號、目前倉位、最近 N 天內的換倉、Actions 是否有按時執行，
以及「恐慌後賣選擇權」觀察條件（vol_alert，用即時的幣安現貨價與 Deribit DVOL）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import pandas as pd

from . import paper

VERSIONS = {"v1": "paper", "v2": "paper_v2"}


def check(days: int = 2, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp(datetime.now(timezone.utc))
    out = {"checked_at_utc": f"{now:%Y-%m-%d %H:%M}", "versions": {}}
    run = paper.ROOT / "data" / "last_run.json"
    if run.exists():
        last = pd.Timestamp(json.loads(run.read_text(encoding="utf-8"))["updated_utc"], tz="UTC")
        out["last_actions_run_utc"] = f"{last:%Y-%m-%d %H:%M}"
        out["actions_stale"] = bool(now - last > pd.Timedelta(hours=36))
    for ver, folder in VERSIONS.items():
        path = paper.ROOT / "data" / folder / "signals.csv"
        if not path.exists():
            continue
        sig = pd.read_csv(path, parse_dates=["signal_date", "generated_at_utc"])
        old = paper.STRATEGY
        paper.STRATEGY = paper.STRATEGIES[ver]
        try:
            pos = paper.executed_positions(sig, pd.DatetimeIndex([now.normalize()]))
        finally:
            paper.STRATEGY = old
        prev = pos.shift(1).fillna(0.0)
        moved = pos[(pos - prev).abs() > 1e-9]
        recent = moved[moved.index >= now.normalize() - pd.Timedelta(days=days)]
        last = sig.iloc[-1]
        out["versions"][ver] = {
            "latest_signal_date": f"{last['signal_date']:%Y-%m-%d}",
            "latest_generated_utc": f"{last['generated_at_utc']:%Y-%m-%d %H:%M}",
            "target_pos": float(last["target_pos"]), "close": float(last["close"]),
            "trend": float(last["trend"]), "ls_z90": float(last["ls_z90"]), "oi_z90": float(last["oi_z90"]),
            "held_pos": float(pos.iloc[-1]),
            "changes": [{"date": f"{d:%Y-%m-%d}", "from": float(prev.loc[d]), "to": float(pos.loc[d])}
                        for d in recent.index],
        }
    v3 = check_v3(days, now)
    if v3:
        out["versions"]["v3"] = v3
    return out


def check_v3(days: int, now: pd.Timestamp) -> dict | None:
    """v3（BTC＋黃金）：兩條腿各自的倉位與最近換倉。"""
    from . import paper_v3
    path = paper.ROOT / "data" / "paper_v3" / "signals.csv"
    if not path.exists():
        return None
    sig = pd.read_csv(path, parse_dates=["signal_date", "generated_at_utc"])
    pos = paper_v3.executed(sig, pd.DatetimeIndex([now.normalize()]))
    last = sig.iloc[-1]
    changes = []
    for leg, name in (("btc", "BTC"), ("gold", "黃金")):
        s = pos[leg]
        prev = s.shift(1).fillna(0.0)
        moved = s[(s - prev).abs() > 1e-9]
        for d in moved[moved.index >= now.normalize() - pd.Timedelta(days=days)].index:
            changes.append({"leg": name, "date": f"{d:%Y-%m-%d}", "from": float(prev.loc[d]), "to": float(s.loc[d])})
    return {"latest_signal_date": f"{last['signal_date']:%Y-%m-%d}",
            "latest_generated_utc": f"{last['generated_at_utc']:%Y-%m-%d %H:%M}",
            "btc": {"target": float(last["target_btc"]), "held": float(pos["btc"].iloc[-1]),
                    "trend": float(last["btc_trend"]), "weight": float(last["w_btc"]), "close": float(last["btc_close"])},
            "gold": {"target": float(last["target_gold"]), "held": float(pos["gold"].iloc[-1]),
                     "trend": float(last["gold_trend"]), "weight": float(last["w_gold"]),
                     "close": float(last["gold_close"])},
            "changes": changes}


# ---------------------------------------------------------------- 恐慌賣選擇權提醒（見 docs/vrp）

SPOT_KLINES = "https://data-api.binance.vision/api/v3/klines"
HISTORY_NOTE = ("歷史（2021–2026，BTC 7 天跌 >15% 後賣 30 天價平跨式）：13 次獨立事件中不對沖有 11 次賺錢，"
                "平均每 30 天約 +12%、最差 −11%；樣本很少，崩盤若持續擴大賣方會大虧。")


def _btc_daily_spot(days: int = 10) -> pd.Series:
    import requests
    r = requests.get(SPOT_KLINES, params={"symbol": "BTCUSDT", "interval": "1d", "limit": days}, timeout=20)
    r.raise_for_status()
    rows = r.json()
    return pd.Series([float(x[4]) for x in rows],
                     index=pd.to_datetime([int(x[0]) for x in rows], unit="ms", utc=True))


def vol_alert(now: pd.Timestamp | None = None, btc: pd.Series | None = None,
              dvol: pd.Series | None = None) -> dict:
    """回傳目前是否符合「恐慌後賣選擇權」的觀察條件。網路失敗時回傳 error。"""
    from . import vrp
    now = now or pd.Timestamp(datetime.now(timezone.utc))
    try:
        if btc is None:
            btc = _btc_daily_spot()
        if dvol is None:
            hist = pd.read_csv(vrp.DVOL_CSV, index_col=0, parse_dates=True)["dvol"] if vrp.DVOL_CSV.exists() \
                else pd.Series(dtype=float)
            recent = vrp.fetch_dvol_since(now - pd.Timedelta(days=30))
            dvol = recent.combine_first(hist).sort_index()
    except Exception as e:  # noqa: BLE001 - 提醒失敗不影響換倉檢查
        return {"error": f"取得 BTC 或 DVOL 失敗：{e}"}
    price, ref = float(btc.iloc[-1]), float(btc.iloc[-8]) if len(btc) >= 8 else float("nan")
    drop7 = price / ref - 1
    iv = float(dvol.iloc[-1])
    iv7 = float(dvol.iloc[-8]) if len(dvol) >= 8 else float("nan")
    pct = float((dvol < iv).mean())  # 歷史上比現在低的比例
    reasons = []
    if drop7 < -0.15:
        reasons.append(f"BTC 7 天跌 {drop7:.1%}（> 15%）")
    if iv - iv7 > 0.15:
        reasons.append(f"DVOL 7 天上升 {100 * (iv - iv7):.0f} 點（> 15 點）")
    if pct >= 0.8:
        reasons.append(f"DVOL {iv * 100:.0f} 位於歷史 {pct:.0%} 分位（前 20% 高）")
    return {"triggered": bool(reasons), "reasons": reasons, "btc": price, "btc_7d": round(drop7, 4),
            "dvol": round(iv * 100, 1), "dvol_7d_change": round(100 * (iv - iv7), 1),
            "dvol_percentile": round(pct, 3), "note": HISTORY_NOTE if reasons else ""}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="檢查紙上交易最近的換倉")
    ap.add_argument("--days", type=int, default=2, help="往回看幾天的換倉（預設 2）")
    out = check(ap.parse_args(argv).days)
    out["vol_alert"] = vol_alert()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
