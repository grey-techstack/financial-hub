"""參與度（市場寬度）三組指標，皆以各指數成分股計算、含最近一年每日歷史：

1. 站上均線比例：收盤價高於 N 日移動平均線的成分股比例（Bloomberg「Members Above Moving Average」）。
2. 52 週淨新高：創 52 週新高的家數 − 創新低的家數，占有效成分股比例（CNN Fear & Greed 的 Stock Price Strength）。
3. McClellan 震盪指標與累積指數（CNN 的 Stock Price Breadth）：
   比例調整淨值 RANA = (上漲 − 下跌) ÷ (上漲 + 下跌) × 1000（成交量版 v 與家數版 i），
   震盪指標 = EMA19(RANA) − EMA39(RANA)，累積指數 = 1000 + 逐日累加的震盪指標（水位為相對值）。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from common import fnum
from registry import MA_WINDOWS

LOG = logging.getLogger("breadth")
NH_WINDOW = 252  # 52 週


def build_frames(charts: dict[str, dict], calendar: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """回傳 (收盤價, 成交量) 兩個 DataFrame：columns = 代號, index = 交易日曆（缺值 NaN）。"""
    cal = pd.Index(calendar)
    closes: dict[str, pd.Series] = {}
    vols: dict[str, pd.Series] = {}
    for sym, ch in charts.items():
        if not ch or not ch.get("close"):
            continue
        idx = pd.Index(ch["dates"])
        s = pd.Series(ch["close"], index=idx, dtype="float64")
        s = s[~s.index.duplicated(keep="last")]
        closes[sym] = s.reindex(cal)
        vraw = ch.get("volume") or [0.0] * len(ch["close"])
        v = pd.Series(vraw, index=idx, dtype="float64")
        v = v[~v.index.duplicated(keep="last")]
        vols[sym] = v.reindex(cal)
    px = pd.DataFrame(closes, index=cal)
    vol = pd.DataFrame(vols, index=cal)
    LOG.info("close frame: %d 檔 x %d 日", px.shape[1], px.shape[0])
    return px, vol


def build_close_frame(charts: dict[str, dict], calendar: list[str]) -> pd.DataFrame:
    return build_frames(charts, calendar)[0]


def _tail(s: pd.Series, n: int, nd: int) -> list:
    return [fnum(x, nd) for x in s.iloc[-n:].tolist()]


def _rank(s: pd.Series, n: int = 252):
    win = s.iloc[-n:].dropna()
    if len(win) < 20:
        return None
    return fnum((win <= win.iloc[-1]).sum() / len(win) * 100, 0)


def compute_breadth(df: pd.DataFrame, members: dict[str, list[str]], windows: list[int] | None = None,
                    history_days: int = 252, vol: pd.DataFrame | None = None) -> dict:
    windows = windows or MA_WINDOWS
    px = df.ffill(limit=5)  # 停牌等短暫缺值以前值補上
    above_all: dict[int, pd.DataFrame] = {}
    valid_all: dict[int, pd.DataFrame] = {}
    for n in windows:
        ma = px.rolling(n, min_periods=n).mean()
        above_all[n] = px > ma
        valid_all[n] = ma.notna() & px.notna()
    # 52 週新高 / 新低（以收盤價）
    hi = px.rolling(NH_WINDOW, min_periods=NH_WINDOW).max()
    lo = px.rolling(NH_WINDOW, min_periods=NH_WINDOW).min()
    is_high = (px >= hi) & hi.notna()
    is_low = (px <= lo) & lo.notna()
    nh_valid = hi.notna() & px.notna()
    # 漲跌家數與成交量
    prev = px.shift(1)
    up = px > prev
    down = px < prev
    volf = None
    if vol is not None and not vol.empty:
        volf = vol.reindex(columns=px.columns).fillna(0.0)
    dates = list(px.index[-history_days:])
    out: dict[str, dict] = {}
    for key, syms in members.items():
        cols = [s for s in dict.fromkeys(syms) if s in px.columns]
        rec = {"members": len(syms), "priced": len(cols), "latest": {}, "prev": {}, "week": {}, "month": {}, "counts": {},
               "history": {"dates": dates}}
        if not cols:
            out[key] = rec
            continue
        for n in windows:
            a = above_all[n][cols].sum(axis=1).astype(float)
            v = valid_all[n][cols].sum(axis=1).astype(float)
            pct = a / v.replace(0.0, np.nan) * 100.0
            rec["latest"][str(n)] = fnum(pct.iloc[-1], 1)
            rec["prev"][str(n)] = fnum(pct.iloc[-2], 1) if len(pct) > 1 else None
            rec["week"][str(n)] = fnum(pct.iloc[-6], 1) if len(pct) > 5 else None
            rec["month"][str(n)] = fnum(pct.iloc[-22], 1) if len(pct) > 21 else None
            rec["counts"][str(n)] = int(v.iloc[-1])
            rec["history"][str(n)] = _tail(pct, history_days, 1)
        # 52 週淨新高
        nh = is_high[cols].sum(axis=1).astype(float)
        nl = is_low[cols].sum(axis=1).astype(float)
        nv = nh_valid[cols].sum(axis=1).astype(float)
        net = (nh - nl) / nv.replace(0.0, np.nan) * 100.0
        rec["nhnl"] = {"latest": fnum(net.iloc[-1], 2), "prev": fnum(net.iloc[-2], 2) if len(net) > 1 else None,
                       "week": fnum(net.iloc[-6], 2) if len(net) > 5 else None,
                       "nh": int(nh.iloc[-1]), "nl": int(nl.iloc[-1]), "n": int(nv.iloc[-1]),
                       "rank1y": _rank(net), "history": _tail(net, history_days, 2)}
        # McClellan（v = 成交量版，i = 家數版）
        variants = {"i": (up[cols].sum(axis=1).astype(float), down[cols].sum(axis=1).astype(float))}
        if volf is not None:
            variants["v"] = ((volf[cols] * up[cols]).sum(axis=1), (volf[cols] * down[cols]).sum(axis=1))
        rec["mcc"] = {}
        for tag, (a, d) in variants.items():
            tot = (a + d).replace(0.0, np.nan)
            rana = ((a - d) / tot * 1000.0).fillna(0.0)
            osc = rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean()
            summ = 1000.0 + osc.cumsum()
            rec["mcc"][tag] = {
                "osc": _tail(osc, history_days, 1), "sum": _tail(summ, history_days, 0),
                "latest_osc": fnum(osc.iloc[-1], 1), "prev_osc": fnum(osc.iloc[-2], 1) if len(osc) > 1 else None,
                "latest_sum": fnum(summ.iloc[-1], 0), "prev_sum": fnum(summ.iloc[-2], 0) if len(summ) > 1 else None,
                "week_sum": fnum(summ.iloc[-6], 0) if len(summ) > 5 else None,
                "rank1y": _rank(summ), "hi1y": fnum(summ.iloc[-252:].max(), 0), "lo1y": fnum(summ.iloc[-252:].min(), 0),
            }
        out[key] = rec
    # 每檔最新在各均線上方的旗標（bit i 對應 windows[i]）
    flags: dict[str, int] = {}
    last_above = {n: above_all[n].iloc[-1] for n in windows}
    last_valid = {n: valid_all[n].iloc[-1] for n in windows}
    for sym in px.columns:
        b = 0
        for i, n in enumerate(windows):
            if bool(last_valid[n][sym]) and bool(last_above[n][sym]):
                b |= (1 << i)
        flags[sym] = b
    return {"indexes": out, "flags": flags}
