"""每日市場日報（規則式）：把 breadth / valuation / macro 轉成訊號、表格與中文解讀。

輸出：
- reports/YYYY-MM-DD.md 與 reports/latest.md（Markdown）
- data/latest.json（儀表板首頁與訊號卡片用的摘要）
"""
from __future__ import annotations

import logging
import math

from common import fnum
from registry import INDEXES, MA_WINDOWS

LOG = logging.getLogger("report")
LEVEL_ICON = {"alert": "🔴", "watch": "🟠", "info": "🔵", "good": "🟢"}


# ----------------------------------------------------------------- 小工具
def _last(vals, k=0):
    return vals[-1 - k] if vals and len(vals) > k else None


def _chg(vals, k):
    a, b = _last(vals), _last(vals, k)
    return (a - b) if a is not None and b is not None else None


def _pct(vals, k):
    a, b = _last(vals), _last(vals, k)
    return (a / b - 1) * 100 if a is not None and b not in (None, 0) else None


def _rank(vals, n=252):
    if not vals:
        return None
    win = [v for v in vals[-n:] if v is not None]
    if len(win) < 20:
        return None
    x = win[-1]
    return sum(1 for v in win if v <= x) / len(win) * 100


def f(x, nd=1, suffix="", dash="—"):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return dash
    return f"{x:,.{nd}f}{suffix}"


def s(x, nd=1, suffix="", dash="—"):
    """帶正負號。"""
    if x is None:
        return dash
    return f"{'+' if x >= 0 else '−'}{abs(x):,.{nd}f}{suffix}"


def pe(x, nd=1):
    """本益比：負值或 >500 視為無意義（n/m）。"""
    if x is None:
        return "—"
    if x <= 0 or x > 500:
        return "n/m"
    return f"{x:,.{nd}f}"


def zone(p):
    """參與度分區 -> (標籤, 等級)。"""
    if p is None:
        return ("—", "info")
    if p < 20:
        return ("極度超賣", "alert")
    if p < 30:
        return ("超賣區", "alert")
    if p < 40:
        return ("接近超賣", "watch")
    if p > 80:
        return ("極度超買", "alert")
    if p > 70:
        return ("超買區", "alert")
    if p > 60:
        return ("接近超買", "watch")
    return ("中性", "info")


def _series(macro, key):
    x = (macro.get("series") or {}).get(key) or {}
    return list(x.get("dates") or []), list(x.get("values") or [])


def _aligned_diffs(d1, v1, d2, v2, n=60):
    m1 = dict(zip(d1, v1))
    m2 = dict(zip(d2, v2))
    common = sorted(set(m1) & set(m2))[-(n + 1):]
    if len(common) < 20:
        return [], []
    a = [m1[d] for d in common]
    b = [m2[d] for d in common]
    da = [(a[i] / a[i - 1] - 1) * 100 for i in range(1, len(a))]   # 黃金 %
    db = [(b[i] - b[i - 1]) * 100 for i in range(1, len(b))]        # 殖利率 bp
    return da, db


def _corr(x, y):
    n = len(x)
    if n < 10 or n != len(y):
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


# ----------------------------------------------------------------- 各區塊
def index_table(macro, breadth, valuation, asof):
    rows = []
    for ix in INDEXES:
        key = ix["key"]
        m = (macro.get("indexes") or {}).get(key) or {}
        dates, close = list(m.get("dates") or []), list(m.get("close") or [])
        if not close:
            continue
        year = asof[:4]
        ytd_base = next((c for d, c in zip(dates, close) if d >= f"{year}-01-01"), None)
        # 今年第一個交易日的前一日收盤才是基準
        prev_year_close = None
        for d, c in zip(dates, close):
            if d < f"{year}-01-01":
                prev_year_close = c
        base = prev_year_close or ytd_base
        hi52 = max(close[-252:]) if close else None
        ma50 = sum(close[-50:]) / 50 if len(close) >= 50 else None
        ma200 = sum(close[-200:]) / 200 if len(close) >= 200 else None
        b = (breadth.get("indexes") or {}).get(key) or {}
        v = (valuation.get("indexes") or {}).get(key) or {}
        rows.append({
            "key": key, "name": ix["name"], "en": ix["en"], "approx": ix["approx"], "close": _last(close),
            "d1": _pct(close, 1), "d5": _pct(close, 5), "d21": _pct(close, 21),
            "ytd": (close[-1] / base - 1) * 100 if base else None,
            "from_high": (close[-1] / hi52 - 1) * 100 if hi52 else None,
            "above50": (close[-1] > ma50) if ma50 else None, "above200": (close[-1] > ma200) if ma200 else None,
            "b20": (b.get("latest") or {}).get("20"), "b50": (b.get("latest") or {}).get("50"), "b200": (b.get("latest") or {}).get("200"),
            "b20_w": ((b.get("latest") or {}).get("20") - (b.get("week") or {}).get("20")) if (b.get("latest") or {}).get("20") is not None and (b.get("week") or {}).get("20") is not None else None,
            "members": b.get("members"), "priced": b.get("priced"),
            "fpe": v.get("fpe"), "ntm": v.get("ntm"), "tpe": v.get("tpe"),
        })
    return rows


