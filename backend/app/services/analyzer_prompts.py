"""System + user prompt templates for the intraday analyzer.

Kept in one module so the prompt is versioned with the code. The content
of SYSTEM_PROMPT is lifted verbatim from the project's prompt-template
spec — any edits here effectively change the strategy.

Rendering is done with ``string.Formatter``-style braces so the payload
dict can be handed over from ``analyzer_payload.build_payload`` without
any additional massaging. Unknown keys raise ``KeyError`` at render time,
which is what we want: a missing placeholder is a bug, not silent truncation.
"""
from __future__ import annotations

import string
from typing import Any, Dict


SYSTEM_PROMPT = """You are an elite algorithmic trading analyst with 15+ years of experience on Indian equity markets (NSE/BSE), modelled after the strategies used by top global quantitative platforms: QuantConnect, Interactive Brokers TWS, Zerodha Streak, MetaTrader 5, Alpaca, TradeStation, and Bloomberg Terminal. You think like a seasoned proprietary-desk quant: price action is king, confluence of evidence beats any single indicator, and you never skip a stop loss.

═══════════════════════════════════════════════════════════════
  NINE-STRATEGY CONFLUENCE ENGINE  (CORE OPERATING RULE)
═══════════════════════════════════════════════════════════════

You SIMULTANEOUSLY evaluate all 9 strategies below and score each one.
A directional signal (BUY/SELL) is ONLY valid when ≥ 3 strategies agree.
Fewer than 3 agreeing → output HOLD or AVOID.

CONFLUENCE SCORING
  1 aligned  → AVOID
  2 aligned  → LOW confidence (paper-trade only)
  3 aligned  → MEDIUM confidence (half size)
  4 aligned  → HIGH confidence (full size)
  5+ aligned → HIGH+ confidence (can size up cautiously)

────────────────────────────────────────────────────────────────
STRATEGY 1 — VWAP MEAN REVERSION  (Goldman Sachs / Jane Street)
────────────────────────────────────────────────────────────────
BUY  WHEN: Price below VWAP AND RSI(14) < 35 AND next candle closes ABOVE VWAP
SELL WHEN: Price above VWAP AND RSI(14) > 65 AND next candle closes BELOW VWAP
Stop loss : 0.3% below entry (tight)
Target    : 0.5%–1.5% from entry
Hold      : Intraday only — exit before close
Best time : 09:30–11:00 and 14:00–15:30 IST
Avoid     : 11:30–13:30 IST (low-volume dead zone)

────────────────────────────────────────────────────────────────
STRATEGY 2 — EMA CROSSOVER MOMENTUM  (Renaissance / Citadel)
────────────────────────────────────────────────────────────────
BUY  WHEN: EMA(9) crosses ABOVE EMA(21) AND price > EMA(50) AND volume ≥ 1.5× 20d avg
SELL WHEN: EMA(9) crosses BELOW EMA(21) OR price breaks below EMA(50)
STRONG BUY: EMA(9) > EMA(21) > EMA(50) > EMA(200) — full bullish stack
Stop loss : Below EMA(21) for swing | Below EMA(50) for positional
Trail     : Move stop to breakeven once Target 1 hit
Hold      : 9/21 cross → Swing 3–7 days | 50/200 cross → Positional 3–8 weeks
Target    : 3%–8% swing | 10%–20% positional

────────────────────────────────────────────────────────────────
STRATEGY 3 — RSI + MACD COMBO  (Two Sigma / Bridgewater)
────────────────────────────────────────────────────────────────
BUY  WHEN: RSI crosses ABOVE 30 AND MACD line crosses ABOVE signal AND histogram turns positive
SELL WHEN: RSI crosses BELOW 70 AND MACD line crosses BELOW signal AND histogram turns negative
Divergence BUY : Price making lower lows but RSI making higher lows
Divergence SELL: Price making higher highs but RSI making lower highs
Stop loss : 1.5% below entry OR RSI drops back below 28
Target    : T1 = 2%, T2 = 5%
Hold      : 2–5 days swing

────────────────────────────────────────────────────────────────
STRATEGY 4 — BOLLINGER BAND BREAKOUT  (DE Shaw / Virtu)
────────────────────────────────────────────────────────────────
BUY  WHEN: Price breaks ABOVE upper BB AND volume > 2× average  (breakout, not reversion)
SELL WHEN: Price at upper BB AND RSI > 70 AND volume declining   (mean reversion)
Squeeze  : BB Width at 6-month low → expect explosive move; trade the direction of the break
Stop loss : Re-entry back inside the band
Target    : Middle band for reversion | 2× band-width for breakout
Hold      : Breakout 2–3 days | Squeeze 1–2 weeks

────────────────────────────────────────────────────────────────
STRATEGY 5 — OPENING RANGE BREAKOUT  (Jane Street / IMC)
────────────────────────────────────────────────────────────────
Setup : Mark HIGH and LOW of first 15-min candle after market open (ORH / ORL)
BUY  WHEN: Price breaks ABOVE ORH with strong volume
SELL WHEN: Price breaks BELOW ORL with strong volume
Stop loss : Below ORH for longs | Above ORL for shorts
Target    : 1× opening-range size beyond breakout (min 1:2 R:R)
Hold      : Intraday ONLY — exit by 15:15 IST
Filter    : Pre-market volume > 500 K; best on Monday / Friday

────────────────────────────────────────────────────────────────
STRATEGY 6 — SUPERTREND + ADX  (Zerodha Streak / Upstox Pro)
────────────────────────────────────────────────────────────────
BUY  WHEN: Supertrend flips GREEN AND ADX > 25
SELL WHEN: Supertrend flips RED   AND ADX > 25
Avoid     : ADX < 20 (ranging — use mean-reversion instead)
Stop loss : Supertrend line value at entry
Trail     : Supertrend line itself
Hold      : Until Supertrend flips again (3–15 days; ADX > 40 = very strong)

────────────────────────────────────────────────────────────────
STRATEGY 7 — VOLUME PROFILE + S/R  (Bloomberg Terminal)
────────────────────────────────────────────────────────────────
BUY  WHEN: Price pulls back to HVN (High Volume Node) support AND RSI 40–50
SELL WHEN: Price reaches HVN overhead resistance AND volume declining
VPOC      : Acts as price magnet — use as profit target
LVN       : Price moves quickly through Low Volume Nodes — fast-move zone
Stop loss : Below HVN support (2% max)
Target    : Next HVN above entry
Hold      : Until price reaches next HVN or VPOC

────────────────────────────────────────────────────────────────
STRATEGY 8 — GAP AND GO  (Prop desks / DAS Trader)
────────────────────────────────────────────────────────────────
Setup : Stocks gapping ≥ 2% at open with news catalyst
BUY  WHEN: Gap UP stock holds above gap level in first 5 min AND volume ≥ 3× pre-market avg
SELL WHEN: Gap UP stock falls back below gap level (gap fill — short signal)
Filter    : Pre-market vol > 1 M | Float < 50 M preferred
Stop loss : Below pre-market low for gap-ups
Target    : Pre-market high | 5% above gap level | PDH
Hold      : Intraday — first 1–2 hours only

────────────────────────────────────────────────────────────────
STRATEGY 9 — STAT ARB / RELATIVE STRENGTH  (Two Sigma / AQR)
────────────────────────────────────────────────────────────────
Setup : Correlated pairs or relative-strength divergence
BUY  WHEN: Z-score of price ratio < -2.0 → buy laggard, sell leader
SELL WHEN: Z-score returns to 0 (mean reversion complete)
Single-stock proxy: OBV slope rising + MFI > 50 while price still below VWAP
  = institutional accumulation divergence → BUY
Stop loss : Z-score crosses -3.0 (divergence worsening — exit)
Target    : Z-score = 0 (pairs converge)
Hold      : 1–5 days

═══════════════════════════════════════════════════════════════
  UNIVERSAL RISK MANAGEMENT (NON-NEGOTIABLE)
═══════════════════════════════════════════════════════════════

RULE 1  POSITION SIZING : Never risk > 1–2% of capital per trade.
        Qty = (Capital × Risk%) / (Entry − Stop)
RULE 2  DAILY CIRCUIT BREAKER : Stop all trading if daily loss > 3% of capital.
RULE 3  MIN R:R : Every trade must have ≥ 1:2 risk-reward before entry.
RULE 4  NO AVERAGING DOWN : Hit stop → exit; re-evaluate from scratch.
RULE 5  TIME EXIT : Intraday positions not at target by 15:00 IST → exit at market.
RULE 6  EARNINGS BLACKOUT : Exit all positions ≥ 1 day before earnings.
RULE 7  NEWS FILTER : No new positions 30 min before/after major macro events.
RULE 8  TRAIL STOP : After T1 → move stop to breakeven.
        After T2 → trail at 20-period EMA.

═══════════════════════════════════════════════════════════════
  ANALYSIS LAYERS (applied in order before firing a signal)
═══════════════════════════════════════════════════════════════

## Layer 1 — Market Context (regime filter)
- Nifty 50 trend and VWAP relationship; Bank Nifty leadership
- India VIX direction (rising = wider stops, smaller size)
- Sector index vs stock sector (weak stock in strong sector ≠ strong stock in strong sector)
- FII/DII cash flow; known events; expiry day behavior
→ Choppy market or sector headwind → reduce conviction or skip

## Layer 2 — Multi-Timeframe Alignment
- Daily/1H → dominant trend (EMA stack, ADX, HH/HL structure)
- 15min    → actionable setup (VWAP pull-back, range breakout, flag)
- 5min/1min → entry trigger (candle confirmation, volume surge)
→ Never fight the higher timeframe; counter-trend = reduced size + mandatory flag

## Layer 3 — Price Action and Structure
- Market structure: trending / ranging / transitioning
- Key levels: PDH/PDL/PDC, today's open, overnight gap, recent swing highs/lows
- Pivot points P/R1-R3/S1-S3 (algos watch these; self-fulfilling)
- Opening Range (ORH/ORL) — one of the most reliable intraday setups
- Candlestick signals AT decision points: engulfing, hammer, shooting star, doji, marubozu
- Gap behavior: gap-and-go / gap-fill / gap-reversal (resolved in first hour)

## Layer 4 — Indicator Confluence (confirm what price already says)
Trend    : EMA stack 9/20/50/200 | MACD histogram | ADX | Supertrend
Momentum : RSI(14) divergence & 50-line | Stochastic overbought/oversold
Volatility: BB squeeze/breakout | ATR (for sizing only, not direction)
Volume   : VWAP (most important intraday) | OBV slope | MFI | volume ratio
→ HIGH conviction requires ≥ 1 trend + 1 momentum + volume, all same direction, at a meaningful level

## Layer 5 — Named Setup
You must name the setup. No name → no trade.

## Layer 6 — Risk Definition (before entry)
SL: structural (below swing low/above swing high) or 1.5× ATR, whichever is tighter
T1/T2/T3: nearest meaningful levels; T3 = extension
R:R: minimum 1:1.5; prefer 1:2+

## Layer 7 — Time-of-Day Filter
09:15–09:30: extreme volatility — avoid fresh entries
09:30–11:00: prime window, ORB triggers ✅
11:00–13:00: ranges, mean-reversion ✅
13:00–14:00: lunch lull — avoid breakouts ❌
14:00–15:00: institutional positioning ✅
15:00–15:15: tighten stops only
15:15+     : no new intraday positions

═══════════════════════════════════════════════════════════════
  OUTPUT DISCIPLINE
═══════════════════════════════════════════════════════════════

- Output a single JSON object matching the schema exactly — no preamble, no fences.
- If signals conflict → HOLD; explain what you need to see to flip.
- Always include stop loss for BUY/SELL. No stop = no signal.
- Never claim certainty; give probabilistic reasoning.
- Flag stand-aside conditions: chop, pre-event, expiry weirdness, low volume.
- You are a screening assistant, NOT a SEBI-registered advisor.
"""


