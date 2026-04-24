"""Technical + fundamental scoring engine.

Both scores are normalised to 0..100. Composite score is a weighted
combination — intraday leans on technicals, long-term on fundamentals.

Technical indicators computed by hand (no TA-Lib dependency so Render's
free tier stays happy):
- RSI(14)
- MACD (12, 26, 9)
- SMA 20 / 50 / 200
- ATR(14) as %
- Volume ratio (today vs 20-day avg)

Fundamental score rewards high ROE + earnings growth + reasonable
valuation and penalises high leverage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from app.data.universe import StockMeta
from app.models.schemas import (
    FundamentalSnapshot,
    ScoreBreakdown,
    Suggestion,
    TechnicalSnapshot,
)
from app.services.data_provider import OHLCV


# ---------- Technical indicators ------------------------------------------------

def _closes(candles: List[OHLCV]) -> np.ndarray:
    return np.array([c.close for c in candles], dtype=float)


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.zeros_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(candles: List[OHLCV], period: int = 14) -> float:
    closes = _closes(candles)
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.clip(deltas, 0, None)
    losses = -np.clip(deltas, None, 0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def macd(candles: List[OHLCV]) -> Tuple[float, float]:
    closes = _closes(candles)
    if len(closes) < 35:
        return 0.0, 0.0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal = _ema(macd_line, 9)
    return float(macd_line[-1]), float(signal[-1])


def sma(candles: List[OHLCV], window: int) -> float:
    closes = _closes(candles)
    if len(closes) < window:
        return float(closes.mean())
    return float(closes[-window:].mean())


def atr_pct(candles: List[OHLCV], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 1.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = float(np.mean(trs[-period:]))
    last = candles[-1].close
    return (atr / last) * 100 if last else 1.0


def volume_ratio(candles: List[OHLCV], window: int = 20) -> float:
    if len(candles) < window + 1:
        return 1.0
    recent = [c.volume for c in candles[-window:]]
    today = candles[-1].volume
    avg = float(np.mean(recent))
    return today / avg if avg > 0 else 1.0


def build_technical_snapshot(candles: List[OHLCV]) -> TechnicalSnapshot:
    last_close = candles[-1].close
    prev_close = candles[-2].close if len(candles) >= 2 else last_close
    macd_val, macd_sig = macd(candles)
    return TechnicalSnapshot(
        last_price=round(last_close, 2),
        change_pct=round(((last_close - prev_close) / prev_close) * 100, 2) if prev_close else 0.0,
        rsi=round(rsi(candles), 2),
        macd=round(macd_val, 3),
        macd_signal=round(macd_sig, 3),
        sma_20=round(sma(candles, 20), 2),
        sma_50=round(sma(candles, 50), 2),
        sma_200=round(sma(candles, 200), 2),
        volume_ratio=round(volume_ratio(candles), 2),
        atr_pct=round(atr_pct(candles), 2),
    )


# ---------- Scoring -------------------------------------------------------------

def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def technical_score(snap: TechnicalSnapshot, horizon: str) -> Tuple[float, List[str]]:
    """Score 0..100 with human-readable signals."""
    signals: List[str] = []
    score = 50.0

    # RSI component
    if horizon == "intraday":
        if 45 <= snap.rsi <= 65:
            score += 10
            signals.append(f"RSI {snap.rsi} in momentum zone")
        elif snap.rsi > 75:
            score -= 10
            signals.append(f"RSI {snap.rsi} overbought")
        elif snap.rsi < 30:
            score += 6
            signals.append(f"RSI {snap.rsi} oversold bounce setup")
    else:  # longterm: prefer not-overbought
        if 40 <= snap.rsi <= 60:
            score += 8
            signals.append(f"RSI {snap.rsi} neutral, room to run")
        elif snap.rsi > 75:
            score -= 6
            signals.append(f"RSI {snap.rsi} overbought, wait for dip")

    # MACD crossover
    if snap.macd > snap.macd_signal:
        score += 10
        signals.append("MACD above signal (bullish)")
    else:
        score -= 8
        signals.append("MACD below signal (bearish)")

    # Trend via SMAs
    if snap.last_price > snap.sma_20 > snap.sma_50:
        score += 10
        signals.append("Price > SMA20 > SMA50 uptrend")
    elif snap.last_price < snap.sma_20 < snap.sma_50:
        score -= 10
        signals.append("Price < SMA20 < SMA50 downtrend")

    if snap.last_price > snap.sma_200:
        score += 5
        signals.append("Above 200-SMA (long-term uptrend)")
    else:
        score -= 5
        signals.append("Below 200-SMA (long-term weakness)")

    # Volume
    if horizon == "intraday" and snap.volume_ratio > 1.4:
        score += 10
        signals.append(f"Volume {snap.volume_ratio}x 20d avg (breakout fuel)")
    elif snap.volume_ratio < 0.6:
        score -= 4
        signals.append("Volume drying up")

    # Volatility (intraday wants some; long-term prefers calmer)
    if horizon == "intraday":
        if 1.0 <= snap.atr_pct <= 3.5:
            score += 5
            signals.append(f"ATR {snap.atr_pct}% healthy intraday range")
        elif snap.atr_pct > 4.5:
            score -= 5
            signals.append(f"ATR {snap.atr_pct}% too volatile")
    else:
        if snap.atr_pct < 2.5:
            score += 3
        elif snap.atr_pct > 4.0:
            score -= 5
            signals.append("High volatility - not ideal for long hold")

    return _clip(score), signals


def fundamental_score(fund: FundamentalSnapshot) -> Tuple[float, List[str]]:
    signals: List[str] = []
    score = 50.0

    # ROE
    if fund.roe >= 20:
        score += 15
        signals.append(f"Strong ROE {fund.roe}%")
    elif fund.roe >= 15:
        score += 8
    elif fund.roe < 8:
        score -= 10
        signals.append(f"Weak ROE {fund.roe}%")

    # Earnings growth
    if fund.eps_growth_3y >= 15:
        score += 12
        signals.append(f"EPS growth {fund.eps_growth_3y}% 3Y CAGR")
    elif fund.eps_growth_3y >= 8:
        score += 5
    elif fund.eps_growth_3y < 0:
        score -= 12
        signals.append("Negative EPS growth")

    # Revenue growth
    if fund.revenue_growth_3y >= 12:
        score += 6
    elif fund.revenue_growth_3y < 0:
        score -= 8

    # Valuation sanity (P/E)
    if 0 < fund.pe <= 20:
        score += 8
        signals.append(f"Reasonable valuation (P/E {fund.pe})")
    elif fund.pe > 60:
        score -= 10
        signals.append(f"Rich valuation (P/E {fund.pe})")

    # Leverage
    if fund.debt_to_equity <= 0.5:
        score += 6
        signals.append("Low debt")
    elif fund.debt_to_equity > 2:
        score -= 10
        signals.append(f"High leverage D/E {fund.debt_to_equity}")

    # Dividend (mild bonus)
    if fund.dividend_yield >= 2:
        score += 3
        signals.append(f"Div yield {fund.dividend_yield}%")

    # Promoter holding (confidence signal)
    if fund.promoter_holding >= 50:
        score += 3

    return _clip(score), signals


def composite(technical: float, fundamental: float, horizon: str) -> float:
    if horizon == "intraday":
        # Intraday: technicals dominate but fundamentals act as a quality filter.
        return _clip(0.8 * technical + 0.2 * fundamental)
    # Long-term: fundamentals dominate but technicals matter for timing.
    return _clip(0.35 * technical + 0.65 * fundamental)


# ---------- Suggestion builder --------------------------------------------------

def _action_from_score(score: float) -> str:
    if score >= 65:
        return "BUY"
    if score <= 35:
        return "SELL"
    return "HOLD"


def _risk_targets(snap: TechnicalSnapshot, horizon: str, action: str) -> Tuple[float, float, float]:
    price = snap.last_price
    if horizon == "intraday":
        sl_pct = max(0.6, snap.atr_pct * 0.9)
        tp_pct = max(1.5, snap.atr_pct * 1.8)
    else:
        sl_pct = 8.0
        tp_pct = 20.0
    if action == "SELL":
        sl_pct, tp_pct = -sl_pct, -tp_pct
    sl = round(price * (1 - sl_pct / 100), 2)
    tp = round(price * (1 + tp_pct / 100), 2)
    return price, sl, tp


def build_suggestion(
    meta: StockMeta,
    candles: List[OHLCV],
    horizon: str,
) -> Suggestion:
    tech_snap = build_technical_snapshot(candles)
    fund_snap = FundamentalSnapshot(
        market_cap_cr=meta.market_cap_cr,
        pe=meta.pe,
        pb=meta.pb,
        roe=meta.roe,
        debt_to_equity=meta.debt_to_equity,
        eps_growth_3y=meta.eps_growth_3y,
        revenue_growth_3y=meta.revenue_growth_3y,
        dividend_yield=meta.dividend_yield,
        promoter_holding=meta.promoter_holding,
    )
    t_score, t_signals = technical_score(tech_snap, horizon)
    f_score, f_signals = fundamental_score(fund_snap)
    comp = composite(t_score, f_score, horizon)
    action = _action_from_score(comp)
    entry, sl, tp = _risk_targets(tech_snap, horizon, action)
    expected = round(((tp - entry) / entry) * 100, 2) if entry else 0.0

    return Suggestion(
        symbol=meta.symbol,
        name=meta.name,
        sector=meta.sector,
        horizon=horizon,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        entry=round(entry, 2),
        stop_loss=sl,
        target=tp,
        expected_return_pct=expected,
        score=ScoreBreakdown(
            technical=round(t_score, 1),
            fundamental=round(f_score, 1),
            composite=round(comp, 1),
            signals=t_signals + f_signals,
        ),
        technical=tech_snap,
        fundamental=fund_snap,
    )
