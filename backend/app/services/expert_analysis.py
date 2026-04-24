"""Plain-English technical analysis in the style of an experienced swing trader.

Given a series of daily OHLCV candles this module computes:

- Key support / resistance levels (swing pivots + round-number zones)
- Trend classification (strong up / up / sideways / down / strong down)
- Momentum regime (overbought / neutral / oversold / building)
- Volume profile for the last 20 sessions
- Fibonacci retracements over the recent swing
- Narrative bullet points the UI can render verbatim

Everything here is deterministic — the chart-based Claude analyzer
still lives in ``services/analyzer.py`` for LLM-backed signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np

from app.services.data_provider import OHLCV
from app.services.scoring import rsi, macd, sma


# ----------------------------------------------------------------- levels

def _pivot_swings(highs: np.ndarray, lows: np.ndarray, lookback: int = 3) -> tuple[list[float], list[float]]:
    """Simple fractal pivots: a high is a pivot-high if it's the max within
    +/-lookback bars; analogous for lows."""
    pivot_highs: list[float] = []
    pivot_lows: list[float] = []
    n = len(highs)
    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == window_h.max():
            pivot_highs.append(float(highs[i]))
        if lows[i] == window_l.min():
            pivot_lows.append(float(lows[i]))
    return pivot_highs, pivot_lows


def _cluster(levels: list[float], tolerance_pct: float = 0.015) -> list[float]:
    """Merge nearby levels into cluster means, keeping strongest first."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters: list[list[float]] = [[levels[0]]]
    for lvl in levels[1:]:
        last = clusters[-1][-1]
        if abs(lvl - last) / last <= tolerance_pct:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    # Sort clusters by size (strength) descending; return cluster means.
    clusters.sort(key=lambda c: len(c), reverse=True)
    return [round(float(np.mean(c)), 2) for c in clusters]


# ----------------------------------------------------------------- trend / regime

