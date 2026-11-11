# BTC 每日資金流與清算報告（免費版）

用**完全免費的公開資料**，每天自動更新類似 CoinGlass 的幾張圖：

| 圖表 | 資料來源 | 說明 |
|---|---|---|
| BTC 現貨 ETF 每日淨流入／累計淨流入 | [Farside Investors](https://farside.co.uk/bitcoin-etf-flow-all-data/) | 抓網頁表格，單位百萬美元 |
| 預估清算熱力圖（近 14 天） | K 線 + 持倉量 + 多空比 | **自行推估的近似值**，見下方模型說明 |
| 預估清算地圖（現價 ±12%） | 同上 | 現在這一刻各價位的潛在清算量與累計量 |
| 價格／持倉量／資金費率／多空比 | Binance 期貨 → 失敗時改用 OKX | 公開 API，不需 key |
| 每日實際清算量 | OKX BTC-USDT 永續強平單 | 每次執行累積，歷史會越來越長 |

輸出：

- `docs/index.html`：報告頁（可以直接開 GitHub Pages）
- `docs/img/*.png`：圖表
- `data/daily_summary.csv`：每日摘要（收盤價、持倉量、資金費率、多空比、多空清算量、ETF 淨流入），每次執行都會**累積**
- `data/etf_flows.csv`：各檔 ETF 每日流量完整表
- `data/liquidations_raw.csv`：最近 10 天的 OKX 原始清算單

## 自動更新（GitHub Actions）

`.github/workflows/btc-daily.yml` 每 6 小時跑一次，跑完會把 `data/`、`docs/` commit 回 repo。

啟用步驟：

1. 把這些檔案合併到 repo 的**預設分支**（GitHub 只會在預設分支上執行排程）。
2. 到 **Settings → Actions → General → Workflow permissions**，選 **Read and write permissions**。
3. 到 **Actions** 分頁，選 *BTC daily report* → **Run workflow**，先手動跑一次確認。
4. （選用）**Settings → Pages**：Source 選 *Deploy from a branch*，分支選預設分支、資料夾選 `/docs`，就能用網址看報告。

> GitHub Actions 的機器在美國，Binance 會回 451 拒絕連線；程式會自動改用 OKX，所以不用處理。
> 如果某個來源暫時失敗，報告頁的「資料狀態」會標示 ❌，其他圖照常更新。

## 在自己電腦上跑

```bash
pip install -r requirements.txt
```

```bash
python -m btc_daily.main
```

不連網、用模擬資料測試整個流程：

```bash
python -m btc_daily.main --demo --out /tmp/btc-demo
```

圖表裡的中文需要 CJK 字型（Windows／macOS 內建即可；Linux 請裝 `fonts-noto-cjk`）。

## 清算熱力圖模型（近似）

CoinGlass 的熱力圖要買 Professional 方案（約 $699／月）才拿得到。這裡用公開數據推估：

1. 每根 1 小時 K 棒，若持倉量增加 ΔOI，就當作有 ΔOI 美元的新倉位在典型價 (H+L+C)/3 開倉，依多空帳戶比拆成多／空。
2. 用假設的槓桿分佈（5x 10%、10x 30%、25x 30%、50x 20%、100x 10%）、維持保證金率 0.5% 算出強平價：
   - 多單：開倉價 × (1 − 1/槓桿 + 0.5%)
   - 空單：開倉價 × (1 + 1/槓桿 − 0.5%)
3. 持倉量下降時，依比例縮減所有尚未清算的部位（視為平倉）。
4. 價格碰到某個價位後，該價位的清算量歸零（已被清算）。

限制：交易所實際的槓桿分佈、維持保證金階梯、各人開倉成本都無法取得，所以只能看「哪裡可能堆積較多清算」的相對位置，不要當成精確數字。參數可以在 `btc_daily/heatmap.py` 的 `DEFAULT_LEVERAGE` 調整。

## 沒有做的項目

- **交易所 BTC 淨流入／流出（鏈上）**：需要交易所錢包地址標記，目前找不到穩定的免費來源（CryptoQuant、Glassnode、CoinGlass 都要付費）。

## 量化研究：歷史數據庫與回測（`quant/`）

從幣安官方歷史數據站 `data.binance.vision` 下載 BTCUSDT 永續合約的長期歷史（美國主機也能連，不受 451 限制）：

| 數據 | 起始 | 頻率 |
|---|---|---|
| K 線（含主動買入量） | 2020-01 | 1 小時 |
| 資金費率 | 2020-01 | 每 8 小時（只有月檔，當月要等月底） |
| 持倉量、大戶／全體多空比、主動買賣量比 | 2020-09 | 5 分鐘 → 整理成 1 小時 |

建立／更新數據庫（第一次約 2 分鐘，之後只下載新檔）：

```bash
python -m quant.history
```

輸出 `data/history/`：`btcusdt_1h.csv.gz`（每小時）、`btcusdt_funding.csv.gz`、`btc_daily.csv.gz`（每日特徵表：報酬、已實現波動、資金費率 z 分數、持倉量變化、多空比、主動買入比、ETF 淨流入）。

跑基準策略回測，報告輸出到 `docs/backtest/README.md`：

```bash
python -m quant.run_baseline
```

第三步：衍生品過濾的滾動前推驗證，報告輸出到 `docs/filters/README.md`：

```bash
python -m quant.run_filters
```

紙上交易（凍結策略，每天產生建議倉位並結算），報告輸出到 `docs/paper/README.md`：

```bash
python -m quant.paper
```

訊號紀錄 `data/paper/signals.csv` 只會新增、不會改寫，每筆都記下產生時間；績效以「產生當天的 UTC 收盤」執行來結算。

回測規則：第 D 天收盤的訊號只能賺第 D+1 天的報酬；扣除每單位換手 7 bps 成本與永續資金費率；ETF 流量往後挪一天（公布時間在美股收盤後）。

## 測試

```bash
python -m pytest -q tests
```

---

# 記帳本（docs/ledger）

可安裝到手機桌面的記帳網頁 App，資料只存在你的瀏覽器（IndexedDB），可離線使用。

- 開啟 GitHub Pages 後，網址是 `<你的 Pages 網址>/ledger/`；手機用 Safari／Chrome 開啟後選「加入主畫面」。
- 本機預覽：`python3 -m http.server -d docs/ledger 8000`
- 測試：`node --test tests/ledger/*.test.mjs`
- 架構說明：[docs/ledger/ARCHITECTURE.md](docs/ledger/ARCHITECTURE.md)
