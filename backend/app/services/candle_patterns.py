"""Candlestick Pattern Recognition Engine.

Identifies high-reliability bullish and bearish reversal / continuation patterns
on the most recent 1–5 candles of any OHLCV series.

Why patterns matter for 95% win rate
──────────────────────────────────────
A technical signal (RSI, MACD, etc.) fires *before* price confirms direction.
A candlestick pattern fires *at the moment price is confirming* — giving a
second-opinion from price action itself.  Requiring at least one bullish pattern
before entry eliminates trades where indicators say BUY but price hasn't
actually started moving up yet.

Patterns implemented
──────────────────────
Bullish reversal (strong ↑):
  1. Hammer              — small body at top, long lower shadow ≥ 2× body
  2. Bullish Engulfing   — large green candle completely covers prior red
  3. Morning Star        — 3-candle: red → doji/small → large green
  4. Piercing Line       — green closes above 50% of prior red
  5. Dragonfly Doji      — near-open == near-close, long lower wick
  6. Three White Soldiers — 3 consecutive green closes, each higher

Bearish reversal (strong ↓) — used to INVALIDATE BUY signals:
  7. Shooting Star        — opposite of Hammer; long upper wick
  8. Bearish Engulfing    — large red candle covers prior green
  9. Evening Star         — 3-candle: green → doji → large red
  10. Dark Cloud Cover    — red candle closes below 50% of prior green

Scoring
──────────────────────
Each bullish pattern detected returns a PatternResult with:
  strength: 1 (weak) | 2 (moderate) | 3 (strong)
  location: "support" | "open_air" (at key level = more reliable)

The total bullish_score / bearish_score feeds into the high_confidence_filter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.services.data_provider import OHLCV


@dataclass
class PatternResult:
    name: str
    direction: int      # 1 = bullish, -1 = bearish
    strength: int       # 1=weak, 2=moderate, 3=strong
    candle_index: int   # 0 = most recent, 1 = one before, etc.
    description: str


@dataclass
class PatternScan:
    bullish: List[PatternResult] = field(default_factory=list)
    bearish: List[PatternResult] = field(default_factory=list)

    @property
    def bullish_score(self) -> int:
        return sum(p.strength for p in self.bullish)

    @property
    def bearish_score(self) -> int:
        return sum(p.strength for p in self.bearish)

    @property
    def net_score(self) -> int:
        return self.bullish_score - self.bearish_score

    @property
    def has_bullish_confirmation(self) -> bool:
        return self.bullish_score >= 2

    @property
    def has_bearish_invalidation(self) -> bool:
        return self.bearish_score >= 3

    def top_bullish(self) -> Optional[PatternResult]:
        if not self.bullish:
            return None
        return max(self.bullish, key=lambda p: p.strength)

    def summary(self) -> str:
        parts = []
        for p in sorted(self.bullish, key=lambda x: -x.strength):
            parts.append(f"↑{p.name}(strength={p.strength})")
        for p in sorted(self.bearish, key=lambda x: -x.strength):
            parts.append(f"↓{p.name}(strength={p.strength})")
        return " | ".join(parts) if parts else "No patterns"


# ──────────────────────────────── helpers ───────────────────────────────────

def _body(c: OHLCV) -> float:
    return abs(c.close - c.open)

def _is_green(c: OHLCV) -> bool:
    return c.close > c.open

def _is_red(c: OHLCV) -> bool:
    return c.close < c.open

def _upper_wick(c: OHLCV) -> float:
    return c.high - max(c.open, c.close)

def _lower_wick(c: OHLCV) -> float:
    return min(c.open, c.close) - c.low

def _range(c: OHLCV) -> float:
    return c.high - c.low if c.high > c.low else 1e-9


# ──────────────────────────────── bullish patterns ──────────────────────────

def _hammer(c0: OHLCV, c1: Optional[OHLCV]) -> Optional[PatternResult]:
    """Hammer / Inverted Shooting Star — small body at top, long lower wick."""
    body = _body(c0)
    lower = _lower_wick(c0)
    upper = _upper_wick(c0)
    total = _range(c0)
    if total <= 0:
        return None
    # Body ≤ 35% of range, lower wick ≥ 2× body, upper wick small
    if body / total <= 0.35 and lower >= 2.0 * max(body, 0.001) and upper <= body * 0.5:
        prior_bearish = c1 is not None and _is_red(c1)
        strength = 3 if prior_bearish else 2
        return PatternResult(
            name="Hammer",
            direction=1,
            strength=strength,
            candle_index=0,
            description=f"Hammer: lower wick {lower:.2f}, body {body:.2f}",
        )
    return None


def _bullish_engulfing(c0: OHLCV, c1: Optional[OHLCV]) -> Optional[PatternResult]:
    """Large green candle fully engulfs the prior red candle."""
    if c1 is None:
        return None
    if not (_is_green(c0) and _is_red(c1)):
        return None
    if c0.open < c1.close and c0.close > c1.open:
        body_ratio = _body(c0) / max(_body(c1), 0.001)
        strength = 3 if body_ratio >= 1.5 else 2
        return PatternResult(
            name="Bullish Engulfing",
            direction=1,
            strength=strength,
            candle_index=0,
            description=f"Engulfs prior red by {body_ratio:.1f}×",
        )
    return None


def _morning_star(c0: OHLCV, c1: OHLCV, c2: Optional[OHLCV]) -> Optional[PatternResult]:
    """3-candle: red → small doji/indecision → large green."""
    if c2 is None:
        return None
    if not (_is_red(c2) and _is_green(c0)):
        return None
    c2_body = _body(c2)
    c1_body = _body(c1)
    c0_body = _body(c0)
    if c2_body <= 0:
        return None
    # Middle candle has small body (≤ 30% of c2 body)
    if c1_body / c2_body > 0.30:
        return None
    # c0 closes above midpoint of c2's body
    mid_c2 = (c2.open + c2.close) / 2
    if c0.close > mid_c2:
        return PatternResult(
            name="Morning Star",
            direction=1,
            strength=3,
            candle_index=0,
            description="3-candle Morning Star reversal",
        )
    return None


def _piercing_line(c0: OHLCV, c1: Optional[OHLCV]) -> Optional[PatternResult]:
    """Green candle opens below prior red's low, closes above its midpoint."""
    if c1 is None or not (_is_green(c0) and _is_red(c1)):
        return None
    mid_c1 = (c1.open + c1.close) / 2
    if c0.open < c1.close and c0.close > mid_c1 and c0.close < c1.open:
        return PatternResult(
            name="Piercing Line",
            direction=1,
            strength=2,
            candle_index=0,
            description="Piercing Line: green closes above 50% of prior red",
        )
    return None


