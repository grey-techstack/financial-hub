# 每日 AI 市場解讀（Routine 執行指南）

這份文件給「每日自動執行的 Claude Routine」看：每個美股交易日收盤後，讀取本 repo 最新數據與規則式日報，
寫一份繁體中文的市場解讀，存檔、推上 GitHub，並回覆摘要作為通知內容。

## 產出

- `reports/YYYY-MM-DD-insight.md`：當日解讀（YYYY-MM-DD 用 `data/latest.json` 的 `asof`，即資料所屬的交易日）
- `reports/latest-insight.md`：同一份內容的複本，儀表板「今日報告」分頁會讀這個檔顯示為「AI 解讀」

## 步驟

1. 取得最新程式與資料：`git pull`（工作目錄是 repo 根目錄）。
2. 檢查資料是否新鮮：`data/latest.json` 的 `asof` 應是最近一個美股交易日。
   若 `data/status.json` 的 `generated_at` 距今超過 20 小時，先自己跑一次管線再繼續：
   `pip install -r requirements.txt && python3 pipeline/run_all.py --workers 12`（全量約 5–8 分鐘；失敗就改跑 `--quick`）。
3. 讀取素材（全部都在 repo 內，不需要上網）：
   - `reports/latest.md`：規則式日報（指數表現、參與度、實質利率與黃金、估值、波動率）
   - `data/latest.json`：訊號清單（`signals`）、各指數與總經數字
   - `data/history/index_pe.csv`：指數 forward PE 每日累積（用來說「PE 相較一週／一月前」）
   - `data/breadth.json` 的 `history`：參與度歷史（判斷惡化／改善的速度）
   - 最近 3–5 份 `reports/*-insight.md`：延續前幾天的觀點、避免重複講同一件事
4. 寫解讀（300–700 字，繁體中文，Markdown），固定結構：
   - `# AI 市場解讀 YYYY-MM-DD`
   - **今日一句話**：最重要的一件事，用數字說
   - **參與度**：三大指數站上 20/50/200 日線比例的位置與變化；是否進入超賣（<30%）／接近超賣（<40%）／超買（>70%）；
     短期超賣 vs 中長期趨勢（200 日線比例）要分開講；再看 NYSE 的 52 週淨新高（≤ −5% 極端恐懼）與 McClellan 成交量累積指數
     （一年百分位、震盪指標是否翻正）是否與均線比例互相印證
   - **實質利率與黃金**：10 年期實質利率的 5 日／21 日變化（bp）與一年百分位；名目利率拆解成實質 + 通膨預期；
     黃金的反應是否符合「實質利率升、黃金跌」；相關係數是否鬆動
   - **估值**：SOX / NASDAQ 100 / S&P 500 的 forward PE 與 NTM PE；相對歷史累積區間的位置；追蹤清單裡 EPS 預估修正最大的名字
   - **波動率**：VIX、MOVE 的水位與一年百分位；債市波動是否領先
   - **明日觀察**：2–3 個具體的觀察點（例如「S&P 500 站上 20 日線比例若跌破 30% 進入超賣」）
   要求：每個判斷都引用具體數字；解釋「為什麼」而不只是描述；指出和前幾天相比的變化；語氣是研究筆記，不是投資建議；
   資料有缺（例如 FRED 沒更新）就明說。
5. 存檔：同一份內容寫入 `reports/YYYY-MM-DD-insight.md` 與 `reports/latest-insight.md`。
6. 提交前先設定作者身分（repo 擁有者，不要用 Claude 的身分、不要加 Co-Authored-By）：
   `git config user.name "grey-techstack" && git config user.email "178301854+grey-techstack@users.noreply.github.com"`，
   然後 `git add reports data && git commit -m "AI 解讀 YYYY-MM-DD" && git push`（push 失敗先 `git pull --rebase` 再推）。
7. 回覆一段 3–5 句的摘要（今日一句話 + 最重要的 2 個觀察 + 明日觀察），這段會成為通知內容。

## 注意

- 不要修改 pipeline 程式或 data/ 內容（除了步驟 2 的正常執行結果）。
- 假日或資料未更新（`asof` 與上一份 insight 相同）就只回覆「今日無新資料」，不要重複產生同一天的解讀。
- 指數 PE 是「Σ市值 ÷ Σ盈餘」，含虧損公司；NTM 是依財年剩餘月數混合本財年與下一財年 EPS 共識，最接近 Bloomberg BEst P/E。
  Russell、NASDAQ 綜合、NYSE 綜合的成分股是近似名單，講到時可以提一下。