def _atr_pct(candles: List[OHLCV], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    prev_close = candles[-period - 1].close
    for c in candles[-period:]:
        tr = max(
            c.high - c.low,
            abs(c.high - prev_close),
            abs(c.low - prev_close),
        )
        trs.append(tr)
        prev_close = c.close
    atr = float(np.mean(trs))
    return atr / candles[-1].close * 100.0


def _trend_label(close: float, sma20: float, sma50: float, sma200: float) -> str:
    if close > sma20 > sma50 > sma200:
        return "strong uptrend"
    if close > sma50 > sma200:
        return "uptrend"
    if close < sma20 < sma50 < sma200:
        return "strong downtrend"
    if close < sma50 < sma200:
        return "downtrend"
    if sma20 and sma50 and abs(sma20 - sma50) / sma50 < 0.01:
        return "sideways"
    return "transitional"


def _momentum_label(rsi_val: float, macd_line: float, macd_sig: float) -> str:
    hist = macd_line - macd_sig
    if rsi_val >= 70:
        return "overbought — stretched"
    if rsi_val >= 60 and hist > 0:
        return "strong bullish momentum"
    if rsi_val <= 30:
        return "oversold — bounce candidate"
    if rsi_val <= 40 and hist < 0:
        return "bearish momentum, still weak"
    if hist > 0 and rsi_val > 50:
        return "momentum building up"
    if hist < 0 and rsi_val < 50:
        return "momentum fading"
    return "neutral momentum"


# ----------------------------------------------------------------- payload

@dataclass
class ExpertAnalysis:
    last_price: float
    change_pct_1d: float
    change_pct_5d: float
    change_pct_20d: float
    trend: str
    momentum: str
    rsi: float
    macd_hist: float
    atr_pct: float
    volatility_label: str
    volume_vs_avg_20d: float
    avg_volume_20d: float
    supports: List[float]
    resistances: List[float]
    nearest_support: float
    nearest_resistance: float
    risk_reward_ratio: float
    fib_levels: dict[str, float]
    narrative: List[str] = field(default_factory=list)


def analyze(candles: List[OHLCV]) -> ExpertAnalysis:
    if len(candles) < 30:
        raise ValueError("Need at least 30 candles for expert analysis")

    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    volumes = np.array([c.volume for c in candles], dtype=float)

    last = float(closes[-1])
    change_1d = float((closes[-1] / closes[-2] - 1) * 100) if len(closes) > 1 else 0.0
    change_5d = float((closes[-1] / closes[-6] - 1) * 100) if len(closes) > 5 else 0.0
    change_20d = float((closes[-1] / closes[-21] - 1) * 100) if len(closes) > 20 else 0.0

    sma20 = sma(candles, 20)
    sma50 = sma(candles, 50)
    sma200 = sma(candles, 200) if len(candles) >= 200 else sma(candles, min(len(candles), 100))

    rsi_val = rsi(candles)
    macd_line, macd_sig = macd(candles)
    hist = macd_line - macd_sig
    atr_pct = _atr_pct(candles)

    # Pivots within the last ~90 sessions to keep levels relevant.
    window = min(len(candles), 90)
    ph, pl = _pivot_swings(highs[-window:], lows[-window:])
    # Add round-number anchors within 10% of price.
    rn_step = 50 if last >= 500 else 10 if last >= 100 else 5
    rn = [round(last / rn_step) * rn_step + k * rn_step for k in range(-3, 4)]
    rn = [float(x) for x in rn if 0.9 * last <= x <= 1.1 * last]
    resistances_all = _cluster([l for l in ph + rn if l > last])
    supports_all = _cluster([l for l in pl + rn if l < last])
    resistances = resistances_all[:4]
    supports = supports_all[:4]

    nearest_r = min(resistances) if resistances else round(last * 1.05, 2)
    nearest_s = max(supports) if supports else round(last * 0.95, 2)
    upside = nearest_r - last
    downside = last - nearest_s
    rr = upside / downside if downside > 0 else 0.0

    # 90-day swing for Fibonacci retracements.
    swing_high = float(highs[-window:].max())
    swing_low = float(lows[-window:].min())
    rng = swing_high - swing_low
    fib = {
        "0.0": round(swing_high, 2),
        "0.236": round(swing_high - rng * 0.236, 2),
        "0.382": round(swing_high - rng * 0.382, 2),
        "0.5":   round(swing_high - rng * 0.5, 2),
        "0.618": round(swing_high - rng * 0.618, 2),
        "0.786": round(swing_high - rng * 0.786, 2),
        "1.0":   round(swing_low, 2),
    }

    # Volume.
    avg_vol_20 = float(volumes[-20:].mean()) if len(volumes) >= 20 else float(volumes.mean())
    vol_today = float(volumes[-1])
    vol_ratio = vol_today / avg_vol_20 if avg_vol_20 > 0 else 1.0

    trend = _trend_label(last, sma20, sma50, sma200)
    momentum = _momentum_label(rsi_val, macd_line, macd_sig)
    vol_label = (
        "low"
        if atr_pct < 1.5
        else "moderate"
        if atr_pct < 3
        else "high"
        if atr_pct < 5
        else "extreme"
    )

    narrative: List[str] = []
    narrative.append(
        f"Price at ₹{last:.2f} is in a {trend} on the daily timeframe "
        f"(20DMA ₹{sma20:.2f}, 50DMA ₹{sma50:.2f}, 200DMA ₹{sma200:.2f})."
    )
    narrative.append(
        f"Momentum is {momentum}; RSI {rsi_val:.0f}, MACD histogram {hist:+.2f}."
    )
    if vol_ratio >= 1.5:
        narrative.append(
            f"Today's volume is {vol_ratio:.1f}× the 20-day average — strong participation."
        )
    elif vol_ratio <= 0.7:
        narrative.append(
            f"Volume is only {vol_ratio:.1f}× average — weak conviction, wait for confirmation."
        )
    else:
        narrative.append(f"Volume near average ({vol_ratio:.1f}×) — normal participation.")

    narrative.append(
        f"Nearest resistance ₹{nearest_r:.2f} ({(nearest_r / last - 1) * 100:+.1f}%), "
        f"nearest support ₹{nearest_s:.2f} ({(nearest_s / last - 1) * 100:+.1f}%). "
        f"Reward:risk from here ≈ {rr:.2f}."
    )

    if rsi_val >= 70 and "uptrend" in trend:
        narrative.append(
            "Extended trend — wait for a pullback to 20DMA or breakout on volume rather than chasing."
        )
    elif rsi_val <= 30 and "downtrend" in trend:
        narrative.append(
            "Oversold in a downtrend — early buyers often get stopped out. Wait for higher-low + volume pop."
        )
    elif trend == "sideways":
        narrative.append(
            "Range-bound — buy near support, sell near resistance; stop below/above the band."
        )
    elif rr >= 2 and "uptrend" in trend:
        narrative.append(
            f"Clean setup: in uptrend with {rr:.1f}× upside to nearest resistance — risk 1 to make {rr:.1f}."
        )

    return ExpertAnalysis(
        last_price=round(last, 2),
        change_pct_1d=round(change_1d, 2),
        change_pct_5d=round(change_5d, 2),
        change_pct_20d=round(change_20d, 2),
        trend=trend,
        momentum=momentum,
        rsi=round(rsi_val, 1),
        macd_hist=round(hist, 3),
        atr_pct=round(atr_pct, 2),
        volatility_label=vol_label,
        volume_vs_avg_20d=round(vol_ratio, 2),
        avg_volume_20d=round(avg_vol_20, 0),
        supports=supports,
        resistances=resistances,
        nearest_support=round(nearest_s, 2),
        nearest_resistance=round(nearest_r, 2),
        risk_reward_ratio=round(rr, 2),
        fib_levels=fib,
        narrative=narrative,
    )
