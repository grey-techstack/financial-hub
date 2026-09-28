"""估值：個股 forward PE、NTM（未來 12 個月混合）PE、指數層級聚合 PE，並每日累積歷史。

指數 PE 的算法：Σ 成分股市值 / Σ 成分股（EPS × 流通股數），即「總市值 / 總盈餘」（市值加權，含虧損公司的負盈餘）。
NTM EPS = w × 本財年 EPS 預估 + (1 − w) × 下一財年 EPS 預估，w = 本財年剩餘月數 / 12（接近 Bloomberg 的 BEst 混合 12 個月）。
"""
from __future__ import annotations

import datetime as dt
import logging
import statistics

from common import HIST, fnum, upsert_csv
from registry import INDEXES, INDEX_BY_KEY, PE_INDEXES

LOG = logging.getLogger("valuation")
MIN_COVERAGE = 0.5  # 指數聚合 PE 所需的最低市值覆蓋率


def ntm_blend(est: dict, asof: dt.date) -> tuple[float | None, float | None]:
    e0, e1, end0 = est.get("eps_0y"), est.get("eps_p1y"), est.get("end_0y")
    if e0 is None and e1 is None:
        return None, None
    if e1 is None:
        return e0, 1.0
    if e0 is None or not end0:
        return e1, 0.0
    try:
        d_end = dt.date.fromisoformat(str(end0)[:10])
    except ValueError:
        return e1, 0.0
    w = max(0.0, min(1.0, ((d_end - asof).days / 30.4375) / 12.0))
    return w * e0 + (1 - w) * e1, w


def suspect(eps, price, ttm) -> bool:
    """資料異常防呆：正 EPS 卻使 PE < 3，或預估 EPS 為 TTM 的 5 倍以上（如 Yahoo 偶發的小數點錯位），視為可疑、不納入指數聚合。"""
    if eps is None or not price:
        return False
    if eps > 0 and price / eps < 3:
        return True
    if ttm and ttm > 0 and eps / ttm > 5:
        return True
    return False


def _rec(sym: str, q: dict, est: dict | None, asof: dt.date, membership: list[str], sector: str | None, fallback_name: str | None) -> dict:
    p = q.get("regularMarketPrice")
    rec = {
        "n": q.get("longName") or q.get("shortName") or fallback_name or sym,
        "x": q.get("exchange"), "t": q.get("quoteType"), "cur": q.get("currency"),
        "p": fnum(p, 2), "c": fnum(q.get("regularMarketChangePercent"), 2),
        "mc": int(q["marketCap"]) if q.get("marketCap") else None,
        "sh": int(q["sharesOutstanding"]) if q.get("sharesOutstanding") else None,
        "fpe": fnum(q.get("forwardPE"), 2), "tpe": fnum(q.get("trailingPE"), 2),
        "fe": fnum(q.get("epsForward"), 3), "ce": fnum(q.get("epsCurrentYear"), 3), "te": fnum(q.get("epsTrailingTwelveMonths"), 3),
        "ma50": fnum(q.get("fiftyDayAverage"), 2), "ma200": fnum(q.get("twoHundredDayAverage"), 2),
        "h52": fnum(q.get("fiftyTwoWeekHigh"), 2), "l52": fnum(q.get("fiftyTwoWeekLow"), 2),
        "pb": fnum(q.get("priceToBook"), 2), "dy": fnum(q.get("dividendYield"), 2),
        "sec": sector, "ix": membership,
    }
    if est:
        ne, w = ntm_blend(est, asof)
        rec.update({
            "e0": fnum(est.get("eps_0y"), 3), "e1": fnum(est.get("eps_p1y"), 3),
            "fy": (str(est.get("end_0y"))[:10] if est.get("end_0y") else None),
            "fy1": (str(est.get("end_p1y"))[:10] if est.get("end_p1y") else None),
            "ne": fnum(ne, 3), "w": fnum(w, 3),
            "ntm": fnum(p / ne, 2) if (p and ne and ne > 0) else None,
            "na": est.get("n_p1y") or est.get("n_0y"),
            "nx": est.get("next_earnings"), "peg": fnum(est.get("peg"), 2),
            "eq0": fnum(est.get("eps_0q"), 3), "eq1": fnum(est.get("eps_p1q"), 3),
        })
        r90 = est.get("eps_p1y_90d")
        if r90 and est.get("eps_p1y") and r90 != 0:
            rec["rev90"] = fnum((est["eps_p1y"] / r90 - 1) * 100, 1)  # 下一財年 EPS 預估 90 日修正幅度 (%)
        r30 = est.get("eps_p1y_30d")
        if r30 and est.get("eps_p1y") and r30 != 0:
            rec["rev30"] = fnum((est["eps_p1y"] / r30 - 1) * 100, 1)
    if suspect(rec.get("fe"), p, rec.get("te")) or suspect(rec.get("ne"), p, rec.get("te")):
        rec["sus"] = 1
    return {k: v for k, v in rec.items() if v is not None and v != []}


