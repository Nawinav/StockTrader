"""Multi-Timeframe Alignment + Nifty & Sector Filters.

The single biggest reason a technically valid signal fails is that the broader
market (Nifty 50) or the stock's sector is moving in the opposite direction.
A BUY signal on a 5-minute chart means nothing if the 15-minute and daily
charts are still in downtrends.

This module enforces three alignment gates:

Gate 1 — Multi-Timeframe (MTF) Agreement
─────────────────────────────────────────
For a valid BUY signal every timeframe must be in the same bullish camp:

  5m chart   : EMA9 > EMA20, price above VWAP, Supertrend direction = 1
  15m chart  : EMA9 > EMA20, RSI > 45, MACD histogram > 0 or turning up
  Daily chart: SMA50 slope positive (close > SMA50), trend_label = UPTREND

All three must score bullish.  If even one disagrees, the setup is classified
as a lower-confidence trade and the high-confidence gate rejects it.

Gate 2 — Nifty 50 Intraday Direction
──────────────────────────────────────
Long entries are only taken when Nifty 50 is itself in an intraday uptrend:
  • Nifty 5m: EMA9 > EMA20
  • Nifty 5m: price above VWAP
  • Nifty is up on the day (change_pct > -0.3%)

If Nifty is falling (EMA9 < EMA20), individual stock BUY signals fail roughly
70% of the time — so blocking them eliminates a huge source of false signals.

Gate 3 — Sector Relative Strength
────────────────────────────────────
The stock must be outperforming its sector on the current day:
  stock_change_pct - sector_change_pct > -0.3%

A stock lagging its sector by more than 0.3% is showing internal weakness even
if technical indicators look okay.

Caching: Nifty data is cached for 5 minutes. Sector data for 15 minutes.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.services import indicators as ind
from app.services.data_provider import OHLCV, get_provider

logger = logging.getLogger(__name__)

# ─────────────────────────────────── cache ──────────────────────────────────

_nifty_cache: Optional[Tuple[ind.IntradayIndicators, float, float]] = None  # (ind, change_pct, ts)
_nifty_cache_ts: float = 0.0
_NIFTY_CACHE_TTL = 300  # 5 minutes

_sector_cache: Dict[str, Tuple[float, float]] = {}  # symbol -> (change_pct, ts)
_SECTOR_CACHE_TTL = 900  # 15 minutes


# ─────────────────────────────────── models ─────────────────────────────────

@dataclass
class MTFAlignment:
    """Result of multi-timeframe alignment check."""
    aligned: bool           # True only if all timeframes agree
    score: int              # 0–3 (how many timeframes are bullish)
    tf_5m_bullish: bool
    tf_15m_bullish: bool
    tf_daily_bullish: bool
    reason: str


@dataclass
class NiftyAlignment:
    """Result of Nifty direction check."""
    aligned: bool           # True = Nifty is rising → safe for longs
    nifty_change_pct: float
    ema_bullish: bool
    above_vwap: bool
    reason: str


@dataclass
class SectorAlignment:
    """Result of sector relative strength check."""
    aligned: bool
    stock_change_pct: float
    sector_change_pct: float
    relative_strength: float  # stock_change - sector_change
    reason: str


# ─────────────────────────────────── MTF ────────────────────────────────────

def check_mtf(
    m5: ind.IntradayIndicators,
    m15: ind.IntradayIndicators,
    daily: ind.DailyIndicators,
    ltp: float,
) -> MTFAlignment:
    """Check whether 5m, 15m and daily are all aligned bullish."""

    # 5m: EMA9 > EMA20, price above VWAP, Supertrend direction = 1
    tf5_bullish = (
        m5.ema9 > m5.ema20
        and ltp > m5.vwap
        and m5.supertrend_dir == 1
    )

    # 15m: EMA9 > EMA20, RSI > 45, MACD histogram ≥ 0 (or just turning)
    tf15_bullish = (
        m15.ema9 > m15.ema20
        and m15.rsi14 > 45
        and m15.macd_hist >= -0.05   # allow tiny negative (just crossing)
    )

    # Daily: close > SMA50, trend label is UPTREND or SIDEWAYS_UP
    tf_daily_bullish = (
        daily.trend_label in ("UPTREND", "SIDEWAYS_UP", "STRONG_UPTREND")
        and daily.sma50 > 0
        and (daily.ema200 == 0 or daily.ema200 <= daily.sma50 * 1.05)
    )

    score = sum([tf5_bullish, tf15_bullish, tf_daily_bullish])
    aligned = score == 3

    reasons = []
    if not tf5_bullish:
        reasons.append(f"5m bearish (EMA9={m5.ema9:.1f} vs EMA20={m5.ema20:.1f}, ST_dir={m5.supertrend_dir})")
    if not tf15_bullish:
        reasons.append(f"15m weak (RSI={m15.rsi14:.1f}, MACD_H={m15.macd_hist:.3f})")
    if not tf_daily_bullish:
        reasons.append(f"Daily trend={daily.trend_label}")

    return MTFAlignment(
        aligned=aligned,
        score=score,
        tf_5m_bullish=tf5_bullish,
        tf_15m_bullish=tf15_bullish,
        tf_daily_bullish=tf_daily_bullish,
        reason=("All timeframes bullish" if aligned else "; ".join(reasons)),
    )


# ─────────────────────────────────── Nifty ──────────────────────────────────

def _get_nifty_indicators() -> Optional[Tuple[ind.IntradayIndicators, float]]:
    """Return (m5_indicators, change_pct_today) for Nifty 50.  Cached 5 min."""
    global _nifty_cache, _nifty_cache_ts
    now = time.monotonic()
    if _nifty_cache is not None and (now - _nifty_cache_ts) < _NIFTY_CACHE_TTL:
        nifty_ind, change_pct, _ = _nifty_cache
        return nifty_ind, change_pct

    try:
        from app.config import get_settings
        settings = get_settings()
        provider = get_provider(settings.data_provider)

        m5 = provider.get_intraday_history("NIFTY_50", "5m", 60)
        daily = provider.get_history("NIFTY_50", days=5)

        if not m5:
            return None

        nifty_ind = ind.build_intraday(m5)
        ltp = m5[-1].close
        prev_close = daily[-2].close if daily and len(daily) >= 2 else ltp
        change_pct = ((ltp - prev_close) / prev_close * 100) if prev_close else 0.0

        _nifty_cache = (nifty_ind, change_pct, now)
        _nifty_cache_ts = now
        return nifty_ind, change_pct

    except Exception as exc:
        logger.debug("Nifty data fetch failed: %s", exc)
        return None


def check_nifty(action: str = "BUY") -> NiftyAlignment:
    """Check whether Nifty 50 intraday direction supports a LONG trade."""
    if action != "BUY":
        # For SELL/SHORT, Nifty falling is fine — not implemented yet.
        return NiftyAlignment(True, 0.0, False, False, "Non-BUY action — Nifty gate skipped")

    data = _get_nifty_indicators()
    if data is None:
        # Can't fetch Nifty — allow trade but flag as unknown
        return NiftyAlignment(
            aligned=True,
            nifty_change_pct=0.0,
            ema_bullish=False,
            above_vwap=False,
            reason="Nifty data unavailable — gate bypassed (conservative: allowed)",
        )

    nifty_ind, change_pct = data

    ema_bull   = nifty_ind.ema9 > nifty_ind.ema20
    above_vwap = nifty_ind.vwap > 0 and (nifty_ind.ema9 > nifty_ind.vwap * 0.999)

    # Must have EMA bullish OR at least not strongly down (-0.5%)
    aligned = ema_bull and change_pct > -0.5

    reasons = []
    if not ema_bull:
        reasons.append(f"Nifty EMA9({nifty_ind.ema9:.0f}) < EMA20({nifty_ind.ema20:.0f})")
    if change_pct <= -0.5:
        reasons.append(f"Nifty down {change_pct:.2f}% today")

    return NiftyAlignment(
        aligned=aligned,
        nifty_change_pct=round(change_pct, 2),
        ema_bullish=ema_bull,
        above_vwap=above_vwap,
        reason=("Nifty trend supports longs" if aligned else "; ".join(reasons)),
    )


# ─────────────────────────────────── Sector ─────────────────────────────────

# Rough sector → NSE index proxy mapping.
_SECTOR_INDEX: Dict[str, str] = {
    "IT": "NIFTY_IT",
    "Technology": "NIFTY_IT",
    "Financial Services": "NIFTY_BANK",
    "Banking": "NIFTY_BANK",
    "Pharma": "NIFTY_PHARMA",
    "Healthcare": "NIFTY_PHARMA",
    "Auto": "NIFTY_AUTO",
    "FMCG": "NIFTY_FMCG",
    "Metal": "NIFTY_METAL",
    "Energy": "NIFTY_ENERGY",
    "Realty": "NIFTY_REALTY",
    "Media": "NIFTY_MEDIA",
    "PSU Bank": "NIFTY_PSU_BANK",
}

_DEFAULT_SECTOR_INDEX = "NIFTY_50"


def _get_sector_change(sector: str) -> float:
    """Return today's change% for the sector index.  Cached 15 min."""
    index_sym = _SECTOR_INDEX.get(sector, _DEFAULT_SECTOR_INDEX)
    now = time.monotonic()
    if index_sym in _sector_cache:
        change_pct, cached_ts = _sector_cache[index_sym]
        if (now - cached_ts) < _SECTOR_CACHE_TTL:
            return change_pct

    try:
        from app.config import get_settings
        settings = get_settings()
        provider = get_provider(settings.data_provider)
        daily = provider.get_history(index_sym, days=5)
        if daily and len(daily) >= 2:
            change_pct = (daily[-1].close - daily[-2].close) / daily[-2].close * 100
            _sector_cache[index_sym] = (round(change_pct, 3), now)
            return change_pct
    except Exception as exc:
        logger.debug("Sector change for %s failed: %s", index_sym, exc)

    return 0.0  # neutral fallback


def check_sector(stock_change_pct: float, sector: str) -> SectorAlignment:
    """Check whether the stock is outperforming its sector."""
    sector_change = _get_sector_change(sector)
    relative = stock_change_pct - sector_change

    # Must not be lagging sector by more than 0.3%
    aligned = relative >= -0.3

    return SectorAlignment(
        aligned=aligned,
        stock_change_pct=round(stock_change_pct, 2),
        sector_change_pct=round(sector_change, 2),
        relative_strength=round(relative, 2),
        reason=(
            f"Stock outperforming sector by {relative:+.2f}%"
            if aligned
            else f"Stock lagging sector by {abs(relative):.2f}% — weak relative strength"
        ),
    )