def breadth_signals(rows, breadth):
    sig = []
    majors = [r for r in rows if r["key"] in ("DJI", "SPX", "COMP")]
    vals = [r["b20"] for r in majors if r["b20"] is not None]
    if len(vals) == 3:
        names = "／".join(r["name"] for r in majors)
        pct_txt = " / ".join(f"{r['b20']:.0f}%" for r in majors)
        if max(vals) < 30:
            sig.append({"level": "alert", "topic": "breadth", "short": "三大指數參與度已進入超賣區",
                        "text": f"三大指數（{names}）成分股站上 20 日線的比例僅 {pct_txt}，已進入超賣區間（<30%），短線賣壓極端，歷史上常出現反彈但趨勢未必轉強。"})
        elif max(vals) < 40:
            sig.append({"level": "watch", "topic": "breadth", "short": "三大指數均已接近超賣的區間",
                        "text": f"三大指數（{names}）成分股站上 20 日線的比例為 {pct_txt}，均已接近超賣的區間（<40%）。"})
        elif min(vals) > 70:
            sig.append({"level": "alert", "topic": "breadth", "short": "三大指數參與度進入超買區",
                        "text": f"三大指數（{names}）成分股站上 20 日線的比例達 {pct_txt}，已進入超買區間（>70%），短線追價風險升高。"})
        elif min(vals) > 60:
            sig.append({"level": "watch", "topic": "breadth", "short": "三大指數參與度接近超買",
                        "text": f"三大指數（{names}）成分股站上 20 日線的比例為 {pct_txt}，接近超買區間（>60%）。"})
    for r in rows:
        if r["key"] in ("DJI", "SPX", "COMP"):
            continue
        z, lvl = zone(r["b20"])
        if lvl == "alert":
            sig.append({"level": "alert", "topic": "breadth", "short": f"{r['name']} 20 日線參與度 {r['b20']:.0f}%（{z}）",
                        "text": f"{r['name']} 成分股站上 20 日線比例 {r['b20']:.0f}%，屬{z}。"})
    for r in rows:
        if r["b20_w"] is not None and abs(r["b20_w"]) >= 15 and r["key"] in ("SPX", "NDX", "RUT", "SOX"):
            direction = "惡化" if r["b20_w"] < 0 else "改善"
            sig.append({"level": "watch" if r["b20_w"] < 0 else "info", "topic": "breadth",
                        "short": f"{r['name']} 參與度 5 日{direction} {s(r['b20_w'], 0, ' pt')}",
                        "text": f"{r['name']} 站上 20 日線的比例 5 個交易日內{direction} {s(r['b20_w'], 0)} 個百分點（{f(r['b20'] - r['b20_w'], 0)}% → {f(r['b20'], 0)}%）。"})
    spx = next((r for r in rows if r["key"] == "SPX"), None)
    if spx and spx["b200"] is not None:
        if spx["b200"] < 40:
            sig.append({"level": "watch", "topic": "breadth", "short": f"S&P 500 僅 {spx['b200']:.0f}% 成分股在 200 日線上",
                        "text": f"S&P 500 只有 {spx['b200']:.0f}% 的成分股站在 200 日線之上，中長期趨勢轉弱，反彈宜視為逃命波而非新多頭，除非此比例回到 50% 以上。"})
        elif spx["b200"] > 75:
            sig.append({"level": "good", "topic": "breadth", "short": f"S&P 500 有 {spx['b200']:.0f}% 成分股在 200 日線上",
                        "text": f"S&P 500 有 {spx['b200']:.0f}% 的成分股站在 200 日線之上，中長期趨勢健康，短線超賣多屬多頭中的拉回。"})
    return sig


