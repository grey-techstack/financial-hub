"""一鍵更新：抓成分股 → 報價 → 總經 → 歷史價 → 參與度 → 估值 → 日報。

用法：
  python3 pipeline/run_all.py            # 全量（含 NASDAQ/NYSE 綜合、Russell 近似，約 5–8 分鐘）
  python3 pipeline/run_all.py --quick    # 只跑 道瓊/S&P 500/NASDAQ 100/SOX（約 1 分鐘）
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from breadth import build_frames, compute_breadth  # noqa: E402
from common import DATA, HIST, REPORTS, read_csv_rows, read_watchlist, setup_logging, write_json  # noqa: E402
from constituents import load_constituents, russell_proxies, save_universe  # noqa: E402
from macro import build_macro, trading_calendar  # noqa: E402
from registry import ALIASES, INDEXES, MA_WINDOWS, PE_INDEXES, PE_UNIVERSE_INDEXES  # noqa: E402
from report import build_report  # noqa: E402
from valuation import append_history, build_valuation, split_outputs  # noqa: E402
from yahoo import Yahoo  # noqa: E402

LOG = logging.getLogger("run_all")
QUICK_SOURCES = ["sp500", "ndx", "dow", "sox"]
FULL_SOURCES = QUICK_SOURCES + ["sp400", "sp600", "tsx", "us_universe"]


def report_only() -> int:
    from common import read_json
    breadth = read_json(DATA / "breadth.json")
    valuation = read_json(DATA / "valuation.json")
    macro = read_json(DATA / "macro.json")
    status = read_json(DATA / "status.json", {}) or {}
    if not (breadth and valuation and macro):
        LOG.error("data/ 內缺少 breadth/valuation/macro，請先跑完整管線")
        return 2
    asof = breadth.get("asof") or macro.get("asof")
    md, latest = build_report(breadth, valuation, macro, read_csv_rows(HIST / "index_pe.csv"), asof, status)
    (REPORTS / f"{asof}.md").write_text(md, encoding="utf-8")
    (REPORTS / "latest.md").write_text(md, encoding="utf-8")
    write_json(DATA / "latest.json", latest)
    from build_single import build
    build()
    LOG.info("日報已重新產生：%s", asof)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="只跑核心指數，跳過全市場")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--no-history", action="store_true", help="不寫入歷史 CSV（測試用）")
    ap.add_argument("--report-only", action="store_true", help="不抓資料，只用 data/ 現有檔案重新產生日報")
    args = ap.parse_args()
    setup_logging()
    if args.report_only:
        return report_only()
    t_start = time.time()
    timings: dict[str, float] = {}
    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")

    write_json(DATA / "registry.json", {"indexes": INDEXES, "aliases": ALIASES, "pe_indexes": PE_INDEXES, "windows": MA_WINDOWS}, compact=True)

    # 1) 成分股
    t0 = time.time()
    sets, meta = load_constituents(QUICK_SOURCES if args.quick else FULL_SOURCES)
    members: dict[str, list[str]] = {}
    for ix in INDEXES:
        if ix["source"] in sets:
            members[ix["key"]] = [r["symbol"] for r in sets[ix["source"]]]
    if "us_universe" in sets:
        members["COMP"] = [r["symbol"] for r in sets["us_universe"] if r.get("exch") == "Q"]
        members["NYA"] = [r["symbol"] for r in sets["us_universe"] if r.get("exch") == "N"]
    timings["constituents"] = time.time() - t0

    watchlist = read_watchlist()
    etfs = [ix["etf"] for ix in INDEXES if ix.get("etf")]
    all_syms: list[str] = []
    for syms in members.values():
        all_syms.extend(syms)
    all_syms = list(dict.fromkeys(all_syms + watchlist + etfs))

    # 2) 批次報價（市值、PE 欄位）
    y = Yahoo(workers=args.workers)
    t0 = time.time()
    quotes = y.quotes(all_syms)
    timings["quotes"] = time.time() - t0
    if "us_universe" in sets:
        rp = russell_proxies(sets["us_universe"], quotes)
        sets.update(rp)
        for key, src in (("RUI", "r1000"), ("RUT", "r2000"), ("RUA", "r3000")):
            members[key] = [r["symbol"] for r in sets[src]]
        # 綜合指數只保留有報價者，避免下市代號
        for key in ("COMP", "NYA"):
            members[key] = [s for s in members[key] if s in quotes]
    save_universe(sets, meta)

    # 3) 總經、指數序列；交易日曆
    t0 = time.time()
    macro = build_macro(y)
    calendar = trading_calendar(macro)
    if not calendar:
        LOG.error("拿不到 S&P 500 日曆，中止")
        return 2
    asof = calendar[-1]
    asof_date = dt.date.fromisoformat(asof)
    macro["asof"] = asof
    write_json(DATA / "macro.json", macro, compact=True)
    timings["macro"] = time.time() - t0

    # 4) 成分股歷史價 → 參與度
    t0 = time.time()
    breadth_syms = list(dict.fromkeys(s for syms in members.values() for s in syms))
    charts = y.charts(breadth_syms, "2y")
    df, vol = build_frames(charts, calendar)
    del charts
    breadth = compute_breadth(df, members, vol=vol)
    del df, vol
    idx_close = {k: (v.get("close") or [None])[-1] for k, v in (macro.get("indexes") or {}).items()}
    for key, rec in breadth["indexes"].items():
        ix = next((x for x in INDEXES if x["key"] == key), {})
        rec.update({"name": ix.get("name"), "en": ix.get("en"), "approx": ix.get("approx"), "symbol": ix.get("yahoo"), "close": idx_close.get(key)})
        m = (macro.get("indexes") or {}).get(key) or {}
        cl = m.get("close") or []
        rec["chg_pct"] = round((cl[-1] / cl[-2] - 1) * 100, 2) if len(cl) > 1 and cl[-2] else None
    breadth.update({"asof": asof, "windows": [10, 20, 50, 100, 150, 200, 250], "order": [ix["key"] for ix in INDEXES if ix["key"] in breadth["indexes"]]})
    write_json(DATA / "breadth.json", breadth, compact=True)
    timings["breadth"] = time.time() - t0

    # 5) 分析師預估 → 估值
    t0 = time.time()
    pe_universe = list(dict.fromkeys([s for k in PE_UNIVERSE_INDEXES for s in members.get(k, [])] + watchlist))
    estimates = y.estimates_many(pe_universe, workers=min(8, args.workers))
    valuation = build_valuation(quotes, estimates, members, sets, watchlist, asof_date, idx_close)
    core_syms = pe_universe + etfs + [s for k in ("MID", "SML", "TSX") for s in members.get(k, [])]
    main, compact = split_outputs(valuation, core_syms)
    write_json(DATA / "valuation.json", main, compact=True)
    write_json(DATA / "universe_quotes.json", compact, compact=True)
    if not args.no_history:
        append_history(valuation, asof_date, pe_universe)
    timings["valuation"] = time.time() - t0

    # 6) 日報
    t0 = time.time()
    hist_rows = read_csv_rows(HIST / "index_pe.csv")
    status = {"generated_at": generated_at, "sources": meta.get("status", {}), "quick": args.quick,
              "symbols_quoted": len(quotes), "symbols_breadth": len(breadth_syms), "estimates": len(estimates), "timings": {k: round(v, 1) for k, v in timings.items()}}
    md, latest = build_report(breadth, valuation, macro, hist_rows, asof, status)
    (REPORTS / f"{asof}.md").write_text(md, encoding="utf-8")
    (REPORTS / "latest.md").write_text(md, encoding="utf-8")
    write_json(DATA / "latest.json", latest)
    timings["report"] = time.time() - t0
    status["timings"] = {k: round(v, 1) for k, v in timings.items()}
    status["total_seconds"] = round(time.time() - t_start, 1)
    write_json(DATA / "status.json", status)
    try:
        from build_single import build
        LOG.info("單一 HTML：%s", build())
    except Exception as e:  # noqa: BLE001
        LOG.warning("打包單一 HTML 失敗：%s", e)
    LOG.info("完成 %s，共 %.0fs：%s", asof, time.time() - t_start, status["timings"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
