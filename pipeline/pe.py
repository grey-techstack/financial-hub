#!/usr/bin/env python3
"""查 forward PE：python3 pipeline/pe.py NVDA SOX "S&P 500" 2330.TW [--json] [--live]

- 個股：即時抓 Yahoo 報價 + 分析師預估，列出 Forward PE（下一財年）、NTM PE、Trailing PE、EPS 預估與修正
- 指數：讀 data/valuation.json 的聚合 PE（或 --live 現場計算），並列出權重最大的成分股
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import setup_logging  # noqa: E402
from lookup import lookup  # noqa: E402
from yahoo import Yahoo  # noqa: E402


def fmt(x, nd=2, suffix=""):
    if x is None:
        return "—"
    try:
        return f"{float(x):,.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return str(x)


def print_symbol(res: dict) -> None:
    r = res["record"]
    mc = r.get("mc")
    mc_txt = f"{mc / 1e9:,.1f}B {r.get('cur', '')}" if mc else "—"
    print(f"\n{res['symbol']}  {r.get('n', '')}   {fmt(r.get('p'))} ({fmt(r.get('c'), 2, '%')})   市值 {mc_txt}   {r.get('x', '')}")
    print("-" * 78)
    print(f"  Forward PE（下一財年 FY{(r.get('fy1') or '')[:4]}）: {fmt(r.get('fpe'))}     NTM PE（混合 12 月）: {fmt(r.get('ntm'))}     Trailing PE: {fmt(r.get('tpe'))}")
    print(f"  EPS  TTM {fmt(r.get('te'))} | 本財年({r.get('fy') or '?'}) {fmt(r.get('e0'))} | 下一財年 {fmt(r.get('e1'))} | NTM {fmt(r.get('ne'))} (本財年權重 {fmt(r.get('w'), 2)})")
    print(f"  分析師 {r.get('na') or '—'} 位 | 下一財年 EPS 30 日修正 {fmt(r.get('rev30'), 1, '%')} / 90 日修正 {fmt(r.get('rev90'), 1, '%')} | PEG {fmt(r.get('peg'))} | 下次財報 {r.get('nx') or '—'}")
    print(f"  50 日均線 {fmt(r.get('ma50'))} | 200 日均線 {fmt(r.get('ma200'))} | 52 週 {fmt(r.get('l52'))}–{fmt(r.get('h52'))} | 所屬指數 {', '.join(r.get('ix') or []) or '—'}")
    hist = res.get("history") or []
    if hist:
        print(f"  歷史快照（共 {len(hist)} 日）:")
        for h in hist[-8:]:
            print(f"    {h['date']}  價 {fmt(h.get('price'))}  Fwd {fmt(h.get('fpe'))}  NTM {fmt(h.get('ntm'))}  Trailing {fmt(h.get('tpe'))}")


def print_index(res: dict) -> None:
    a = res["aggregate"]
    ix = res["index"]
    print(f"\n{ix['name']} ({ix['en']}, {ix['yahoo']})   收盤 {fmt(a.get('close'))}   {'[成分股近似]' if ix.get('approx') else ''}   資料 {res.get('asof') or ''} ({res.get('source')})")
    print("-" * 78)
    print(f"  Forward PE（下一財年）: {fmt(a.get('fpe'))}  (覆蓋 {a.get('fpe_n')} 檔, 市值 {fmt((a.get('fpe_cov') or 0) * 100, 0, '%')})")
    print(f"  NTM PE（混合 12 月）  : {fmt(a.get('ntm'))}  (覆蓋 {a.get('ntm_n')} 檔, 市值 {fmt((a.get('ntm_cov') or 0) * 100, 0, '%')})")
    print(f"  Trailing PE           : {fmt(a.get('tpe'))}   本財年 PE: {fmt(a.get('cpe'))}   成分股 Fwd PE 中位數: {fmt(a.get('median_fpe'))}   虧損比例: {fmt(a.get('neg_share'), 0, '%')}")
    print(f"  成分股 {a.get('members')} 檔（有報價 {a.get('priced')}）")
    print("  權重最大成分股：")
    for t in (a.get("top") or [])[:10]:
        print(f"    {t['s']:<8} {(t.get('n') or '')[:30]:<30} 權重 {fmt(t.get('w'), 1, '%'):>7}  Fwd {fmt(t.get('fpe')):>7}  NTM {fmt(t.get('ntm')):>7}  Trailing {fmt(t.get('tpe')):>7}")
    hist = res.get("history") or []
    if hist:
        print(f"  歷史快照（共 {len(hist)} 日）:")
        for h in hist[-8:]:
            print(f"    {h['date']}  收盤 {fmt(h.get('close'))}  Fwd {fmt(h.get('fpe'))}  NTM {fmt(h.get('ntm'))}  Trailing {fmt(h.get('tpe'))}")


def main() -> int:
    ap = argparse.ArgumentParser(description="查 forward PE（股票或指數）")
    ap.add_argument("names", nargs="+", help="代號 / 名稱 / 指數（NVDA, SOX, SPX, NASDAQ, 2330.TW ...）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--live", action="store_true", help="指數改為現場重算（較慢）")
    args = ap.parse_args()
    setup_logging("WARNING")
    y = Yahoo(workers=8)
    results = []
    for name in args.names:
        res = lookup(y, name, live_index=args.live)
        if not res:
            print(f"\n找不到：{name}", file=sys.stderr)
            continue
        results.append(res)
        if not args.json:
            if res["kind"] == "index":
                print_index(res)
            else:
                print_symbol(res)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
