"""Rule-based algo-engine signal router.

Endpoint
────────
  GET  /api/signals/{symbol}
  POST /api/signals/{symbol}   (optional body: capital + risk_pct overrides)

Returns an AlgoSignal produced by the 9-strategy confluence engine — no
LLM call, fully deterministic, sub-100ms latency.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.data.universe import get_by_symbol
from app.models.algo_signal import AlgoSignal, StrategyDetail
from app.services import algo_engine
from app.services import indicators as ind
from app.services.analyzer_payload import build_payload
from app.services.cache import cache
from app.services.data_provider import get_provider

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/signals", tags=["algo-signals"])


class SignalRequest(BaseModel):
    """Optional body to override risk parameters."""
    capital: float = Field(100_000.0, ge=1_000, description="Available capital in INR")
    risk_pct: float = Field(1.5, ge=0.1, le=5.0, description="Max % of capital to risk per trade")
    bust_cache: bool = False


def _cache_key(symbol: str) -> str:
    bucket = int(time.time() // 30)   # 30-second buckets
    return f"algo_signal::{symbol.upper()}::{bucket}"


def _run_signal(symbol: str, capital: float, risk_pct: float) -> AlgoSignal:
    settings = get_settings()
    provider = get_provider(settings.data_provider)

    meta = get_by_symbol(symbol)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")

    # ── Fetch / compute all indicators ────────────────────────────────────
    daily_candles = provider.get_history(symbol, days=260)
    m5_candles = provider.get_intraday_history(symbol, "5m", 60)
    m15_candles = provider.get_intraday_history(symbol, "15m", 40)

    if not daily_candles:
        raise HTTPException(status_code=503, detail=f"No daily data for {symbol}")

    daily_ind = ind.build_daily(daily_candles)
    m5_ind = ind.build_intraday(m5_candles) if m5_candles else ind.build_intraday(daily_candles[-60:])
    m15_ind = ind.build_intraday(m15_candles) if m15_candles else ind.build_intraday(daily_candles[-40:])

    # ── Key levels ────────────────────────────────────────────────────────
    quote = provider.get_quote(symbol)
    ltp = float(quote.close) if quote and quote.close else float(daily_candles[-1].close)

    day_open = float(m5_candles[0].open) if m5_candles else float(daily_candles[-1].open)
    prev_close = float(daily_candles[-2].close) if len(daily_candles) >= 2 else ltp

    levels = ind.build_key_levels(daily_candles, m5_candles or [], day_open)

    avg_daily_vol = float(
        sum(c.volume for c in daily_candles[-20:]) / max(1, len(daily_candles[-20:]))
    )
    day_vol = sum(c.volume for c in (m5_candles or [])) or float(daily_candles[-1].volume)
    gap_pct = (day_open - prev_close) / prev_close * 100 if prev_close else 0.0
    gap_type = (
        "gap_up" if gap_pct > 0.15
        else "gap_down" if gap_pct < -0.15
        else "flat"
    )

    ctx = algo_engine.MarketContext(
        ltp=ltp,
        day_open=day_open,
        prev_close=prev_close,
        day_change_pct=round((ltp - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
        avg_daily_volume=avg_daily_vol,
        day_volume=day_vol,
        gap_type=gap_type,
        gap_pct=round(gap_pct, 2),
        capital=capital,
        risk_pct=risk_pct,
    )

    # ── Run engine ────────────────────────────────────────────────────────
    result = algo_engine.run(
        symbol=symbol,
        m5=m5_ind,
        m15=m15_ind,
        daily=daily_ind,
        levels=levels,
        ctx=ctx,
        meta_market_cap_cr=float(meta.market_cap_cr or 10_000),
    )

    # ── Convert to Pydantic ───────────────────────────────────────────────
    return AlgoSignal(
        stock=result.stock,
        date=result.date,
        time=result.time,
        action=result.action,
        entry_price=result.entry_price,
        stop_loss=result.stop_loss,
        target_1=result.target_1,
        target_2=result.target_2,
        hold_period=result.hold_period,
        confidence=result.confidence,
        risk_reward_ratio=result.risk_reward_ratio,
        strategies_triggered=result.strategies_triggered,
        strategy_confluence_count=result.strategy_confluence_count,
        reason=result.reason,
        book_profit_instruction=result.book_profit_instruction,
        risk_per_trade_percent=result.risk_per_trade_percent,
        suggested_position_size_units=result.suggested_position_size_units,
        pre_trade_filters_passed=result.pre_trade_filters_passed,
        filter_failures=result.filter_failures,
        strategy_details=[StrategyDetail(**d) for d in result.strategy_details],
        indicators_snapshot=result.indicators_snapshot,
    )


@router.get("/{symbol}", response_model=AlgoSignal)
def get_signal(symbol: str) -> AlgoSignal:
    """Return the algo-engine signal for *symbol* (cached 30 s)."""
    symbol = symbol.upper().strip()
    ck = _cache_key(symbol)
    hit = cache.get(ck)
    if hit:
        cached, _ = hit
        if isinstance(cached, AlgoSignal):
            cached.meta_cached = True
            return cached

    t0 = time.time()
    signal = _run_signal(symbol, capital=100_000.0, risk_pct=1.5)
    signal.meta_latency_ms = int((time.time() - t0) * 1000)
    signal.meta_cached = False
    cache.set(ck, signal, 30)
    return signal


@router.post("/{symbol}", response_model=AlgoSignal)
def post_signal(symbol: str, body: SignalRequest) -> AlgoSignal:
    """Return the algo-engine signal, optionally overriding capital/risk."""
    symbol = symbol.upper().strip()

    if not body.bust_cache:
        ck = _cache_key(symbol)
        hit = cache.get(ck)
        if hit:
            cached, _ = hit
            if isinstance(cached, AlgoSignal):
                cached.meta_cached = True
                return cached

    t0 = time.time()
    signal = _run_signal(symbol, capital=body.capital, risk_pct=body.risk_pct)
    signal.meta_latency_ms = int((time.time() - t0) * 1000)
    signal.meta_cached = False
    cache.set(_cache_key(symbol), signal, 30)
    return signal
