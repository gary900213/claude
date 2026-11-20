"""一次性：在「你自己的電腦」上執行，登入 YouTube 帳號取得 refresh token。

    pip install google-auth-oauthlib
    python get_token.py client_secret.json

會開瀏覽器請你登入並同意，最後印出三個值，貼到 GitHub Secrets。
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

if len(sys.argv) != 2:
    sys.exit(__doc__)
flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], ["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(sys.argv[1]))
info = info.get("installed") or info.get("web")
print("\n把下面三個值加到 GitHub → Settings → Secrets and variables → Actions：\n")
print("YT_CLIENT_ID     =", info["client_id"])
print("YT_CLIENT_SECRET =", info["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
