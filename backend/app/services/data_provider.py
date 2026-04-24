"""Market data provider.

Abstracts over the source of OHLCV data so the scoring engine and the
intraday analyzer stay clean. During MVP we generate deterministic
pseudo-random OHLCV series per-symbol so scores and signals are stable
within a refresh cycle but vary across stocks. Swap ``MockProvider`` for
``UpstoxProvider`` in production.

The analyzer needs multi-timeframe intraday candles (1m/5m/15m/1h) in
addition to the daily series, so the provider exposes
``get_intraday_history(symbol, timeframe, n_candles)``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Protocol

import numpy as np


Timeframe = Literal["1m", "5m", "15m", "1h"]

# Minutes per timeframe.
_TF_MIN: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

# Indian market session (IST). We generate candles inside [09:15, 15:30) IST.
# IST is UTC+5:30; we work in IST-naive datetimes for simplicity.
IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_now() -> datetime:
    """Return the current time in IST (naive, tz stripped)."""
    return (datetime.now(timezone.utc) + IST_OFFSET).replace(tzinfo=None)


def session_bounds(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(hour=9, minute=15, second=0, microsecond=0)
    end = day.replace(hour=15, minute=30, second=0, microsecond=0)
    return start, end


@dataclass
class OHLCV:
    open: float
    high: float
    low: float
    close: float
    volume: float
    # Optional — populated for intraday candles, left blank for daily.
    timestamp: datetime | None = None


class DataProvider(Protocol):
    def get_history(self, symbol: str, days: int = 260) -> List[OHLCV]: ...
    def get_quote(self, symbol: str) -> OHLCV: ...
    def get_intraday_history(
        self, symbol: str, timeframe: Timeframe, n_candles: int
    ) -> List[OHLCV]: ...


# --------------------------------------------------------------------- Mock

def _symbol_seed(symbol: str, bucket_minutes: int = 10) -> int:
    """Deterministic seed that changes every ``bucket_minutes``."""
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp() // (bucket_minutes * 60))
    raw = f"{symbol.upper()}::{bucket}".encode()
    return int(hashlib.sha256(raw).hexdigest(), 16) % (2**32)


class MockProvider:
    """Generate synthetic but plausible OHLCV history per symbol."""

    def __init__(self, base_price_hint: dict[str, float] | None = None):
        self.base_price_hint = base_price_hint or {}

    def _base_price(self, symbol: str) -> float:
        if symbol in self.base_price_hint:
            return self.base_price_hint[symbol]
        h = int(hashlib.md5(symbol.encode()).hexdigest(), 16)
        return 100 + (h % 4500)

    # ---- Daily --------------------------------------------------------

    def get_history(self, symbol: str, days: int = 260) -> List[OHLCV]:
        rng = np.random.default_rng(_symbol_seed(symbol))
        base = self._base_price(symbol)
        drift = rng.uniform(-0.0005, 0.0012)
        vol = rng.uniform(0.010, 0.030)
        prices = [base]
        for _ in range(days):
            shock = rng.normal(loc=drift, scale=vol)
            prices.append(max(1.0, prices[-1] * (1 + shock)))
        history: List[OHLCV] = []
        for i in range(1, len(prices)):
            o = prices[i - 1]
            c = prices[i]
            hi = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.004)))
            v = abs(rng.normal(1.0, 0.35)) * 1_000_000
            history.append(OHLCV(o, hi, lo, c, v))
        return history

    def get_quote(self, symbol: str) -> OHLCV:
        return self.get_history(symbol, days=30)[-1]

    # ---- Intraday -----------------------------------------------------

    def get_intraday_history(
        self,
        symbol: str,
        timeframe: Timeframe,
        n_candles: int,
    ) -> List[OHLCV]:
        """Synthesise N most-recent intraday candles at the given timeframe.

        The series is anchored to today's session if market is open (or the
        most recent session if not). Higher timeframes reuse the 1m path to
        stay internally consistent.
        """
        if timeframe not in _TF_MIN:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        # Build a 1-minute base path for today's session (or last session).
        now = ist_now()
        sess_start, sess_end = session_bounds(now)
        if now < sess_start:
            # Before market open — use yesterday's session.
            sess_start -= timedelta(days=1)
            sess_end -= timedelta(days=1)
            end_t = sess_end
        elif now >= sess_end:
            end_t = sess_end
        else:
            # Round current time down to the minute inside today's session.
            end_t = now.replace(second=0, microsecond=0)

        total_minutes = int((end_t - sess_start).total_seconds() // 60)
        if total_minutes <= 0:
            total_minutes = 1

        # Use the daily series to pick today's open price as the anchor.
        daily = self.get_history(symbol, days=30)
        anchor_close = daily[-1].close
        rng = np.random.default_rng(_symbol_seed(symbol, bucket_minutes=5))
        # Intraday vol scaled down from daily vol.
        intraday_vol = rng.uniform(0.0010, 0.0028)
        drift = rng.uniform(-0.00012, 0.00018)

        prices = [anchor_close * (1 + rng.normal(0, 0.003))]
        for _ in range(total_minutes):
            shock = rng.normal(loc=drift, scale=intraday_vol)
            prices.append(max(0.5, prices[-1] * (1 + shock)))

        # Build 1-minute OHLCV list.
        per_min: List[OHLCV] = []
        for i in range(1, len(prices)):
            ts = sess_start + timedelta(minutes=i)
            o = prices[i - 1]
            c = prices[i]
            hi = max(o, c) * (1 + abs(rng.normal(0, 0.0008)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.0008)))
            # Volume profile: U-shape (open + close heavy, midday thin).
            frac = i / total_minutes
            u = 1.6 - 1.2 * (1 - abs(2 * frac - 1))  # high at ends, low mid
            v = abs(rng.normal(20_000 * u, 8_000))
            per_min.append(OHLCV(o, hi, lo, c, v, timestamp=ts))

        # Aggregate up to the requested timeframe.
        step = _TF_MIN[timeframe]
        aggregated: List[OHLCV] = []
        for i in range(0, len(per_min), step):
            chunk = per_min[i : i + step]
            if not chunk:
                continue
            o = chunk[0].open
            c = chunk[-1].close
            hi = max(x.high for x in chunk)
            lo = min(x.low for x in chunk)
            v = sum(x.volume for x in chunk)
            ts = chunk[-1].timestamp
            aggregated.append(OHLCV(o, hi, lo, c, v, timestamp=ts))

        # Return the most-recent n_candles.
        return aggregated[-n_candles:] if n_candles > 0 else aggregated


# --------------------------------------------------------------------- Upstox

# Short-TTL cache so repeated dashboard refreshes don't hammer Upstox.
# Daily history barely changes within a day; intraday needs to stay fresh.
_HISTORY_TTL_SECONDS = 6 * 60 * 60   # 6 hours
_INTRADAY_TTL_SECONDS = 60           # 1 minute
_QUOTE_TTL_SECONDS = 30              # 30 seconds

# Upstox v2 historical-candle endpoint only accepts day/week/month. For
# intraday resolution we call the intraday endpoint and aggregate.
_UPSTOX_INTRADAY_INTERVAL: dict[str, str] = {
    "1m": "1minute",
    "5m": "1minute",
    "15m": "1minute",
    "1h": "30minute",
}


def _parse_candle(raw: list) -> OHLCV:
    """Upstox candle: [timestamp, open, high, low, close, volume, oi?]."""
    ts_raw = raw[0]
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        # Strip tzinfo to stay consistent with the rest of the module.
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None) + IST_OFFSET
    except (ValueError, TypeError):
        ts = None
    return OHLCV(
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        volume=float(raw[5]) if len(raw) > 5 else 0.0,
        timestamp=ts,
    )


class UpstoxProvider:
    """Live market-data provider backed by Upstox v2.

    Implements the same ``DataProvider`` protocol as ``MockProvider`` so
    the scoring engine and analyzer do not need to change.
    """

    def __init__(self, client):
        self.client = client

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _instrument_key(symbol: str) -> str:
        # Imported lazily so the mock path does not pay the import cost.
        from app.data.instruments import instrument_key
        return instrument_key(symbol)

    # ---- Daily --------------------------------------------------------

    def get_history(self, symbol: str, days: int = 260) -> List[OHLCV]:
        from app.services.cache import cache
        cache_key = f"upstox:history:{symbol.upper()}:{days}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached[0]

        key = self._instrument_key(symbol)
        today = datetime.now(timezone.utc).date()
        # Pad the lookback to account for weekends/holidays so we still
        # return ``days`` trading sessions.
        frm = (today - timedelta(days=int(days * 1.6) + 30)).isoformat()
        to = today.isoformat()
        candles = self.client.get_historical_candles(key, "day", to, frm)

        # Upstox returns newest-first; scoring expects oldest-first.
        parsed = [_parse_candle(c) for c in reversed(candles)]
        parsed = parsed[-days:]

        # ── Inject today's live candle when market is open ──────────────────
        # Upstox's daily historical endpoint only returns *completed* days
        # (i.e. yesterday and earlier). During market hours we synthesise
        # a partial "today" candle from intraday data so that all indicators
        # and entry prices reflect the current session, not yesterday's close.
        now_ist = ist_now()
        sess_start, sess_end = session_bounds(now_ist)
        market_is_open = sess_start <= now_ist < sess_end
        if market_is_open:
            try:
                intraday_key = f"upstox:today_candle:{symbol.upper()}"
                today_cached = cache.get(intraday_key)
                if today_cached is not None:
                    today_candle = today_cached[0]
                else:
                    # Fetch 1-minute bars for the whole session so far.
                    raw_1m = self.client.get_intraday_candles(key, "1minute")
                    bars = [_parse_candle(c) for c in reversed(raw_1m)]
                    if bars:
                        today_candle = OHLCV(
                            open=bars[0].open,
                            high=max(b.high for b in bars),
                            low=min(b.low for b in bars),
                            close=bars[-1].close,
                            volume=sum(b.volume for b in bars),
                        )
                        cache.set(intraday_key, today_candle, 60)  # 60-second TTL
                    else:
                        today_candle = None
                if today_candle is not None:
                    parsed = parsed + [today_candle]
            except Exception as exc:
                # If today's candle injection fails, silently continue with
                # yesterday's data rather than breaking the whole history call.
                logger.warning("today-candle injection failed for %s: %s", symbol, exc)

        cache.set(cache_key, parsed, _HISTORY_TTL_SECONDS)
        return parsed

    def get_quote(self, symbol: str) -> OHLCV:
        from app.services.cache import cache
        cache_key = f"upstox:ltp:{symbol.upper()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached[0]

        key = self._instrument_key(symbol)
        data = self.client.get_ltp([key])
        # Upstox keys the response by a normalised instrument identifier
        # that may or may not match ``key`` exactly — so just grab the
        # first (and only) entry.
        if not data:
            raise RuntimeError(f"Upstox returned no LTP for {symbol}")
        entry = next(iter(data.values()))
        ltp = float(entry.get("last_price") or entry.get("ltp") or 0.0)
        if ltp <= 0:
            raise RuntimeError(f"Upstox LTP for {symbol} was zero/invalid")
        quote = OHLCV(open=ltp, high=ltp, low=ltp, close=ltp, volume=0.0)
        cache.set(cache_key, quote, _QUOTE_TTL_SECONDS)
        return quote

    # ---- Intraday -----------------------------------------------------

    def get_intraday_history(
        self,
        symbol: str,
        timeframe: Timeframe,
        n_candles: int,
    ) -> List[OHLCV]:
        if timeframe not in _TF_MIN:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        from app.services.cache import cache
        cache_key = f"upstox:intraday:{symbol.upper()}:{timeframe}:{n_candles}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached[0]

        key = self._instrument_key(symbol)
        interval = _UPSTOX_INTRADAY_INTERVAL[timeframe]
        raw = self.client.get_intraday_candles(key, interval)
        # Upstox returns newest-first.
        per_bar = [_parse_candle(c) for c in reversed(raw)]

        # If the native interval already matches the requested timeframe
        # (1m or 1h via 30m pairs) or we asked for 1m, no aggregation needed.
        step = _TF_MIN[timeframe]
        native_step = 1 if interval == "1minute" else 30
        if step == native_step:
            aggregated = per_bar
        else:
            # Aggregate base candles up to the requested step. Works for
            # 5m/15m out of 1m base.
            ratio = step // native_step if native_step else step
            aggregated = []
            for i in range(0, len(per_bar), ratio):
                chunk = per_bar[i : i + ratio]
                if not chunk:
                    continue
                aggregated.append(OHLCV(
                    open=chunk[0].open,
                    high=max(x.high for x in chunk),
                    low=min(x.low for x in chunk),
                    close=chunk[-1].close,
                    volume=sum(x.volume for x in chunk),
                    timestamp=chunk[-1].timestamp,
                ))

        result = aggregated[-n_candles:] if n_candles > 0 else aggregated
        cache.set(cache_key, result, _INTRADAY_TTL_SECONDS)
        return result


def get_provider(kind: str) -> DataProvider:
    if kind == "mock":
        return MockProvider()
    if kind == "upstox":
        from app.integrations.upstox import UpstoxClient
        return UpstoxProvider(UpstoxClient())
    raise ValueError(f"Unknown data provider: {kind}")
