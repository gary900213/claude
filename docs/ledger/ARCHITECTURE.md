# 記帳 APP 架構規劃

> 狀態：MVP 已完成（里程碑 1–5），第二版加入每月預算與固定收支（里程碑 6）。

## 1. 技術選擇

**做成 PWA（可安裝到手機桌面的網頁 App），放在 `docs/ledger/`。**

| 項目 | 選擇 | 原因 |
|---|---|---|
| 介面 | 原生 HTML + CSS + JavaScript（ES Modules），不用框架 | 不需要 build、不需要 npm，直接開檔就能跑 |
| 資料儲存 | 瀏覽器 IndexedDB | 資料只存在自己手機／電腦，不需要伺服器、帳號或費用 |
| 離線 | Service Worker 快取 | 沒網路也能記帳 |
| 部署 | GitHub Pages（repo 已用 `/docs` 當 Pages 來源） | 網址會是 `<你的 Pages 網址>/ledger/`，手機開啟後「加入主畫面」即可 |
| 備份 | 匯出／匯入 JSON、匯出 CSV | 資料只在本機，所以一定要能備份、換手機 |
| 測試 | Node 內建 `node:test` 測純邏輯 | 不需安裝套件 |

> 取捨：資料不會自動跨裝置同步。之後若需要，可在 storage 層換成雲端（例如 Supabase / Firebase），上層程式不用改。

## 2. 功能範圍

**MVP（第一版）**
- 新增／編輯／刪除一筆收支：金額、類別、日期、備註
- 預設類別（見第 3 節），可新增自訂類別、隱藏不用的類別
- 首頁：本月收入、支出、結餘＋最近紀錄列表
- 依月份瀏覽紀錄，可依類別篩選、搜尋備註
- 統計：本月各類別支出佔比（圓餅圖）、近 6 個月收支趨勢（長條圖）
- 備份：匯出／匯入 JSON、匯出 CSV（可用 Excel 開）

**第二版（已完成）**
- 每月預算：總預算＋各支出類別預算，首頁顯示使用進度、剩餘金額、每天平均還能花多少，80% 以上變橘色、超過變紅色
- 固定收支：每月固定日期（沒有這天就用月底），開啟 App 時自動記入到期的紀錄，最多往回補 24 個月；可暫停、可刪除（已記入的保留）
- 深色模式（跟隨系統）

**第三版（已完成）**
- 記帳鍵盤：金額用畫面上的數字鍵盤輸入，可以直接算加減（例如 120+35），電腦上也能用實體鍵盤
- 編輯紀錄時可以「再記一筆一樣的」
- 統計頁顯示平均每天支出，以及和上個月同期（例如 10/1–10/17 對 11/1–11/17）的比較
- 首頁顯示今天花了多少

**第四版（已完成）：Apple Pay 自動記帳**
- iPhone 捷徑的「交易」自動化在感應付款時，把金額、商店、時間以一則留言送到使用者自己的 secret GitHub Gist（收件匣）
- 記帳本開啟或切回前景時讀取 Gist 留言（`api.github.com/gists/<id>/comments`，不需要權杖），新的交易自動記帳，標示「Apple Pay」
- 為什麼繞這一圈：捷徑打開網址會用 Safari，而 iPhone 上「加到主畫面」的網頁 App 和 Safari 的資料是分開的，捷徑沒辦法直接寫進桌面 App
- 依商店名稱猜類別（`domain/inbox.js` 的 `DEFAULT_RULES`）；使用者改過類別後記住這家店（含其他分店），之後自動套用
- 沒帶到金額的交易放在「待補金額」；已處理過的交易記在 `inboxSeen`，同一筆不會記兩次
- 不想用 GitHub：捷徑改成附加到 iCloud 雲碟的文字檔，在 App 裡「從檔案匯入」
- 網購或 App 內的 Apple Pay 不會觸發「交易」自動化，所以另外支援**銀行刷卡通知**：捷徑的「訊息」或「電子郵件」自動化把通知全文送進同一個收件匣，`parseNotice()` 從文字讀出金額（只認有幣別或「金額」字樣的數字，避免把卡號末四碼當成金額）、商店、日期；退款、驗證碼、帳單通知略過，外幣消費放到待補金額。兩種方式不要同時開，否則實體感應會記兩次

**第五版（已完成）：Gmail 刷卡通知，不用 iPhone 捷徑**
- 記帳本產生一段 Google Apps Script 程式碼（`domain/gmail.js`），使用者貼到 script.google.com、以自己的身分部署成「網頁應用程式」
- 記帳本開啟時呼叫該網址（帶 `key` 和 `since`），腳本用 `GmailApp.search` 找刷卡通知信，回傳信件開頭 800 字；記帳本用 `parseNotice()` 解析後匯入
- 搜尋條件寫死在腳本裡（寄件人或主旨關鍵字），不從網址傳入，所以網址外流也讀不到其他信；`key` 是記帳本產生的隨機字串
- 呼叫時不帶自訂標頭，瀏覽器不會送 OPTIONS 預檢（Apps Script 不支援）
- 第一次設定從前一天開始抓，避免一次匯入一個月的通知；之後用 `gmailSince` 只抓新的，再用 `inboxSeen` 去重
- 退款、驗證碼、帳單等字樣只在「出現在金額之前」才略過，Email 底部的「請勿洩漏密碼」警語不會讓整封被略過
- 設定頁有「貼一則刷卡通知測試」，不用真的刷卡就能確認讀得對不對