def aggregate(records: dict[str, dict], syms: list[str]) -> dict:
    pairs = [(s, records[s]) for s in dict.fromkeys(syms) if s in records]
    mem = [r for _, r in pairs]
    with_mc = [r for r in mem if r.get("mc")]
    sym_of = {id(r): s for s, r in pairs}
    total_mc = float(sum(r["mc"] for r in with_mc))

    def agg(eps_key: str) -> tuple[float | None, int, float | None]:
        """Σ市值 / Σ盈餘。盈餘 = EPS × (市值 / 股價)，即隱含股數，確保市值與盈餘口徑一致（Yahoo 的 sharesOutstanding
        在多股別公司如 GOOGL/GOOG、BRK 會與市值不一致）。可疑 EPS（見 suspect）整檔排除。"""
        num = 0.0
        den = 0.0
        n = 0
        for r in with_mc:
            eps = r.get(eps_key)
            p = r.get("p")
            if eps is None or not p:
                continue
            if eps_key != "te" and suspect(eps, p, r.get("te")):
                continue
            num += r["mc"]
            den += eps * (r["mc"] / p)
            n += 1
        pe = (num / den) if den > 0 else None
        cov = (num / total_mc) if total_mc else None
        return pe, n, cov

    fpe, fpe_n, fpe_cov = agg("fe")
    ntm, ntm_n, ntm_cov = agg("ne")
    tpe, tpe_n, tpe_cov = agg("te")
    cpe, cpe_n, cpe_cov = agg("ce")
    # 市值覆蓋率低於 50% 的聚合值沒有代表性（例如只有少數成分股有分析師預估），不輸出
    fpe = fpe if (fpe_cov or 0) >= MIN_COVERAGE else None
    ntm = ntm if (ntm_cov or 0) >= MIN_COVERAGE else None
    tpe = tpe if (tpe_cov or 0) >= MIN_COVERAGE else None
    cpe = cpe if (cpe_cov or 0) >= MIN_COVERAGE else None
    pos = [r["fpe"] for r in mem if r.get("fpe") and 0 < r["fpe"] < 500]
    ntm_pos = [r["ntm"] for r in mem if r.get("ntm") and 0 < r["ntm"] < 500]
    top = sorted(with_mc, key=lambda r: -r["mc"])[:15]
    return {
        "members": len(syms), "priced": len(mem), "mc_total": int(total_mc),
        "fpe": fnum(fpe, 2), "fpe_n": fpe_n, "fpe_cov": fnum(fpe_cov, 3),
        "ntm": fnum(ntm, 2), "ntm_n": ntm_n, "ntm_cov": fnum(ntm_cov, 3),
        "tpe": fnum(tpe, 2), "tpe_n": tpe_n, "tpe_cov": fnum(tpe_cov, 3),
        "cpe": fnum(cpe, 2), "cpe_cov": fnum(cpe_cov, 3),
        "median_fpe": fnum(statistics.median(pos), 2) if pos else None,
        "median_ntm": fnum(statistics.median(ntm_pos), 2) if ntm_pos else None,
        "neg_share": fnum(sum(1 for r in mem if r.get("fe") is not None and r["fe"] <= 0) / len(mem) * 100, 1) if mem else None,
        "top": [{"s": sym_of[id(r)], "n": r.get("n"), "w": fnum(r["mc"] / total_mc * 100, 2) if total_mc else None,
                 "fpe": r.get("fpe"), "ntm": r.get("ntm"), "tpe": r.get("tpe"), "c": r.get("c")} for r in top],
    }


