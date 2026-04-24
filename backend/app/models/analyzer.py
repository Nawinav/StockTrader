"""Pydantic schemas for the intraday analyzer.

Mirrors the JSON output contract defined in the Claude prompt template
exactly. The Claude client returns a JSON string; the orchestrator
validates it against `AnalyzerSignal` — if validation fails we retry
once with a correction message before surfacing an error to the caller.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------- Request ------------------------------------------------------

class CurrentPosition(BaseModel):
    has_position: bool = False
    side: Literal["long", "short", "none"] = "none"
    entry: float = 0.0
    quantity: int = 0
    unrealized_pnl: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    age_minutes: int = 0


class AccountParams(BaseModel):
    capital: Optional[float] = Field(None, description="Available capital in INR")
    risk_pct: Optional[float] = Field(None, ge=0.1, le=5.0, description="Max % of capital per trade")
    max_daily_loss_pct: Optional[float] = Field(None, ge=0.5, le=10.0)
    day_pnl: float = 0.0
    trades_today: int = 0
    max_trades: int = 10


class AnalyzeRequest(BaseModel):
    """Optional body for POST /api/analyze/{symbol}."""
    position: Optional[CurrentPosition] = None
    account: Optional[AccountParams] = None
    # Force re-analysis ignoring the cache. Useful from the UI "Refresh" button.
    bust_cache: bool = False


# ---------- Response (matches the JSON schema in the prompt template) ----

AnalyzerAction = Literal["BUY", "SELL", "HOLD", "EXIT", "AVOID"]
EntryType = Literal["MARKET", "LIMIT", "STOP"]
StopLossType = Literal["STRUCTURAL", "ATR", "PERCENT"]
TargetLevel = Literal["T1", "T2", "T3"]


class SignalEntry(BaseModel):
    type: EntryType
    price: Optional[float] = None
    valid_until_ist: str


class SignalStopLoss(BaseModel):
    price: float
    type: StopLossType
    rationale: str


class SignalTarget(BaseModel):
    level: TargetLevel
    price: float
    rr: float = Field(..., description="Reward-to-risk multiple at this target")
    rationale: str


class SignalPositionSize(BaseModel):
    quantity: int
    rupee_risk: float
    rupee_exposure: float
    calc: str


class SignalReasoning(BaseModel):
    market_context: str
    trend_alignment: str
    price_action: str
    indicator_confluence: str
    volume_confirmation: str
    key_levels: str
    time_of_day: str


class AnalyzerSignal(BaseModel):
    """Exact schema returned by the analyzer (must match the prompt template)."""
    symbol: str
    timestamp_ist: str
    action: AnalyzerAction
    confidence: int = Field(..., ge=0, le=100)
    setup_name: str
    timeframe_basis: str

    # ── 9-strategy confluence fields (new) ──────────────────────────────
    strategies_triggered: List[str] = Field(
        default=[],
        description="Strategy tags that fired in the same direction",
    )
    strategy_confluence_count: int = Field(
        default=0,
        ge=0, le=9,
        description="Number of agreeing strategies (3+ = valid signal)",
    )
    hold_period: Optional[str] = Field(
        default=None,
        description="Intraday | Swing 3-5 days | Positional 2-4 weeks",
    )

    entry: SignalEntry
    stop_loss: SignalStopLoss
    targets: List[SignalTarget]
    position_size: SignalPositionSize
    trail_strategy: str
    reasoning: SignalReasoning
    conflicting_signals: List[str] = []
    invalidation: str
    what_to_watch: List[str] = []
    risk_flags: List[str] = []
    disclaimer_acknowledged: bool = True

    # Additional server-side metadata (not from Claude). Populated by the
    # orchestrator so the frontend can show what ran.
    meta_provider: Optional[str] = None       # "stub" | "anthropic"
    meta_model: Optional[str] = None          # e.g., "claude-sonnet-4-6"
    meta_cached: Optional[bool] = None
    meta_latency_ms: Optional[int] = None
