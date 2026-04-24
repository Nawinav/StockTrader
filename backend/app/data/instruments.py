"""Mapping from NSE trading symbol -> Upstox instrument_key.

Upstox identifies instruments as ``NSE_EQ|<ISIN>`` for NSE equities (and
``BSE_EQ|<ISIN>`` for BSE). The source of truth is Upstox's own
instruments dump, which we download on first use and cache to disk:

    https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz

Loading priority:
  1. ``UPSTOX_INSTRUMENTS_PATH`` (explicit local CSV/JSON override)
  2. Downloaded instruments file (cached at ``backend/upstox_instruments.json``)
  3. Hardcoded fallback map below

The hardcoded map stays as a last-resort fallback so the app still boots
if the Upstox CDN is down, but ISINs there can go stale — always prefer
the live instruments feed.
"""
from __future__ import annotations

import csv
import gzip
import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict

import httpx

logger = logging.getLogger(__name__)

UPSTOX_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
)

# Cached to the backend working directory.
INSTRUMENTS_CACHE = Path("upstox_instruments.json")
# Re-download after this many seconds (7 days — symbols rarely change).
INSTRUMENTS_TTL_SECONDS = 7 * 24 * 3600


# ── NSE Index instrument keys (never in the equity instruments feed) ─────────
# These are fixed by Upstox — they don't change with ISIN updates.
_NSE_INDEX_KEYS: Dict[str, str] = {
    "NIFTY_50":       "NSE_INDEX|Nifty 50",
    "NIFTY50":        "NSE_INDEX|Nifty 50",
    "NIFTY":          "NSE_INDEX|Nifty 50",
    "NIFTY_BANK":     "NSE_INDEX|Nifty Bank",
    "NIFTYBANK":      "NSE_INDEX|Nifty Bank",
    "NIFTY_IT":       "NSE_INDEX|Nifty IT",
    "NIFTYIT":        "NSE_INDEX|Nifty IT",
    "NIFTY_PHARMA":   "NSE_INDEX|Nifty Pharma",
    "NIFTY_AUTO":     "NSE_INDEX|Nifty Auto",
    "NIFTY_FMCG":     "NSE_INDEX|Nifty FMCG",
    "NIFTY_METAL":    "NSE_INDEX|Nifty Metal",
    "NIFTY_ENERGY":   "NSE_INDEX|Nifty Energy",
    "NIFTY_REALTY":   "NSE_INDEX|Nifty Realty",
    "NIFTY_MEDIA":    "NSE_INDEX|Nifty Media",
    "NIFTY_PSU_BANK": "NSE_INDEX|Nifty PSU Bank",
    "INDIA_VIX":      "NSE_INDEX|India VIX",
}

# Hardcoded fallback — used only if the live download fails AND no
# override CSV is set. Can drift; prefer the live feed.
_FALLBACK_NSE_ISIN: Dict[str, str] = {
    "RELIANCE":   "INE002A01018",
    "TCS":        "INE467B01029",
    "HDFCBANK":   "INE040A01034",
    "INFY":       "INE009A01021",
    "ICICIBANK":  "INE090A01021",
    "HINDUNILVR": "INE030A01027",
    "ITC":        "INE154A01025",
    "LT":         "INE018A01030",
    "SBIN":       "INE062A01020",
    "BHARTIARTL": "INE397D01024",
    "KOTAKBANK":  "INE237A01028",
    "AXISBANK":   "INE238A01034",
    "ASIANPAINT": "INE021A01026",
    "MARUTI":     "INE585B01010",
    "BAJFINANCE": "INE296A01024",
    "SUNPHARMA":  "INE044A01036",
    "TITAN":      "INE280A01028",
    "ULTRACEMCO": "INE481G01011",
    "NESTLEIND":  "INE239A01016",
    "WIPRO":      "INE075A01022",
    "POWERGRID":  "INE752E01010",
    "NTPC":       "INE733E01010",
    "ONGC":       "INE213A01029",
    "COALINDIA":  "INE522F01014",
    "TATAMOTORS": "INE155A01022",
    "TATASTEEL":  "INE081A01020",
    "JSWSTEEL":   "INE019A01038",
    "HCLTECH":    "INE860A01027",
    "TECHM":      "INE669C01036",
    "ADANIENT":   "INE423A01024",
    "ADANIPORTS": "INE742F01042",
    "DIVISLAB":   "INE361B01024",
    "DRREDDY":    "INE089A01031",
    "CIPLA":      "INE059A01026",
    "BAJAJFINSV": "INE918I01026",
    "HEROMOTOCO": "INE158A01026",
    "EICHERMOT":  "INE066A01021",
    "BPCL":       "INE029A01011",
    "GRASIM":     "INE047A01021",
    "BRITANNIA":  "INE216A01030",
}


def _cache_is_fresh() -> bool:
    if not INSTRUMENTS_CACHE.exists():
        return False
    age = time.time() - INSTRUMENTS_CACHE.stat().st_mtime
    return age < INSTRUMENTS_TTL_SECONDS


