"""查詢函式庫：輸入股票代號 / 公司名 / 指數名稱，回傳 forward PE 等估值資料（CLI 與本機伺服器共用）。"""
from __future__ import annotations

import csv
import glob
import logging

from common import DATA, HIST, read_csv_rows, read_json, today
from registry import ALIASES, INDEX_BY_KEY, INDEXES
from valuation import _rec, aggregate
from yahoo import Yahoo, to_yahoo_symbol

LOG = logging.getLogger("lookup")


def resolve(q: str) -> dict:
    """把使用者輸入轉成查詢目標。"""
    raw = q.strip()
    key = raw.upper()
    if key in ALIASES:
        target = ALIASES[key]
        if target in INDEX_BY_KEY:
            return {"kind": "index", "key": target, "query": raw}
        return {"kind": "symbol", "symbol": target, "query": raw}
    for ix in INDEXES:
        if key in (ix["name"].upper(), ix["en"].upper()):
            return {"kind": "index", "key": ix["key"], "query": raw}
    return {"kind": "symbol", "symbol": to_yahoo_symbol(raw), "query": raw, "unverified": True}


def ticker_history(symbol: str, limit: int = 400) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(str(HIST / "pe" / "*.csv"))):
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("symbol") == symbol:
                    rows.append({k: r.get(k) for k in ("date", "price", "fpe", "ntm", "tpe", "fe", "ne")})
    return rows[-limit:]


def index_history(key: str, limit: int = 400) -> list[dict]:
    rows = [r for r in read_csv_rows(HIST / "index_pe.csv") if r.get("index") == key]
    return rows[-limit:]


def lookup_symbol(y: Yahoo, symbol: str, with_chart: bool = True) -> dict | None:
    quotes = y.quotes([symbol])
    q = quotes.get(symbol)
    if not q:
        # 也許是名稱：用搜尋找代號
        hits = [h for h in y.search(symbol) if h.get("type") in ("EQUITY", "ETF", "INDEX")]
        if not hits:
            return None
        symbol = hits[0]["symbol"]
        q = y.quotes([symbol]).get(symbol)
        if not q:
            return None
    est = y.estimates(symbol) if q.get("quoteType") == "EQUITY" else None
    val = read_json(DATA / "valuation.json", {}) or {}
    cached = (val.get("tickers") or {}).get(symbol) or {}
    rec = _rec(symbol, q, est, today(), cached.get("ix", []), cached.get("sec"), None)
    out = {"kind": "symbol", "symbol": symbol, "record": rec, "estimates": est, "history": ticker_history(symbol), "asof": today().isoformat()}
    if with_chart:
        ch = y.chart(symbol, "1y")
        if ch:
            out["chart"] = {"dates": ch["dates"], "close": ch["close"]}
    return out


def lookup_index(y: Yahoo, key: str, live: bool = False) -> dict | None:
    ix = INDEX_BY_KEY.get(key)
    if not ix:
        return None
    val = read_json(DATA / "valuation.json", {}) or {}
    agg = (val.get("indexes") or {}).get(key)
    source = "cache"
    if agg is None or live:
        # 現場計算：抓成分股 → 報價 → 預估
        from constituents import load_constituents
        sets, _ = load_constituents([ix["source"]])
        rows = sets.get(ix["source"]) or []
        syms = [r["symbol"] for r in rows]
        if not syms:
            return None
        quotes = y.quotes(syms)
        ests = y.estimates_many(syms, workers=8)
        recs = {s: _rec(s, q, ests.get(s), today(), [key], None, None) for s, q in quotes.items()}
        agg = aggregate(recs, syms)
        ch = y.chart(ix["yahoo"], "5d")
        agg.update({"name": ix["name"], "en": ix["en"], "symbol": ix["yahoo"], "approx": ix["approx"], "close": (ch or {}).get("close", [None])[-1]})
        source = "live"
    out = {"kind": "index", "key": key, "index": ix, "aggregate": agg, "history": index_history(key), "source": source, "asof": val.get("asof")}
    ch = y.chart(ix["yahoo"], "1y")
    if ch:
        out["chart"] = {"dates": ch["dates"], "close": ch["close"]}
    return out


def lookup(y: Yahoo, q: str, live_index: bool = False) -> dict | None:
    r = resolve(q)
    if r["kind"] == "index":
        return lookup_index(y, r["key"], live=live_index)
    return lookup_symbol(y, r["symbol"])
