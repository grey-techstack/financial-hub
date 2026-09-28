"""極簡 Yahoo Finance 客戶端（不依賴 yfinance）。

- chart():         v8 圖表 API（免 crumb），取歷史收盤價
- quotes():        v7 批次報價（需 crumb），一次最多 ~250 檔，含 forwardPE / epsForward / marketCap ...
- quote_summary(): v10 quoteSummary（需 crumb），取分析師 EPS 預估、財年結束日
- search():        名稱 -> 代號
所有請求都有重試與退避；429/5xx 會等待後重試。
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter

LOG = logging.getLogger("yahoo")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
Q1 = "https://query1.finance.yahoo.com"
Q2 = "https://query2.finance.yahoo.com"

QUOTE_FIELDS = ",".join([
    "symbol", "shortName", "longName", "quoteType", "exchange", "currency",
    "regularMarketPrice", "regularMarketChangePercent", "regularMarketTime",
    "marketCap", "sharesOutstanding",
    "forwardPE", "trailingPE", "epsForward", "epsTrailingTwelveMonths", "epsCurrentYear", "priceEpsCurrentYear",
    "fiftyDayAverage", "twoHundredDayAverage", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "priceToBook", "dividendYield",
])


class YahooError(RuntimeError):
    pass


def to_yahoo_symbol(sym: str) -> str:
    """交易所代號 -> Yahoo 代號（BRK.B -> BRK-B；已含 ^ 或 = 的原樣保留）。"""
    s = sym.strip().upper()
    if s.startswith("^") or "=" in s:
        return s
    if "." in s and not s.endswith((".TO", ".V", ".TW", ".HK", ".L", ".SS", ".SZ")):
        s = s.replace(".", "-")
    return s


class Yahoo:
    def __init__(self, workers: int = 12, timeout: int = 30):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
        self.s.mount("https://", adapter)
        self.workers = workers
        self.timeout = timeout
        self._crumb: str | None = None
        self._lock = threading.Lock()

    # ---- crumb / cookie -------------------------------------------------
    def crumb(self, refresh: bool = False) -> str:
        with self._lock:
            if self._crumb and not refresh:
                return self._crumb
            last = ""
            for attempt in range(4):
                try:
                    self.s.get("https://fc.yahoo.com", timeout=self.timeout)  # 404 也會種 cookie
                    r = self.s.get(f"{Q2}/v1/test/getcrumb", timeout=self.timeout)
                    txt = r.text.strip()
                    if r.status_code == 200 and txt and "<" not in txt:
                        self._crumb = txt
                        return txt
                    last = f"{r.status_code} {txt[:60]}"
                except requests.RequestException as e:  # noqa: PERF203
                    last = str(e)
                time.sleep(1.5 * (attempt + 1))
            raise YahooError(f"無法取得 Yahoo crumb: {last}")

    # ---- low level ------------------------------------------------------
    def _get_json(self, url: str, params: dict | None = None, need_crumb: bool = False, retries: int = 5):
        for attempt in range(retries):
            p = dict(params or {})
            try:
                if need_crumb:
                    p["crumb"] = self.crumb()
                r = self.s.get(url, params=p, timeout=self.timeout)
            except requests.RequestException as e:
                LOG.debug("request error %s: %s", url, e)
                time.sleep(min(20, 1.5 ** attempt + random.random()))
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    time.sleep(1)
                    continue
            if r.status_code in (401, 403) and need_crumb:
                self.crumb(refresh=True)
                continue
            if r.status_code in (400, 404):
                return None
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(60, 2 ** attempt + random.random() * 2)
                LOG.debug("HTTP %s on %s, sleeping %.1fs", r.status_code, url, wait)
                time.sleep(wait)
                continue
            LOG.warning("HTTP %s on %s: %s", r.status_code, url, r.text[:120])
            return None
        return None

    # ---- chart ----------------------------------------------------------
    def chart(self, symbol: str, range_: str = "2y", interval: str = "1d") -> dict | None:
        """回傳 {"symbol", "dates": [YYYY-MM-DD], "close": [float], "meta": {...}}；失敗回 None。"""
        j = self._get_json(f"{Q1}/v8/finance/chart/{symbol}", {"range": range_, "interval": interval, "events": "div,splits"})
        try:
            res = j["chart"]["result"][0]
        except (TypeError, KeyError, IndexError):
            return None
        ts = res.get("timestamp") or []
        closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        meta = res.get("meta") or {}
        try:
            tz = ZoneInfo(meta.get("exchangeTimezoneName") or "America/New_York")
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("America/New_York")
        dates, vals = [], []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            dates.append(dt.datetime.fromtimestamp(t, tz).date().isoformat())
            vals.append(float(c))
        # 同一天若有多筆（盤中快照）保留最後一筆
        dedup: dict[str, float] = {}
        for d, v in zip(dates, vals):
            dedup[d] = v
        return {
            "symbol": symbol,
            "dates": list(dedup.keys()),
            "close": list(dedup.values()),
            "meta": {k: meta.get(k) for k in ("symbol", "shortName", "longName", "currency", "regularMarketPrice", "exchangeName", "instrumentType", "regularMarketTime")},
        }

    def charts(self, symbols: list[str], range_: str = "2y", workers: int | None = None) -> dict[str, dict]:
        out: dict[str, dict] = {}
        symbols = list(dict.fromkeys(symbols))
        t0 = time.time()

        def one(sym):
            return sym, self.chart(sym, range_)

        with ThreadPoolExecutor(workers or self.workers) as ex:
            for i, (sym, res) in enumerate(ex.map(one, symbols), 1):
                if res and res["close"]:
                    out[sym] = res
                if i % 500 == 0:
                    LOG.info("charts %d/%d (%.0fs)", i, len(symbols), time.time() - t0)
        LOG.info("charts done: %d/%d ok in %.0fs", len(out), len(symbols), time.time() - t0)
        return out

    # ---- batch quotes ---------------------------------------------------
    def quotes(self, symbols: list[str], fields: str = QUOTE_FIELDS, chunk: int = 200) -> dict[str, dict]:
        out: dict[str, dict] = {}
        symbols = list(dict.fromkeys(s for s in symbols if s))
        for i in range(0, len(symbols), chunk):
            part = symbols[i:i + chunk]
            j = self._get_json(f"{Q2}/v7/finance/quote", {"symbols": ",".join(part), "fields": fields}, need_crumb=True)
            res = ((j or {}).get("quoteResponse") or {}).get("result") or []
            if not res and len(part) > 20:
                # 批次失敗時拆半再試一次
                for k in range(0, len(part), 50):
                    sub = part[k:k + 50]
                    jj = self._get_json(f"{Q2}/v7/finance/quote", {"symbols": ",".join(sub), "fields": fields}, need_crumb=True)
                    res += ((jj or {}).get("quoteResponse") or {}).get("result") or []
            for q in res:
                if q.get("symbol"):
                    out[q["symbol"]] = q
        LOG.info("quotes: %d/%d symbols", len(out), len(symbols))
        return out

    # ---- quoteSummary ---------------------------------------------------
    def quote_summary(self, symbol: str, modules: str) -> dict | None:
        j = self._get_json(f"{Q2}/v10/finance/quoteSummary/{symbol}", {"modules": modules}, need_crumb=True)
        try:
            return j["quoteSummary"]["result"][0]
        except (TypeError, KeyError, IndexError):
            return None

    @staticmethod
    def _raw(d, *keys):
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        if isinstance(cur, dict):
            cur = cur.get("raw")
        return cur

    def estimates(self, symbol: str) -> dict | None:
        """分析師 EPS 預估（本財年 0y、下一財年 +1y、本季 0q、下季 +1q）與財年結束日。"""
        res = self.quote_summary(symbol, "earningsTrend,defaultKeyStatistics,calendarEvents")
        if not res:
            return None
        out: dict = {"symbol": symbol}
        for t in (res.get("earningsTrend") or {}).get("trend") or []:
            p = t.get("period")
            if p in ("0q", "+1q", "0y", "+1y"):
                key = p.replace("+", "p")
                out[f"eps_{key}"] = self._raw(t, "earningsEstimate", "avg")
                out[f"end_{key}"] = t.get("endDate")
                out[f"n_{key}"] = self._raw(t, "earningsEstimate", "numberOfAnalysts")
                out[f"rev_{key}"] = self._raw(t, "revenueEstimate", "avg")
                out[f"eps_{key}_30d"] = self._raw(t, "epsTrend", "30daysAgo")
                out[f"eps_{key}_90d"] = self._raw(t, "epsTrend", "90daysAgo")
        ks = res.get("defaultKeyStatistics") or {}
        out["fy_end_next"] = (ks.get("nextFiscalYearEnd") or {}).get("fmt")
        out["fy_end_last"] = (ks.get("lastFiscalYearEnd") or {}).get("fmt")
        out["forward_pe_ks"] = self._raw(ks, "forwardPE")
        out["forward_eps_ks"] = self._raw(ks, "forwardEps")
        out["trailing_eps_ks"] = self._raw(ks, "trailingEps")
        out["peg"] = self._raw(ks, "pegRatio")
        ce = res.get("calendarEvents") or {}
        eds = ((ce.get("earnings") or {}).get("earningsDate")) or []
        out["next_earnings"] = (eds[0].get("fmt") if eds and isinstance(eds[0], dict) else None)
        return out

    def estimates_many(self, symbols: list[str], workers: int = 8) -> dict[str, dict]:
        out: dict[str, dict] = {}
        symbols = list(dict.fromkeys(symbols))
        t0 = time.time()
        with ThreadPoolExecutor(workers) as ex:
            for sym, res in ex.map(lambda s: (s, self.estimates(s)), symbols):
                if res:
                    out[sym] = res
        LOG.info("estimates: %d/%d in %.0fs", len(out), len(symbols), time.time() - t0)
        return out

    # ---- search ---------------------------------------------------------
    def search(self, q: str, n: int = 8) -> list[dict]:
        j = self._get_json(f"{Q2}/v1/finance/search", {"q": q, "quotesCount": n, "newsCount": 0, "listsCount": 0})
        out = []
        for x in (j or {}).get("quotes") or []:
            if x.get("symbol"):
                out.append({"symbol": x["symbol"], "name": x.get("shortname") or x.get("longname"),
                            "type": x.get("quoteType"), "exchange": x.get("exchDisp") or x.get("exchange")})
        return out