def macro_block(macro):
    out = {}
    for key in ("DFII10", "DGS10", "T10YIE", "DGS2", "GOLD", "MOVE", "VIX", "TNX", "DXY"):
        d, v = _series(macro, key)
        if not v:
            continue
        is_rate = key in ("DFII10", "DGS10", "T10YIE", "DGS2", "TNX")
        out[key] = {
            "date": _last(d), "v": _last(v),
            "d1": (_chg(v, 1) * 100 if is_rate else _pct(v, 1)) if len(v) > 1 else None,
            "d5": (_chg(v, 5) * 100 if is_rate else _pct(v, 5)) if len(v) > 5 else None,
            "d21": (_chg(v, 21) * 100 if is_rate else _pct(v, 21)) if len(v) > 21 else None,
            "rank1y": _rank(v), "hi1y": max(x for x in v[-252:] if x is not None), "lo1y": min(x for x in v[-252:] if x is not None),
            "unit": "bp" if is_rate else "%",
        }
    gd, gv = _series(macro, "GOLD")
    rd, rv = _series(macro, "DFII10")
    da, db = _aligned_diffs(gd, gv, rd, rv, 60)
    out["corr_gold_real_60d"] = _corr(da, db)
    return out


def macro_signals(mb):
    sig = []
    r = mb.get("DFII10")
    g = mb.get("GOLD")
    if r:
        if r["d5"] is not None and abs(r["d5"]) >= 15:
            up = r["d5"] > 0
            gold_txt = f"，黃金同期 {s(g['d5'], 1, '%')}" if g and g.get("d5") is not None else ""
            sig.append({"level": "watch", "topic": "rates",
                        "short": f"10 年期實質利率 5 日{'急升' if up else '大幅回落'} {s(r['d5'], 0, ' bp')}",
                        "text": f"美國 10 年期實質利率（TIPS）5 個交易日{'上升' if up else '下降'} {s(r['d5'], 0, ' bp')} 至 {f(r['v'], 2, '%')}{gold_txt}。實質利率是黃金最主要的定價變數：{'實質利率上升壓抑黃金（持有黃金的機會成本上升）' if up else '實質利率回落有利黃金'}。"})
        if r["rank1y"] is not None and r["rank1y"] >= 95:
            sig.append({"level": "watch", "topic": "rates", "short": f"實質利率 {f(r['v'], 2, '%')} 處於一年高檔",
                        "text": f"10 年期實質利率 {f(r['v'], 2, '%')} 位於過去一年第 {r['rank1y']:.0f} 百分位（一年高點 {f(r['hi1y'], 2, '%')}），對黃金與高估值成長股構成壓力。"})
        elif r["rank1y"] is not None and r["rank1y"] <= 5:
            sig.append({"level": "info", "topic": "rates", "short": f"實質利率 {f(r['v'], 2, '%')} 處於一年低檔",
                        "text": f"10 年期實質利率 {f(r['v'], 2, '%')} 位於過去一年第 {r['rank1y']:.0f} 百分位（一年低點 {f(r['lo1y'], 2, '%')}），金融環境偏鬆，有利黃金與長天期資產。"})
    n, be = mb.get("DGS10"), mb.get("T10YIE")
    if r and n and be and None not in (r.get("d5"), n.get("d5"), be.get("d5")) and abs(n["d5"]) >= 10:
        driver = "實質利率" if abs(r["d5"]) >= abs(be["d5"]) else "通膨預期"
        sig.append({"level": "info", "topic": "rates", "short": f"10 年期名目利率 5 日 {s(n['d5'], 0, ' bp')}，主要來自{driver}",
                    "text": f"10 年期公債殖利率 5 日 {s(n['d5'], 0, ' bp')}，拆解為實質利率 {s(r['d5'], 0, ' bp')} ＋ 通膨預期 {s(be['d5'], 0, ' bp')}，主要由{driver}驅動。{'實質利率驅動的升息對風險資產與黃金都是逆風' if driver == '實質利率' and n['d5'] > 0 else ''}"})
    if g:
        if g["d5"] is not None and abs(g["d5"]) >= 4:
            sig.append({"level": "watch", "topic": "gold", "short": f"黃金 5 日 {s(g['d5'], 1, '%')}",
                        "text": f"黃金 5 個交易日 {s(g['d5'], 1, '%')} 至 {f(g['v'], 0)} 美元/盎司" + (f"，同期實質利率 {s(r['d5'], 0, ' bp')}" if r and r.get('d5') is not None else "") + "。"})
        if g["rank1y"] is not None and g["rank1y"] >= 99 and g["v"] >= g["hi1y"]:
            sig.append({"level": "info", "topic": "gold", "short": "黃金創一年新高", "text": f"黃金 {f(g['v'], 0)} 美元創過去一年新高。"})
    c = mb.get("corr_gold_real_60d")
    if c is not None:
        if c > -0.1:
            sig.append({"level": "info", "topic": "gold", "short": f"黃金與實質利率近 60 日相關 {c:+.2f}，負相關鬆動",
                        "text": f"黃金與 10 年期實質利率近 60 個交易日的日變動相關係數為 {c:+.2f}，傳統的負相關暫時鬆動，代表有其他因素（央行買盤、避險需求、美元）主導金價。"})
    return sig


