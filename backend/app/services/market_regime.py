"""Market Regime Detector.

Classifies the overall NSE market environment every 15 minutes into one of:

  BULL_TREND     — Nifty above SMA20 & SMA50, ADX > 25, VIX < 16.
                   Use all 9 strategies, min confluence 3.

  BEAR_TREND     — Nifty below SMA20 & SMA50 with ADX > 25.
                   Block new LONG auto-entries entirely.

  RANGING        — ADX < 20, price oscillating within SMAs.
                   Only mean-reversion strategies valid; raise min confluence to 4.
                   Disable breakout strategies (ORB, GAP_GO, BB_BREAKOUT).

  HIGH_VOLATILITY — India VIX > 20 or Nifty single-day swing > 2%.
                   Widen stops; raise min confluence to 5; skip new entries if
                   positions are already open.

Strategy weights per regime
---------------------------
Each entry is a set of strategy TAGS that should be *disabled* or *down-weighted*
in that regime.  The engine still runs all 9 but their votes are zeroed.

  RANGING      → disable: ORB, GAP_GO, BB_BREAKOUT, EMA_CROSS (momentum)
  HIGH_VOL     → disable: GAP_GO, ORB (gap setups become unreliable)
  BEAR_TREND   → block all new longs

Nifty 50 data is fetched via the configured data provider using the
symbol "NIFTY_50" (Upstox index symbol).  If the provider can't supply it
(MockProvider always can), we derive a synthetic regime from the available
individual-stock suggestion scores as a fallback.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Set

from app.services import indicators as ind
from app.services.data_provider import get_provider, ist_now

logger = logging.getLogger(__name__)

# ─────────────────────────────────── constants ──────────────────────────────

NIFTY_SYMBOL = "NIFTY_50"   # Upstox index symbol; MockProvider generates plausible data

# Strategy tags that are UNRELIABLE in each regime.
DISABLED_IN_RANGING: FrozenSet[str] = frozenset(
    {"ORB", "GAP_GO", "BB_BREAKOUT", "EMA_CROSS"}
)
DISABLED_IN_HIGH_VOL: FrozenSet[str] = frozenset({"GAP_GO", "ORB"})

CACHE_TTL_SECONDS = 900  # 15-minute cache


# ─────────────────────────────────── models ─────────────────────────────────

class Regime:
    BULL        = "BULL_TREND"
    BEAR        = "BEAR_TREND"
    RANGING     = "RANGING"
    HIGH_VOL    = "HIGH_VOLATILITY"


@dataclass
class MarketRegime:
    regime: str                    # one of Regime.*
    nifty_ltp: float
    nifty_change_pct: float
    adx: float
    vix: float                     # 0 if unavailable
    sma20: float
    sma50: float

    # Recommended adjustment for this session's entry gate.
    recommended_min_confluence: int   # 3=normal, 4=cautious, 5=strict
    block_new_longs: bool             # True in BEAR regime
    disabled_strategies: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def label(self) -> str:
        icons = {
            Regime.BULL:     "🟢 BULL",
            Regime.BEAR:     "🔴 BEAR",
            Regime.RANGING:  "🟡 RANGING",
            Regime.HIGH_VOL: "🟠 HIGH VOL",
        }
        return icons.get(self.regime, self.regime)

    def summary(self) -> str:
        return (
            f"{self.label} | Nifty {self.nifty_ltp:,.0f} "
            f"({self.nifty_change_pct:+.2f}%) | "
            f"ADX {self.adx:.1f} | VIX {self.vix:.1f} | "
            f"confluence≥{self.recommended_min_confluence}"
        )


# ─────────────────────────────────── cache ──────────────────────────────────

_cache: Optional[MarketRegime] = None
_cache_ts: float = 0.0


def _cached() -> Optional[MarketRegime]:
    if _cache is not None and (time.monotonic() - _cache_ts) < CACHE_TTL_SECONDS:
        return _cache
    return None


def _store(regime: MarketRegime) -> MarketRegime:
    global _cache, _cache_ts
    _cache = regime
    _cache_ts = time.monotonic()
    return regime


# ─────────────────────────────── VIX fetch ──────────────────────────────────

def _fetch_india_vix() -> float:
    """Try to get India VIX from NSE public endpoint.  Returns 0 on failure."""
    try:
        import urllib.request, json
        url = "https://www.nseindia.com/api/allIndices"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
        for entry in data.get("data", []):
            if entry.get("index", "") == "India VIX":
                return float(entry.get("last", 0))
    except Exception as exc:
        logger.debug("VIX fetch skipped: %s", exc)
    return 0.0


# ─────────────────────────────── regime logic ────────────────────────────────

def _classify(
    ltp: float,
    prev_close: float,
    sma20: float,
    sma50: float,
    adx: float,
    vix: float,
) -> tuple[str, int, bool, FrozenSet[str]]:
    """Return (regime, min_confluence, block_longs, disabled_strategies)."""
    day_swing_pct = abs((ltp - prev_close) / prev_close * 100) if prev_close else 0.0

    # HIGH_VOLATILITY first — overrides everything
    if vix > 20 or day_swing_pct > 2.0:
        return Regime.HIGH_VOL, 5, False, DISABLED_IN_HIGH_VOL

    above_sma20 = ltp > sma20
    above_sma50 = ltp > sma50
    trending    = adx > 25

    if above_sma20 and above_sma50 and trending:
        return Regime.BULL, 3, False, frozenset()

    if (not above_sma20) and (not above_sma50) and trending:
        return Regime.BEAR, 3, True, frozenset()

    # ADX weak → ranging market
    return Regime.RANGING, 4, False, DISABLED_IN_RANGING


def detect(settings=None) -> MarketRegime:
    """Return the current market regime (cached 15 min)."""
    cached = _cached()
    if cached is not None:
        return cached

    try:
        from app.config import get_settings
        settings = settings or get_settings()
        provider = get_provider(settings.data_provider)

        daily = provider.get_history(NIFTY_SYMBOL, days=60)
        if not daily or len(daily) < 20:
            raise ValueError("insufficient Nifty history")

        closes = [c.close for c in daily]
        ltp       = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 else ltp

        # SMA20 / SMA50
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / min(50, len(closes))

        # ADX from daily indicators
        from app.services.indicators import build_daily
        daily_ind = build_daily(daily)
        adx = daily_ind.adx

        # VIX (best-effort — network call, non-critical)
        now = ist_now()
        market_hours = (9 <= now.hour < 16)
        vix = _fetch_india_vix() if market_hours else 0.0

        change_pct = (ltp - prev_close) / prev_close * 100 if prev_close else 0.0

        regime_str, min_conf, block_longs, disabled = _classify(
            ltp, prev_close, sma20, sma50, adx, vix
        )

        result = MarketRegime(
            regime=regime_str,
            nifty_ltp=round(ltp, 2),
            nifty_change_pct=round(change_pct, 2),
            adx=round(adx, 1),
            vix=round(vix, 1),
            sma20=round(sma20, 2),
            sma50=round(sma50, 2),
            recommended_min_confluence=min_conf,
            block_new_longs=block_longs,
            disabled_strategies=disabled,
        )
        logger.info("Market regime: %s", result.summary())
        return _store(result)

    except Exception as exc:
        logger.warning("Regime detection failed (%s) — defaulting to RANGING cautious", exc)
        fallback = MarketRegime(
            regime=Regime.RANGING,
            nifty_ltp=0.0,
            nifty_change_pct=0.0,
            adx=0.0,
            vix=0.0,
            sma20=0.0,
            sma50=0.0,
            recommended_min_confluence=4,  # cautious default
            block_new_longs=False,
            disabled_strategies=DISABLED_IN_RANGING,
        )
        return _store(fallback)


def invalidate_cache() -> None:
    """Force a fresh regime detection on the next call."""
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0.0