def _download_instruments() -> list[dict] | None:
    """Fetch Upstox's complete instruments list. Returns parsed JSON rows
    on success, ``None`` on any failure (caller falls back to cache/map)."""
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(UPSTOX_INSTRUMENTS_URL)
        if resp.status_code != 200:
            logger.warning("Upstox instruments download: HTTP %s", resp.status_code)
            return None
        raw = gzip.decompress(resp.content)
        rows = json.loads(raw)
        if not isinstance(rows, list):
            logger.warning("Upstox instruments: unexpected payload shape")
            return None
        return rows
    except Exception as exc:  # network / gzip / json errors
        logger.warning("Upstox instruments download failed: %s", exc)
        return None


def _refresh_cache() -> Dict[str, str]:
    """Download, filter to NSE equities, save JSON, return map."""
    rows = _download_instruments()
    if rows is None:
        return {}
    mapping: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        seg = (row.get("segment") or "").upper()
        itype = (row.get("instrument_type") or "").upper()
        if seg != "NSE_EQ" or itype not in ("EQ", "EQUITY"):
            continue
        sym = (row.get("trading_symbol") or row.get("tradingsymbol") or "").upper()
        key = row.get("instrument_key") or ""
        if sym and key:
            mapping[sym] = key
    if mapping:
        try:
            INSTRUMENTS_CACHE.write_text(json.dumps(mapping, indent=0))
        except OSError as exc:
            logger.warning("Could not write instruments cache: %s", exc)
    return mapping


def _load_cache() -> Dict[str, str]:
    if not INSTRUMENTS_CACHE.exists():
        return {}
    try:
        data = json.loads(INSTRUMENTS_CACHE.read_text())
        if isinstance(data, dict):
            return {str(k).upper(): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read instruments cache: %s", exc)
    return {}


def _load_csv_overrides(path: str) -> Dict[str, str]:
    """Optional: ``tradingsymbol -> instrument_key`` from a user-supplied CSV."""
    overrides: Dict[str, str] = {}
    if not os.path.exists(path):
        return overrides
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts = (row.get("tradingsymbol") or row.get("trading_symbol") or "").strip().upper()
            ik = (row.get("instrument_key") or row.get("instrument_token") or "").strip()
            exch = (row.get("exchange") or row.get("segment") or "").strip().upper()
            if not ts or not ik:
                continue
            if exch and "NSE" not in exch:
                continue
            overrides[ts] = ik
    return overrides


@lru_cache(maxsize=1)
def _symbol_map() -> Dict[str, str]:
    """Build the authoritative ``symbol -> instrument_key`` map.

    Priority:
      1. Fallback (hardcoded) — seeds the map.
      2. Upstox instruments feed (overwrites fallback entries).
      3. User CSV at ``UPSTOX_INSTRUMENTS_PATH`` (overwrites everything).
    """
    mapping: Dict[str, str] = {
        sym: f"NSE_EQ|{isin}" for sym, isin in _FALLBACK_NSE_ISIN.items()
    }

    # 2) Upstox feed — use cache if fresh, else download.
    feed: Dict[str, str] = {}
    if _cache_is_fresh():
        feed = _load_cache()
    if not feed:
        feed = _refresh_cache()
        if not feed:
            # Download failed; fall back to stale cache if we have one.
            feed = _load_cache()
    mapping.update(feed)

    # 3) User override.
    path = os.environ.get("UPSTOX_INSTRUMENTS_PATH", "").strip()
    if path:
        mapping.update(_load_csv_overrides(path))

    return mapping


def refresh_instruments() -> int:
    """Force a re-download of the Upstox instruments feed.

    Returns the number of NSE-equity symbols loaded. Clears the
    in-memory ``@lru_cache`` so subsequent ``instrument_key`` calls see
    the fresh data.
    """
    try:
        INSTRUMENTS_CACHE.unlink(missing_ok=True)
    except OSError:
        pass
    _symbol_map.cache_clear()
    return len(_symbol_map())


def instrument_key(symbol: str) -> str:
    """Return the Upstox instrument_key for an NSE trading symbol or index.

    Checks NSE indices first (e.g. NIFTY_50 → 'NSE_INDEX|Nifty 50'), then
    the equity instruments feed.  Raises ``KeyError`` if unknown.
    """
    sym = symbol.upper().strip()
    # Indices use a fixed key format — check before hitting the equity feed.
    if sym in _NSE_INDEX_KEYS:
        return _NSE_INDEX_KEYS[sym]
    mapping = _symbol_map()
    if sym not in mapping:
        raise KeyError(
            f"No Upstox instrument_key for symbol {sym!r}. "
            "Symbol may not be listed on NSE or the instruments feed is stale — "
            "try hitting /auth/upstox/refresh-instruments or set UPSTOX_INSTRUMENTS_PATH."
        )
    return mapping[sym]


def known_symbols() -> list[str]:
    return sorted(_symbol_map().keys())