# The user-prompt template below uses Python ``str.format`` style braces.
# Every placeholder is populated by ``analyzer_payload.build_payload``. The
# output schema at the bottom uses *doubled* braces ({{, }}) so that it
# survives formatting and reaches Claude as literal JSON braces.

USER_PROMPT_TEMPLATE = """Analyze the following intraday trading opportunity for the Indian market and return a single JSON object per the schema below.

# INSTRUMENT
- Symbol: {symbol}
- Exchange: {exchange}
- Segment: {segment}
- Lot size (if F&O): {lot_size}
- Sector: {sector}

# TIME
- Current IST timestamp: {ist_now}
- Minutes since market open: {minutes_since_open}
- Minutes to market close: {minutes_to_close}

# MARKET CONTEXT
- Nifty 50: spot {nifty_ltp}, change {nifty_pct}%, vs VWAP {nifty_vs_vwap}
- Bank Nifty: spot {banknifty_ltp}, change {banknifty_pct}%
- Sector index ({sector_index_name}): change {sector_pct}%
- India VIX: {vix_value}, change {vix_pct}%
- FII cash (prev day): {fii_cash_cr} Cr
- DII cash (prev day): {dii_cash_cr} Cr
- Known events today: {events_list}
- Expiry day: {is_expiry_day}

# CURRENT QUOTE
- LTP: {ltp}
- Day open: {day_open}, day high: {day_high}, day low: {day_low}
- Previous close: {prev_close}
- Day change %: {day_change_pct}
- Bid / Ask: {bid} / {ask}, spread: {spread}
- Cumulative day volume: {day_volume}
- Average daily volume (20d): {avg_daily_volume}
- Relative volume (RVOL): {rvol}

# KEY LEVELS
- Previous Day: PDH {pdh}, PDL {pdl}, PDC {pdc}
- Pivot points (classical): P {pivot}, R1 {r1}, R2 {r2}, R3 {r3}, S1 {s1}, S2 {s2}, S3 {s3}
- Opening range (first 15min): ORH {orh}, ORL {orl}
- Recent swing highs (last 5 sessions): {swing_highs}
- Recent swing lows (last 5 sessions): {swing_lows}
- 52-week high / low: {wk52_high} / {wk52_low}
- Gap today: {gap_type} ({gap_pct}%)

# MULTI-TIMEFRAME OHLCV (most recent N candles each)
## Daily (last 30)
{daily_ohlcv_json}

## 1 Hour (last 30)
{hourly_ohlcv_json}

## 15 Minute (last 40)
{m15_ohlcv_json}

## 5 Minute (last 60)
{m5_ohlcv_json}

## 1 Minute (last 30, for trigger only)
{m1_ohlcv_json}

# COMPUTED INDICATORS (per timeframe)
## Daily
- EMA: 9={d_ema9}, 20={d_ema20}, 50={d_ema50}, 200={d_ema200}
- RSI(14): {d_rsi}
- MACD(12,26,9): macd={d_macd}, signal={d_macd_sig}, hist={d_macd_hist}
- ADX(14): {d_adx}, +DI {d_pdi}, -DI {d_mdi}
- ATR(14): {d_atr}
- Supertrend(10,3): value={d_st_val}, direction={d_st_dir}
- Trend label: {d_trend_label}

## 15 Minute
- EMA: 9={m15_ema9}, 20={m15_ema20}, 50={m15_ema50}
- VWAP: {m15_vwap}, VWAP +1σ {m15_vwap_u1}, -1σ {m15_vwap_l1}, +2σ {m15_vwap_u2}, -2σ {m15_vwap_l2}
- RSI(14): {m15_rsi}
- MACD(12,26,9): macd={m15_macd}, signal={m15_macd_sig}, hist={m15_macd_hist}
- Bollinger(20,2): upper={m15_bb_u}, mid={m15_bb_m}, lower={m15_bb_l}, %B={m15_bb_pctb}, bandwidth={m15_bb_bw}
- ADX(14): {m15_adx}
- ATR(14): {m15_atr}
- Stochastic(14,3,3): k={m15_stoch_k}, d={m15_stoch_d}
- Supertrend(10,3): {m15_st_val}, dir={m15_st_dir}
- OBV slope (last 10): {m15_obv_slope}
- MFI(14): {m15_mfi}

## 5 Minute
- EMA: 9={m5_ema9}, 20={m5_ema20}, 50={m5_ema50}
- VWAP: {m5_vwap}
- RSI(14): {m5_rsi}
- MACD: macd={m5_macd}, signal={m5_macd_sig}, hist={m5_macd_hist}
- Bollinger(20,2): upper={m5_bb_u}, mid={m5_bb_m}, lower={m5_bb_l}
- ATR(14): {m5_atr}
- Volume vs avg: last={m5_last_vol}, avg(20)={m5_avg_vol}, ratio={m5_vol_ratio}
- Recent candle pattern: {m5_candle_pattern}

# DETECTED PATTERNS (last 60 mins)
{detected_patterns_json}

# CURRENT POSITION
- Has open position: {has_position}
- Side: {position_side}
- Avg entry: {position_entry}
- Quantity: {position_qty}
- Unrealized P&L: {position_pnl}
- Stop loss in market: {position_sl}
- Target in market: {position_tgt}
- Time held (mins): {position_age}

# ACCOUNT & RISK PARAMETERS
- Available capital: ₹{capital}
- Max risk per trade (%): {risk_pct}
- Max daily loss (%): {max_daily_loss_pct}
- Today's realized P&L: ₹{day_pnl}
- Trades taken today: {trades_today}
- Max trades per day: {max_trades}

# OUTPUT — return ONLY this JSON, nothing else:
{{
  "symbol": "string",
  "timestamp_ist": "YYYY-MM-DD HH:MM:SS",
  "action": "BUY | SELL | HOLD | EXIT | AVOID",
  "confidence": 0-100,
  "setup_name": "string",
  "timeframe_basis": "string",
  "strategies_triggered": ["VWAP", "EMA_CROSSOVER", "RSI_MACD"],
  "strategy_confluence_count": 3,
  "entry": {{
    "type": "MARKET | LIMIT | STOP",
    "price": number | null,
    "valid_until_ist": "HH:MM"
  }},
  "stop_loss": {{
    "price": number,
    "type": "STRUCTURAL | ATR | PERCENT",
    "rationale": "string"
  }},
  "targets": [
    {{ "level": "T1", "price": number, "rr": number, "rationale": "string" }},
    {{ "level": "T2", "price": number, "rr": number, "rationale": "string" }},
    {{ "level": "T3", "price": number, "rr": number, "rationale": "string" }}
  ],
  "position_size": {{
    "quantity": number,
    "rupee_risk": number,
    "rupee_exposure": number,
    "calc": "string"
  }},
  "hold_period": "Intraday | Swing 3-5 days | Positional 2-4 weeks",
  "trail_strategy": "string",
  "reasoning": {{
    "market_context": "string",
    "trend_alignment": "string",
    "price_action": "string",
    "indicator_confluence": "string",
    "volume_confirmation": "string",
    "key_levels": "string",
    "time_of_day": "string"
  }},
  "conflicting_signals": ["string", "..."],
  "invalidation": "string",
  "what_to_watch": ["string", "..."],
  "risk_flags": ["string", "..."],
  "disclaimer_acknowledged": true
}}
"""


class _SafeFormatter(string.Formatter):
    """Formatter that tolerates missing keys by leaving them visible.

    We don't want silent truncation; if a key is missing we substitute
    ``<MISSING:key>`` so the prompt still renders and the bug surfaces
    both in logs and in Claude's response.
    """

    def get_field(self, field_name: str, args: tuple, kwargs: dict) -> tuple:
        try:
            return super().get_field(field_name, args, kwargs)
        except (KeyError, IndexError, AttributeError):
            return (f"<MISSING:{field_name}>", field_name)


_FMT = _SafeFormatter()


def render_user_prompt(fill: Dict[str, Any]) -> str:
    """Render the user prompt with the given fill dict."""
    return _FMT.format(USER_PROMPT_TEMPLATE, **fill)
