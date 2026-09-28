# Financial Hub：市場數據儀表板 + 每日日報

一個可以每天打開看的「股市數據頁」，對應 Bloomberg 終端機上常看的幾張表／圖，全部用免費資料源重建：

| 分頁 | 內容 | 對應 Bloomberg |
|---|---|---|
| 今日報告 | 規則式訊號、完整日報、AI 解讀 | — |
| 參與度 | 各指數成分股站上 10/20/50/100/150/200/250 日均線的比例（表 + 一年歷史圖） | `Percentage of Members Above Moving Average` |
| 實質利率與黃金 | 10 年期實質利率（TIPS）、名目殖利率、通膨預期、黃金；相關係數 | `GTII10 Govt` vs `XAU` |
| Forward PE | 輸入股票／指數名稱查 Forward PE、NTM PE、Trailing PE、EPS 共識與修正；指數估值總覽；PE 歷史每日累積 | `BEst P/E` |
| 波動率 | VIX、MOVE 一年走勢與百分位 | `MOVE Index`, `VIX` |

涵蓋指數：道瓊、S&P 500、NASDAQ 100、NASDAQ 綜合*、NYSE 綜合*、費城半導體 SOX、Russell 1000/2000/3000*、S&P 400、S&P 600、S&P/TSX*（* 為近似名單）。

## 快速開始（本機）

```bash
pip3 install -r requirements.txt
python3 pipeline/run_all.py --quick     # 約 30 秒：道瓊 / S&P 500 / NASDAQ 100 / SOX
python3 pipeline/run_all.py             # 約 5–8 分鐘：全部指數（含 5,000+ 檔全市場參與度）
python3 pipeline/serve.py               # 開啟 http://127.0.0.1:8787 儀表板（本機即時模式）
```

本機 `serve.py` 模式下，Forward PE 查詢可以即時查**任何**代號（不限每日名單），例如 `2330.TW`、`0700.HK`、`SHOP.TO`。

命令列直接查：

```bash
python3 pipeline/pe.py NVDA SOX "S&P 500" 2330.TW      # 個股：即時抓；指數：讀今日聚合結果
python3 pipeline/pe.py NDX --live                        # 指數改成現場重算
python3 pipeline/pe.py TSM --json                        # JSON 輸出
```

## 自動更新與網頁

1. **GitHub Actions**（`.github/workflows/update-data.yml`）：週一至週五 22:15 UTC（台北 06:15）自動跑全量管線並提交 `data/` 與 `reports/`。
   也可在 Actions 頁面手動觸發（`workflow_dispatch`）。
2. **GitHub Pages**（`.github/workflows/pages.yml`）：資料更新後自動部署靜態站。
   第一次需到 repo **Settings → Pages → Source 選「GitHub Actions」**，之後網址為 `https://grey-techstack.github.io/financial-hub/`。
3. **每日 AI 解讀**：由 Claude Routine 每日執行 `docs/daily-report.md` 的流程，產生 `reports/YYYY-MM-DD-insight.md`，並推播摘要。

## 追蹤清單

編輯 `config/watchlist.txt`（一行一個代號），隔天起這些代號會出現在「追蹤清單」、每日累積 PE 歷史，並納入日報的 EPS 修正訊號。

## 資料與方法

| 項目 | 來源 | 說明 |
|---|---|---|
| 報價、PE 欄位、分析師 EPS 共識 | Yahoo Finance（免 API key） | `forwardPE` = 股價 ÷ 下一財年 EPS 共識；`earningsTrend` 提供本財年/下一財年 EPS 與 30/90 日修正 |
| 實質利率、殖利率、通膨預期 | FRED（DFII10 / DGS10 / T10YIE / DGS2），備援 Treasury.gov | FRED 對瀏覽器 UA 會刻意拖慢，程式用簡單 UA |
| 黃金、VIX、MOVE、美元、指數 | Yahoo Finance | `GC=F`、`^VIX`、`^MOVE`、`DX-Y.NYB` |
| S&P 500/400/600、TSX 成分股 | Wikipedia | 每日重抓，失敗沿用快取 |
| NASDAQ 100 | Nasdaq 官方 API | |
| 道瓊 30 | State Street DIA ETF 持股檔 | |
| SOX | Nasdaq Global Indexes 權重頁 | 失敗時用 `config/sox_fallback.txt` |
| 全市場（NASDAQ 綜合、NYSE 綜合、Russell 近似） | nasdaqtrader 上市清單 + 市值排名 | Russell 1000 = 市值前 1000、2000 = 第 1001–3000 |

- **指數 PE** = Σ成分股市值 ÷ Σ成分股盈餘（盈餘 = EPS × 隱含股數，隱含股數 = 市值 ÷ 股價；含虧損公司；EPS 明顯異常者排除，如 Yahoo 偶發的小數點錯位）。
- **NTM PE**（混合 12 個月）= 股價 ÷ [w × 本財年 EPS + (1 − w) × 下一財年 EPS]，w = 本財年剩餘月數 ÷ 12，最接近 Bloomberg 的 BEst P/E（BF12M）。
- **PE 歷史**：免費來源沒有歷史的分析師預估，所以由管線每日快照累積（`data/history/`），自 2026-09-28 起；累積 20 個交易日後日報會顯示百分位。
- **參與度**：以 Yahoo 兩年日收盤價計算，成分股名單用「今日名單」回溯（有生存者偏誤，但與常見做法一致）。
- 資料僅供研究參考，不構成投資建議。

## 目錄

```
index.html, assets/        儀表板（純靜態，無建置步驟）
pipeline/
  run_all.py               一鍵更新（--quick 快速模式）
  yahoo.py                 Yahoo Finance 客戶端（chart / 批次報價 / quoteSummary / search）
  constituents.py          成分股來源
  breadth.py               參與度
  valuation.py             個股與指數 PE、NTM 混合、歷史累積
  macro.py                 FRED / 財政部 / Yahoo 總經序列
  report.py                規則式日報與訊號
  lookup.py, pe.py         查詢函式庫與 CLI
  serve.py                 本機伺服器（靜態站 + /api/lookup 即時查詢）
config/watchlist.txt       追蹤清單
data/                      每日輸出（JSON）與歷史 CSV
reports/                   日報（規則式 *.md 與 AI 解讀 *-insight.md）
docs/daily-report.md       AI 解讀 Routine 的執行指南
```
