"""Assemble the full payload required by the analyzer's user prompt.

The prompt template has ~90 placeholders covering instrument metadata,
time, market context, quote, key levels, multi-timeframe OHLCV,
per-timeframe indicators, detected patterns, open position, and account
parameters. This module gathers them all from the data provider, the
universe metadata, and the indicator module, then flattens them into a
dict ready for ``str.format``-style rendering.

Writing this as a pure function makes it trivial to snapshot a payload
for offline debugging ("replay the exact input Claude saw at 10:42 AM").
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.data.universe import StockMeta, get_by_symbol
from app.models.analyzer import AccountParams, AnalyzeRequest, CurrentPosition
from app.services import indicators as ind
from app.services.data_provider import DataProvider, OHLCV, ist_now, session_bounds


# ---------------------------------------------------------------------- helpers

def _ohlcv_to_json(series: List[OHLCV], include_ts: bool = False) -> str:
    rows = []
    for c in series:
        row: Dict[str, Any] = {
            "o": round(c.open, 2),
            "h": round(c.high, 2),
            "l": round(c.low, 2),
            "c": round(c.close, 2),
            "v": round(c.volume, 0),
        }
        if include_ts and c.timestamp is not None:
            row["t"] = c.timestamp.strftime("%Y-%m-%d %H:%M")
        rows.append(row)
    return json.dumps(rows, separators=(",", ":"))


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------- main


@dataclass
class AnalyzerPayload:
    """Full payload dict + raw indicator objects kept for server-side use."""

    symbol: str
    meta: StockMeta
    fill: Dict[str, Any]               # everything keyed for str.format
    daily: ind.DailyIndicators
    m15: ind.IntradayIndicators
    m5: ind.IntradayIndicators
    levels: ind.KeyLevels


def _market_context() -> Dict[str, Any]:
    """Placeholder market-context block.

    Live implementation: query provider for NIFTY / BANKNIFTY / VIX + FII/DII
    data. With MockProvider we fall back to reasonable neutral defaults so
    the prompt is still well-formed and Claude can reason over them.
    """
    return {
        "nifty_ltp": 23450.0,
        "nifty_pct": 0.22,
        "nifty_vs_vwap": "above",
        "banknifty_ltp": 51320.0,
        "banknifty_pct": 0.11,
        "sector_index_name": "Nifty sector index",
        "sector_pct": 0.18,
        "vix_value": 13.4,
        "vix_pct": -1.2,
        "fii_cash_cr": 420.0,
        "dii_cash_cr": 610.0,
        "events_list": "none",
        "is_expiry_day": False,
    }


def _time_context(now: datetime) -> Dict[str, Any]:
    start, end = session_bounds(now)
    if now < start:
        mins_since_open = 0
        mins_to_close = _minutes(end - start)
    elif now >= end:
        mins_since_open = _minutes(end - start)
        mins_to_close = 0
    else:
        mins_since_open = _minutes(now - start)
        mins_to_close = _minutes(end - now)
    return {
        "ist_now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "minutes_since_open": mins_since_open,
        "minutes_to_close": mins_to_close,
    }


def _current_quote(
    quote: OHLCV,
    prev_close: float,
    day_ohlc: OHLCV,
    cum_vol: float,
    avg_daily_vol: float,
    rvol: float,
) -> Dict[str, Any]:
    spread = max(0.05, quote.close * 0.0002)
    bid = round(quote.close - spread / 2, 2)
    ask = round(quote.close + spread / 2, 2)
    return {
        "ltp": round(quote.close, 2),
        "day_open": round(day_ohlc.open, 2),
        "day_high": round(day_ohlc.high, 2),
        "day_low": round(day_ohlc.low, 2),
        "prev_close": round(prev_close, 2),
        "day_change_pct": round((quote.close - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
        "bid": bid,
        "ask": ask,
        "spread": round(spread, 2),
        "day_volume": round(cum_vol, 0),
        "avg_daily_volume": round(avg_daily_vol, 0),
        "rvol": round(rvol, 2),
    }


def build_payload(
    symbol: str,
    provider: DataProvider,
    settings: Settings,
    request: Optional[AnalyzeRequest] = None,
) -> AnalyzerPayload:
    meta = get_by_symbol(symbol)
    if meta is None:
        raise ValueError(f"Unknown symbol: {symbol}")

    # ---- Multi-timeframe history ---------------------------------------
    daily = provider.get_history(symbol, days=260)
    m1 = provider.get_intraday_history(symbol, "1m", 30)
    m5 = provider.get_intraday_history(symbol, "5m", 60)
    m15 = provider.get_intraday_history(symbol, "15m", 40)
    h1 = provider.get_intraday_history(symbol, "1h", 30)

    # ---- Indicators -----------------------------------------------------
    daily_ind = ind.build_daily(daily)
    m15_ind = ind.build_intraday(m15)
    m5_ind = ind.build_intraday(m5)

    # ---- Today's aggregate --------------------------------------------
    prev_close = daily[-2].close if len(daily) >= 2 else daily[-1].close
    if m5:
        day_open = m5[0].open
        day_high = max(x.high for x in m5)
        day_low = min(x.low for x in m5)
        cum_vol = sum(x.volume for x in m5)
        last_close = m5[-1].close
        day_ohlc = OHLCV(day_open, day_high, day_low, last_close, cum_vol)
    else:
        last = daily[-1]
        day_ohlc = OHLCV(last.open, last.high, last.low, last.close, last.volume)
        cum_vol = last.volume

    avg_daily_vol = float(sum(c.volume for c in daily[-20:]) / max(1, len(daily[-20:])))
    rvol = (cum_vol / avg_daily_vol) if avg_daily_vol else 1.0

    quote = provider.get_quote(symbol)
    # Override the quote's close with the intraday last tick for consistency.
    quote = OHLCV(quote.open, quote.high, quote.low, day_ohlc.close, quote.volume)

    # ---- Key levels -----------------------------------------------------
    levels = ind.build_key_levels(daily, m5, day_ohlc.open)

    # ---- Patterns -------------------------------------------------------
    patterns = ind.detect_recent_patterns(m5, m15)

    # ---- Time / market / account ---------------------------------------
    now = ist_now()
    time_ctx = _time_context(now)
    market_ctx = _market_context()
    quote_ctx = _current_quote(quote, prev_close, day_ohlc, cum_vol, avg_daily_vol, rvol)

    req = request or AnalyzeRequest()
    account = req.account or AccountParams()
    position = req.position or CurrentPosition()
    capital = account.capital if account.capital is not None else settings.default_capital_inr
    risk_pct = account.risk_pct if account.risk_pct is not None else settings.default_risk_pct
    max_dd = (
        account.max_daily_loss_pct
        if account.max_daily_loss_pct is not None
        else settings.default_max_daily_loss_pct
    )

    # ---- Build the giant fill dict -------------------------------------
    fill: Dict[str, Any] = {
        # Instrument
        "symbol": meta.symbol,
        "exchange": "NSE",
        "segment": "EQ",
        "lot_size": 1,
        "sector": meta.sector,
        # Time
        **time_ctx,
        # Market
        **market_ctx,
        # Current quote
        **quote_ctx,
        # Key levels
        "pdh": levels.pdh,
        "pdl": levels.pdl,
        "pdc": levels.pdc,
        "pivot": levels.pivot,
        "r1": levels.r1,
        "r2": levels.r2,
        "r3": levels.r3,
        "s1": levels.s1,
        "s2": levels.s2,
        "s3": levels.s3,
        "orh": levels.orh,
        "orl": levels.orl,
        "swing_highs": levels.swing_highs,
        "swing_lows": levels.swing_lows,
        "wk52_high": levels.wk52_high,
        "wk52_low": levels.wk52_low,
        "gap_type": levels.gap_type,
        "gap_pct": levels.gap_pct,
        # OHLCV JSON strings (drop to last N to keep tokens lean)
        "daily_ohlcv_json": _ohlcv_to_json(daily[-30:]),
        "hourly_ohlcv_json": _ohlcv_to_json(h1, include_ts=True),
        "m15_ohlcv_json": _ohlcv_to_json(m15, include_ts=True),
        "m5_ohlcv_json": _ohlcv_to_json(m5[-60:], include_ts=True),
        "m1_ohlcv_json": _ohlcv_to_json(m1[-30:], include_ts=True),
        # Daily indicators
        "d_ema9": daily_ind.ema9,
        "d_ema20": daily_ind.ema20,
        "d_ema50": daily_ind.ema50,
        "d_ema200": daily_ind.ema200,
        "d_rsi": daily_ind.rsi14,
        "d_macd": daily_ind.macd,
        "d_macd_sig": daily_ind.macd_signal,
        "d_macd_hist": daily_ind.macd_hist,
        "d_adx": daily_ind.adx,
        "d_pdi": daily_ind.plus_di,
        "d_mdi": daily_ind.minus_di,
        "d_atr": daily_ind.atr14,
        "d_st_val": daily_ind.supertrend,
        "d_st_dir": daily_ind.supertrend_dir,
        "d_trend_label": daily_ind.trend_label,
        # 15m indicators
        "m15_ema9": m15_ind.ema9,
        "m15_ema20": m15_ind.ema20,
        "m15_ema50": m15_ind.ema50,
        "m15_vwap": m15_ind.vwap,
        "m15_vwap_u1": m15_ind.vwap_u1,
        "m15_vwap_l1": m15_ind.vwap_l1,
        "m15_vwap_u2": m15_ind.vwap_u2,
        "m15_vwap_l2": m15_ind.vwap_l2,
        "m15_rsi": m15_ind.rsi14,
        "m15_macd": m15_ind.macd,
        "m15_macd_sig": m15_ind.macd_signal,
        "m15_macd_hist": m15_ind.macd_hist,
        "m15_bb_u": m15_ind.bb_upper,
        "m15_bb_m": m15_ind.bb_middle,
        "m15_bb_l": m15_ind.bb_lower,
        "m15_bb_pctb": m15_ind.bb_pctb,
        "m15_bb_bw": m15_ind.bb_bandwidth,
        "m15_adx": m15_ind.adx,
        "m15_atr": m15_ind.atr14,
        "m15_stoch_k": m15_ind.stoch_k,
        "m15_stoch_d": m15_ind.stoch_d,
        "m15_st_val": m15_ind.supertrend,
        "m15_st_dir": m15_ind.supertrend_dir,
        "m15_obv_slope": m15_ind.obv_slope,
        "m15_mfi": m15_ind.mfi14,
        # 5m indicators
        "m5_ema9": m5_ind.ema9,
        "m5_ema20": m5_ind.ema20,
        "m5_ema50": m5_ind.ema50,
        "m5_vwap": m5_ind.vwap,
        "m5_rsi": m5_ind.rsi14,
        "m5_macd": m5_ind.macd,
        "m5_macd_sig": m5_ind.macd_signal,
        "m5_macd_hist": m5_ind.macd_hist,
        "m5_bb_u": m5_ind.bb_upper,
        "m5_bb_m": m5_ind.bb_middle,
        "m5_bb_l": m5_ind.bb_lower,
        "m5_atr": m5_ind.atr14,
        "m5_last_vol": m5_ind.last_volume,
        "m5_avg_vol": m5_ind.avg_volume_20,
        "m5_vol_ratio": m5_ind.vol_ratio,
        "m5_candle_pattern": m5_ind.candle_pattern,
        # Patterns
        "detected_patterns_json": json.dumps(patterns, separators=(",", ":")),
        # Position
        "has_position": position.has_position,
        "position_side": position.side,
        "position_entry": position.entry,
        "position_qty": position.quantity,
        "position_pnl": position.unrealized_pnl,
        "position_sl": position.stop_loss,
        "position_tgt": position.target,
        "position_age": position.age_minutes,
        # Account & risk
        "capital": capital,
        "risk_pct": risk_pct,
        "max_daily_loss_pct": max_dd,
        "day_pnl": account.day_pnl,
        "trades_today": account.trades_today,
        "max_trades": account.max_trades,
    }

    return AnalyzerPayload(
        symbol=meta.symbol,
        meta=meta,
        fill=fill,
        daily=daily_ind,
        m15=m15_ind,
        m5=m5_ind,
        levels=levels,
    )
