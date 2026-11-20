# 心情調適 YouTube 頻道（全自動、全免費）

每天自動做一支「心情調適」影片並上傳到 YouTube，全部使用免費工具：

| 步驟 | 工具 | 費用 |
|---|---|---|
| 腳本 | `topics/*.json` 題庫（由 Claude 撰寫） | 免費 |
| 旁白 | [edge-tts](https://github.com/rany2/edge-tts)，台灣女聲 `zh-TW-HsiaoChenNeural` | 免費 |
| 背景音樂 | numpy 自己合成的環境音，沒有版權問題 | 免費 |
| 畫面、縮圖 | Pillow 畫柔焦漸層，ffmpeg 慢速平移並加上字幕 | 免費 |
| 上傳 | YouTube Data API v3 | 免費（每天約可傳 6 支） |
| 排程 | GitHub Actions，每天台灣時間 19:23 | 公開 repo 免費；私人 repo 每月有 2000 分鐘免費額度 |

## 本機試做

```bash
sudo apt-get install ffmpeg fonts-noto-cjk   # macOS：brew install ffmpeg，並安裝 Noto Sans CJK TC 字型
pip install -r yt_calm/requirements.txt
python -m yt_calm.make_video --list            # 看題庫
python -m yt_calm.make_video --topic 001_tired_day
```

成品會放在 `out/yt_calm/<主題>/`，裡面有 `video.mp4`、`thumbnail.jpg`、`metadata.json`。

## 設定自動上傳（只需要做一次）

1. **建立 Google Cloud 專案**：到 <https://console.cloud.google.com/>，新增一個專案。
2. **啟用 API**：「API 和服務 → 程式庫」，搜尋 **YouTube Data API v3**，然後按「啟用」。
3. **OAuth 同意畫面**：
   - 使用者類型選「外部」。
   - 在「測試使用者」加入你自己的 Google 帳號。
   - 接著按 **「發布應用程式」**。如果一直停在「測試中」，refresh token 7 天就會失效。
4. **建立憑證**：「憑證 → 建立憑證 → OAuth 用戶端 ID」，應用程式類型選「電腦版應用程式」，然後下載 JSON，例如存成 `client_secret.json`。
5. **在你自己的電腦取得 token**：
   ```bash
   pip install google-auth-oauthlib
   python yt_calm/get_token.py client_secret.json
   ```
   瀏覽器會打開，登入有 YouTube 頻道的那個帳號並同意授權，終端機會印出三個值。
6. **把三個值放到 GitHub**：Repo 的 **Settings → Secrets and variables → Actions → New repository secret**，新增：
   - `YT_CLIENT_ID`
   - `YT_CLIENT_SECRET`
   - `YT_REFRESH_TOKEN`
7. **（選用）設定公開程度**：同一頁切到 **Variables** 分頁，新增 `YT_PRIVACY`，值可以是：
   - `private`：預設，只有你看得到，方便先檢查
   - `unlisted`：不公開，有連結的人才看得到
   - `public`：公開
8. **讓排程生效**：把這些檔案合併到預設分支，到 **Settings → Actions → General** 選 *Read and write permissions*。然後到 **Actions → YT calm channel → Run workflow** 手動跑一次測試。

> 還沒設定 secrets 時，workflow 只會做影片，不會上傳。成品可以在該次執行頁面底部的 *Artifacts* 下載，保留 7 天。
>
> 自訂縮圖需要頻道先完成[電話驗證](https://www.youtube.com/verify)，否則只會用 YouTube 自動截圖，影片照常上傳。

## 新增題目

在 `topics/` 新增一個 JSON 檔，檔名開頭的數字決定發布順序：

```json
{
  "id": "008_xxx",
  "title": "主標題｜副標題",
  "thumbnail_text": "縮圖\n兩行字",
  "palette": ["#深色", "#淺色"],
  "tags": ["心情調適", "..."],
  "description": "影片說明",
  "lines": ["一句一行，會變成一則字幕", "", "空字串代表停頓 5 秒"]
}
```

題庫用完時 workflow 會失敗，GitHub 會寄信通知你。這時開一個 Claude 對話，請它「幫 yt_calm 再寫 10 支腳本」就可以了。

## 可以調整的地方

在 workflow 或本機設定環境變數即可：

| 變數 | 預設值 | 說明 |
|---|---|---|
| `YT_VOICE` | `zh-TW-HsiaoChenNeural` | 也可以用 `zh-TW-YunJheNeural`（男聲）或 `zh-TW-HsiaoYuNeural` |
| `YT_RATE` | `-12%` | 語速 |
| `YT_PITCH` | `-2Hz` | 音高 |

## 注意事項

- 說明欄會自動標註「AI 合成語音」，上傳時也會勾選「含有合成內容」，符合 YouTube 的揭露規定。
- YouTube 對大量產出、重複性高的內容審查嚴格。題目和腳本要有變化，營利審核才比較容易通過。建議先用 `private` 跑一陣子，確認品質後再改成 `public`。
- edge-tts 是非官方的免費服務，Microsoft 隨時可能更改或停用。
