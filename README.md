# Financial Hub：市場數據儀表板 + 每日日報

一個可以每天打開看的「股市數據頁」，對應 Bloomberg 終端機上常看的幾張表／圖，全部用免費資料源重建：

| 分頁 | 內容 | 對應 Bloomberg |
|---|---|---|
| 今日報告 | 規則式訊號、完整日報、AI 解讀 | — |
| 參與度 | 各指數成分股站上 10/20/50/100/150/200/250 日均線的比例（表 + 一年歷史圖）；52 週淨新高（創新高家數 − 創新低家數）；McClellan 成交量震盪指標與累積指數；每個指標旁有 i 說明標記 | `Percentage of Members Above Moving Average`；CNN Fear & Greed 的 Stock Price Strength / Breadth |
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

## 自動更新與「在哪裡看」

1. **GitHub Actions**（`.github/workflows/update-data.yml`）：週一至週五 22:08 / 22:23 / 22:38 UTC（台北 06:08 起，另 07:23 補跑）自動跑全量管線，8 小時內已更新則略過並提交 `data/` 與 `reports/`。
   也可在 Actions 頁面手動觸發（`workflow_dispatch`）。
2. **每日 AI 解讀**（只用 Claude Max plan，不需要 API key）：一個帶 repo 權限的常駐 Claude session 由 Routine 每個交易日
   07:05（台北）喚醒，依 `docs/daily-report.md` 寫 `reports/YYYY-MM-DD-insight.md` 並推上 repo，儀表板「今日報告」會顯示；
   另一個 Routine 07:30 讀公開網址並推播摘要。`pipeline/insight.py` 是用 Claude API 的備用路徑，預設不啟用（沒有
   `ANTHROPIC_API_KEY` secret 就自動略過，不會產生費用）。
3. **看儀表板的三種方式**：
   - **單一 HTML 檔**：`python3 pipeline/build_single.py` 會產生 `dist/dashboard.html`（資料內嵌，可直接用瀏覽器開、不需伺服器，
     也能丟到任何靜態空間）與 `dist/artifact.html`（發布成 Claude 頁面用的片段版）。
   - **本機**：`python3 pipeline/serve.py`，另有即時查詢任何代號的功能。
   - **GitHub Pages**（`.github/workflows/pages.yml`）：GitHub 免費方案的 private repo 不能開 Pages，先把 repo 改成 public
     （Settings → General → Danger Zone → Change visibility），再到 Settings → Pages → Source 選「GitHub Actions」。
     之後每次資料更新都會自動部署（沒開通時部署步驟會自動略過，不會報錯）。
     **自訂網域**：到 Settings → Pages → Custom domain 填子網域；DNS 用 **A / AAAA 記錄指向 GitHub Pages 的四組 IP**，
     不要用 CNAME 指到 `<帳號>.github.io`（CNAME 會在公開的 DNS 記錄裡洩漏 GitHub 帳號），再加一筆 null MX（`0 .`）
     讓 GitHub 的 DNS 檢查接受子網域使用 A 記錄；憑證簽發後勾選 Enforce HTTPS。網域字串與帳號不要寫進 repo 任何檔案，
     以免有人用網域搜尋就找到 repo（Actions 來源的 Pages 不需要 `CNAME` 檔，自訂網域存在 Settings 裡）。
     不想公開 repo 的話，Cloudflare Pages / Netlify / Vercel 的免費方案都能連 private repo 直接部署（build command 留空、輸出目錄 `/`）。

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
- **參與度**：以 Yahoo 兩年日收盤價與成交量計算，成分股名單用「今日名單」回溯（有生存者偏誤，但與常見做法一致）。52 週新高／新低以收盤價判定；McClellan 用比例調整淨值 (上漲 − 下跌)/(上漲 + 下跌)×1000 的 EMA19 − EMA39，累積指數起點 1000，水位為相對值。
- 資料僅供研究參考，不構成投資建議。

## 安全檢查

`.github/workflows/security.yml` 在每次 push / PR 與每週一自動執行，等同 GitLab 的 Secret Detection、Dependency Scanning 與 SAST：

| 檢查 | 工具 | 內容 |
|---|---|---|
| 祕密偵測 | gitleaks | 掃整個 git 歷史找 API key / token / 密碼；有發現 CI 直接失敗，結果上傳到 Security → Code scanning |
| 相依套件弱點 | pip-audit | `requirements.txt` 解析後的版本比對 PyPI Advisory / OSV 弱點資料庫 |
| 靜態分析 | CodeQL | Python 與 JavaScript 的安全與品質規則 |
| 套件更新 | Dependabot | 每週檢查 pip 與 GitHub Actions 新版，自動開 PR |

建議再到 repo **Settings → Code security** 開啟 GitHub 內建的 **Secret scanning** 與 **Push protection**（public repo 免費），
這樣含祕密的 commit 在 push 時就會被擋下，不用等 CI。本機也可裝 pre-commit（`pip install pre-commit && pre-commit install`），
commit 前先跑 gitleaks。原則：憑證只放 GitHub Actions secrets 或環境變數，永遠不進檔案。

## 目錄

```
index.html, assets/        儀表板（純靜態，無建置步驟）
pipeline/
  run_all.py               一鍵更新（--quick 快速模式；--report-only 只重做日報）
  build_single.py          打包成單一 HTML（dist/）
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
