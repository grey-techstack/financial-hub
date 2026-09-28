"""指數成分股來源。

- S&P 500 / 400 / 600：Wikipedia 成分股表
- NASDAQ 100：Nasdaq 官方 API
- 道瓊 30：State Street DIA ETF 持股檔（xlsx）
- SOX 費城半導體：Nasdaq Global Indexes 權重頁（POST）；失敗時用 config/sox_fallback.txt
- S&P/TSX：Wikipedia
- 美股全市場：nasdaqtrader.com 上市清單（nasdaqlisted + otherlisted），用來推估
  NASDAQ 綜合 / NYSE 綜合 / Russell 1000/2000/3000（依市值排名近似）

每個來源失敗時會沿用 data/universe.json 內上一次成功的名單。
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import re
import warnings

import pandas as pd
import requests

from common import CONFIG, DATA, read_json, today, write_json
from yahoo import UA, to_yahoo_symbol

LOG = logging.getLogger("constituents")
HDR = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
warnings.filterwarnings("ignore", category=FutureWarning)

WIKI = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
    "tsx":   "https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index",
}


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=HDR, timeout=60, **kw)
    r.raise_for_status()
    return r


def _clean_name(n: str) -> str:
    n = re.sub(r"\s+", " ", str(n)).strip()
    n = re.sub(r"\s*-?\s*(Class [A-C] )?(Common Stock|Common Shares|Ordinary Shares?|American Depositary Shares?.*|Depositary Shares?.*)$", "", n, flags=re.I)
    return n.strip(" -,")


# ---------------------------------------------------------------- S&P via Wikipedia
def fetch_sp(kind: str) -> list[dict]:
    html = _get(WIKI[kind]).text
    tables = pd.read_html(io.StringIO(html))
    for t in tables:
        cols = [str(c) for c in t.columns]
        if "Symbol" in cols and ("Security" in cols or "Company" in cols):
            name_col = "Security" if "Security" in cols else "Company"
            sector_col = next((c for c in cols if "Sector" in c), None)
            out = []
            for _, row in t.iterrows():
                sym = str(row["Symbol"]).strip()
                if not sym or sym == "nan":
                    continue
                out.append({"symbol": to_yahoo_symbol(sym), "name": _clean_name(row[name_col]),
                            "sector": (str(row[sector_col]) if sector_col else None)})
            if len(out) >= 300:
                return out
    raise RuntimeError(f"Wikipedia {kind}: 找不到成分股表")


def fetch_tsx() -> list[dict]:
    html = _get(WIKI["tsx"]).text
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c) for c in t.columns]
        if "Ticker" in cols and "Company" in cols and len(t) >= 150:
            sector_col = next((c for c in cols if "Sector" in c), None)
            out = []
            for _, row in t.iterrows():
                raw = str(row["Ticker"]).strip().upper()
                if not raw or raw == "NAN":
                    continue
                sym = raw.replace(".", "-")
                if not sym.endswith("-TO"):
                    sym = sym + ".TO"
                else:
                    sym = sym[:-3] + ".TO"
                out.append({"symbol": sym, "name": _clean_name(row["Company"]), "sector": (str(row[sector_col]) if sector_col else None)})
            return out
    raise RuntimeError("Wikipedia TSX: 找不到成分股表")


# ---------------------------------------------------------------- NASDAQ 100 via Nasdaq API
def fetch_ndx() -> list[dict]:
    r = requests.get("https://api.nasdaq.com/api/quote/list-type/nasdaq100", headers={**HDR, "Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    rows = (((r.json() or {}).get("data") or {}).get("data") or {}).get("rows") or []
    out = [{"symbol": to_yahoo_symbol(x["symbol"]), "name": _clean_name(x.get("companyName", "")), "sector": x.get("sector") or None}
           for x in rows if x.get("symbol")]
    if len(out) < 90:
        raise RuntimeError(f"Nasdaq API 只回 {len(out)} 檔")
    return out


# ---------------------------------------------------------------- Dow 30 via SPDR DIA holdings
DIA_URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-dia.xlsx"


def fetch_dow() -> list[dict]:
    r = _get(DIA_URL, allow_redirects=True)
    df = pd.read_excel(io.BytesIO(r.content), header=None)
    hdr_row = None
    for i in range(min(len(df), 30)):
        vals = [str(x).strip() for x in df.iloc[i].tolist()]
        if "Ticker" in vals and "Name" in vals:
            hdr_row = i
            break
    if hdr_row is None:
        raise RuntimeError("DIA 持股檔找不到表頭")
    hdr = [str(x).strip() for x in df.iloc[hdr_row].tolist()]
    body = df.iloc[hdr_row + 1:].copy()
    body.columns = hdr
    out = []
    for _, row in body.iterrows():
        tick = str(row.get("Ticker", "")).strip()
        name = str(row.get("Name", "")).strip()
        if not tick or tick in ("-", "nan") or "DOLLAR" in name.upper() or "CASH" in name.upper():
            continue
        w = row.get("Weight")
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = None
        out.append({"symbol": to_yahoo_symbol(tick), "name": name.title(), "sector": None, "weight": w})
    if not 25 <= len(out) <= 35:
        raise RuntimeError(f"DIA 持股檔筆數異常: {len(out)}")
    return out


# ---------------------------------------------------------------- SOX via Nasdaq Global Indexes
def fetch_sox() -> list[dict]:
    s = requests.Session()
    s.headers.update(HDR)
    s.get("https://indexes.nasdaqomx.com/Index/Weighting/SOX", timeout=60)
    hdr = {"Accept": "application/json, text/javascript, */*", "X-Requested-With": "XMLHttpRequest",
           "Referer": "https://indexes.nasdaqomx.com/Index/Weighting/SOX"}
    d0 = today()
    for k in range(0, 10):
        d = d0 - dt.timedelta(days=k)
        if d.weekday() >= 5:
            continue
        for tod in ("SOD", "EOD"):
            body = {"id": "SOX", "tradeDate": d.strftime("%Y-%m-%dT00:00:00.000"), "timeOfDay": tod}
            try:
                r = s.post("https://indexes.nasdaqomx.com/Index/WeightingData", json=body, headers=hdr, timeout=60)
                rows = (r.json() or {}).get("aaData") or []
            except Exception as e:  # noqa: BLE001
                LOG.debug("SOX weighting %s %s: %s", d, tod, e)
                rows = []
            if len(rows) >= 20:
                out = [{"symbol": to_yahoo_symbol(x["Symbol"]), "name": _clean_name(x.get("Name", "")).title(), "sector": "Semiconductors"}
                       for x in rows if x.get("Symbol")]
                _save_fallback(out)
                return out
    raise RuntimeError("Nasdaq indexes 無 SOX 權重資料")


def _save_fallback(rows: list[dict]) -> None:
    try:
        with open(CONFIG / "sox_fallback.txt", "w", encoding="utf-8") as f:
            f.write(f"# SOX 成分股快照 {today().isoformat()}（自動更新；線上抓取失敗時使用）\n")
            for r in rows:
                f.write(f"{r['symbol']}\t{r['name']}\n")
    except OSError:
        pass


def sox_fallback() -> list[dict]:
    out = []
    for line in open(CONFIG / "sox_fallback.txt", encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        sym, _, name = line.rstrip("\n").partition("\t")
        out.append({"symbol": sym.strip(), "name": name.strip(), "sector": "Semiconductors"})
    return out


# ---------------------------------------------------------------- 美股全市場（nasdaqtrader）
EXCLUDE_NAME = re.compile(
    r"warrant|\bright(s)?\b|\bunit(s)?\b|preferred|prefered|\bnotes?\b|debenture|\betf\b|\betn\b|fund\b|trust preferred|"
    r"subordinated|depositary shares?,? each representing (a )?1/|convertible|closed.end|due 20\d\d|"
    r"\bbond\b|\bindex\b|trust units|ishares|spdr|proshares|vanguard|invesco|direxion|wisdomtree|graniteshares",
    re.I)
ADR_NAME = re.compile(r"depositary|\bADR\b|\bADS\b|\bADSs\b", re.I)


def fetch_us_universe() -> list[dict]:
    out: dict[str, dict] = {}
    txt = _get("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt").text
    for line in txt.splitlines():
        p = line.split("|")
        if len(p) < 7 or p[0] in ("Symbol",) or line.startswith("File Creation"):
            continue
        sym, name, cat, test, fin, lot, etf = p[:7]
        if test == "Y" or etf == "Y" or EXCLUDE_NAME.search(name):
            continue
        if re.search(r"[\$\^\+=]", sym) or ("." in sym and not re.match(r"^[A-Z]+\.[AB]$", sym)):
            continue
        out[sym] = {"symbol": to_yahoo_symbol(sym), "name": _clean_name(name), "exch": "Q", "adr": bool(ADR_NAME.search(name))}
    txt = _get("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt").text
    for line in txt.splitlines():
        p = line.split("|")
        if len(p) < 8 or p[0] in ("ACT Symbol",) or line.startswith("File Creation"):
            continue
        sym, name, exch, cqs, etf, lot, test, nasdaq_sym = p[:8]
        if test == "Y" or etf == "Y" or EXCLUDE_NAME.search(name):
            continue
        if re.search(r"[\$\^\+=]", sym) or ("." in sym and not re.match(r"^[A-Z]+\.[AB]$", sym)):
            continue
        out[sym] = {"symbol": to_yahoo_symbol(sym), "name": _clean_name(name), "exch": exch, "adr": bool(ADR_NAME.search(name))}
    rows = list(out.values())
    if len(rows) < 3000:
        raise RuntimeError(f"nasdaqtrader 清單過短: {len(rows)}")
    return rows


def russell_proxies(universe: list[dict], quotes: dict[str, dict]) -> dict[str, list[dict]]:
    """以市值排名近似 Russell 1000 / 2000 / 3000（排除 ADR 與無市值者）。"""
    ranked = []
    for u in universe:
        if u.get("adr"):
            continue
        q = quotes.get(u["symbol"]) or {}
        mc = q.get("marketCap")
        if q.get("quoteType") not in (None, "EQUITY"):
            continue
        if mc:
            ranked.append((float(mc), u))
    ranked.sort(key=lambda x: -x[0])
    rows = [dict(u, sector=None) for _, u in ranked]
    return {"r1000": rows[:1000], "r2000": rows[1000:3000], "r3000": rows[:3000]}


# ---------------------------------------------------------------- 總入口
FETCHERS = {
    "sp500": lambda: fetch_sp("sp500"),
    "sp400": lambda: fetch_sp("sp400"),
    "sp600": lambda: fetch_sp("sp600"),
    "ndx": fetch_ndx,
    "dow": fetch_dow,
    "sox": fetch_sox,
    "tsx": fetch_tsx,
    "us_universe": fetch_us_universe,
}


def load_constituents(sources: list[str], cache_path=None) -> tuple[dict[str, list[dict]], dict]:
    """抓取指定來源；失敗時沿用快取。回傳 (名單, 狀態)。"""
    cache_path = cache_path or (DATA / "universe.json")
    cache = read_json(cache_path, {}) or {}
    cached_sets = cache.get("sets") or {}
    fetched_at = dict(cache.get("fetched_at") or {})
    out: dict[str, list[dict]] = {}
    status: dict[str, str] = {}
    for src in sources:
        fn = FETCHERS.get(src)
        try:
            rows = fn() if fn else None
            if not rows:
                raise RuntimeError("空名單")
            out[src] = rows
            fetched_at[src] = today().isoformat()
            status[src] = f"ok ({len(rows)})"
            LOG.info("%s: %d 檔", src, len(rows))
        except Exception as e:  # noqa: BLE001
            if src == "sox":
                try:
                    out[src] = sox_fallback()
                    status[src] = f"fallback file ({len(out[src])}): {e}"
                    LOG.warning("SOX 線上抓取失敗，改用 fallback 檔: %s", e)
                    continue
                except Exception:  # noqa: BLE001
                    pass
            if cached_sets.get(src):
                out[src] = cached_sets[src]
                status[src] = f"cached {fetched_at.get(src)} ({len(out[src])}): {e}"
                LOG.warning("%s 抓取失敗，沿用 %s 的快取: %s", src, fetched_at.get(src), e)
            else:
                status[src] = f"FAILED: {e}"
                LOG.error("%s 抓取失敗且無快取: %s", src, e)
    return out, {"fetched_at": fetched_at, "status": status}


def save_universe(sets: dict[str, list[dict]], meta: dict, path=None) -> None:
    path = path or (DATA / "universe.json")
    write_json(path, {"asof": today().isoformat(), "fetched_at": meta.get("fetched_at", {}), "status": meta.get("status", {}), "sets": sets}, compact=True)
