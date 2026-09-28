#!/usr/bin/env python3
"""把儀表板打包成單一 HTML（CSS、JS、資料、日報全部內嵌）。

用途：private repo 開不了 GitHub Pages 時，這個檔案可以直接用瀏覽器打開（file://），
也可以發布成 Claude 私有頁面（artifact）或放到任何靜態空間。
輸出：dist/dashboard.html
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, HIST, REPORTS, ROOT, read_json  # noqa: E402

DIST = ROOT / "dist"


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def build(out: Path | None = None, include_universe: bool = True, artifact: bool = False) -> Path:
    """artifact=True 時輸出 Claude 頁面用的片段版：發布時平台會自己包 doctype/head/body，
    檔案只保留 <title>、<style>、頁面內容與 <script>。"""
    out = out or (DIST / ("artifact.html" if artifact else "dashboard.html"))
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    year = dt.datetime.now(dt.timezone.utc).year
    payload = {
        "latest": read_json(DATA / "latest.json"),
        "breadth": read_json(DATA / "breadth.json"),
        "macro": read_json(DATA / "macro.json"),
        "valuation": read_json(DATA / "valuation.json"),
        "registry": read_json(DATA / "registry.json"),
        "status": read_json(DATA / "status.json"),
        "universe_quotes": read_json(DATA / "universe_quotes.json") if include_universe else None,
        "report_md": _text(REPORTS / "latest.md"),
        "insight_md": _text(REPORTS / "latest-insight.md"),
        "index_pe_csv": _text(HIST / "index_pe.csv"),
        "pe_csv": _text(HIST / "pe" / f"{year}.csv"),
        "pe_csv_prev": _text(HIST / "pe" / f"{year - 1}.csv"),
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    head_extra = f"<style>\n{css}\n</style>"
    html = html.replace('<link rel="stylesheet" href="assets/style.css">', head_extra)
    body_scripts = f"<script>window.FH_DATA={data_js};</script>\n<script>\n{js}\n</script>"
    html = html.replace('<script src="assets/app.js"></script>', body_scripts)
    if artifact:
        import re
        title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        style = re.search(r"<style>.*?</style>", html, re.S).group(0)
        body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
        html = f"<title>{title}</title>\n{style}\n{body}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    for art in (False, True):
        p = build(artifact=art)
        print(f"{p} ({p.stat().st_size / 1e6:.2f} MB)")
