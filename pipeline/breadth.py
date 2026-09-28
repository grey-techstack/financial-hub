"""參與度（市場寬度）：各指數成分股站上 N 日均線的比例，含最近一年的每日歷史。"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from common import fnum
from registry import MA_WINDOWS

LOG = logging.getLogger("breadth")


def build_close_frame(charts: dict[str, dict], calendar: list[str]) -> pd.DataFrame:
    """columns = 代號, index = 交易日曆（字串日期）, 值 = 收盤價（缺值 NaN）。"""
    cal = pd.Index(calendar)
    cols: dict[str, pd.Series] = {}
    for sym, ch in charts.items():
        if not ch or not ch.get("close"):
            continue
        s = pd.Series(ch["close"], index=pd.Index(ch["dates"]), dtype="float64")
        s = s[~s.index.duplicated(keep="last")]
        cols[sym] = s.reindex(cal)
    df = pd.DataFrame(cols, index=cal)
    LOG.info("close frame: %d 檔 x %d 日", df.shape[1], df.shape[0])
    return df


def compute_breadth(df: pd.DataFrame, members: dict[str, list[str]], windows: list[int] | None = None,
                    history_days: int = 252) -> dict:
    """回傳 {key: {"latest": {win: pct}, "prev": {...}, "week": {...}, "month": {...}, "counts": {win: n},
                  "history": {"dates": [...], win: [...]}, "priced": n, "members": n}, "flags": {sym: bitmask}}"""
    windows = windows or MA_WINDOWS
    px = df.ffill(limit=5)  # 停牌等短暫缺值以前值補上
    above_all: dict[int, pd.DataFrame] = {}
    valid_all: dict[int, pd.DataFrame] = {}
    for n in windows:
        ma = px.rolling(n, min_periods=n).mean()
        above_all[n] = px > ma
        valid_all[n] = ma.notna() & px.notna()
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
            rec["history"][str(n)] = [fnum(x, 1) for x in pct.iloc[-history_days:].tolist()]
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
