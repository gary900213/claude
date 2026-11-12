"""檢查紙上交易（BTC，v1／v2）最近有沒有換倉，給每日聊天通知用。

只讀 GitHub Actions 寫好的紀錄，不會產生或修改任何訊號。

用法：python -m quant.check_changes [--days 2]
輸出一段 JSON：各版本最新訊號、目前倉位、最近 N 天內的換倉，以及 Actions 是否有按時執行。
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
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="檢查紙上交易最近的換倉")
    ap.add_argument("--days", type=int, default=2, help="往回看幾天的換倉（預設 2）")
    print(json.dumps(check(ap.parse_args(argv).days), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
