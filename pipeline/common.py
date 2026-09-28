"""共用工具：路徑、JSON/CSV 讀寫、日誌。"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HIST = DATA / "history"
REPORTS = ROOT / "reports"
CONFIG = ROOT / "config"

for _p in (DATA, HIST, HIST / "pe", REPORTS):
    _p.mkdir(parents=True, exist_ok=True)


def setup_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=getattr(logging, (level or os.environ.get("LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def today() -> dt.date:
    """資料日期：以美東時間為準（UTC 早上跑時仍算前一交易日的資料）。"""
    return dt.datetime.now(dt.timezone.utc).date()


def read_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1, allow_nan=False)
    os.replace(tmp, path)


def read_csv_rows(path: Path) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def upsert_csv(path: Path, rows: list[dict], key_fields: tuple[str, ...], fieldnames: list[str]) -> None:
    """把 rows 併入 CSV：同 key 的舊列被取代（同一天重跑不會重複）。"""
    existing = read_csv_rows(path)
    new_keys = {tuple(r[k] for k in key_fields) for r in rows}
    kept = [r for r in existing if tuple(r.get(k, "") for k in key_fields) not in new_keys]
    merged = kept + rows
    merged.sort(key=lambda r: tuple(r.get(k, "") for k in key_fields))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    os.replace(tmp, path)


def fnum(x, nd: int = 2):
    """JSON 友善的數字：None/NaN -> None，其餘四捨五入。"""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return round(v, nd)


def read_watchlist() -> list[str]:
    path = CONFIG / "watchlist.txt"
    out: list[str] = []
    try:
        for line in open(path, encoding="utf-8"):
            s = line.split("#", 1)[0].strip().upper()
            if s:
                out.append(s)
    except FileNotFoundError:
        pass
    return out
