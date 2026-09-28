"""指數清單、別名、ETF 代理、總經序列：整個專案的「設定中心」。"""
from __future__ import annotations

# key: 內部代號；name: 顯示名；yahoo: Yahoo 指數代號；source: constituents.py 的成分股來源；
# approx: 成分股為近似（以市值排名 / 交易所上市清單推估，非官方名單）
INDEXES: list[dict] = [
    {"key": "DJI",  "name": "道瓊工業",        "en": "Dow Jones Industrial", "yahoo": "^DJI",    "source": "dow",         "approx": False, "etf": "DIA"},
    {"key": "SPX",  "name": "S&P 500",         "en": "S&P 500",              "yahoo": "^GSPC",   "source": "sp500",       "approx": False, "etf": "SPY"},
    {"key": "NDX",  "name": "NASDAQ 100",      "en": "Nasdaq-100",           "yahoo": "^NDX",    "source": "ndx",         "approx": False, "etf": "QQQ"},
    {"key": "COMP", "name": "NASDAQ 綜合",     "en": "Nasdaq Composite",     "yahoo": "^IXIC",   "source": "nasdaq_comp", "approx": True,  "etf": "ONEQ"},
    {"key": "NYA",  "name": "NYSE 綜合",       "en": "NYSE Composite",       "yahoo": "^NYA",    "source": "nyse_comp",   "approx": True,  "etf": None},
    {"key": "SOX",  "name": "費城半導體",      "en": "PHLX Semiconductor",   "yahoo": "^SOX",    "source": "sox",         "approx": False, "etf": "SOXX"},
    {"key": "RUI",  "name": "Russell 1000",    "en": "Russell 1000",         "yahoo": "^RUI",    "source": "r1000",       "approx": True,  "etf": "IWB"},
    {"key": "RUT",  "name": "Russell 2000",    "en": "Russell 2000",         "yahoo": "^RUT",    "source": "r2000",       "approx": True,  "etf": "IWM"},
    {"key": "RUA",  "name": "Russell 3000",    "en": "Russell 3000",         "yahoo": "^RUA",    "source": "r3000",       "approx": True,  "etf": "IWV"},
    {"key": "MID",  "name": "S&P 400 中型股",  "en": "S&P MidCap 400",       "yahoo": "^MID",    "source": "sp400",       "approx": False, "etf": "MDY"},
    {"key": "SML",  "name": "S&P 600 小型股",  "en": "S&P SmallCap 600",     "yahoo": "^SP600",  "source": "sp600",       "approx": False, "etf": "IJR"},
    {"key": "TSX",  "name": "S&P/TSX 綜合",    "en": "S&P/TSX Composite",    "yahoo": "^GSPTSE", "source": "tsx",         "approx": True,  "etf": "XIC.TO"},
]
INDEX_BY_KEY = {x["key"]: x for x in INDEXES}
INDEX_BY_YAHOO = {x["yahoo"]: x for x in INDEXES}

# 會計算「指數層級 forward PE」並每日累積歷史的指數（成分股名單可靠、分析師覆蓋率高）
PE_INDEXES = ["DJI", "SPX", "NDX", "SOX", "MID", "SML", "RUT", "COMP", "TSX"]
# 每日抓分析師預估（NTM 混合 PE）並累積個股 PE 歷史的個股範圍 = 這些指數的成分股 ∪ watchlist
PE_UNIVERSE_INDEXES = ["DJI", "SPX", "NDX", "SOX"]

# 移動平均視窗（交易日）
MA_WINDOWS = [10, 20, 50, 100, 150, 200, 250]

# 查詢時的別名（大小寫不拘）-> 指數 key 或 Yahoo 代號
ALIASES: dict[str, str] = {
    "SOX": "SOX", "^SOX": "SOX", "費半": "SOX", "費城半導體": "SOX", "半導體": "SOX", "SEMI": "SOX",
    "SPX": "SPX", "^GSPC": "SPX", "SP500": "SPX", "S&P500": "SPX", "S&P 500": "SPX", "標普": "SPX", "標普500": "SPX", "SPY": "SPX",
    "NDX": "NDX", "^NDX": "NDX", "NASDAQ100": "NDX", "NASDAQ 100": "NDX", "NAS100": "NDX", "那斯達克100": "NDX", "QQQ": "NDX",
    "COMP": "COMP", "^IXIC": "COMP", "IXIC": "COMP", "NASDAQ": "COMP", "那斯達克": "COMP", "CCMP": "COMP",
    "NYA": "NYA", "^NYA": "NYA", "NYSE": "NYA",
    "DJI": "DJI", "^DJI": "DJI", "DJIA": "DJI", "DOW": "DJI", "DOW JONES": "DJI", "道瓊": "DJI", "INDU": "DJI", "DIA": "DJI",
    "RUI": "RUI", "^RUI": "RUI", "RUSSELL 1000": "RUI", "R1000": "RUI",
    "RUT": "RUT", "^RUT": "RUT", "RUSSELL 2000": "RUT", "R2000": "RUT", "RTY": "RUT", "IWM": "RUT", "羅素2000": "RUT",
    "RUA": "RUA", "^RUA": "RUA", "RUSSELL 3000": "RUA", "R3000": "RUA",
    "MID": "MID", "^MID": "MID", "SP400": "MID", "S&P 400": "MID", "MDY": "MID",
    "SML": "SML", "^SP600": "SML", "SP600": "SML", "S&P 600": "SML", "IJR": "SML",
    "TSX": "TSX", "^GSPTSE": "TSX", "SPTSX": "TSX", "TSX COMPOSITE": "TSX",
    "VIX": "^VIX", "^VIX": "^VIX", "MOVE": "^MOVE", "^MOVE": "^MOVE",
    "GOLD": "GC=F", "黃金": "GC=F", "XAU": "GC=F", "GC=F": "GC=F",
    "US10Y": "^TNX", "TNX": "^TNX", "^TNX": "^TNX",
}

# 總經 / 波動率序列
FRED_SERIES = {
    "DFII10": {"name": "美國 10 年期實質利率 (TIPS)", "unit": "%"},
    "DGS10":  {"name": "美國 10 年期公債殖利率", "unit": "%"},
    "T10YIE": {"name": "10 年期通膨預期 (Breakeven)", "unit": "%"},
    "DGS2":   {"name": "美國 2 年期公債殖利率", "unit": "%"},
}
YAHOO_SERIES = {
    "GOLD": {"symbol": "GC=F",  "name": "黃金期貨 (COMEX 近月)", "unit": "USD/oz"},
    "MOVE": {"symbol": "^MOVE", "name": "MOVE 指數 (美債波動率)", "unit": ""},
    "VIX":  {"symbol": "^VIX",  "name": "VIX 指數 (美股波動率)", "unit": ""},
    "TNX":  {"symbol": "^TNX",  "name": "10 年期美債殖利率 (CBOE)", "unit": "%"},
    "DXY":  {"symbol": "DX-Y.NYB", "name": "美元指數", "unit": ""},
}
