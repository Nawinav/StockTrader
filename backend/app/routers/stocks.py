"""Single-stock detail endpoint."""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings
from app.data.universe import get_by_symbol
from app.models.schemas import (
    FundamentalSnapshot,
    ScoreBreakdown,
    StockDetail,
)
from app.services.data_provider import get_provider
from app.services.scoring import (
    build_technical_snapshot,
    composite,
    fundamental_score,
    technical_score,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


# How many daily candles per chart timeframe.
_TIMEFRAME_DAYS: dict[str, int] = {
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 252,
    "2Y": 504,
}


class Candle(BaseModel):
    time: int       # unix seconds (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChartResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: List[Candle]


class ExpertAnalysisResponse(BaseModel):
    symbol: str
    name: str
    sector: str
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
    narrative: List[str]
    intraday_score: ScoreBreakdown
    longterm_score: ScoreBreakdown


@router.get("/{symbol}", response_model=StockDetail)
def stock_detail(symbol: str) -> StockDetail:
    meta = get_by_symbol(symbol)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")

    provider = get_provider(get_settings().data_provider)
    candles = provider.get_history(meta.symbol, days=260)
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

    f_score, f_signals = fundamental_score(fund_snap)

    def pack(horizon: str) -> ScoreBreakdown:
        t_score, t_signals = technical_score(tech_snap, horizon)
        comp = composite(t_score, f_score, horizon)
        return ScoreBreakdown(
            technical=round(t_score, 1),
            fundamental=round(f_score, 1),
            composite=round(comp, 1),
            signals=t_signals + f_signals,
        )

    return StockDetail(
        symbol=meta.symbol,
        name=meta.name,
        sector=meta.sector,
        technical=tech_snap,
        fundamental=fund_snap,
        intraday_score=pack("intraday"),
        longterm_score=pack("longterm"),
    )


@router.get("/{symbol}/analysis", response_model=ExpertAnalysisResponse)
def stock_analysis(symbol: str) -> ExpertAnalysisResponse:
    """Plain-English expert analysis plus intraday/longterm scores."""
    from app.services.expert_analysis import analyze as expert_analyze
    meta = get_by_symbol(symbol)
    if not meta:
        raise HTTPException(404, f"Unknown symbol: {symbol}")
    provider = get_provider(get_settings().data_provider)
    candles = provider.get_history(meta.symbol, days=260)
    if not candles:
        raise HTTPException(502, f"No candles returned for {symbol}")
    expert = expert_analyze(candles)

    # Build the scores too so the UI has everything in one payload.
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
    f_score, f_signals = fundamental_score(fund_snap)

    def pack(horizon: str) -> ScoreBreakdown:
        t_score, t_signals = technical_score(tech_snap, horizon)
        comp = composite(t_score, f_score, horizon)
        return ScoreBreakdown(
            technical=round(t_score, 1),
            fundamental=round(f_score, 1),
            composite=round(comp, 1),
            signals=t_signals + f_signals,
        )

    return ExpertAnalysisResponse(
        symbol=meta.symbol,
        name=meta.name,
        sector=meta.sector,
        last_price=expert.last_price,
        change_pct_1d=expert.change_pct_1d,
        change_pct_5d=expert.change_pct_5d,
        change_pct_20d=expert.change_pct_20d,
        trend=expert.trend,
        momentum=expert.momentum,
        rsi=expert.rsi,
        macd_hist=expert.macd_hist,
        atr_pct=expert.atr_pct,
        volatility_label=expert.volatility_label,
        volume_vs_avg_20d=expert.volume_vs_avg_20d,
        avg_volume_20d=expert.avg_volume_20d,
        supports=expert.supports,
        resistances=expert.resistances,
        nearest_support=expert.nearest_support,
        nearest_resistance=expert.nearest_resistance,
        risk_reward_ratio=expert.risk_reward_ratio,
        fib_levels=expert.fib_levels,
        narrative=expert.narrative,
        intraday_score=pack("intraday"),
        longterm_score=pack("longterm"),
    )


@router.get("/{symbol}/chart", response_model=ChartResponse)
def stock_chart(
    symbol: str,
    timeframe: str = Query(default="3M", pattern="^(1M|3M|6M|1Y|2Y)$"),
) -> ChartResponse:
    """Return daily OHLCV candles formatted for lightweight-charts."""
    meta = get_by_symbol(symbol)
    if not meta:
        raise HTTPException(404, f"Unknown symbol: {symbol}")
    days = _TIMEFRAME_DAYS[timeframe]
    provider = get_provider(get_settings().data_provider)
    # Fetch a bit extra so weekends/holidays still leave us the full window.
    raw = provider.get_history(meta.symbol, days=max(days + 20, 260))
    raw = raw[-days:]

    # Synthesize timestamps if the provider doesn't attach them. lightweight-charts
    # only needs ``time`` to be monotonically increasing; daily bars aligned to
    # weekday are fine.
    candles: List[Candle] = []
    now = datetime.now(timezone.utc).date()
    for i, c in enumerate(raw):
        if c.timestamp is not None:
            ts = int(c.timestamp.replace(tzinfo=timezone.utc).timestamp())
        else:
            # i-th bar from the end -> that many business days back.
            offset_days = len(raw) - 1 - i
            d = now
            for _ in range(offset_days):
                d = d.fromordinal(d.toordinal() - 1)
                # Skip weekends.
                while d.weekday() >= 5:
                    d = d.fromordinal(d.toordinal() - 1)
            ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
        candles.append(Candle(
            time=ts,
            open=round(c.open, 2),
            high=round(c.high, 2),
            low=round(c.low, 2),
            close=round(c.close, 2),
            volume=round(c.volume, 0),
        ))
    return ChartResponse(symbol=meta.symbol, timeframe=timeframe, candles=candles)
