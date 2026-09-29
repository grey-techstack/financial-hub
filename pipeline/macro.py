"""總經與波動率序列：FRED（實質利率、公債殖利率、通膨預期）＋ Yahoo（黃金、MOVE、VIX、美元、各指數）。"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import time

import requests

from common import DATA, fnum, read_json, today
from registry import FRED_SERIES, INDEXES, YAHOO_SERIES
from yahoo import UA, Yahoo

LOG = logging.getLogger("macro")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
# FRED 對瀏覽器 UA 會刻意拖慢（tarpit），用簡單的程式 UA 反而秒回
SIMPLE_UA = "financial-hub/1.0"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                "{year}/all?type={typ}&field_tdr_date_value={year}&page&_format=csv")


def fetch_fred(series_id: str, years: int = 2) -> tuple[list[str], list[float]]:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            r = requests.get(FRED_URL.format(id=series_id), headers={"User-Agent": SIMPLE_UA}, timeout=20)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"FRED {series_id} 連線失敗: {last_err}")
    cutoff = (today() - dt.timedelta(days=365 * years + 10)).isoformat()
    dates, vals = [], []
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 2 or row[0] in ("DATE", "observation_date") or row[0] < cutoff:
            continue
        try:
            vals.append(float(row[1]))
            dates.append(row[0])
        except ValueError:
            continue  # "." = 缺值
    if not dates:
        raise RuntimeError(f"FRED {series_id} 無資料")
    return dates, vals


def fetch_treasury(typ: str, col: str, years: int = 2) -> tuple[list[str], list[float]]:
    """美國財政部每日殖利率曲線 CSV（FRED 的備援）。typ = daily_treasury_real_yield_curve / daily_treasury_yield_curve"""
    out: dict[str, float] = {}
    y0 = today().year
    for year in range(y0 - years, y0 + 1):
        r = requests.get(TREASURY_URL.format(year=year, typ=typ), headers={"User-Agent": UA}, timeout=30)
        if r.status_code != 200:
            continue
        for row in csv.DictReader(io.StringIO(r.text)):
            d = row.get("Date") or ""
            key = next((k for k in row if k.strip().lower() == col.lower()), None)
            try:
                mm, dd, yy = d.split("/")
                out[f"{yy}-{mm}-{dd}"] = float(row[key])
            except (ValueError, KeyError, TypeError):
                continue
    if not out:
        raise RuntimeError(f"treasury {typ} 無資料")
    dates = sorted(out)
    return dates, [out[d] for d in dates]


TREASURY_FALLBACK = {"DFII10": ("daily_treasury_real_yield_curve", "10 YR"), "DGS10": ("daily_treasury_yield_curve", "10 Yr"), "DGS2": ("daily_treasury_yield_curve", "2 Yr")}


def build_macro(yahoo: Yahoo) -> dict:
    prev = read_json(DATA / "macro.json", {}) or {}
    prev_series = prev.get("series") or {}
    series: dict[str, dict] = {}
    for sid, meta in FRED_SERIES.items():
        try:
            d, v = fetch_fred(sid)
            series[sid] = {"name": meta["name"], "unit": meta["unit"], "source": "FRED", "dates": d, "values": [fnum(x, 3) for x in v]}
            LOG.info("FRED %s: %d 筆, 最新 %s=%s", sid, len(d), d[-1], v[-1])
        except Exception as e:  # noqa: BLE001
            fb = TREASURY_FALLBACK.get(sid)
            if fb:
                try:
                    d, v = fetch_treasury(*fb)
                    series[sid] = {"name": meta["name"], "unit": meta["unit"], "source": "Treasury.gov", "dates": d, "values": [fnum(x, 3) for x in v]}
                    LOG.warning("FRED %s 失敗（%s），改用財政部資料：%d 筆", sid, e, len(d))
                    continue
                except Exception as e2:  # noqa: BLE001
                    LOG.warning("財政部備援 %s 也失敗：%s", sid, e2)
            LOG.warning("FRED %s 失敗（%s），沿用舊資料", sid, e)
            if sid in prev_series:
                series[sid] = prev_series[sid]
    if "T10YIE" not in series and "DGS10" in series and "DFII10" in series:
        m_real = dict(zip(series["DFII10"]["dates"], series["DFII10"]["values"]))
        d = [x for x in series["DGS10"]["dates"] if x in m_real]
        nom = dict(zip(series["DGS10"]["dates"], series["DGS10"]["values"]))
        series["T10YIE"] = {"name": FRED_SERIES["T10YIE"]["name"], "unit": "%", "source": "計算 (名目−實質)", "dates": d, "values": [fnum(nom[x] - m_real[x], 3) for x in d]}
    for key, meta in YAHOO_SERIES.items():
        ch = yahoo.chart(meta["symbol"], "2y")
        if ch and ch["close"]:
            series[key] = {"name": meta["name"], "unit": meta["unit"], "source": "Yahoo", "symbol": meta["symbol"],
                           "dates": ch["dates"], "values": [fnum(x, 3) for x in ch["close"]]}
            LOG.info("Yahoo %s: %d 筆, 最新 %s=%s", key, len(ch["dates"]), ch["dates"][-1], ch["close"][-1])
        elif key in prev_series:
            LOG.warning("Yahoo %s 失敗，沿用舊資料", key)
            series[key] = prev_series[key]
    indexes: dict[str, dict] = {}
    prev_idx = prev.get("indexes") or {}
    for ix in INDEXES:
        ch = yahoo.chart(ix["yahoo"], "2y")
        if ch and ch["close"]:
            indexes[ix["key"]] = {"name": ix["name"], "symbol": ix["yahoo"], "dates": ch["dates"], "close": [fnum(x, 2) for x in ch["close"]]}
        elif ix["key"] in prev_idx:
            indexes[ix["key"]] = prev_idx[ix["key"]]
    return {"asof": today().isoformat(), "series": series, "indexes": indexes}


def trading_calendar(macro: dict) -> list[str]:
    """以 S&P 500 的交易日作為全市場的日曆。"""
    spx = (macro.get("indexes") or {}).get("SPX") or {}
    return list(spx.get("dates") or [])
