"""把 make_video 產生的影片上傳到 YouTube（YouTube Data API v3，免費）。

需要三個環境變數（GitHub Secrets）：
    YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN   ← 用 yt_calm/get_token.py 取得
選用：
    YT_PRIVACY = private（預設）| unlisted | public

用法：
    python -m yt_calm.upload out/yt_calm/001_tired_day
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

PUBLISHED = Path(__file__).resolve().parent / "published.json"


def youtube():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(folder: Path) -> str:
    meta = json.loads((folder / "metadata.json").read_text("utf-8"))
    privacy = os.environ.get("YT_PRIVACY", "private")
    yt = youtube()
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"][:5000],
            "tags": meta["tags"],
            "categoryId": "22",  # People & Blogs
            "defaultLanguage": "zh-TW",
            "defaultAudioLanguage": "zh-TW",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # 旁白是 AI 語音，主動揭露
        },
    }
    media = MediaFileUpload(str(folder / "video.mp4"), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"上傳中 {status.progress() * 100:.0f}%")
    vid = resp["id"]
    print(f"上傳完成：https://youtu.be/{vid}（{privacy}）")
    try:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(folder / "thumbnail.jpg"))).execute()
    except HttpError as e:  # 頻道沒做手機驗證時不能自訂縮圖
        print(f"⚠️ 縮圖設定失敗（頻道可能尚未驗證電話）：{e}")

    done = json.loads(PUBLISHED.read_text("utf-8")) if PUBLISHED.exists() else {}
    done[meta["id"]] = {"video_id": vid, "privacy": privacy, "uploaded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    PUBLISHED.write_text(json.dumps(done, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return vid


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    upload(Path(sys.argv[1]))