def build_valuation(quotes: dict[str, dict], estimates: dict[str, dict], members: dict[str, list[str]],
                    sets: dict[str, list[dict]], watchlist: list[str], asof: dt.date, index_closes: dict[str, float]) -> dict:
    membership: dict[str, list[str]] = {}
    for key, syms in members.items():
        for s in syms:
            membership.setdefault(s, []).append(key)
    sector: dict[str, str] = {}
    names: dict[str, str] = {}
    for rows in sets.values():
        for r in rows:
            if r.get("sector") and r["symbol"] not in sector:
                sector[r["symbol"]] = r["sector"]
            names.setdefault(r["symbol"], r.get("name"))
    records: dict[str, dict] = {}
    for sym, q in quotes.items():
        records[sym] = _rec(sym, q, estimates.get(sym), asof, membership.get(sym, []), sector.get(sym), names.get(sym))
    indexes: dict[str, dict] = {}
    for key in PE_INDEXES:
        if key not in members:
            continue
        agg = aggregate(records, members[key])
        ix = INDEX_BY_KEY[key]
        agg.update({"name": ix["name"], "en": ix["en"], "symbol": ix["yahoo"], "approx": ix["approx"], "close": index_closes.get(key), "etf": ix.get("etf")})
        indexes[key] = agg
        LOG.info("%s: fwd PE %s (cov %.0f%%), NTM %s, trailing %s, members %d", key, agg["fpe"], (agg["fpe_cov"] or 0) * 100, agg["ntm"], agg["tpe"], agg["members"])
    etf = {}
    for ix in INDEXES:
        e = ix.get("etf")
        if e and e in records:
            etf[e] = {"index": ix["key"], "p": records[e].get("p"), "tpe": records[e].get("tpe"), "n": records[e].get("n")}
    return {"asof": asof.isoformat(), "tickers": records, "indexes": indexes, "etf": etf, "watchlist": watchlist}


def split_outputs(val: dict, keep: list[str]) -> tuple[dict, dict]:
    """valuation.json 只保留完整欄位的核心名單（PE 範圍 ∪ watchlist ∪ ETF）；其餘代號輸出精簡版供搜尋。

    精簡格式：{sym: [name, exch, price, chg%, mktcap, fwdPE, trailPE, ma50, ma200, [index keys]]}
    """
    keep_set = set(keep)
    core = {s: r for s, r in val["tickers"].items() if s in keep_set}
    compact = {}
    for s, r in val["tickers"].items():
        compact[s] = [r.get("n"), r.get("x"), r.get("p"), r.get("c"), r.get("mc"), r.get("fpe"), r.get("tpe"), r.get("ma50"), r.get("ma200"), r.get("ix") or []]
    main = dict(val)
    main["tickers"] = core
    return main, {"asof": val["asof"], "fields": ["name", "exch", "price", "chg", "mc", "fpe", "tpe", "ma50", "ma200", "ix"], "tickers": compact}


def append_history(val: dict, asof: dt.date, pe_universe: list[str]) -> None:
    d = asof.isoformat()
    rows = []
    for key, agg in val["indexes"].items():
        rows.append({"date": d, "index": key, "close": agg.get("close"), "fpe": agg.get("fpe"), "ntm": agg.get("ntm"), "tpe": agg.get("tpe"),
                     "cpe": agg.get("cpe"), "median_fpe": agg.get("median_fpe"), "fpe_cov": agg.get("fpe_cov"), "ntm_cov": agg.get("ntm_cov"), "members": agg.get("members")})
    upsert_csv(HIST / "index_pe.csv", rows, ("date", "index"),
               ["date", "index", "close", "fpe", "ntm", "tpe", "cpe", "median_fpe", "fpe_cov", "ntm_cov", "members"])
    trows = []
    for s in dict.fromkeys(pe_universe):
        r = val["tickers"].get(s)
        if not r:
            continue
        trows.append({"date": d, "symbol": s, "price": r.get("p"), "fpe": r.get("fpe"), "ntm": r.get("ntm"), "tpe": r.get("tpe"),
                      "fe": r.get("fe"), "ne": r.get("ne"), "e0": r.get("e0"), "e1": r.get("e1"), "mc": r.get("mc")})
    upsert_csv(HIST / "pe" / f"{asof.year}.csv", trows, ("date", "symbol"),
               ["date", "symbol", "price", "fpe", "ntm", "tpe", "fe", "ne", "e0", "e1", "mc"])
    LOG.info("history: %d index rows, %d ticker rows appended for %s", len(rows), len(trows), d)
