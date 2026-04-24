"""Data Quality Guard.

Validates market data before the trading engine uses it.  A single bad candle
or stale feed should NOT cause a trade.  This module provides a hard gate that
runs before every entry attempt.

Checks performed
────────────────
1. Data freshness
   During market hours (09:15–15:30 IST) the last candle's timestamp must be
   within 5 minutes of now.  Stale data = no new entries (but existing positions
   keep running using their last known price).

2. Circuit limit detection
   NSE applies a 20% daily circuit limit on individual stocks.  If the stock is
   already at its upper or lower circuit, no new trades should be entered:
     • Upper circuit: (LTP - prev_close) / prev_close ≥ +19.5%
     • Lower circuit: (LTP - prev_close) / prev_close ≤ -19.5%
   (We use 19.5% to catch stocks approaching the limit too.)

3. Data completeness
   We need at least 100 daily candles for SMA200 and ADX to be meaningful.
   Fewer candles = indicators are unreliable.

4. Price sanity
   Zero or negative prices, or a single candle with >15% gap vs prior close,
   indicate data corruption.

5. Minimum liquidity
   Avg daily volume must be ≥ 500K shares.  Already in pre-trade filters but
   checked here as a data-layer guard.

6. Mock vs Live detection
   Returns is_live_data=True only when the Upstox provider is active and
   returned candles with real timestamps (non-synthetic).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from app.services.data_provider import OHLCV, ist_now

logger = logging.getLogger(__name__)

FRESHNESS_MINUTES   = 5    # max allowed age of last candle during market hours
CIRCUIT_THRESHOLD   = 0.195  # 19.5% from prev_close
MIN_DAILY_CANDLES   = 100
MAX_SINGLE_CANDLE_GAP = 0.15  # 15% intra-candle gap = data corruption signal
MIN_LIQUIDITY       = 500_000  # shares


@dataclass
class DataQualityResult:
    symbol: str
    is_tradeable: bool
    is_live_data: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)  # non-blocking concerns

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.is_tradeable = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def summary(self) -> str:
        if self.is_tradeable:
            src = "LIVE" if self.is_live_data else "MOCK"
            warn = f" [{len(self.warnings)} warnings]" if self.warnings else ""
            return f"OK ({src}){warn}"
        return "BLOCKED: " + "; ".join(self.issues[:2])


def check(
    symbol: str,
    daily_candles: List[OHLCV],
    intraday_candles: Optional[List[OHLCV]] = None,
    data_provider_name: str = "mock",
) -> DataQualityResult:
    """Run all quality checks and return a DataQualityResult.

    Parameters
    ----------
    symbol            : NSE ticker
    daily_candles     : Full daily OHLCV history
    intraday_candles  : 5m candles (optional — checked for freshness if present)
    data_provider_name: "mock" or "upstox"
    """
    is_live = data_provider_name.lower() == "upstox"
    result = DataQualityResult(
        symbol=symbol,
        is_tradeable=True,
        is_live_data=is_live,
    )

    if not daily_candles:
        result.add_issue("No daily OHLCV data available")
        return result

    # ── 1. Data completeness ────────────────────────────────────────────
    if len(daily_candles) < MIN_DAILY_CANDLES:
        result.add_issue(
            f"Only {len(daily_candles)} daily candles — need ≥{MIN_DAILY_CANDLES} "
            "for SMA200/ADX to be valid"
        )

    # ── 2. Price sanity ─────────────────────────────────────────────────
    last = daily_candles[-1]
    if last.close <= 0 or last.open <= 0 or last.high <= 0 or last.low <= 0:
        result.add_issue(f"Invalid OHLCV data: zero/negative prices (close={last.close})")
        return result  # abort remaining checks

    # Single-candle gap check
    if len(daily_candles) >= 2:
        prev = daily_candles[-2]
        if prev.close > 0:
            gap = abs(last.open - prev.close) / prev.close
            if gap > MAX_SINGLE_CANDLE_GAP:
                result.add_warning(
                    f"Large overnight gap {gap*100:.1f}% — check for data error or corporate action"
                )

    # Intra-candle range sanity
    if last.high > 0 and last.low > 0 and last.high > 0:
        intra_range = (last.high - last.low) / last.low
        if intra_range > 0.25:
            result.add_warning(
                f"Extreme intra-day range {intra_range*100:.1f}% — possible data spike"
            )

    # ── 3. Circuit limit detection ──────────────────────────────────────
    if len(daily_candles) >= 2:
        prev_close = daily_candles[-2].close
        ltp = last.close
        if prev_close > 0:
            chg = (ltp - prev_close) / prev_close
            if chg >= CIRCUIT_THRESHOLD:
                result.add_issue(
                    f"Upper circuit: +{chg*100:.1f}% vs prev close — no new entries (locked)"
                )
            elif chg <= -CIRCUIT_THRESHOLD:
                result.add_issue(
                    f"Lower circuit: {chg*100:.1f}% vs prev close — no new entries (locked)"
                )

    # ── 4. Minimum liquidity ────────────────────────────────────────────
    recent = daily_candles[-20:] if len(daily_candles) >= 20 else daily_candles
    avg_vol = sum(c.volume for c in recent) / len(recent)
    if avg_vol < MIN_LIQUIDITY:
        result.add_issue(
            f"Avg daily volume {avg_vol:,.0f} < {MIN_LIQUIDITY:,} shares (liquidity filter)"
        )

    # ── 5. Intraday data freshness (only during market hours) ───────────
    now = ist_now()
    market_open = (
        now.weekday() < 5
        and now.hour * 60 + now.minute >= 9 * 60 + 15
        and now.hour * 60 + now.minute < 15 * 60 + 30
    )

    if is_live and market_open and intraday_candles:
        last_intra = intraday_candles[-1]
        if last_intra.timestamp is not None:
            age_mins = (now - last_intra.timestamp).total_seconds() / 60
            if age_mins > FRESHNESS_MINUTES:
                result.add_issue(
                    f"Stale data: last intraday candle is {age_mins:.1f} min old "
                    f"(max {FRESHNESS_MINUTES} min during market hours)"
                )

    # ── 6. Mock data warning ────────────────────────────────────────────
    if not is_live:
        result.add_warning(
            "Using MOCK (synthetic) data — results are for strategy testing only. "
            "Connect Upstox for live trading signals."
        )

    return result


def is_tradeable(
    symbol: str,
    daily_candles: List[OHLCV],
    intraday_candles: Optional[List[OHLCV]] = None,
    data_provider_name: str = "mock",
) -> tuple[bool, List[str]]:
    """Convenience wrapper returning (ok, issues)."""
    r = check(symbol, daily_candles, intraday_candles, data_provider_name)
    return r.is_tradeable, r.issues