def vol_signals(mb):
    sig = []
    v = mb.get("VIX")
    m = mb.get("MOVE")
    if v:
        lvl = "alert" if v["v"] >= 30 else "watch" if v["v"] >= 22 else "info"
        state = "恐慌" if v["v"] >= 30 else "偏高" if v["v"] >= 22 else "正常" if v["v"] >= 15 else "低檔"
        if lvl != "info" or (v["d1"] is not None and abs(v["d1"]) >= 15):
            sig.append({"level": lvl, "topic": "vol", "short": f"VIX {f(v['v'], 1)}（{state}），1 日 {s(v['d1'], 0, '%')}",
                        "text": f"VIX {f(v['v'], 1)} 屬{state}水位（一年百分位 {f(v['rank1y'], 0)}），1 日 {s(v['d1'], 0, '%')}、5 日 {s(v['d5'], 0, '%')}。"})
    if m:
        if m["v"] >= 120 or (m["rank1y"] is not None and m["rank1y"] >= 85 and m["v"] >= 100):
            sig.append({"level": "watch", "topic": "vol", "short": f"MOVE {f(m['v'], 0)}，債市波動偏高",
                        "text": f"MOVE 指數 {f(m['v'], 0)}（一年百分位 {f(m['rank1y'], 0)}），美債波動率偏高；債市波動通常先於股市波動，也會透過實質利率影響黃金。"})
        elif m["rank1y"] is not None and m["rank1y"] >= 85:
            sig.append({"level": "info", "topic": "vol", "short": f"MOVE {f(m['v'], 0)}，處於一年區間高檔但絕對水位溫和",
                        "text": f"MOVE 指數 {f(m['v'], 0)} 位於一年第 {f(m['rank1y'], 0)} 百分位，相對過去一年偏高，但絕對水位仍屬溫和（壓力區通常 >120）。"})
        elif m["rank1y"] is not None and m["rank1y"] <= 10:
            sig.append({"level": "info", "topic": "vol", "short": f"MOVE {f(m['v'], 0)}，債市波動處於一年低檔",
                        "text": f"MOVE 指數 {f(m['v'], 0)}（一年百分位 {f(m['rank1y'], 0)}），債市極為平靜，市場對利率路徑有高度共識。"})
    return sig


def pe_stats(valuation, hist_rows):
    """指數 PE 的歷史統計（來自 data/history/index_pe.csv，隨每日累積變長）。"""
    out = {}
    by_key: dict[str, list[tuple[str, float, float | None]]] = {}
    for r in hist_rows:
        try:
            fpe = float(r["fpe"]) if r.get("fpe") else None
            ntm = float(r["ntm"]) if r.get("ntm") else None
        except ValueError:
            continue
        if fpe is None:
            continue
        by_key.setdefault(r["index"], []).append((r["date"], fpe, ntm))
    for key, agg in (valuation.get("indexes") or {}).items():
        rows = sorted(by_key.get(key, []))
        vals = [x[1] for x in rows]
        st = {"n": len(rows), "since": rows[0][0] if rows else None}
        if len(rows) >= 20 and agg.get("fpe") is not None:
            st["rank"] = sum(1 for v in vals if v <= agg["fpe"]) / len(vals) * 100
            mn = min(rows, key=lambda x: x[1])
            mx = max(rows, key=lambda x: x[1])
            st["min"], st["min_date"], st["max"], st["max_date"] = mn[1], mn[0], mx[1], mx[0]
            if len(vals) > 21:
                st["d21"] = (agg["fpe"] / vals[-22] - 1) * 100
        out[key] = st
    return out


