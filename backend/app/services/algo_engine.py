"""Rule-based Algorithmic Trading Engine.

Implements 9 quantitative strategies simultaneously and fires a signal
only when ≥ 3 strategies agree on direction (confluence rule).

Strategies implemented
──────────────────────
  S1  VWAP Mean Reversion       (Goldman Sachs / Jane Street style)
  S2  EMA Crossover Momentum    (Renaissance Technologies / Citadel style)
  S3  RSI + MACD Combo          (Two Sigma / Bridgewater style)
  S4  Bollinger Band Breakout   (DE Shaw / Virtu Financial style)
  S5  Opening Range Breakout    (Jane Street / IMC Trading style)
  S6  Supertrend + ADX Filter   (Zerodha Streak / Upstox Pro style)
  S7  Volume Profile S/R        (Bloomberg Terminal style)
  S8  Gap and Go                (Prop trading / DAS Trader style)
  S9  Stat Arb / Relative Str   (Two Sigma / AQR Capital style)

Confluence scoring
──────────────────
  1 strategy  → AVOID  (no trade)
  2 strategies → HOLD  (low, paper-trade only)
  3 strategies → MEDIUM confidence signal
  4 strategies → HIGH confidence signal
  5+           → HIGH confidence signal (can size up)

All price calculations are pure arithmetic — no broker calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services import indicators as ind

# Independent signals and regime are imported lazily inside run() to avoid
# circular-import issues at module load time.



# ─────────────────────────────────────────────── data contract ─────────────

@dataclass
class MarketContext:
    """Slice of the fill-dict that the engine needs for market-wide context."""
    ltp: float
    day_open: float
    prev_close: float
    day_change_pct: float
    avg_daily_volume: float
    day_volume: float
    gap_type: str          # "gap_up" | "gap_down" | "flat"
    gap_pct: float
    # risk params
    capital: float = 100_000.0
    risk_pct: float = 1.5


@dataclass
class StrategyResult:
    """Output of a single strategy evaluation."""
    name: str        # human label
    tag: str         # short ID used in strategies_triggered list
    direction: int   # 1=bullish / -1=bearish / 0=neutral
    reason: str      # one-liner justification


# ─────────────────────────────────────────── pre-trade filters ─────────────

def _check_pre_trade_filters(
    ctx: MarketContext,
    m5: ind.IntradayIndicators,
    meta_market_cap_cr: float,
) -> Tuple[bool, List[str]]:
    """Return (passed, list_of_failures)."""
    failures: List[str] = []

    if ctx.avg_daily_volume < 500_000:
        failures.append(
            f"Avg daily volume {ctx.avg_daily_volume:,.0f} < 500 000 (liquidity filter)"
        )
    if ctx.ltp < 50:
        failures.append(f"LTP ₹{ctx.ltp:.2f} < ₹50 (penny-stock filter)")

    # ATR% must be > 1.5 for enough intraday range
    if ctx.ltp > 0:
        atr_pct = (m5.atr14 / ctx.ltp) * 100
        if atr_pct < 1.5:
            failures.append(
                f"ATR% {atr_pct:.2f}% < 1.5% (insufficient volatility)"
            )

    if meta_market_cap_cr < 500:
        failures.append(
            f"Market cap ₹{meta_market_cap_cr:.0f} Cr < ₹500 Cr (micro-cap filter)"
        )

    return len(failures) == 0, failures


# ─────────────────────────────────── individual strategy evaluators ────────

def _s1_vwap_mean_reversion(
    ltp: float,
    m5: ind.IntradayIndicators,
) -> StrategyResult:
    """VWAP Mean Reversion — intraday anchor strategy."""
    vwap = m5.vwap
    rsi = m5.rsi14
    macd_hist = m5.macd_hist

    if vwap <= 0:
        return StrategyResult("VWAP Mean Reversion", "VWAP", 0, "VWAP not available")

    # BUY: price dipped below VWAP and RSI oversold, momentum turning up
    if ltp < vwap and rsi < 40 and macd_hist > -0.1:
        gap = round((vwap - ltp) / vwap * 100, 2)
        return StrategyResult(
            "VWAP Mean Reversion", "VWAP", 1,
            f"Price {gap}% below VWAP; RSI {rsi:.1f} oversold; MACD hist recovering"
        )
    # SELL: price extended above VWAP with RSI overbought, momentum fading
    if ltp > vwap and rsi > 62 and macd_hist < 0.1:
        gap = round((ltp - vwap) / vwap * 100, 2)
        return StrategyResult(
            "VWAP Mean Reversion", "VWAP", -1,
            f"Price {gap}% above VWAP; RSI {rsi:.1f} overbought; MACD hist fading"
        )
    return StrategyResult("VWAP Mean Reversion", "VWAP", 0,
                          f"Price vs VWAP neutral (RSI {rsi:.1f})")


def _s2_ema_crossover(
    ltp: float,
    m5: ind.IntradayIndicators,
    daily: ind.DailyIndicators,
) -> StrategyResult:
    """EMA Crossover Momentum — trend-following."""
    e9, e20, e50 = m5.ema9, m5.ema20, m5.ema50
    vol_ratio = m5.vol_ratio
    d_e200 = daily.ema200

    # Strong bullish stack: 9 > 20 > 50 with volume confirmation
    if e9 > e20 > e50 and vol_ratio >= 1.5:
        stack = "9>20>50"
        if ltp > d_e200:
            stack += ">200d (golden stack)"
        return StrategyResult(
            "EMA Crossover Momentum", "EMA_CROSSOVER", 1,
            f"EMA stack {stack}, vol {vol_ratio:.1f}x avg"
        )
    # Partial bullish: 9 > 20 and price above 50, decent volume
    if e9 > e20 and ltp > e50 and vol_ratio >= 1.3:
        return StrategyResult(
            "EMA Crossover Momentum", "EMA_CROSSOVER", 1,
            f"EMA(9) crossed above EMA(20), price above EMA(50), vol {vol_ratio:.1f}x"
        )
    # Bearish: 9 < 20 or price broke EMA50
    if e9 < e20 and ltp < e50:
        return StrategyResult(
            "EMA Crossover Momentum", "EMA_CROSSOVER", -1,
            f"EMA(9) < EMA(20) and price below EMA(50) — bearish momentum"
        )
    return StrategyResult(
        "EMA Crossover Momentum", "EMA_CROSSOVER", 0,
        f"EMA stack not aligned (9={e9:.2f}, 20={e20:.2f}, 50={e50:.2f})"
    )


def _s3_rsi_macd(
    ltp: float,
    m15: ind.IntradayIndicators,
) -> StrategyResult:
    """RSI + MACD Combo — momentum oscillator confluence."""
    rsi = m15.rsi14
    macd_line = m15.macd
    macd_sig = m15.macd_signal
    macd_hist = m15.macd_hist

    # Oversold recovery: RSI crossing up from oversold + MACD bullish cross
    if 28 <= rsi <= 52 and macd_line > macd_sig and macd_hist > 0:
        return StrategyResult(
            "RSI + MACD Combo", "RSI_MACD", 1,
            f"RSI {rsi:.1f} recovering from oversold; MACD line ({macd_line:.4f}) "
            f"above signal; histogram +{macd_hist:.4f}"
        )
    # Strong buy: RSI in momentum zone with positive MACD
    if 50 <= rsi <= 65 and macd_hist > 0 and macd_line > 0:
        return StrategyResult(
            "RSI + MACD Combo", "RSI_MACD", 1,
            f"RSI {rsi:.1f} momentum zone; MACD positive and growing"
        )
    # Overbought fade: RSI crossing down from overbought + MACD bearish cross
    if 48 <= rsi <= 72 and macd_line < macd_sig and macd_hist < 0:
        return StrategyResult(
            "RSI + MACD Combo", "RSI_MACD", -1,
            f"RSI {rsi:.1f} fading; MACD line ({macd_line:.4f}) below signal; "
            f"histogram {macd_hist:.4f}"
        )
    if rsi > 72:
        return StrategyResult(
            "RSI + MACD Combo", "RSI_MACD", -1,
            f"RSI {rsi:.1f} severely overbought"
        )
    return StrategyResult(
        "RSI + MACD Combo", "RSI_MACD", 0,
        f"RSI {rsi:.1f} / MACD hist {macd_hist:.4f} — no clear signal"
    )


def _s4_bollinger_band(
    ltp: float,
    m15: ind.IntradayIndicators,
) -> StrategyResult:
    """Bollinger Band Breakout / Mean Reversion."""
    bb_upper = m15.bb_upper
    bb_lower = m15.bb_lower
    bb_mid = m15.bb_middle
    bb_pctb = m15.bb_pctb
    vol_ratio = m15.vol_ratio
    rsi = m15.rsi14

    # Breakout: price bursts above upper band with high volume
    if ltp > bb_upper and vol_ratio > 1.8:
        return StrategyResult(
            "Bollinger Band Breakout", "BOLLINGER", 1,
            f"Price broke above BB upper ({bb_upper:.2f}) with {vol_ratio:.1f}x volume"
        )
    # Mean reversion BUY: price at or below lower band
    if bb_pctb < 0.12 and rsi < 38:
        return StrategyResult(
            "Bollinger Band Breakout", "BOLLINGER", 1,
            f"Price at/below BB lower ({bb_lower:.2f}), %B={bb_pctb:.2f}, RSI {rsi:.1f}"
        )
    # Squeeze: extremely tight bands → imminent move; wait for direction
    # We flag the bias based on where price is vs mid
    bw = m15.bb_bandwidth
    if bw < 0.03 and ltp > bb_mid:
        return StrategyResult(
            "Bollinger Band Breakout", "BOLLINGER", 1,
            f"BB squeeze (BW={bw:.4f}), price above midband — upside bias"
        )
    if bw < 0.03 and ltp < bb_mid:
        return StrategyResult(
            "Bollinger Band Breakout", "BOLLINGER", -1,
            f"BB squeeze (BW={bw:.4f}), price below midband — downside bias"
        )
    # Mean reversion SELL: price extended at upper band, RSI overbought
    if bb_pctb > 0.90 and rsi > 68:
        return StrategyResult(
            "Bollinger Band Breakout", "BOLLINGER", -1,
            f"Price at BB upper ({bb_upper:.2f}), %B={bb_pctb:.2f}, RSI {rsi:.1f} overbought"
        )
    return StrategyResult(
        "Bollinger Band Breakout", "BOLLINGER", 0,
        f"Price inside bands (%B={bb_pctb:.2f}) — no breakout signal"
    )


def _s5_orb(
    ltp: float,
    levels: ind.KeyLevels,
    vol_ratio: float,
) -> StrategyResult:
    """Opening Range Breakout — first 15-min high/low breakout."""
    orh = levels.orh
    orl = levels.orl

    if orh <= 0 or orl <= 0 or orh == orl:
        return StrategyResult("Opening Range Breakout", "ORB", 0, "ORB levels not set")

    orb_size = orh - orl

    # Bullish breakout above ORH
    if ltp > orh * 1.001 and vol_ratio >= 1.4:
        target = round(orh + orb_size, 2)
        return StrategyResult(
            "Opening Range Breakout", "ORB", 1,
            f"Price ({ltp:.2f}) broke above ORH ({orh:.2f}) with {vol_ratio:.1f}x vol; "
            f"ORB target {target:.2f}"
        )
    # Bearish breakdown below ORL
    if ltp < orl * 0.999 and vol_ratio >= 1.4:
        target = round(orl - orb_size, 2)
        return StrategyResult(
            "Opening Range Breakout", "ORB", -1,
            f"Price ({ltp:.2f}) broke below ORL ({orl:.2f}) with {vol_ratio:.1f}x vol; "
            f"ORB target {target:.2f}"
        )
    return StrategyResult(
        "Opening Range Breakout", "ORB", 0,
        f"Price ({ltp:.2f}) inside ORB ({orl:.2f}-{orh:.2f})"
    )


def _s6_supertrend_adx(
    ltp: float,
    m15: ind.IntradayIndicators,
    daily: ind.DailyIndicators,
) -> StrategyResult:
    """Supertrend + ADX Trend Filter."""
    st_dir_15 = m15.supertrend_dir
    adx_15 = m15.adx
    st_dir_d = daily.supertrend_dir
    adx_d = daily.adx

    # Both timeframes agree — strongest signal
    if st_dir_15 == 1 and adx_15 > 25:
        strength = "strong" if adx_15 > 35 else "moderate"
        daily_confirm = " (daily Supertrend also green)" if st_dir_d == 1 else ""
        return StrategyResult(
            "Supertrend + ADX", "SUPERTREND_ADX", 1,
            f"Supertrend GREEN on 15m; ADX {adx_15:.1f} ({strength} trend){daily_confirm}"
        )
    if st_dir_15 == -1 and adx_15 > 25:
        strength = "strong" if adx_15 > 35 else "moderate"
        daily_confirm = " (daily Supertrend also red)" if st_dir_d == -1 else ""
        return StrategyResult(
            "Supertrend + ADX", "SUPERTREND_ADX", -1,
            f"Supertrend RED on 15m; ADX {adx_15:.1f} ({strength} trend){daily_confirm}"
        )
    if adx_15 < 20:
        return StrategyResult(
            "Supertrend + ADX", "SUPERTREND_ADX", 0,
            f"ADX {adx_15:.1f} < 20 — ranging market, trend filter inactive"
        )
    return StrategyResult(
        "Supertrend + ADX", "SUPERTREND_ADX", 0,
        f"Supertrend dir={st_dir_15}, ADX {adx_15:.1f} — inconclusive"
    )


def _s7_volume_sr(
    ltp: float,
    levels: ind.KeyLevels,
    m15: ind.IntradayIndicators,
) -> StrategyResult:
    """Volume Profile + Support/Resistance (classical pivot approximation)."""
    rsi = m15.rsi14
    vol_ratio = m15.vol_ratio

    def near(price: float, ref: float, pct: float = 1.5) -> bool:
        return ref > 0 and abs(price - ref) / ref * 100 <= pct

    # Near key support levels
    at_support = (
        near(ltp, levels.s1) or
        near(ltp, levels.s2) or
        near(ltp, levels.pdl)
    )
    # Near key resistance levels
    at_resistance = (
        near(ltp, levels.r1) or
        near(ltp, levels.r2) or
        near(ltp, levels.pdh)
    )

    if at_support and 35 <= rsi <= 58:
        which = (
            f"S1({levels.s1:.2f})" if near(ltp, levels.s1)
            else f"S2({levels.s2:.2f})" if near(ltp, levels.s2)
            else f"PDL({levels.pdl:.2f})"
        )
        return StrategyResult(
            "Volume Profile S/R", "VOLUME_SR", 1,
            f"Price near {which} support; RSI {rsi:.1f} in buy zone"
        )
    if at_resistance and rsi > 58 and vol_ratio < 1.5:
        which = (
            f"R1({levels.r1:.2f})" if near(ltp, levels.r1)
            else f"R2({levels.r2:.2f})" if near(ltp, levels.r2)
            else f"PDH({levels.pdh:.2f})"
        )
        return StrategyResult(
            "Volume Profile S/R", "VOLUME_SR", -1,
            f"Price at {which} resistance; RSI {rsi:.1f} extended; volume fading"
        )
    return StrategyResult(
        "Volume Profile S/R", "VOLUME_SR", 0,
        f"Price not at key S/R levels (RSI {rsi:.1f})"
    )


def _s8_gap_and_go(
    ltp: float,
    ctx: MarketContext,
    m5: ind.IntradayIndicators,
) -> StrategyResult:
    """Gap and Go — news-catalyst gap follow-through."""
    gap_type = ctx.gap_type
    gap_pct = ctx.gap_pct
    pdc = ctx.prev_close
    vol_ratio = m5.vol_ratio

    # Gap UP and holding: bullish gap-and-go
    if gap_type == "gap_up" and gap_pct >= 2.0 and ltp > pdc * 1.01 and vol_ratio >= 1.5:
        return StrategyResult(
            "Gap and Go", "GAP_AND_GO", 1,
            f"Gap UP {gap_pct:.1f}%; price holding above PDC+1%; vol {vol_ratio:.1f}x"
        )
    # Gap UP failing: gap fill trade (short)
    if gap_type == "gap_up" and gap_pct >= 2.0 and ltp < pdc * 1.005:
        return StrategyResult(
            "Gap and Go", "GAP_AND_GO", -1,
            f"Gap UP {gap_pct:.1f}% failing below gap level — gap fill in progress"
        )
    # Gap DOWN and holding: bearish continuation
    if gap_type == "gap_down" and gap_pct <= -2.0 and ltp < pdc * 0.99 and vol_ratio >= 1.5:
        return StrategyResult(
            "Gap and Go", "GAP_AND_GO", -1,
            f"Gap DOWN {abs(gap_pct):.1f}%; price below PDC-1%; vol {vol_ratio:.1f}x"
        )
    return StrategyResult(
        "Gap and Go", "GAP_AND_GO", 0,
        f"Gap {gap_type} {gap_pct:+.1f}% — no actionable gap setup"
    )


def _s9_stat_arb_rel_strength(
    ltp: float,
    ctx: MarketContext,
    m5: ind.IntradayIndicators,
    m15: ind.IntradayIndicators,
) -> StrategyResult:
    """Statistical Arb / Relative Strength divergence.

    Single-stock approximation: combines OBV slope (institutional flow) with
    price vs VWAP divergence. When volume is accumulating while price still
    lags VWAP, a mean reversion to fair value is probable — and vice versa.
    """
    obv_slope = m5.obv_slope   # positive = net buying pressure
    mfi = m5.mfi14             # volume-weighted momentum
    vwap = m5.vwap
    rsi = m15.rsi14

    # Positive divergence: OBV/MFI rising while price below VWAP
    if obv_slope > 0.4 and mfi > 52 and ltp < vwap and rsi < 55:
        return StrategyResult(
            "Stat Arb / Relative Strength", "STAT_ARB", 1,
            f"OBV slope +{obv_slope:.2f} (accumulation), MFI {mfi:.1f} > 50; "
            f"price below VWAP — positive divergence buy"
        )
    # Negative divergence: OBV/MFI falling while price above VWAP
    if obv_slope < -0.4 and mfi < 48 and ltp > vwap and rsi > 45:
        return StrategyResult(
            "Stat Arb / Relative Strength", "STAT_ARB", -1,
            f"OBV slope {obv_slope:.2f} (distribution), MFI {mfi:.1f} < 50; "
            f"price above VWAP — negative divergence sell"
        )
    # Stock dramatically underperforming market while market positive
    if ctx.day_change_pct < -2.0 and ctx.gap_type == "gap_down":
        return StrategyResult(
            "Stat Arb / Relative Strength", "STAT_ARB", -1,
            f"Stock -2%+ vs neutral market context — relative weakness"
        )
    return StrategyResult(
        "Stat Arb / Relative Strength", "STAT_ARB", 0,
        f"OBV slope {obv_slope:.2f}, MFI {mfi:.1f} — no divergence signal"
    )


# ──────────────────────────────────────── confluence + signal builder ───────

def _hold_period(strategies_triggered: List[str], daily: ind.DailyIndicators) -> str:
    tags = set(strategies_triggered)
    # Intraday setups dominate when present
    if "ORB" in tags or ("GAP_AND_GO" in tags and "VWAP" in tags):
        return "Intraday"
    # Strong trend setups → swing
    if "SUPERTREND_ADX" in tags or "EMA_CROSSOVER" in tags:
        # Check daily EMA stack for positional upgrade
        d = daily
        if d.ema9 > d.ema20 > d.ema50 and d.adx > 30:
            return "Positional 2-4 weeks"
        return "Swing 3-5 days"
    return "Intraday"


def _confidence(count: int) -> str:
    if count >= 4:
        return "HIGH"
    if count == 3:
        return "MEDIUM"
    return "LOW"


def _price_targets(
    action: str,
    ltp: float,
    atr: float,
    levels: ind.KeyLevels,
    ctx: MarketContext,
) -> Tuple[float, float, float]:
    """Return (entry, stop_loss, target_1, target_2) — also stop is returned."""
    if atr <= 0:
        atr = ltp * 0.015   # fallback: 1.5% of price

    entry = round(ltp, 2)

    if action == "BUY":
        sl = round(entry - 1.5 * atr, 2)
        # Ensure stop is not too far (cap at 3%)
        sl = max(sl, round(entry * 0.97, 2))
        risk = entry - sl
        t1 = round(entry + 2.0 * risk, 2)
        t2 = round(entry + 3.5 * risk, 2)
        # Override T1 with nearest resistance if tighter and still ≥1R
        nr = levels.r1
        if 0 < nr < t1 and (nr - entry) >= risk:
            t1 = round(nr, 2)
        nr2 = levels.r2
        if 0 < nr2 < t2 and (nr2 - entry) >= 2 * risk:
            t2 = round(nr2, 2)
    else:  # SELL
        sl = round(entry + 1.5 * atr, 2)
        sl = min(sl, round(entry * 1.03, 2))
        risk = sl - entry
        t1 = round(entry - 2.0 * risk, 2)
        t2 = round(entry - 3.5 * risk, 2)
        # Override T1 with nearest support if tighter and still ≥1R
        ns = levels.s1
        if 0 < ns < entry and (entry - ns) >= risk:
            t1 = round(ns, 2)
        ns2 = levels.s2
        if 0 < ns2 > t2 and (entry - ns2) >= 2 * risk:
            t2 = round(ns2, 2)

    return entry, sl, t1, t2


def _position_size(entry: float, stop: float, capital: float, risk_pct: float) -> int:
    """Fixed fractional risk sizing."""
    if entry <= 0 or stop <= 0:
        return 0
    risk_inr = capital * risk_pct / 100.0
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return 0
    return int(math.floor(risk_inr / stop_dist))


def _rr_string(entry: float, stop: float, t1: float) -> str:
    risk = abs(entry - stop)
    reward = abs(t1 - entry)
    if risk <= 0:
        return "1:2"
    ratio = reward / risk
    return f"1:{ratio:.1f}"


# ──────────────────────────────────────────────────── public API ────────────

@dataclass
class AlgoEngineResult:
    """Full output of the algo engine for one stock."""
    stock: str
    date: str
    time: str
    action: str                         # BUY / SELL / HOLD / AVOID
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    hold_period: str
    confidence: str                     # HIGH / MEDIUM / LOW
    risk_reward_ratio: str
    strategies_triggered: List[str]
    strategy_confluence_count: int
    reason: str
    book_profit_instruction: str
    risk_per_trade_percent: float
    suggested_position_size_units: int
    # Pre-trade filter status
    pre_trade_filters_passed: bool
    filter_failures: List[str]
    # Raw per-strategy detail for transparency
    strategy_details: List[Dict[str, Any]] = field(default_factory=list)
    # Indicator snapshot for the frontend
    indicators_snapshot: Dict[str, Any] = field(default_factory=dict)
    # Market regime at signal time
    market_regime: str = "UNKNOWN"
    regime_min_confluence: int = 3
    regime_disabled_strategies: List[str] = field(default_factory=list)
    # Independent signal votes (PCR + FII)
    independent_votes: List[Dict[str, Any]] = field(default_factory=list)
    # Event filter
    event_blocked: bool = False
    event_reasons: List[str] = field(default_factory=list)


def run(
    symbol: str,
    m5: ind.IntradayIndicators,
    m15: ind.IntradayIndicators,
    daily: ind.DailyIndicators,
    levels: ind.KeyLevels,
    ctx: MarketContext,
    meta_market_cap_cr: float = 10_000.0,
) -> AlgoEngineResult:
    """Run all 9 strategies + independent signals and return a confluence signal.

    Enhancement layers over the base 9-strategy engine
    ─────────────────────────────────────────────────────
    Layer A — Market Regime Detector
        Detects whether the market is BULL / BEAR / RANGING / HIGH_VOLATILITY.
        Disables unreliable strategies in each regime and raises the minimum
        confluence threshold automatically.

    Layer B — Independent Signal Sources
        Adds two strategy votes sourced from data *completely orthogonal* to
        OHLCV: Options PCR (market sentiment) and FII net flow (institutional).
        These cannot correlate with the 9 price/volume strategies, so they
        genuinely increase confluence confidence.

    Layer C — Corporate Event Filter
        Checks the NSE corporate calendar and blocks entries in the ±2-day
        window around earnings, ex-dates, RBI MPC, and Budget announcements.

    Parameters
    ----------
    symbol          : NSE ticker
    m5, m15, daily  : Pre-computed indicator bundles
    levels          : Key price levels (ORB, pivots, PDH/PDL)
    ctx             : Market-context snapshot (LTP, volume, gap info, capital)
    meta_market_cap_cr : Market cap in Crore INR for the pre-trade filter

    Returns
    -------
    AlgoEngineResult with action, targets, enhanced confluence score, and full
    strategy-level breakdown including regime and independent signal data.
    """
    # Lazy imports to avoid circular dependencies at module load.
    try:
        from app.services.market_regime import detect as detect_regime
        regime = detect_regime()
    except Exception:
        regime = None

    try:
        from app.services.independent_signals import get_votes
        ind_votes = get_votes()
    except Exception:
        ind_votes = []

    try:
        from app.services.event_filter import check as check_events
        ev_result = check_events(symbol)
    except Exception:
        ev_result = None

    now_utc = datetime.now(timezone.utc)
    # Convert to IST for display (IST = UTC+5:30)
    now_ist = datetime.fromtimestamp(
        now_utc.timestamp() + 5.5 * 3600
    )

    ltp = ctx.ltp

    # ── Pre-trade filters ─────────────────────────────────────────────────
    filters_ok, filter_failures = _check_pre_trade_filters(ctx, m5, meta_market_cap_cr)

    # ── Layer A: Market Regime — disabled strategies & min confluence ──────
    disabled_tags: set = set()
    regime_min_conf = 3
    regime_str = "UNKNOWN"
    regime_block_longs = False
    regime_disabled_list: List[str] = []

    if regime is not None:
        regime_str = regime.regime
        regime_min_conf = regime.recommended_min_confluence
        disabled_tags = set(regime.disabled_strategies)
        regime_block_longs = regime.block_new_longs
        regime_disabled_list = list(regime.disabled_strategies)
        if regime_block_longs:
            filter_failures.append(
                f"BEAR regime ({regime.nifty_change_pct:+.2f}% Nifty) — no new longs"
            )
            filters_ok = False

    # ── Layer C: Event Filter — block if near high-impact event ───────────
    event_blocked = False
    event_reasons: List[str] = []
    if ev_result is not None and ev_result.blocked:
        event_blocked = True
        event_reasons = ev_result.reasons
        filter_failures.append(
            "Event filter: " + "; ".join(event_reasons[:2])
        )
        filters_ok = False

    # ── Run all 9 strategies ──────────────────────────────────────────────
    all_results = [
        _s1_vwap_mean_reversion(ltp, m5),
        _s2_ema_crossover(ltp, m5, daily),
        _s3_rsi_macd(ltp, m15),
        _s4_bollinger_band(ltp, m15),
        _s5_orb(ltp, levels, m5.vol_ratio),
        _s6_supertrend_adx(ltp, m15, daily),
        _s7_volume_sr(ltp, levels, m15),
        _s8_gap_and_go(ltp, ctx, m5),
        _s9_stat_arb_rel_strength(ltp, ctx, m5, m15),
    ]

    # Apply regime filter — zero-out votes from disabled strategies.
    results = []
    for r in all_results:
        if r.tag in disabled_tags:
            results.append(StrategyResult(
                r.name, r.tag, 0,
                f"[Regime {regime_str}: disabled] {r.reason}"
            ))
        else:
            results.append(r)

    # ── Layer B: Independent signal votes ─────────────────────────────────
    # PCR and FII votes are appended to the directional count.
    # Neutral votes (direction==0) do NOT count towards confluence.
    ind_bullish_count = 0
    ind_bearish_count = 0
    ind_vote_dicts: List[Dict[str, Any]] = []
    for v in ind_votes:
        ind_vote_dicts.append({
            "name": v.name,
            "tag": v.tag,
            "direction": v.direction,
            "direction_label": v.direction_label,
            "reason": v.reason,
            "data_available": v.data_available,
        })
        if v.direction == 1:
            ind_bullish_count += 1
        elif v.direction == -1:
            ind_bearish_count += 1

    # Tally OHLCV strategy votes
    bullish = [r for r in results if r.direction == 1]
    bearish = [r for r in results if r.direction == -1]
    b_count = len(bullish) + ind_bullish_count
    s_count = len(bearish) + ind_bearish_count

    # ── Confluence rule (enhanced) ────────────────────────────────────────
    # Minimum threshold is now max(3, regime_min_conf) so regime tightening
    # is always respected.
    eff_min_conf = max(3, regime_min_conf)

    if b_count >= eff_min_conf and b_count > s_count:
        action = "BUY"
        agreed = bullish
        count = b_count
    elif s_count >= eff_min_conf and s_count > b_count:
        action = "SELL"
        agreed = bearish
        count = s_count
    elif b_count == 2 or s_count == 2:
        action = "HOLD"
        agreed = bullish if b_count >= s_count else bearish
        count = max(b_count, s_count)
    else:
        action = "AVOID"
        agreed = []
        count = max(b_count, s_count)

    triggered_tags = [r.tag for r in agreed]
    confidence = _confidence(count)

    # ── Price levels ──────────────────────────────────────────────────────
    atr = m5.atr14
    if action in ("BUY", "SELL"):
        entry, stop_loss, t1, t2 = _price_targets(action, ltp, atr, levels, ctx)
    else:
        entry = round(ltp, 2)
        stop_loss = round(ltp * 0.985, 2)
        t1 = round(ltp * 1.02, 2)
        t2 = round(ltp * 1.04, 2)

    rr_str = _rr_string(entry, stop_loss, t1)

    # ── Position sizing ───────────────────────────────────────────────────
    risk_pct = ctx.risk_pct
    qty = _position_size(entry, stop_loss, ctx.capital, risk_pct)

    # ── Hold period ───────────────────────────────────────────────────────
    hold = _hold_period(triggered_tags, daily) if action in ("BUY", "SELL") else "Intraday"

    # ── Reason ────────────────────────────────────────────────────────────
    if agreed:
        reason_parts = [r.reason for r in agreed[:3]]
        reason = " | ".join(reason_parts)
    else:
        neutral = [r.reason for r in results if r.direction == 0][:2]
        reason = "Confluence threshold not met. " + " | ".join(neutral) if neutral else \
                 "No directional confluence — stand aside."

    # ── Book-profit instruction ───────────────────────────────────────────
    if action in ("BUY", "SELL"):
        book = (
            f"Book 50% at Target 1 (₹{t1:.2f}). "
            f"Move stop loss to breakeven (₹{entry:.2f}). "
            f"Book remaining 50% at Target 2 (₹{t2:.2f}). "
            "Trail final stop at 20-period EMA after T2."
        )
    else:
        book = "No trade. Wait for ≥3 strategy confluence before entering."

    # ── Indicator snapshot for frontend ──────────────────────────────────
    snap = {
        "ltp": ltp,
        "vwap": m5.vwap,
        "ema9_5m": m5.ema9,
        "ema20_5m": m5.ema20,
        "ema50_5m": m5.ema50,
        "rsi_15m": m15.rsi14,
        "macd_hist_15m": m15.macd_hist,
        "adx_15m": m15.adx,
        "supertrend_dir_15m": m15.supertrend_dir,
        "bb_pctb_15m": m15.bb_pctb,
        "vol_ratio_5m": m5.vol_ratio,
        "obv_slope_5m": m5.obv_slope,
        "mfi_5m": m5.mfi14,
        "orh": levels.orh,
        "orl": levels.orl,
        "gap_type": ctx.gap_type,
        "gap_pct": ctx.gap_pct,
        "atr_5m": atr,
        "daily_trend": daily.trend_label,
        "daily_adx": daily.adx,
    }

    return AlgoEngineResult(
        stock=symbol,
        date=now_ist.strftime("%Y-%m-%d"),
        time=now_ist.strftime("%H:%M"),
        action=action,
        entry_price=entry,
        stop_loss=stop_loss,
        target_1=t1,
        target_2=t2,
        hold_period=hold,
        confidence=confidence,
        risk_reward_ratio=rr_str,
        strategies_triggered=triggered_tags,
        strategy_confluence_count=count,
        reason=reason,
        book_profit_instruction=book,
        risk_per_trade_percent=risk_pct,
        suggested_position_size_units=qty,
        pre_trade_filters_passed=filters_ok,
        filter_failures=filter_failures,
        market_regime=regime_str,
        regime_min_confluence=regime_min_conf,
        regime_disabled_strategies=regime_disabled_list,
        independent_votes=ind_vote_dicts,
        event_blocked=event_blocked,
        event_reasons=event_reasons,
        strategy_details=[
            {
                "name": r.name,
                "tag": r.tag,
                "direction": r.direction,
                "direction_label": (
                    "BULLISH" if r.direction == 1
                    else "BEARISH" if r.direction == -1
                    else "NEUTRAL"
                ),
                "reason": r.reason,
            }
            for r in results
        ],
        indicators_snapshot=snap,
    )
