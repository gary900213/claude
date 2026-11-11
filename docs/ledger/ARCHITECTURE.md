# 記帳 APP 架構規劃

> 狀態：MVP 已完成（里程碑 1–5）。

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

**之後再做**
- 帳戶（現金／銀行／信用卡）與轉帳
- 每月預算與超支提醒
- 固定收支（房租、訂閱自動產生）
- 深色模式、多幣別

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

// Meta（單筆設定）
{ key: "schemaVersion", value: 1 }
```

IndexedDB 結構：

| Object store | key | 索引 |
|---|---|---|
| `categories` | `id` | `type` |
| `transactions` | `id` | `date`、`categoryId` |
| `meta` | `key` | — |

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
- **UI**：每個畫面一個模組，用 hash 路由（`#/`、`#/add`、`#/list`、`#/stats`、`#/settings`）切換。

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
    ├── storage/
    │   └── db.js          # IndexedDB 包裝
    ├── domain/
    │   ├── stats.js       # 加總、分組、趨勢
    │   ├── validate.js    # 輸入驗證（紀錄、類別、備份檔）
    │   ├── format.js      # 金額、日期格式化
    │   └── csv.js         # 產生 CSV
    ├── services/
    │   ├── ledger.js      # 收支 CRUD
    │   ├── categories.js  # 類別管理
    │   └── backup.js      # 匯出／匯入 JSON、CSV
    └── views/
        ├── components.js  # 共用畫面片段、toast、HTML 跳脫
        ├── charts.js      # <canvas> 圓環圖、長條圖
        ├── home.js        # 首頁：本月摘要＋最近紀錄
        ├── edit.js        # 新增／編輯一筆
        ├── list.js        # 月份列表、篩選、搜尋
        ├── stats.js       # 圖表（用 <canvas> 自己畫，不引入圖表套件）
        └── settings.js    # 類別管理、備份

tests/ledger/
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
