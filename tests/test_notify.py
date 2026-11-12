import json

import pandas as pd

from quant import notify, paper


def _sig(gen):
    return pd.DataFrame({"signal_date": pd.to_datetime(["2026-11-09", "2026-11-10"], utc=True),
                         "generated_at_utc": pd.to_datetime(gen, utc=True),
                         "close": [80000.0, 81000.0], "trend": [-0.3, 0.33], "ls_z90": [0.5, 0.2],
                         "oi_z90": [0.1, 0.0], "filter_ls": [False, False], "filter_oi": [False, False],
                         "target_pos": [0.0, 0.8]})


def test_change_event_only_for_rows_written_this_run():
    now = pd.Timestamp("2026-11-11 07:20", tz="UTC")
    idx = pd.date_range("2026-11-10", "2026-11-11", freq="D", tz="UTC")
    pos = pd.Series([0.0, 0.8], index=idx)
    e = paper.change_event(_sig(["2026-11-10 07:00", "2026-11-11 07:20"]), pos, now)
    assert e["action"] == "買入" and e["from"] == 0.0 and e["to"] == 0.8
    # 同一天稍後再跑：最新訊號不是這次寫的 → 不再通知
    later = pd.Timestamp("2026-11-11 13:20", tz="UTC")
    assert paper.change_event(_sig(["2026-11-10 07:00", "2026-11-11 07:20"]), pos, later) is None
    # 沒有換倉 → 不通知
    assert paper.change_event(_sig(["2026-11-10 07:00", "2026-11-11 07:20"]), pos * 0, now) is None


def _event(**kw):
    e = {"signal_date": "2026-11-10", "from": 0.0, "to": 0.8, "action": "買入", "close": 80000.0,
         "trend": 0.33, "ls_z90": 0.2, "oi_z90": 0.0, "filter_ls": False, "filter_oi": False,
         "version": "v2", "strategy": "v2-2026-11-10", "mode": "archive", "capital": 10000,
         "report": "docs/paper_v2/README.md"}
    e.update(kw)
    return e


def test_compose_change_mail():
    subject, body = notify.compose_change(_event())
    assert "v2" in subject and "買入" in subject and "0.80" in subject
    assert "8,000 美元" in body and "0.1000 BTC" in body and "不是投資建議" in body
    _, body = notify.compose_change(_event(to=0.0, **{"from": 0.8}, action="賣出", trend=-0.33,
                                           filter_ls=True))
    assert "出場原因：趨勢轉空、散戶過度看多" in body


def test_send_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "NOTIFY_DIR", tmp_path)
    (tmp_path / "a.json").write_text(json.dumps(_event(), ensure_ascii=False), encoding="utf-8")
    # 沒設定 SMTP：略過，檔案保留
    assert notify.send_pending(None) == 0 and (tmp_path / "a.json").exists()
    sent = []
    monkeypatch.setattr(notify, "send", lambda cfg, s, b: sent.append(s))
    assert notify.send_pending({"to": ["x"]}) == 0
    assert len(sent) == 1 and not (tmp_path / "a.json").exists()


def test_config_requires_all_three(monkeypatch):
    for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    assert notify.config() is None
    monkeypatch.setenv("SMTP_USER", "a@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.setenv("MAIL_TO", "b@example.com, c@example.com")
    assert notify.config()["to"] == ["b@example.com", "c@example.com"]


def test_check_changes_reports_recent_change(tmp_path, monkeypatch):
    from quant import check_changes
    (tmp_path / "data" / "paper").mkdir(parents=True)
    sig = pd.DataFrame({"signal_date": ["2026-11-09", "2026-11-10"],
                        "generated_at_utc": ["2026-11-10 07:00", "2026-11-11 07:00"],
                        "strategy": "v1", "close": [80000, 82000], "trend": [-0.3, 0.33],
                        "vol_scale": [1.0, 1.0], "ls_z90": [0.0, 0.0], "oi_z90": [0.0, 0.0],
                        "filter_ls": False, "filter_oi": False, "target_pos": [0.0, 0.9],
                        "source": "archive"})
    sig.to_csv(tmp_path / "data" / "paper" / "signals.csv", index=False)
    monkeypatch.setattr(paper, "ROOT", tmp_path)
    out = check_changes.check(days=2, now=pd.Timestamp("2026-11-11 12:00", tz="UTC"))
    v1 = out["versions"]["v1"]
    assert v1["held_pos"] == 0.9
    assert v1["changes"] == [{"date": "2026-11-11", "from": 0.0, "to": 0.9}]


def test_vol_alert_conditions():
    from quant.check_changes import vol_alert
    idx = pd.date_range("2026-01-01", periods=200, freq="D", tz="UTC")
    calm_iv = pd.Series(0.40, index=idx)
    flat = pd.Series(80000.0, index=idx[-10:])
    assert vol_alert(btc=flat, dvol=calm_iv)["triggered"] is False
    crash = flat.copy()
    crash.iloc[-1] = 64000.0  # 7 天 −20%
    spike = calm_iv.copy()
    spike.iloc[-1] = 0.70     # 7 天 +30 點、且是歷史最高
    out = vol_alert(btc=crash, dvol=spike)
    assert out["triggered"] and len(out["reasons"]) == 3 and "13 次獨立事件" in out["note"]