**之後再做**
- 帳戶（現金／銀行／信用卡）與轉帳
- 多幣別、跨裝置同步

## 3. 預設類別

**支出**

| id | 名稱 | 圖示 | 例子 |
|---|---|---|---|
| food | 餐飲 | 🍱 | 三餐、飲料、零食 |
| transport | 交通 | 🚌 | 捷運、公車、加油、停車、計程車 |
| housing | 居住 | 🏠 | 房租、房貸、管理費、水電網路 |
| social | 人情交際 | 🎁 | 聚餐請客、禮金、送禮 |
| other_expense | 其他支出 | 📦 | 購物、娛樂、醫療等不屬於以上的 |

**收入**

| id | 名稱 | 圖示 |
|---|---|---|
| salary | 薪資 | 💼 |
| bonus | 獎金 | 🎉 |
| side_income | 兼職外快 | 🧰 |
| investment | 投資收益 | 📈 |
| other_income | 其他收入 | 💰 |

預設類別存在 `js/defaults.js`，第一次開啟 App 時寫入資料庫；之後使用者可改名、換圖示、隱藏，但不能刪除已有紀錄的類別（改成「隱藏」），避免舊紀錄找不到類別。

## 4. 資料模型

```js
// Category
{
  id: "food",              // 預設類別用固定 id；自訂類別用 crypto.randomUUID()
  type: "expense",         // "expense" | "income"
  name: "餐飲",
  icon: "🍱",
  order: 1,                // 顯示順序
  hidden: false,           // 隱藏 = 軟刪除
  builtin: true            // 是否為預設類別
}

// Transaction
{
  id: "uuid",
  type: "expense",         // "expense" | "income"（冗餘存一份，方便統計與篩選）
  amount: 120,             // 正整數，單位：元（新台幣無小數）。不用浮點數，避免加總誤差
  categoryId: "food",
  date: "2026-11-09",      // 本地日期字串，不存時區，避免跨時區日期跳動
  note: "午餐便當",
  createdAt: 1762646400000,
  updatedAt: 1762646400000
}

// Transaction 由固定收支產生時，多一個欄位
{ ..., recurringId: "uuid" }

// Budget（v2）：每個月套用同一份；amount 為 0 的不存
{ id: "total" | "<支出類別 id>", amount: 30000 }

// RecurringRule（v2）
{
  id: "uuid",
  type: "expense",
  amount: 15000,
  categoryId: "housing",
  note: "房租",
  day: 5,                  // 每月幾號，1~31；該月沒有這天就用月底
  startMonth: "2026-12",   // 從哪個月開始
  lastGenerated: "2026-11",// 已經產生到哪個月（null = 還沒產生過）
  active: true
}

// Meta（單筆設定）
{ key: "schemaVersion", value: 1 }
{ key: "lastExportAt", value: 1762646400000 }
```

IndexedDB 結構：

| Object store | key | 索引 |
|---|---|---|
| `categories` | `id` | `type` |
| `transactions` | `id` | `date`、`categoryId` |
| `meta` | `key` | — |
| `budgets`（v2） | `id` | — |
| `recurring`（v2） | `id` | — |

資料庫版本（`DB_VERSION`）目前是 2。升級時只新增資料表，舊資料不動。

固定收支在 `services/recurring.js` 的 `generateDue()` 產生：讀規則、寫紀錄、更新 `lastGenerated` 在同一個 IndexedDB 交易裡，同時開兩個分頁也不會重複記入。觸發時機：App 開啟、從背景切回前景、儲存固定收支、匯入備份。

備份檔 `version: 2` 起包含 `budgets` 和 `recurring`；匯入時仍接受 v1 備份。

`schemaVersion` 用來做之後的資料升級（例如加入帳戶欄位）。

## 5. 程式分層

```
UI（views/*）  ──呼叫──▶  services（ledger.js）  ──呼叫──▶  storage（db.js）
                               │
                               └──▶  domain（stats.js、validate.js：純函式，可單元測試）
```

- **storage**：唯一碰 IndexedDB 的地方，只提供 `get / getAll / put / delete / query` 這類操作。之後要換雲端只改這層。
- **domain**：純函式，不碰 DOM、不碰資料庫。例如 `summarize(transactions)`、`groupByCategory()`、`monthlyTrend()`、`validateTransaction()`。這層是測試重點。
- **services**：把 storage 跟 domain 組起來，例如 `addTransaction()` = 驗證 → 寫入 → 通知畫面更新。
- **UI**：每個畫面一個模組，用 hash 路由切換，格式是「頁面-參數」，只用英數字和連字號（`#home`、`#list-2026-11`、`#edit-<id>`、`#prefs` 等），在任何網址環境都能正常傳遞。確認動作用畫面內的對話框（`confirmDialog`），不用瀏覽器的 `confirm()`。

