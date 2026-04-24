"""Independent Signal Sources — genuinely orthogonal to OHLCV price data.

These two signals are sourced from options market activity and institutional
fund flows.  They cannot correlate with the 9 price/volume strategies because
they measure *different market participants' behaviour*:

  Signal A — Options Put/Call Ratio (PCR)
  ─────────────────────────────────────────
  Source  : NSE options chain for Nifty 50 (most liquid market proxy)
  Logic   : PCR = Total Put OI / Total Call OI
            PCR < 0.7  → heavy call buying → market bullish → vote BULLISH (+1)
            PCR 0.7–1.1 → neutral / balanced → vote NEUTRAL (0)
            PCR > 1.1  → heavy put buying  → market fearful  → vote BEARISH (-1)

  Why orthogonal: options OI is driven by hedgers and speculators making bets
  about *future* price movement, not by past OHLCV patterns.

  Signal B — FII (Foreign Institutional Investor) Net Flow
  ─────────────────────────────────────────────────────────
  Source  : NSE FII/DII daily participation data
  Logic   : FII net buy > +₹500 Cr → institutions accumulating → BULLISH (+1)
            FII net sell < -₹500 Cr → institutions distributing → BEARISH (-1)
            otherwise → neutral (0)

  Why orthogonal: FII flows reflect global macro positioning, EM fund in/outflows,
  currency views — none of which are captured by any OHLCV indicator.

Both signals are cached for 30 minutes (they update once per NSE session).
The results are returned as a list of StrategyResult-compatible dicts that
algo_engine.run() appends to its vote list before computing confluence.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────── constants ──────────────────────────────

PCR_BULLISH_THRESHOLD = 0.70   # below = heavy call buying = bullish
PCR_BEARISH_THRESHOLD = 1.10   # above = heavy put buying  = bearish

FII_BULL_CRORE  =  500.0   # net buy  > this → bullish
FII_BEAR_CRORE  = -500.0   # net sell < this → bearish

CACHE_TTL = 30 * 60  # 30 minutes

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


# ─────────────────────────────────── models ──────────────────────────────────

@dataclass
class IndependentVote:
    """One independent strategy vote — mirrors algo_engine.StrategyResult."""
    name: str
    tag: str
    direction: int    # 1 = bullish, -1 = bearish, 0 = neutral
    direction_label: str
    reason: str
    data_available: bool = True


# ─────────────────────────────────── cache ───────────────────────────────────

_pcr_cache: Optional[Tuple[float, float]] = None      # (pcr_value, monotonic_ts)
_fii_cache: Optional[Tuple[float, float]] = None      # (net_crore, monotonic_ts)


def _stale(ts: float) -> bool:
    return (time.monotonic() - ts) > CACHE_TTL


# ─────────────────────────────────── PCR ────────────────────────────────────

def _fetch_pcr() -> Optional[float]:
    """Fetch Nifty 50 options chain and compute PCR.  Returns None on failure."""
    try:
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        req = urllib.request.Request(url, headers=_NSE_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read())

        records = data.get("records", {}).get("data", [])
        total_call_oi = 0
        total_put_oi  = 0
        for rec in records:
            ce = rec.get("CE", {})
            pe = rec.get("PE", {})
            total_call_oi += ce.get("openInterest", 0)
            total_put_oi  += pe.get("openInterest", 0)

        if total_call_oi == 0:
            return None
        return round(total_put_oi / total_call_oi, 3)

    except Exception as exc:
        logger.debug("PCR fetch failed: %s", exc)
        return None


def get_pcr() -> Optional[float]:
    global _pcr_cache
    if _pcr_cache is not None and not _stale(_pcr_cache[1]):
        return _pcr_cache[0]
    val = _fetch_pcr()
    if val is not None:
        _pcr_cache = (val, time.monotonic())
    return val


def _pcr_vote() -> IndependentVote:
    pcr = get_pcr()

    if pcr is None:
        return IndependentVote(
            name="Options PCR",
            tag="OPTIONS_PCR",
            direction=0,
            direction_label="NEUTRAL",
            reason="PCR data unavailable — vote withheld",
            data_available=False,
        )

    if pcr < PCR_BULLISH_THRESHOLD:
        return IndependentVote(
            name="Options PCR",
            tag="OPTIONS_PCR",
            direction=1,
            direction_label="BULLISH",
            reason=f"PCR {pcr:.2f} < {PCR_BULLISH_THRESHOLD} — heavy call buying, market bullish",
        )
    elif pcr > PCR_BEARISH_THRESHOLD:
        return IndependentVote(
            name="Options PCR",
            tag="OPTIONS_PCR",
            direction=-1,
            direction_label="BEARISH",
            reason=f"PCR {pcr:.2f} > {PCR_BEARISH_THRESHOLD} — heavy put buying, market fearful",
        )
    else:
        return IndependentVote(
            name="Options PCR",
            tag="OPTIONS_PCR",
            direction=0,
            direction_label="NEUTRAL",
            reason=f"PCR {pcr:.2f} in neutral zone ({PCR_BULLISH_THRESHOLD}–{PCR_BEARISH_THRESHOLD})",
        )


# ─────────────────────────────────── FII/DII ─────────────────────────────────

def _fetch_fii_net() -> Optional[float]:
    """Fetch FII net buy/sell (in crore INR) from NSE.  Returns None on failure."""
    try:
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        req = urllib.request.Request(url, headers=_NSE_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read())

        # Response is a list; find the FII row for 'Equity'
        for row in (data if isinstance(data, list) else []):
            category = (row.get("category") or row.get("clientType") or "").upper()
            if "FII" in category or "FPI" in category:
                # Net value field names vary
                net = (
                    row.get("netValue")
                    or row.get("net")
                    or row.get("netPurchase")
                    or row.get("net_value")
                )
                if net is not None:
                    try:
                        # Values are sometimes formatted with commas
                        return float(str(net).replace(",", ""))
                    except (ValueError, TypeError):
                        pass

    except Exception as exc:
        logger.debug("FII fetch failed: %s", exc)
    return None


def get_fii_net() -> Optional[float]:
    global _fii_cache
    if _fii_cache is not None and not _stale(_fii_cache[1]):
        return _fii_cache[0]
    val = _fetch_fii_net()
    if val is not None:
        _fii_cache = (val, time.monotonic())
    return val


def _fii_vote() -> IndependentVote:
    net = get_fii_net()

    if net is None:
        return IndependentVote(
            name="FII Institutional Flow",
            tag="FII_FLOW",
            direction=0,
            direction_label="NEUTRAL",
            reason="FII data unavailable — vote withheld",
            data_available=False,
        )

    if net > FII_BULL_CRORE:
        return IndependentVote(
            name="FII Institutional Flow",
            tag="FII_FLOW",
            direction=1,
            direction_label="BULLISH",
            reason=f"FII net +₹{net:,.0f}Cr — strong institutional accumulation",
        )
    elif net < FII_BEAR_CRORE:
        return IndependentVote(
            name="FII Institutional Flow",
            tag="FII_FLOW",
            direction=-1,
            direction_label="BEARISH",
            reason=f"FII net ₹{net:,.0f}Cr — institutional distribution / selling",
        )
    else:
        return IndependentVote(
            name="FII Institutional Flow",
            tag="FII_FLOW",
            direction=0,
            direction_label="NEUTRAL",
            reason=f"FII net ₹{net:,.0f}Cr — within neutral band",
        )


# ─────────────────────────────────── public API ──────────────────────────────

def get_votes() -> List[IndependentVote]:
    """Return both independent votes (PCR + FII).

    Each vote with direction != 0 counts towards (or against) confluence in
    algo_engine.run().  Neutral votes (direction == 0) are excluded from the
    confluence count — they neither help nor hurt.
    """
    return [_pcr_vote(), _fii_vote()]


def invalidate_caches() -> None:
    global _pcr_cache, _fii_cache
    _pcr_cache = None
    _fii_cache = None