def pe_signals(valuation, pstats):
    sig = []
    ix = valuation.get("indexes") or {}
    sox, ndx, spx = ix.get("SOX"), ix.get("NDX"), ix.get("SPX")
    if sox and ndx and spx and sox.get("ntm") and ndx.get("ntm") and spx.get("ntm"):
        sig.append({"level": "info", "topic": "valuation",
                    "short": f"NTM PE：SOX {f(sox['ntm'])}x / NDX {f(ndx['ntm'])}x / S&P 500 {f(spx['ntm'])}x",
                    "text": f"未來 12 個月混合 PE：費城半導體 {f(sox['ntm'])} 倍、NASDAQ 100 {f(ndx['ntm'])} 倍、S&P 500 {f(spx['ntm'])} 倍；"
                            f"半導體相對 S&P 500 的估值比為 {f(sox['ntm'] / spx['ntm'], 2)}（>1 溢價，<1 折價）。"})
    for key in ("SOX", "NDX", "SPX"):
        a, st = ix.get(key), pstats.get(key) or {}
        if not a or not a.get("fpe"):
            continue
        if st.get("rank") is not None:
            if st["rank"] <= 10:
                sig.append({"level": "watch", "topic": "valuation", "short": f"{a['name']} forward PE {f(a['fpe'])}x 接近累積歷史低點",
                            "text": f"{a['name']} forward PE {f(a['fpe'])} 倍，位於自 {st['since']} 累積以來第 {st['rank']:.0f} 百分位（最低 {f(st['min'])} 倍於 {st['min_date']}）。估值已接近區間低檔，若盈餘預估未下修，回檔空間有限。"})
            elif st["rank"] >= 90:
                sig.append({"level": "watch", "topic": "valuation", "short": f"{a['name']} forward PE {f(a['fpe'])}x 接近累積歷史高點",
                            "text": f"{a['name']} forward PE {f(a['fpe'])} 倍，位於自 {st['since']} 累積以來第 {st['rank']:.0f} 百分位（最高 {f(st['max'])} 倍於 {st['max_date']}），估值偏貴，對利率與盈餘下修更敏感。"})
        if st.get("d21") is not None and abs(st["d21"]) >= 8:
            sig.append({"level": "info", "topic": "valuation", "short": f"{a['name']} forward PE 一個月{'壓縮' if st['d21'] < 0 else '擴張'} {s(st['d21'], 0, '%')}",
                        "text": f"{a['name']} forward PE 過去 21 個交易日{'壓縮' if st['d21'] < 0 else '擴張'} {s(st['d21'], 0, '%')}。"})
    # 追蹤清單的 EPS 修正
    tk = valuation.get("tickers") or {}
    revs = [(sym, tk[sym]) for sym in (valuation.get("watchlist") or []) if sym in tk and tk[sym].get("rev90") is not None]
    big = [(sym, r) for sym, r in revs if abs(r["rev90"]) >= 10]
    for sym, r in big[:4]:
        sig.append({"level": "info", "topic": "valuation", "short": f"{sym} 下一財年 EPS 預估 90 日{'上修' if r['rev90'] > 0 else '下修'} {s(r['rev90'], 0, '%')}",
                    "text": f"{sym}（{r.get('n')}）下一財年 EPS 共識 90 日內{'上修' if r['rev90'] > 0 else '下修'} {s(r['rev90'], 0, '%')}，forward PE {pe(r.get('fpe'))} 倍 / NTM {pe(r.get('ntm'))} 倍。"})
    return sig


