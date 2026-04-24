"""Pydantic response/request models."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Horizon = Literal["intraday", "longterm"]
Action = Literal["BUY", "SELL", "HOLD"]


class TechnicalSnapshot(BaseModel):
    last_price: float
    change_pct: float
    rsi: float
    macd: float
    macd_signal: float
    sma_20: float
    sma_50: float
    sma_200: float
    volume_ratio: float = Field(..., description="today's vol / 20-day avg vol")
    atr_pct: float


class FundamentalSnapshot(BaseModel):
    market_cap_cr: float
    pe: float
    pb: float
    roe: float
    debt_to_equity: float
    eps_growth_3y: float
    revenue_growth_3y: float
    dividend_yield: float
    promoter_holding: float


class ScoreBreakdown(BaseModel):
    technical: float = Field(..., ge=0, le=100)
    fundamental: float = Field(..., ge=0, le=100)
    composite: float = Field(..., ge=0, le=100)
    signals: List[str] = []


class Suggestion(BaseModel):
    symbol: str
    name: str
    sector: str
    horizon: Horizon
    action: Action
    entry: float
    stop_loss: float
    target: float
    expected_return_pct: float
    score: ScoreBreakdown
    technical: TechnicalSnapshot
    fundamental: FundamentalSnapshot


class SuggestionList(BaseModel):
    horizon: Horizon
    generated_at: str
    next_refresh_at: str
    ttl_seconds: int
    items: List[Suggestion]
    # "mock" = synthetic OHLCV, "upstox" = live NSE data via Upstox v2.
    data_provider: str = "mock"


class WatchlistItem(BaseModel):
    symbol: str
    note: Optional[str] = None
    added_at: str


class WatchlistResponse(BaseModel):
    items: List[WatchlistItem]


class AddWatchlistRequest(BaseModel):
    symbol: str
    note: Optional[str] = None


class StockDetail(BaseModel):
    symbol: str
    name: str
    sector: str
    technical: TechnicalSnapshot
    fundamental: FundamentalSnapshot
    intraday_score: ScoreBreakdown
    longterm_score: ScoreBreakdown
