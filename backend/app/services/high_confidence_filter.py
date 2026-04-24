"""High-Confidence Trade Filter — Grade A+ Entry Scoring System.

Purpose
────────
95%+ win rate is not achieved by being right more often on individual indicator
calls — it is achieved by ONLY taking trades where every independent layer of
evidence agrees simultaneously.  This filter scores each potential trade on
7 dimensions and only passes Grade A+ (score ≥ 80/100).

The 7 Scoring Dimensions
─────────────────────────
1. CONFLUENCE DEPTH          (0–20 pts)
   Base: algo engine confluence count out of 11 (9 strategies + PCR + FII)
   Score = min((count / 6) × 20, 20)   ← requires ≥ 6/11 for full points

2. MULTI-TIMEFRAME ALIGNMENT  (0–20 pts)
   All 3 timeframes bullish → 20 pts
   2/3 bullish              → 10 pts
   1/3 or 0/3               →  0 pts

3. NIFTY DIRECTION           (0–15 pts)
   Nifty EMA bullish AND day change > 0%  → 15 pts
   Nifty EMA bullish only                 → 10 pts
   Nifty neutral / data unavailable       →  5 pts
   Nifty EMA bearish                      →  0 pts

4. VOLUME CONFIRMATION        (0–15 pts)
   Current volume > 200% of avg  → 15 pts
   Current volume > 150% of avg  → 10 pts
   Current volume > 120% of avg  →  5 pts
   Below 120%                    →  0 pts

5. GOLDEN HOUR TIMING         (0–15 pts)
   09:20–10:30 IST (ORB + first momentum window)   → 15 pts
   14:00–15:00 IST (afternoon trend continuation)  → 12 pts
   10:30–11:30 IST (secondary opportunity)         →  5 pts
   11:30–14:00 IST (lunch lull — choppy)           →  0 pts
   15:00–15:20 IST (near EOD — risky)              →  2 pts

6. RISK:REWARD QUALITY        (0–10 pts)
   R:R ≥ 4:1  → 10 pts
   R:R ≥ 3:1  →  8 pts
   R:R ≥ 2:1  →  4 pts
   R:R < 2:1  →  0 pts

7. CANDLESTICK CONFIRMATION   (0–5 pts)
   Bullish pattern with strength ≥ 3  → 5 pts
   Bullish pattern with strength ≥ 2  → 3 pts
   Any bullish pattern                → 1 pt
   Bearish pattern present            → −5 pts (hard deduction)

Grade mapping
──────────────
  90–100 → A+  (ENTER — very high confidence)
  80–89  → A   (ENTER — high confidence)
  65–79  → B   (WATCH — good setup, wait for improvement)
  50–64  → C   (SKIP — marginal)
  <50    → D   (AVOID)

Only A+ and A grades trigger auto-trading entry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from app.services.data_provider import OHLCV, ist_now
from app.services import indicators as ind

logger = logging.getLogger(__name__)

# ─────────────────────────────────── constants ──────────────────────────────

GRADE_THRESHOLDS = {
    "A+": 90,
    "A":  80,
    "B":  65,
    "C":  50,
}

ENTRY_MIN_SCORE = 80   # A or better required to enter
ENTRY_MIN_CONFLUENCE = 5   # out of 11 (9 strategies + PCR + FII)


# ─────────────────────────────────── models ─────────────────────────────────

@dataclass
class DimensionScore:
    name: str
    score: int
    max_score: int
    detail: str


@dataclass
class HighConfidenceResult:
    symbol: str
    total_score: int          # 0–100
    grade: str                # A+ / A / B / C / D
    should_enter: bool        # total_score >= ENTRY_MIN_SCORE
    dimensions: List[DimensionScore] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"[{self.grade}] {self.total_score}/100 — "
            + ("ENTER" if self.should_enter else "SKIP")
            + (f" | Block: {'; '.join(self.blocking_reasons[:2])}" if self.blocking_reasons else "")
        )


# ─────────────────────────────────── scoring ────────────────────────────────

def _score_confluence(confluence_count: int) -> DimensionScore:
    score = min(int((confluence_count / 6) * 20), 20)
    return DimensionScore(
        name="Confluence Depth",
        score=score,
        max_score=20,
        detail=f"{confluence_count}/11 strategies agree → {score}pts",
    )


def _score_mtf(mtf_score: int) -> DimensionScore:
    """mtf_score = 0, 1, 2, or 3 timeframes bullish."""
    pts = {0: 0, 1: 0, 2: 10, 3: 20}
    score = pts.get(mtf_score, 0)
    return DimensionScore(
        name="Multi-Timeframe Alignment",
        score=score,
        max_score=20,
        detail=f"{mtf_score}/3 timeframes bullish → {score}pts",
    )


def _score_nifty(nifty_aligned: bool, nifty_ema_bull: bool) -> DimensionScore:
    if nifty_aligned and nifty_ema_bull:
        score = 15
        detail = "Nifty EMA bullish + day positive → 15pts"
    elif nifty_ema_bull:
        score = 10
        detail = "Nifty EMA bullish (day flat/minor red) → 10pts"
    elif nifty_aligned:
        score = 5
        detail = "Nifty direction neutral / data unavailable → 5pts"
    else:
        score = 0
        detail = "Nifty EMA bearish → 0pts"
    return DimensionScore(name="Nifty Direction", score=score, max_score=15, detail=detail)


def _score_volume(vol_ratio: float) -> DimensionScore:
    if vol_ratio >= 2.0:
        score, detail = 15, f"Volume {vol_ratio:.1f}× avg → 15pts (strong confirmation)"
    elif vol_ratio >= 1.5:
        score, detail = 10, f"Volume {vol_ratio:.1f}× avg → 10pts"
    elif vol_ratio >= 1.2:
        score, detail = 5, f"Volume {vol_ratio:.1f}× avg → 5pts"
    else:
        score, detail = 0, f"Volume {vol_ratio:.1f}× avg → 0pts (below threshold)"
    return DimensionScore(name="Volume Confirmation", score=score, max_score=15, detail=detail)


def _score_time(now: Optional[datetime] = None) -> DimensionScore:
    now = now or ist_now()
    hour, minute = now.hour, now.minute
    time_mins = hour * 60 + minute

    # 09:20–10:30 = golden morning window
    if 9 * 60 + 20 <= time_mins <= 10 * 60 + 30:
        score, detail = 15, f"{hour:02d}:{minute:02d} — Golden morning window → 15pts"
    # 14:00–15:00 = afternoon continuation
    elif 14 * 60 <= time_mins <= 15 * 60:
        score, detail = 12, f"{hour:02d}:{minute:02d} — Afternoon continuation window → 12pts"
    # 10:30–11:30 = secondary window
    elif 10 * 60 + 30 < time_mins <= 11 * 60 + 30:
        score, detail = 5, f"{hour:02d}:{minute:02d} — Secondary window → 5pts"
    # 15:00–15:20 = close to EOD, dangerous
    elif 15 * 60 < time_mins <= 15 * 60 + 20:
        score, detail = 2, f"{hour:02d}:{minute:02d} — Near EOD → 2pts"
    else:
        score, detail = 0, f"{hour:02d}:{minute:02d} — Lunch lull / dead zone → 0pts"

    return DimensionScore(name="Golden Hour Timing", score=score, max_score=15, detail=detail)


def _score_rr(entry: float, stop_loss: float, target1: float) -> DimensionScore:
    risk   = abs(entry - stop_loss)
    reward = abs(target1 - entry)
    if risk <= 0:
        return DimensionScore("Risk:Reward", 0, 10, "Cannot compute R:R (zero risk)")
    rr = reward / risk
    if rr >= 4.0:
        score, detail = 10, f"R:R {rr:.1f}:1 → 10pts"
    elif rr >= 3.0:
        score, detail = 8, f"R:R {rr:.1f}:1 → 8pts"
    elif rr >= 2.0:
        score, detail = 4, f"R:R {rr:.1f}:1 → 4pts"
    else:
        score, detail = 0, f"R:R {rr:.1f}:1 → 0pts (below 2:1 threshold)"
    return DimensionScore(name="Risk:Reward", score=score, max_score=10, detail=detail)


def _score_candles(bullish_score: int, bearish_score: int) -> DimensionScore:
    if bearish_score >= 3:
        score = -5
        detail = f"Bearish pattern strength {bearish_score} → HARD DEDUCTION −5pts"
    elif bullish_score >= 3:
        score, detail = 5, f"Bullish pattern strength {bullish_score} → 5pts"
    elif bullish_score >= 2:
        score, detail = 3, f"Bullish pattern strength {bullish_score} → 3pts"
    elif bullish_score >= 1:
        score, detail = 1, "Weak bullish pattern → 1pt"
    else:
        score, detail = 0, "No patterns detected → 0pts"
    return DimensionScore(name="Candlestick Confirmation", score=score, max_score=5, detail=detail)


# ─────────────────────────────────── public API ─────────────────────────────

def score(
    symbol: str,
    confluence_count: int,
    mtf_score: int,             # 0–3 timeframes bullish
    nifty_aligned: bool,
    nifty_ema_bullish: bool,
    vol_ratio: float,           # current volume / avg volume
    entry: float,
    stop_loss: float,
    target1: float,
    candle_bullish_score: int,
    candle_bearish_score: int,
    entry_time: Optional[datetime] = None,
    require_confluence: bool = True,  # set False when algo engine is disabled
    entry_min_score: int = ENTRY_MIN_SCORE,   # profile-overridable pass threshold
    mtf_min: int = 2,           # profile-overridable minimum MTF timeframes (0–3)
    nifty_hard_block: bool = True,  # False = Nifty bearish penalises score but doesn't hard-block
) -> HighConfidenceResult:
    """Compute the composite high-confidence score for one trade setup.

    ``require_confluence=False`` relaxes the hard confluence block so that
    when the 9-strategy algo engine is switched off in config, the other 6
    dimensions (MTF, Nifty, volume, timing, R:R, candles) can still drive a
    Grade A entry.  The confluence *score* still contributes points normally.

    ``entry_min_score`` and ``mtf_min`` are set by the trading profile:
      ACTIVE profile:          skips HC entirely (not called)
      BALANCED profile:        entry_min_score=65, mtf_min=1, nifty_hard_block=False
      HIGH_CONFIDENCE profile: entry_min_score=80, mtf_min=2, nifty_hard_block=True (defaults)

    ``nifty_hard_block=False`` means a bearish Nifty direction scores 0 pts but
    does not add a blocking reason — a strong individual stock setup can still
    qualify on the other 6 dimensions (useful in BALANCED profile).
    """

    dims = [
        _score_confluence(confluence_count),
        _score_mtf(mtf_score),
        _score_nifty(nifty_aligned, nifty_ema_bullish),
        _score_volume(vol_ratio),
        _score_time(entry_time),
        _score_rr(entry, stop_loss, target1),
        _score_candles(candle_bullish_score, candle_bearish_score),
    ]

    total = max(0, min(100, sum(d.score for d in dims)))

    # Determine grade
    grade = "D"
    for g, threshold in GRADE_THRESHOLDS.items():
        if total >= threshold:
            grade = g
            break

    # Collect blocking reasons for transparency.
    # mtf_min=0 means any MTF alignment is acceptable (ACTIVE profile).
    # nifty_hard_block=False → bearish Nifty scores 0 pts but doesn't hard-block.
    blocking: List[str] = []
    if require_confluence and confluence_count < ENTRY_MIN_CONFLUENCE:
        blocking.append(f"Confluence {confluence_count} < min {ENTRY_MIN_CONFLUENCE}")
    if mtf_min > 0 and mtf_score < mtf_min:
        blocking.append(f"MTF alignment {mtf_score}/3 — need ≥ {mtf_min}")
    if nifty_hard_block and not nifty_ema_bullish and not nifty_aligned:
        blocking.append("Nifty trend bearish")
    if candle_bearish_score >= 3:
        blocking.append("Strong bearish candle pattern present")

    should_enter = total >= entry_min_score and len(blocking) == 0

    return HighConfidenceResult(
        symbol=symbol,
        total_score=total,
        grade=grade,
        should_enter=should_enter,
        dimensions=dims,
        blocking_reasons=blocking,
    )