## 6. 目錄結構

```
docs/ledger/
├── ARCHITECTURE.md        # 本文件
├── index.html             # 唯一的 HTML，載入 app.js
├── manifest.webmanifest   # PWA 設定（名稱、圖示、主題色）
├── sw.js                  # Service Worker（離線快取）
├── css/
│   └── style.css
├── icons/                 # App 圖示 192/512px
└── js/
    ├── app.js             # 進入點：初始化 DB、寫入預設類別、啟動路由
    ├── router.js          # hash 路由
    ├── defaults.js        # 預設類別
    ├── config.js          # PREVIEW 開關（預覽版用）
    ├── sample.js          # 範例資料（預覽版第一次開啟時放入）
    ├── storage/
    │   └── db.js          # IndexedDB 包裝
    ├── domain/
    │   ├── stats.js       # 加總、分組、趨勢
    │   ├── validate.js    # 輸入驗證（紀錄、類別、備份檔）
    │   ├── format.js      # 金額、日期格式化
    │   ├── csv.js         # 產生 CSV
    │   ├── amount.js      # 記帳鍵盤的加減算式
    │   ├── inbox.js       # Apple Pay 交易與刷卡通知解析、商店分類
    │   ├── gmail.js       # 產生 Gmail 讀取用的 Google Apps Script
    │   ├── budget.js      # 預算使用狀況
    │   └── recurring.js   # 固定收支的到期日計算
    ├── services/
    │   ├── ledger.js      # 收支 CRUD
    │   ├── categories.js  # 類別管理
    │   ├── budget.js      # 預算讀寫
    │   ├── recurring.js   # 固定收支規則、自動記入
    │   ├── inbox.js       # Apple Pay 收件匣同步、匯入、學習分類
    │   └── backup.js      # 匯出／匯入 JSON、CSV
    └── views/
        ├── components.js  # 共用畫面片段、toast、HTML 跳脫
        ├── charts.js      # <canvas> 圓環圖、長條圖
        ├── home.js        # 首頁：本月摘要＋最近紀錄
        ├── edit.js        # 新增／編輯一筆
        ├── list.js        # 月份列表、篩選、搜尋
        ├── stats.js       # 圖表（用 <canvas> 自己畫，不引入圖表套件）
        ├── settings.js    # 類別管理、備份、進階功能選單
        ├── budget.js      # 每月預算（#budget）
        ├── recurring.js   # 固定收支列表與表單（#recurring）
        └── applepay.js    # Apple Pay 自動記帳設定與教學（#applepay）

tests/ledger/
├── budget.test.mjs
├── recurring.test.mjs
├── format.test.mjs
├── stats.test.mjs
└── validate.test.mjs
```

執行測試：`node --test tests/ledger/*.test.mjs`

本機預覽：`python3 -m http.server -d docs/ledger 8000`，打開 http://localhost:8000

修改或新增 JS／CSS 檔案後，記得更新 `sw.js` 的 `ASSETS` 並把 `VERSION` 加 1，手機上才會換成新版。

## 7. 畫面

1. **首頁**：上方三格（收入／支出／結餘），下方最近 20 筆，右下角「＋」按鈕
2. **新增／編輯**：支出／收入切換 → 數字鍵盤輸入金額 → 類別圖示格選擇 → 日期（預設今天）→ 備註 → 儲存
3. **明細**：月份左右切換，依日期分組，每天顯示小計；可篩類別、搜備註；點一筆進入編輯
4. **統計**：本月支出類別圓餅圖＋排行、近 6 個月收支長條圖
5. **設定**：類別管理（新增、改名、排序、隱藏）、匯出 JSON／CSV、匯入 JSON

底部 Tab：首頁｜明細｜統計｜設定

## 8. 開發里程碑

1. **骨架**：`index.html`、路由、IndexedDB、寫入預設類別
2. **記帳核心**：新增／編輯／刪除、首頁摘要、明細列表＋ domain 層測試
3. **統計**：圓餅圖、趨勢圖
4. **設定與備份**：類別管理、匯出匯入
5. **PWA**：manifest、Service Worker、圖示，手機可安裝、可離線
6. **預算與固定收支**：資料庫升到 v2、每月預算、固定收支自動記入、備份格式 v2

## 預覽版

另外有一份放在 claude.ai 的預覽版，和正式網站用同一份程式。預覽版是用 `node tools/build_ledger.mjs <輸出資料夾>` 打包成的**單一 HTML 檔**（樣式、程式、圖示全部內嵌，不載入其他檔案），也可以直接用瀏覽器打開。和正式網站的差別：

- 打包時把 `js/config.js` 的 `PREVIEW` 設成 `true`：第一次開啟放入範例資料、頁面上方顯示說明列（可清空或放回範例資料）、不註冊離線快取、匯出改成提示（預覽頁不能下載檔案）。
- 給 claude.ai 用的 `ledger-artifact.html` 沒有 `<html>/<head>/<body>` 外層（平台會自己加上）；不含 `sw.js` 和 `manifest.webmanifest`。