# ----------------------------------------------------------------- 主函式
def build_report(breadth: dict, valuation: dict, macro: dict, hist_rows: list[dict], asof: str, status: dict) -> tuple[str, dict]:
    rows = index_table(macro, breadth, valuation, asof)
    mb = macro_block(macro)
    pst = pe_stats(valuation, hist_rows)
    signals = breadth_signals(rows, breadth) + macro_signals(mb) + vol_signals(mb) + pe_signals(valuation, pst)
    order = {"alert": 0, "watch": 1, "good": 2, "info": 3}
    signals.sort(key=lambda x: order.get(x["level"], 9))
    summary = "；".join(x["short"] for x in signals[:3]) + "。" if signals else "今日無特別訊號。"

    L = []
    L.append(f"# 市場日報 {asof}")
    L.append("")
    L.append(f"> {summary}")
    L.append("")
    L.append("## 重點訊號")
    L.append("")
    for x in signals:
        L.append(f"- {LEVEL_ICON.get(x['level'], '•')} **{x['short']}** — {x['text']}")
    if not signals:
        L.append("- 今日各項指標均在中性區間。")
    L.append("")
    L.append("## 指數表現")
    L.append("")
    L.append("| 指數 | 收盤 | 1 日 | 5 日 | 1 月 | 今年以來 | 距 52 週高 | 50 日線 | 200 日線 | 站上 20D | 站上 50D | 站上 200D | Fwd PE |")
    L.append("|---|---:|---:|---:|---:|---:|---:|:-:|:-:|---:|---:|---:|---:|")
    for r in rows:
        nm = r["name"] + ("*" if r["approx"] else "")
        L.append(f"| {nm} | {f(r['close'], 2)} | {s(r['d1'], 2, '%')} | {s(r['d5'], 2, '%')} | {s(r['d21'], 2, '%')} | {s(r['ytd'], 1, '%')} | {s(r['from_high'], 1, '%')} | "
                 f"{'上' if r['above50'] else '下' if r['above50'] is not None else '—'} | {'上' if r['above200'] else '下' if r['above200'] is not None else '—'} | "
                 f"{f(r['b20'], 0, '%')} | {f(r['b50'], 0, '%')} | {f(r['b200'], 0, '%')} | {pe(r['fpe'])} |")
    L.append("")
    L.append("\\* 成分股為近似名單（依市值排名／交易所上市清單推估）。")
    L.append("")
    L.append("## 參與度（成分股站上 N 日均線的比例 %）")
    L.append("")
    L.append("| 指數 | 成分股 | " + " | ".join(f"{w}D" for w in MA_WINDOWS) + " | 20D 5 日變化 | 20D 分區 |")
    L.append("|---|---:|" + "---:|" * len(MA_WINDOWS) + "---:|:-:|")
    for r in rows:
        b = (breadth.get("indexes") or {}).get(r["key"]) or {}
        lat = b.get("latest") or {}
        cells = " | ".join(f(lat.get(str(w)), 0) for w in MA_WINDOWS)
        z, _ = zone(r["b20"])
        L.append(f"| {r['name']}{'*' if r['approx'] else ''} | {b.get('priced', '—')}/{b.get('members', '—')} | {cells} | {s(r['b20_w'], 0, ' pt')} | {z} |")
    L.append("")
    L.append("解讀：站上 20 日線比例 <40% 為接近超賣、<30% 超賣、>60% 接近超買、>70% 超買；站上 200 日線比例代表中長期趨勢的健康度。")
    L.append("")
    L.append("## 實質利率與黃金")
    L.append("")
    L.append("| 序列 | 最新 | 1 日 | 5 日 | 21 日 | 一年百分位 | 一年區間 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    labels = {"DFII10": "10 年期實質利率 (TIPS)", "DGS10": "10 年期公債殖利率", "T10YIE": "10 年期通膨預期", "DGS2": "2 年期公債殖利率", "GOLD": "黃金 (USD/oz)", "DXY": "美元指數"}
    for key in ("DFII10", "DGS10", "T10YIE", "DGS2", "GOLD", "DXY"):
        x = mb.get(key)
        if not x:
            continue
        nd = 2 if x["unit"] == "bp" else 1
        u = "%" if x["unit"] == "bp" else ""
        d_u = " bp" if x["unit"] == "bp" else "%"
        L.append(f"| {labels[key]}（{x['date']}） | {f(x['v'], nd, u)} | {s(x['d1'], 0 if x['unit']=='bp' else 1, d_u)} | {s(x['d5'], 0 if x['unit']=='bp' else 1, d_u)} | {s(x['d21'], 0 if x['unit']=='bp' else 1, d_u)} | {f(x['rank1y'], 0)} | {f(x['lo1y'], nd)}–{f(x['hi1y'], nd)} |")
    c = mb.get("corr_gold_real_60d")
    L.append("")
    L.append(f"- 黃金與 10 年期實質利率近 60 個交易日的日變動相關係數：**{f(c, 2)}**（負值代表「實質利率升、黃金跌」的關係成立）。")
    L.append("- 實質利率 = 名目殖利率 − 通膨預期；黃金不孳息，實質利率越高持有黃金的機會成本越高。")
    L.append("")
    L.append("## 估值（Forward PE）")
    L.append("")
    L.append("| 指數 | 收盤 | Forward PE（下一財年） | NTM PE（混合 12 月） | Trailing PE | 中位數 Fwd PE | 市值覆蓋率 | 累積歷史 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---|")
    for key, a in (valuation.get("indexes") or {}).items():
        st = pst.get(key) or {}
        hist_txt = (f"第 {st['rank']:.0f} 百分位（{st['n']} 日，自 {st['since']}）" if st.get("rank") is not None else f"累積中（{st.get('n', 0)} 日）")
        L.append(f"| {a['name']}{'*' if a.get('approx') else ''} | {f(a.get('close'), 2)} | {pe(a.get('fpe'))} | {pe(a.get('ntm'))} | {pe(a.get('tpe'))} | {pe(a.get('median_fpe'))} | {f((a.get('fpe_cov') or 0) * 100, 0, '%')} | {hist_txt} |")
    L.append("")
    L.append("指數 PE = Σ成分股市值 ÷ Σ成分股盈餘（含虧損公司）；NTM = 以財年剩餘月數混合本財年與下一財年的分析師 EPS 共識。歷史百分位需累積 20 個交易日後才會顯示。")
    tk = valuation.get("tickers") or {}
    wl = [sym for sym in (valuation.get("watchlist") or []) if sym in tk]
    if wl:
        L.append("")
        L.append("### 追蹤清單")
        L.append("")
        L.append("| 代號 | 名稱 | 價格 | 1 日 | Fwd PE | NTM PE | Trailing PE | 下一財年 EPS | 90 日修正 | 下次財報 |")
        L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for sym in wl:
            r = tk[sym]
            L.append(f"| {sym} | {(r.get('n') or '')[:28]} | {f(r.get('p'), 2)} | {s(r.get('c'), 2, '%')} | {pe(r.get('fpe'))} | {pe(r.get('ntm'))} | {pe(r.get('tpe'))} | {f(r.get('e1'), 2)} | {s(r.get('rev90'), 1, '%')} | {r.get('nx') or '—'} |")
    L.append("")
    L.append("## 波動率")
    L.append("")
    L.append("| 指標 | 最新 | 1 日 | 5 日 | 一年百分位 | 一年區間 |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for key, nm in (("VIX", "VIX（美股波動率）"), ("MOVE", "MOVE（美債波動率）")):
        x = mb.get(key)
        if x:
            L.append(f"| {nm} | {f(x['v'], 1)} | {s(x['d1'], 1, '%')} | {s(x['d5'], 1, '%')} | {f(x['rank1y'], 0)} | {f(x['lo1y'], 1)}–{f(x['hi1y'], 1)} |")
    L.append("")
    L.append("## 資料狀態")
    L.append("")
    for k, v in (status.get("sources") or {}).items():
        L.append(f"- 成分股 {k}: {v}")
    L.append(f"- 產生時間：{status.get('generated_at', '')}（UTC）；資料來源：Yahoo Finance、FRED、Wikipedia、Nasdaq、SSGA、nasdaqtrader。")
    md = "\n".join(L) + "\n"

    latest = {
        "asof": asof, "generated_at": status.get("generated_at"), "summary": summary, "signals": signals,
        "indexes": [{k: (fnum(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        "macro": {k: ({kk: (fnum(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items()} if isinstance(v, dict) else fnum(v, 3)) for k, v in mb.items()},
        "pe": {k: {"name": a["name"], "fpe": a.get("fpe"), "ntm": a.get("ntm"), "tpe": a.get("tpe"), "cov": a.get("fpe_cov"), "close": a.get("close"), "approx": a.get("approx"),
                   "hist": {kk: (fnum(vv, 2) if isinstance(vv, float) else vv) for kk, vv in (pst.get(k) or {}).items()}} for k, a in (valuation.get("indexes") or {}).items()},
        "watchlist": [{"s": sym, **{k: tk[sym].get(k) for k in ("n", "p", "c", "fpe", "ntm", "tpe", "e1", "rev90", "nx")}} for sym in wl],
        "status": status,
    }
    return md, latest
