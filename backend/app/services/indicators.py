"""Technical-indicator enrichment for the intraday analyzer.

The Claude prompt treats indicators as **inputs** — the LLM is expected to
reason over numbers, not to compute them. This module produces the
per-timeframe indicator bundles referenced in the user-prompt template.

Implemented directly in numpy so we don't pull in ``pandas-ta`` and its
transitive deps (Render free tier is tight). Formulas follow the standard
definitions used by TradingView / pandas-ta / TA-Lib:

* EMA(n) : exponential moving average with alpha = 2/(n+1)
* RSI(14): Wilder's smoothing
* MACD   : EMA12 - EMA26, signal EMA9 of the MACD line
* Bollinger(20,2): SMA20 ± 2·stdev
* ADX(14): Wilder; +DI / -DI
* ATR(14): Wilder smoothing of true range
* Supertrend(10,3): HL2 ± 3·ATR10, with flip logic
* Stochastic(14,3,3)
* MFI(14): money-flow index
* OBV    : on-balance volume
* VWAP   : intraday anchored (resets each session) + 1σ / 2σ bands

All functions take ``List[OHLCV]`` (from ``data_provider``) and return
plain floats or small dataclasses so the payload builder can serialise
them straight into JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from app.services.data_provider import OHLCV


# ---------------------------------------------------------------------- helpers

def _closes(c: List[OHLCV]) -> np.ndarray:
    return np.array([x.close for x in c], dtype=float)


def _highs(c: List[OHLCV]) -> np.ndarray:
    return np.array([x.high for x in c], dtype=float)


def _lows(c: List[OHLCV]) -> np.ndarray:
    return np.array([x.low for x in c], dtype=float)


def _vols(c: List[OHLCV]) -> np.ndarray:
    return np.array([x.volume for x in c], dtype=float)


def _safe_last(arr: np.ndarray, default: float = 0.0) -> float:
    if arr is None or len(arr) == 0:
        return default
    v = float(arr[-1])
    if not np.isfinite(v):
        return default
    return v


def ema(values: np.ndarray, span: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2.0 / (span + 1.0)
    out = np.zeros_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) < window:
        # pad with cumulative average at the front
        out = np.zeros_like(values, dtype=float)
        for i in range(len(values)):
            out[i] = values[: i + 1].mean()
        return out
    kernel = np.ones(window) / window
    base = np.convolve(values, kernel, mode="valid")
    # front-pad to keep aligned length
    pad = np.array([values[: i + 1].mean() for i in range(window - 1)])
    return np.concatenate([pad, base])


def _wilder(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing — used by RSI, ADX, ATR."""
    out = np.zeros_like(values, dtype=float)
    if len(values) < period:
        return out
    out[period - 1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


# ---------------------------------------------------------------------- core

def rsi(candles: List[OHLCV], period: int = 14) -> float:
    closes = _closes(candles)
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.clip(deltas, 0, None)
    losses = -np.clip(deltas, None, 0)
    avg_g = _wilder(gains, period)
    avg_l = _wilder(losses, period)
    if avg_l[-1] == 0:
        return 100.0
    rs = avg_g[-1] / avg_l[-1]
    return float(100 - 100 / (1 + rs))


def macd(
    candles: List[OHLCV], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[float, float, float]:
    closes = _closes(candles)
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    line = ema(closes, fast) - ema(closes, slow)
    sig = ema(line, signal)
    hist = line - sig
    return float(line[-1]), float(sig[-1]), float(hist[-1])


def bollinger(
    candles: List[OHLCV], window: int = 20, n_std: float = 2.0
) -> Tuple[float, float, float, float, float]:
    """Returns (upper, middle, lower, %B, bandwidth)."""
    closes = _closes(candles)
    if len(closes) < window:
        last = float(closes[-1]) if len(closes) else 0.0
        return last, last, last, 0.5, 0.0
    window_vals = closes[-window:]
    mid = float(window_vals.mean())
    sd = float(window_vals.std(ddof=0))
    upper = mid + n_std * sd
    lower = mid - n_std * sd
    last = float(closes[-1])
    pctb = (last - lower) / (upper - lower) if upper != lower else 0.5
    bw = (upper - lower) / mid if mid else 0.0
    return upper, mid, lower, pctb, bw


def atr(candles: List[OHLCV], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    highs, lows, closes = _highs(candles), _lows(candles), _closes(candles)
    trs = np.zeros(len(candles))
    for i in range(1, len(candles)):
        trs[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    out = _wilder(trs[1:], period)
    return float(out[-1])


def adx(candles: List[OHLCV], period: int = 14) -> Tuple[float, float, float]:
    """Returns (ADX, +DI, -DI)."""
    if len(candles) < period * 2:
        return 0.0, 0.0, 0.0
    highs, lows, closes = _highs(candles), _lows(candles), _closes(candles)
    plus_dm = np.zeros(len(candles))
    minus_dm = np.zeros(len(candles))
    trs = np.zeros(len(candles))
    for i in range(1, len(candles)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        trs[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr_s = _wilder(trs[1:], period)
    plus_s = _wilder(plus_dm[1:], period)
    minus_s = _wilder(minus_dm[1:], period)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(atr_s > 0, 100 * plus_s / atr_s, 0)
        mdi = np.where(atr_s > 0, 100 * minus_s / atr_s, 0)
        dx = np.where((pdi + mdi) > 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0)
    adx_line = _wilder(dx, period)
    return float(adx_line[-1]), float(pdi[-1]), float(mdi[-1])


def supertrend(
    candles: List[OHLCV], period: int = 10, multiplier: float = 3.0
) -> Tuple[float, int]:
    """Simplified Supertrend — returns (line, direction). dir: 1 up, -1 down."""
    if len(candles) < period + 1:
        return 0.0, 0
    highs, lows, closes = _highs(candles), _lows(candles), _closes(candles)
    hl2 = (highs + lows) / 2.0
    # ATR for the supertrend period
    trs = np.zeros(len(candles))
    for i in range(1, len(candles)):
        trs[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr_vals = _wilder(trs[1:], period)
    # Pad to align with candles length
    atr_padded = np.concatenate([[0.0], atr_vals])

    upperband = hl2 + multiplier * atr_padded
    lowerband = hl2 - multiplier * atr_padded

    st = np.zeros(len(candles))
    direction = np.ones(len(candles), dtype=int)

    for i in range(1, len(candles)):
        if closes[i] > upperband[i - 1]:
            direction[i] = 1
        elif closes[i] < lowerband[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
            # Lock bands (simplified: don't tighten against the trend)
            if direction[i] == 1 and lowerband[i] < lowerband[i - 1]:
                lowerband[i] = lowerband[i - 1]
            if direction[i] == -1 and upperband[i] > upperband[i - 1]:
                upperband[i] = upperband[i - 1]
        st[i] = lowerband[i] if direction[i] == 1 else upperband[i]

    return float(st[-1]), int(direction[-1])


def stochastic(
    candles: List[OHLCV], k_period: int = 14, k_smooth: int = 3, d_smooth: int = 3
) -> Tuple[float, float]:
    if len(candles) < k_period + k_smooth + d_smooth:
        return 50.0, 50.0
    highs, lows, closes = _highs(candles), _lows(candles), _closes(candles)
    k_raw = np.zeros(len(candles))
    for i in range(k_period - 1, len(candles)):
        hh = highs[i - k_period + 1 : i + 1].max()
        ll = lows[i - k_period + 1 : i + 1].min()
        k_raw[i] = 100 * (closes[i] - ll) / (hh - ll) if hh != ll else 50.0
    k_smoothed = sma(k_raw, k_smooth)
    d_line = sma(k_smoothed, d_smooth)
    return float(k_smoothed[-1]), float(d_line[-1])


def mfi(candles: List[OHLCV], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 50.0
    highs, lows, closes, vols = _highs(candles), _lows(candles), _closes(candles), _vols(candles)
    tp = (highs + lows + closes) / 3.0
    rmf = tp * vols
    pos = np.zeros(len(candles))
    neg = np.zeros(len(candles))
    for i in range(1, len(candles)):
        if tp[i] > tp[i - 1]:
            pos[i] = rmf[i]
        elif tp[i] < tp[i - 1]:
            neg[i] = rmf[i]
    p = pos[-period:].sum()
    n = neg[-period:].sum()
    if n == 0:
        return 100.0
    mr = p / n
    return float(100 - 100 / (1 + mr))


def obv_slope(candles: List[OHLCV], lookback: int = 10) -> float:
    """OBV slope over the last ``lookback`` bars — proxy for volume trend."""
    if len(candles) < lookback + 1:
        return 0.0
    closes, vols = _closes(candles), _vols(candles)
    obv = np.zeros(len(candles))
    for i in range(1, len(candles)):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + vols[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - vols[i]
        else:
            obv[i] = obv[i - 1]
    y = obv[-lookback:]
    x = np.arange(len(y))
    # Normalised slope so the number is on a comparable scale across symbols.
    slope = float(np.polyfit(x, y, 1)[0])
    scale = float(np.mean(np.abs(vols[-lookback:]))) or 1.0
    return slope / scale


def vwap_with_bands(
    candles: List[OHLCV], session_start_idx: int = 0, n_std: float = 2.0
) -> Tuple[float, float, float, float, float]:
    """Intraday anchored VWAP + ±1σ and ±2σ bands.

    Assumes ``candles`` is a contiguous intraday series starting at the
    session open (or an anchor). Returns (vwap, u1, l1, u2, l2).
    """
    if len(candles) == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    c = candles[session_start_idx:]
    if not c:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    tp = np.array([(x.high + x.low + x.close) / 3.0 for x in c])
    vols = np.array([x.volume for x in c])
    cum_v = np.cumsum(vols)
    cum_tpv = np.cumsum(tp * vols)
    vwap = np.where(cum_v > 0, cum_tpv / cum_v, tp)
    # Running stdev of TP weighted by volume, approximated by rolling.
    dev = tp - vwap
    cum_dev2_v = np.cumsum(dev * dev * vols)
    var = np.where(cum_v > 0, cum_dev2_v / cum_v, 0.0)
    sd = np.sqrt(var)
    last_vwap = float(vwap[-1])
    last_sd = float(sd[-1])
    return (
        last_vwap,
        last_vwap + last_sd,
        last_vwap - last_sd,
        last_vwap + n_std * last_sd,
        last_vwap - n_std * last_sd,
    )


# ---------------------------------------------------------------------- bundles

@dataclass
class DailyIndicators:
    ema9: float
    ema20: float
    ema50: float
    ema200: float
    rsi14: float
    macd: float
    macd_signal: float
    macd_hist: float
    adx: float
    plus_di: float
    minus_di: float
    atr14: float
    supertrend: float
    supertrend_dir: int
    trend_label: str


@dataclass
class IntradayIndicators:
    ema9: float
    ema20: float
    ema50: float
    vwap: float
    vwap_u1: float
    vwap_l1: float
    vwap_u2: float
    vwap_l2: float
    rsi14: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_pctb: float
    bb_bandwidth: float
    adx: float
    atr14: float
    stoch_k: float
    stoch_d: float
    supertrend: float
    supertrend_dir: int
    obv_slope: float
    mfi14: float
    last_volume: float
    avg_volume_20: float
    vol_ratio: float
    candle_pattern: str


def _trend_label(ema20: float, ema50: float, ema200: float, adx_val: float) -> str:
    if adx_val < 18:
        return "sideways"
    if ema20 > ema50 > ema200:
        return "strong_up" if adx_val > 25 else "up"
    if ema20 < ema50 < ema200:
        return "strong_down" if adx_val > 25 else "down"
    return "sideways"


def build_daily(candles: List[OHLCV]) -> DailyIndicators:
    closes = _closes(candles)
    e9 = _safe_last(ema(closes, 9))
    e20 = _safe_last(ema(closes, 20))
    e50 = _safe_last(ema(closes, 50))
    e200 = _safe_last(ema(closes, 200))
    m, s, h = macd(candles)
    a, pdi, mdi = adx(candles)
    at = atr(candles)
    st, sd = supertrend(candles)
    return DailyIndicators(
        ema9=round(e9, 3),
        ema20=round(e20, 3),
        ema50=round(e50, 3),
        ema200=round(e200, 3),
        rsi14=round(rsi(candles), 2),
        macd=round(m, 4),
        macd_signal=round(s, 4),
        macd_hist=round(h, 4),
        adx=round(a, 2),
        plus_di=round(pdi, 2),
        minus_di=round(mdi, 2),
        atr14=round(at, 3),
        supertrend=round(st, 3),
        supertrend_dir=sd,
        trend_label=_trend_label(e20, e50, e200, a),
    )


def detect_candle_pattern(candles: List[OHLCV]) -> str:
    """Lightweight pattern detection on the last 1-2 candles.

    Returns one of: bullish_engulfing, bearish_engulfing, hammer,
    shooting_star, doji, marubozu_up, marubozu_down, none.
    """
    if len(candles) < 2:
        return "none"
    prev, last = candles[-2], candles[-1]
    body = abs(last.close - last.open)
    rng = last.high - last.low
    if rng == 0:
        return "none"
    upper = last.high - max(last.close, last.open)
    lower = min(last.close, last.open) - last.low

    # Engulfing
    prev_body = abs(prev.close - prev.open)
    if (
        last.close > last.open
        and prev.close < prev.open
        and last.close >= prev.open
        and last.open <= prev.close
        and body > prev_body
    ):
        return "bullish_engulfing"
    if (
        last.close < last.open
        and prev.close > prev.open
        and last.open >= prev.close
        and last.close <= prev.open
        and body > prev_body
    ):
        return "bearish_engulfing"

    # Doji
    if body / rng < 0.1:
        return "doji"

    # Hammer / shooting star
    if body / rng < 0.35:
        if lower > 2 * body and upper < body:
            return "hammer"
        if upper > 2 * body and lower < body:
            return "shooting_star"

    # Marubozu (almost no wicks)
    if body / rng > 0.9:
        return "marubozu_up" if last.close > last.open else "marubozu_down"

    return "none"


def build_intraday(candles: List[OHLCV]) -> IntradayIndicators:
    closes = _closes(candles)
    vols = _vols(candles)
    e9 = _safe_last(ema(closes, 9))
    e20 = _safe_last(ema(closes, 20))
    e50 = _safe_last(ema(closes, 50))
    vw, u1, l1, u2, l2 = vwap_with_bands(candles)
    m, s, h = macd(candles)
    bu, bm, bl, pctb, bw = bollinger(candles)
    a, _, _ = adx(candles)
    at = atr(candles)
    k, d = stochastic(candles)
    st, sd = supertrend(candles)
    obs = obv_slope(candles)
    mf = mfi(candles)
    last_vol = float(vols[-1]) if len(vols) else 0.0
    avg_vol = float(vols[-20:].mean()) if len(vols) >= 20 else float(vols.mean() if len(vols) else 0.0)
    ratio = last_vol / avg_vol if avg_vol else 1.0
    return IntradayIndicators(
        ema9=round(e9, 3),
        ema20=round(e20, 3),
        ema50=round(e50, 3),
        vwap=round(vw, 3),
        vwap_u1=round(u1, 3),
        vwap_l1=round(l1, 3),
        vwap_u2=round(u2, 3),
        vwap_l2=round(l2, 3),
        rsi14=round(rsi(candles), 2),
        macd=round(m, 4),
        macd_signal=round(s, 4),
        macd_hist=round(h, 4),
        bb_upper=round(bu, 3),
        bb_middle=round(bm, 3),
        bb_lower=round(bl, 3),
        bb_pctb=round(pctb, 3),
        bb_bandwidth=round(bw, 4),
        adx=round(a, 2),
        atr14=round(at, 3),
        stoch_k=round(k, 2),
        stoch_d=round(d, 2),
        supertrend=round(st, 3),
        supertrend_dir=sd,
        obv_slope=round(obs, 4),
        mfi14=round(mf, 2),
        last_volume=round(last_vol, 0),
        avg_volume_20=round(avg_vol, 0),
        vol_ratio=round(ratio, 2),
        candle_pattern=detect_candle_pattern(candles),
    )


# ---------------------------------------------------------------------- levels

@dataclass
class KeyLevels:
    pdh: float
    pdl: float
    pdc: float
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float
    orh: float
    orl: float
    swing_highs: List[float]
    swing_lows: List[float]
    wk52_high: float
    wk52_low: float
    gap_type: str
    gap_pct: float


def _classical_pivots(pdh: float, pdl: float, pdc: float) -> Tuple[float, float, float, float, float, float, float]:
    p = (pdh + pdl + pdc) / 3.0
    r1 = 2 * p - pdl
    s1 = 2 * p - pdh
    r2 = p + (pdh - pdl)
    s2 = p - (pdh - pdl)
    r3 = pdh + 2 * (p - pdl)
    s3 = pdl - 2 * (pdh - p)
    return p, r1, r2, r3, s1, s2, s3


def _swings(candles: List[OHLCV], k: int = 3) -> Tuple[List[float], List[float]]:
    highs, lows = _highs(candles), _lows(candles)
    sh, sl = [], []
    for i in range(k, len(candles) - k):
        if highs[i] == highs[i - k : i + k + 1].max():
            sh.append(float(highs[i]))
        if lows[i] == lows[i - k : i + k + 1].min():
            sl.append(float(lows[i]))
    # Deduplicate while preserving order, keep most recent 5.
    sh = list(dict.fromkeys(sh))[-5:]
    sl = list(dict.fromkeys(sl))[-5:]
    return sh, sl


def build_key_levels(
    daily: List[OHLCV],
    m5: List[OHLCV],
    today_open: float,
) -> KeyLevels:
    if len(daily) < 2:
        pdh = pdl = pdc = today_open
    else:
        prev = daily[-2]
        pdh, pdl, pdc = float(prev.high), float(prev.low), float(prev.close)
    p, r1, r2, r3, s1, s2, s3 = _classical_pivots(pdh, pdl, pdc)

    # Opening range = first 15 minutes = first 3 candles at 5m
    if len(m5) >= 3:
        orh = float(max(x.high for x in m5[:3]))
        orl = float(min(x.low for x in m5[:3]))
    elif m5:
        orh = float(max(x.high for x in m5))
        orl = float(min(x.low for x in m5))
    else:
        orh = orl = today_open

    sh, sl = _swings(daily[-20:]) if len(daily) >= 6 else ([], [])

    wk52_high = float(max((c.high for c in daily[-252:]), default=today_open))
    wk52_low = float(min((c.low for c in daily[-252:]), default=today_open))

    gap_abs = today_open - pdc
    gap_pct = (gap_abs / pdc * 100) if pdc else 0.0
    if abs(gap_pct) < 0.15:
        gap_type = "flat"
    elif gap_pct > 0:
        gap_type = "gap_up"
    else:
        gap_type = "gap_down"

    return KeyLevels(
        pdh=round(pdh, 2),
        pdl=round(pdl, 2),
        pdc=round(pdc, 2),
        pivot=round(p, 2),
        r1=round(r1, 2),
        r2=round(r2, 2),
        r3=round(r3, 2),
        s1=round(s1, 2),
        s2=round(s2, 2),
        s3=round(s3, 2),
        orh=round(orh, 2),
        orl=round(orl, 2),
        swing_highs=[round(x, 2) for x in sh],
        swing_lows=[round(x, 2) for x in sl],
        wk52_high=round(wk52_high, 2),
        wk52_low=round(wk52_low, 2),
        gap_type=gap_type,
        gap_pct=round(gap_pct, 2),
    )


# ---------------------------------------------------------------------- patterns

def detect_recent_patterns(m5: List[OHLCV], m15: List[OHLCV]) -> list[dict]:
    """Scan the last ~60 minutes for notable patterns across 5m/15m."""
    out: list[dict] = []
    for tf_label, series in (("5m", m5[-12:]), ("15m", m15[-4:])):
        if len(series) < 2:
            continue
        pattern = detect_candle_pattern(list(series))
        if pattern != "none":
            last = series[-1]
            out.append(
                {
                    "pattern": pattern,
                    "timeframe": tf_label,
                    "time": last.timestamp.strftime("%H:%M") if last.timestamp else "",
                    "level": round(last.close, 2),
                }
            )
    return out