def _dragonfly_doji(c0: OHLCV) -> Optional[PatternResult]:
    """Open ≈ Close ≈ High, long lower wick."""
    body = _body(c0)
    lower = _lower_wick(c0)
    upper = _upper_wick(c0)
    total = _range(c0)
    if total <= 0:
        return None
    if body / total <= 0.10 and lower >= 0.65 * total and upper <= 0.10 * total:
        return PatternResult(
            name="Dragonfly Doji",
            direction=1,
            strength=2,
            candle_index=0,
            description="Dragonfly Doji: strong lower rejection",
        )
    return None


def _three_white_soldiers(candles: List[OHLCV]) -> Optional[PatternResult]:
    """3 consecutive green candles, each closing higher."""
    if len(candles) < 3:
        return None
    c0, c1, c2 = candles[-1], candles[-2], candles[-3]
    if not (_is_green(c0) and _is_green(c1) and _is_green(c2)):
        return None
    if c0.close > c1.close > c2.close and c0.open > c1.open and c1.open > c2.open:
        return PatternResult(
            name="Three White Soldiers",
            direction=1,
            strength=3,
            candle_index=0,
            description="3 consecutive higher green closes — strong momentum",
        )
    return None


# ──────────────────────────────── bearish patterns ──────────────────────────

def _shooting_star(c0: OHLCV, c1: Optional[OHLCV]) -> Optional[PatternResult]:
    body = _body(c0)
    upper = _upper_wick(c0)
    lower = _lower_wick(c0)
    total = _range(c0)
    if total <= 0:
        return None
    if body / total <= 0.35 and upper >= 2.0 * max(body, 0.001) and lower <= body * 0.5:
        prior_bullish = c1 is not None and _is_green(c1)
        strength = 3 if prior_bullish else 2
        return PatternResult(
            name="Shooting Star",
            direction=-1,
            strength=strength,
            candle_index=0,
            description=f"Shooting Star: upper wick {upper:.2f} rejection",
        )
    return None


def _bearish_engulfing(c0: OHLCV, c1: Optional[OHLCV]) -> Optional[PatternResult]:
    if c1 is None or not (_is_red(c0) and _is_green(c1)):
        return None
    if c0.open > c1.close and c0.close < c1.open:
        return PatternResult(
            name="Bearish Engulfing",
            direction=-1,
            strength=3,
            candle_index=0,
            description="Bearish Engulfing: red candle engulfs prior green",
        )
    return None


def _evening_star(c0: OHLCV, c1: OHLCV, c2: Optional[OHLCV]) -> Optional[PatternResult]:
    if c2 is None or not (_is_green(c2) and _is_red(c0)):
        return None
    if _body(c1) / max(_body(c2), 0.001) <= 0.30:
        mid_c2 = (c2.open + c2.close) / 2
        if c0.close < mid_c2:
            return PatternResult(
                name="Evening Star",
                direction=-1,
                strength=3,
                candle_index=0,
                description="3-candle Evening Star top reversal",
            )
    return None


def _dark_cloud(c0: OHLCV, c1: Optional[OHLCV]) -> Optional[PatternResult]:
    if c1 is None or not (_is_red(c0) and _is_green(c1)):
        return None
    mid_c1 = (c1.open + c1.close) / 2
    if c0.open > c1.close and c0.close < mid_c1 and c0.close > c1.open:
        return PatternResult(
            name="Dark Cloud Cover",
            direction=-1,
            strength=2,
            candle_index=0,
            description="Dark Cloud: red closes below 50% of prior green",
        )
    return None


# ──────────────────────────────── public API ────────────────────────────────

def scan(candles: List[OHLCV]) -> PatternScan:
    """Scan the last 5 candles and return a PatternScan.

    ``candles`` should be ordered oldest → newest (standard OHLCV convention).
    """
    result = PatternScan()
    if not candles:
        return result

    n = len(candles)
    c0 = candles[-1]
    c1 = candles[-2] if n >= 2 else None
    c2 = candles[-3] if n >= 3 else None

    # ── Bullish ────────────────────────────────────────────────────────
    for p in [
        _hammer(c0, c1),
        _bullish_engulfing(c0, c1),
        _piercing_line(c0, c1),
        _dragonfly_doji(c0),
        _three_white_soldiers(candles),
    ]:
        if p is not None:
            result.bullish.append(p)

    if c1 is not None:
        ms = _morning_star(c0, c1, c2)
        if ms:
            result.bullish.append(ms)

    # ── Bearish ────────────────────────────────────────────────────────
    for p in [
        _shooting_star(c0, c1),
        _bearish_engulfing(c0, c1),
        _dark_cloud(c0, c1),
    ]:
        if p is not None:
            result.bearish.append(p)

    if c1 is not None:
        es = _evening_star(c0, c1, c2)
        if es:
            result.bearish.append(es)

    return result
