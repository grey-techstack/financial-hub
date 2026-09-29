#!/usr/bin/env python3
"""每日 AI 市場解讀：讀規則式日報與數據，用 Claude API 寫一份繁體中文解讀。

用法：
  ANTHROPIC_API_KEY=... python3 pipeline/insight.py            # 產生 reports/<asof>-insight.md 與 latest-insight.md
  python3 pipeline/insight.py --dry-run                        # 不呼叫 API，只印出會送出的內容長度
  python3 pipeline/insight.py --force                          # 同一天重新產生
沒有 ANTHROPIC_API_KEY 時直接略過（exit 0），不影響其他步驟。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, HIST, REPORTS, read_csv_rows, read_json  # noqa: E402

MODEL = os.environ.get("INSIGHT_MODEL", "claude-opus-5-5")

SYSTEM = """你是一位資深的市場研究員，每天為一位關注美股、半導體、利率與黃金的投資人寫「市場解讀」。
語氣是研究筆記：直接、具體、講因果，不是投資建議，也不要免責聲明式的套話。
使用繁體中文（台灣用語），Markdown 格式，300–700 字。

固定結構（用二級標題）：
# AI 市場解讀 {asof}
## 今日一句話
最重要的一件事，用數字說。
## 參與度
三大指數站上 20/50/200 日線比例的位置與變化；是否進入超賣（<30%）／接近超賣（<40%）／超買（>70%）；
短期超賣與中長期趨勢（200 日線比例）分開講；再看 NYSE 的 52 週淨新高（≤ −5% 極端恐懼）與
McClellan 成交量累積指數（一年百分位、震盪指標是否翻正）是否互相印證。
## 實質利率與黃金
10 年期實質利率的 5 日／21 日變化（bp）與一年百分位；名目利率拆成實質 + 通膨預期；
黃金的反應是否符合「實質利率升、黃金跌」；相關係數是否鬆動。
## 估值
SOX / NASDAQ 100 / S&P 500 的 forward PE 與 NTM PE；相對累積歷史的位置（歷史不足就說明還在累積）；
追蹤清單中 EPS 預估修正最大的名字。
## 波動率
VIX、MOVE 的水位與一年百分位；債市波動是否領先。
## 明日觀察
2–3 個具體、可驗證的觀察點（例如「S&P 500 站上 20 日線比例若跌破 30% 進入超賣」）。

要求：每個判斷都引用具體數字；解釋「為什麼」而不只是描述；指出和前幾天相比的變化（有前幾份解讀時要延續觀點、避免重複）；
資料有缺（例如某序列沒更新）就明說。不要編造數據中沒有的數字。"""


def _tail_rows(path: Path, n: int) -> list[dict]:
    rows = read_csv_rows(path)
    return rows[-n:]


def build_prompt(asof: str) -> str:
    latest = read_json(DATA / "latest.json", {}) or {}
    report = (REPORTS / "latest.md").read_text(encoding="utf-8") if (REPORTS / "latest.md").exists() else ""
    idx_hist = _tail_rows(HIST / "index_pe.csv", 60)
    prev = sorted(glob.glob(str(REPORTS / "*-insight.md")))
    prev = [p for p in prev if not p.endswith(f"{asof}-insight.md")][-3:]
    prev_txt = "\n\n---\n\n".join(Path(p).read_text(encoding="utf-8") for p in prev) if prev else "（尚無前幾天的解讀）"
    slim = {
        "asof": latest.get("asof"), "summary": latest.get("summary"), "signals": latest.get("signals"),
        "indexes": latest.get("indexes"), "macro": latest.get("macro"), "pe": latest.get("pe"), "watchlist": latest.get("watchlist"),
    }
    return (
        f"資料日期（asof）：{asof}\n\n"
        f"## 規則式日報（reports/latest.md）\n\n{report}\n\n"
        f"## 結構化數據（data/latest.json 摘要）\n\n```json\n{json.dumps(slim, ensure_ascii=False)}\n```\n\n"
        f"## 指數 PE 歷史（最近 60 筆，data/history/index_pe.csv）\n\n```json\n{json.dumps(idx_hist, ensure_ascii=False)}\n```\n\n"
        f"## 前幾天的解讀（最多 3 份）\n\n{prev_txt}\n\n"
        f"請依系統提示的結構寫出 {asof} 的市場解讀。"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    latest = read_json(DATA / "latest.json", {}) or {}
    asof = latest.get("asof")
    if not asof:
        print("找不到 data/latest.json，先執行 pipeline/run_all.py")
        return 2
    out = REPORTS / f"{asof}-insight.md"
    if out.exists() and not args.force and not args.dry_run:
        print(f"{out.name} 已存在，略過（--force 可重做）")
        return 0
    prompt = build_prompt(asof)
    system = SYSTEM.replace("{asof}", asof)
    if args.dry_run:
        print(f"dry-run：system {len(system)} 字，prompt {len(prompt)} 字，輸出將寫入 {out}")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("沒有 ANTHROPIC_API_KEY，略過 AI 解讀（在 repo Settings → Secrets 新增後即會自動產生）")
        return 0
    import anthropic

    client = anthropic.Anthropic()
    try:
        # 伺服器端 fallback：若安全分類器拒絕，同一請求自動改由備援模型完成
        with client.beta.messages.stream(
            model=MODEL, max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError as e:
        print(f"beta 參數不被接受（{e.message}），改用一般請求")
        with client.messages.stream(
            model=MODEL, max_tokens=8000, output_config={"effort": "medium"},
            system=system, messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        print("模型拒絕回答，未產生解讀", (msg.stop_details.category if msg.stop_details else ""))
        return 3
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not text:
        print("空回應，未產生解讀")
        return 3
    if not text.startswith("#"):
        text = f"# AI 市場解讀 {asof}\n\n" + text
    text += f"\n\n<sub>由 {msg.model} 於 {asof} 資料產生；輸入 {msg.usage.input_tokens} tokens、輸出 {msg.usage.output_tokens} tokens。</sub>\n"
    out.write_text(text, encoding="utf-8")
    (REPORTS / "latest-insight.md").write_text(text, encoding="utf-8")
    print(f"已寫入 {out} 與 latest-insight.md（{len(text)} 字）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
