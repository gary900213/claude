"""寄信通知：紙上交易換倉、每日流程失敗、測試信。

設定（環境變數；在 GitHub Actions 用 Secrets 提供，不要寫進程式碼或 repo）：
- SMTP_USER      寄件帳號（例如你的 Gmail）
- SMTP_PASSWORD  Gmail「應用程式密碼」（不是登入密碼）
- MAIL_TO        收件人（可用逗號分隔多個）
- SMTP_HOST      預設 smtp.gmail.com
- SMTP_PORT      預設 465（SSL）

沒有設定時只會印出訊息並略過，不會讓每日流程失敗。

用法：
    python -m quant.notify              # 寄出 out/notifications/ 裡待寄的換倉通知
    python -m quant.notify --test       # 寄一封測試信，確認設定正確
    python -m quant.notify --failure    # 寄「每日流程失敗」通知（GitHub Actions 失敗時用）
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTIFY_DIR = ROOT / "out" / "notifications"


def config() -> dict | None:
    user, pw, to = (os.environ.get(k, "").strip() for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"))
    if not (user and pw and to):
        return None
    return {"host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            "port": int(os.environ.get("SMTP_PORT", "465")),
            "user": user, "password": pw, "to": [x.strip() for x in to.split(",") if x.strip()]}


def run_url() -> str | None:
    s, r, i = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{s}/{r}/actions/runs/{i}" if s and r and i else None


def report_url(rel: str) -> str:
    s, r, ref = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_REF_NAME"))
    return f"{s}/{r}/blob/{ref}/{rel}" if s and r and ref else rel


def compose_change(e: dict) -> tuple[str, str]:
    mode = "即時模式" if e["mode"] == "live" else "歷史檔模式"
    subject = (f"[BTC 紙上交易 {e['version']}] {e['action']} → 倉位 {e['to']:.2f} 倍"
               f"（訊號日 {e['signal_date']}）")
    lines = [
        f"策略：{e['strategy']}（{mode}）",
        f"訊號日：{e['signal_date']}（UTC 收盤），收盤價 {e['close']:,.0f}",
        "",
        f"倉位：{e['from']:.2f} 倍 → {e['to']:.2f} 倍（{e['action']} {abs(e['to'] - e['from']):.2f} 倍）",
    ]
    if e.get("capital"):
        notional = abs(e["to"] - e["from"]) * e["capital"]
        lines.append(f"以總資金 {e['capital']:,.0f} 美元計：約 {notional:,.0f} 美元 ≈ "
                     f"{notional / e['close']:.4f} BTC")
    lines += [
        "",
        f"趨勢分數 {e['trend']:+.2f}；散戶多空比 z {e['ls_z90']:.2f}；持倉量水位 z {e['oi_z90']:.2f}",
    ]
    if e["to"] == 0:
        why = []
        if e["trend"] <= 0:
            why.append("趨勢轉空")
        if e["filter_ls"]:
            why.append("散戶過度看多")
        if e["filter_oi"]:
            why.append("持倉量偏高")
        lines.append(f"出場原因：{'、'.join(why) or '—'}")
    lines += [
        "",
        "執行原則：UTC 收盤（台灣 08:00）後立即以市價成交；不要掛低價等回檔。",
        "（紙上交易：這封信只是記錄用，請自行判斷是否實際下單。這不是投資建議。）",
        "",
        f"完整報告：{report_url(e['report'])}",
    ]
    return subject, "\n".join(lines)


def send(cfg: dict, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["user"], ", ".join(cfg["to"])
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=30) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)


def send_pending(cfg: dict | None) -> int:
    files = sorted(NOTIFY_DIR.glob("*.json")) if NOTIFY_DIR.exists() else []
    if not files:
        print("[notify] 沒有換倉，不寄信")
        return 0
    for f in files:
        subject, body = compose_change(json.loads(f.read_text(encoding="utf-8")))
        if cfg is None:
            print(f"[notify] 未設定 SMTP，略過：{subject}")
            continue
        try:
            send(cfg, subject, body)
            f.unlink()
            print(f"[notify] 已寄出：{subject}")
        except Exception as e:  # noqa: BLE001 - 寄信失敗不應讓每日流程失敗
            print(f"[notify] 寄信失敗：{e}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="寄信通知")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--test", action="store_true", help="寄一封測試信")
    g.add_argument("--failure", action="store_true", help="寄每日流程失敗通知")
    args = ap.parse_args(argv)
    cfg = config()
    if args.test or args.failure:
        if cfg is None:
            print("[notify] 未設定 SMTP_USER / SMTP_PASSWORD / MAIL_TO")
            return 1 if args.test else 0
        if args.test:
            subject, body = "[BTC 紙上交易] 測試信", "設定成功：之後換倉時會寄信到這個信箱。"
        else:
            subject = "[BTC 紙上交易] 每日自動流程失敗"
            body = "今天的自動更新沒有跑完，訊號可能沒有產生。\n\n" + (f"執行紀錄：{run_url()}" if run_url() else "")
        try:
            send(cfg, subject, body)
        except Exception as e:  # noqa: BLE001
            print(f"[notify] 寄信失敗：{e}")
            return 1 if args.test else 0
        print(f"[notify] 已寄出：{subject}")
        return 0
    return send_pending(cfg)


if __name__ == "__main__":
    sys.exit(main())
