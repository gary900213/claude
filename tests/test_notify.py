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
