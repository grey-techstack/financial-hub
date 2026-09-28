#!/usr/bin/env python3
"""本機伺服器：python3 pipeline/serve.py [--port 8787]

- 提供儀表板靜態檔（同 GitHub Pages）
- /api/lookup?q=NVDA   即時查任何股票 / 指數的 forward PE（不限每日抓取清單）
- /api/search?q=apple  名稱找代號
- /api/chart?symbol=NVDA&range=1y  收盤價序列
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, setup_logging  # noqa: E402
from lookup import lookup  # noqa: E402
from yahoo import Yahoo  # noqa: E402

Y = Yahoo(workers=8)


class Handler(SimpleHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/lookup":
                q = (qs.get("q") or "").strip()
                if not q:
                    return self._json({"error": "missing q"}, 400)
                res = lookup(Y, q, live_index=qs.get("live") == "1")
                return self._json(res or {"error": f"找不到 {q}"}, 200 if res else 404)
            if u.path == "/api/search":
                return self._json({"quotes": Y.search((qs.get("q") or "").strip())})
            if u.path == "/api/chart":
                ch = Y.chart(qs.get("symbol", ""), qs.get("range", "1y"))
                return self._json(ch or {"error": "no data"}, 200 if ch else 404)
            if u.path == "/api/ping":
                return self._json({"ok": True, "live": True})
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 500)
        if u.path in ("/", ""):
            self.path = "/index.html"
        return super().do_GET()

    def end_headers(self):
        if self.path.endswith((".json", ".csv", ".md")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # 只記 API 與伺服器錯誤，靜態檔 404（如尚未產生的檔）不吵
        try:
            msg = fmt % args
        except Exception:  # noqa: BLE001
            msg = str(args)
        if "/api/" in msg or " 500" in msg:
            sys.stderr.write(f"{self.log_date_time_string()} {msg}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    setup_logging("WARNING")
    handler = partial(Handler, directory=str(ROOT))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"儀表板：{url}   （Ctrl+C 結束）")
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
