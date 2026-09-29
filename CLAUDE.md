# financial-hub 專案規則（Claude 的長期記憶，每次 session 自動載入）

## 身分與提交
- 所有 commit 作者一律用 repo 擁有者，提交前先設定：
  `git config user.name "grey-techstack" && git config user.email "178301854+grey-techstack@users.noreply.github.com"`
- commit 訊息不加 Co-Authored-By、Claude-Session 或任何 Claude 署名；頁面、程式註解、User-Agent 都不放 repo 連結或作者資訊。
- 預設分支是 `claude/stock-market-data-query-2aox9i`（repo 首次 push 的分支）；GitHub Actions 的排程只在預設分支執行。

## 安全（新 repo 也要照做）
- 保留並沿用 `.github/workflows/security.yml`（gitleaks 全歷史祕密偵測 + pip-audit 相依弱點 + CodeQL 靜態分析）、
  `.gitleaks.toml`、`.github/dependabot.yml`、`.pre-commit-config.yaml`。開新 repo 時第一個 commit 就要帶這一套。
- GitHub 內建的 Secret scanning / Push protection / Dependabot alerts **無法從 Claude 的雲端代理啟用**
  （對 repo 設定的 API 寫入固定回 403），要提醒擁有者到 Settings → Code security 手動開啟；提醒一次並在 README 留步驟即可。
- 憑證只能放 GitHub Actions secrets 或環境變數，永遠不寫進檔案；目前沒有任何 secret，也不需要。
- 每次要 commit 前先跑 `gitleaks git --no-banner --redact .`（沒有的話 `pip-audit -r requirements.txt` 也一併跑）。

## 部署與資料
- 靜態站由 `.github/workflows/pages.yml` 部署（Pages Source = GitHub Actions），自訂網域 `<自訂網域>`，CNAME 檔由部署流程寫入。
- 資料由 `update-data.yml` 每個美股交易日 22:15 UTC 更新並 commit；本機開發用 `python3 pipeline/run_all.py --quick`，只重做日報用 `--report-only`。
- AI 解讀走 **Max plan**：一個帶 repo 權限的常駐 Claude session（「財經數據每日 AI 解讀寫入」）由 Routine 每個交易日 06:35 台北時間喚醒，
  寫 `reports/<asof>-insight.md` 並 push；另一個 Routine 06:57 讀公開網址推播摘要。`pipeline/insight.py`（Claude API）只是備用，
  **預設不啟用**：使用者不想有 Max plan 以外的任何花費，不要建立 API key、不要加 `ANTHROPIC_API_KEY` secret、不要接任何付費服務。
- 改指標或資料來源時，同步更新 README「資料與方法」、`docs/daily-report.md` 與頁面上的 ⓘ 說明文字（index.html）。
- 前端沒有建置步驟：改 `assets/app.js` 後用 `node -e "new Function(require('fs').readFileSync('assets/app.js','utf8'))"` 檢查語法，
  並用本機 `python3 pipeline/serve.py` + Playwright 截圖看桌面與手機版。

## 溝通
- 使用者用繁體中文；回報時引用具體數字；研究筆記語氣，不是投資建議。
