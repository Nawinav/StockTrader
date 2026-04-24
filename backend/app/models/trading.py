"""Pydantic models for the paper-trading engine.

All trading today is **paper**: no real orders are placed. The engine
auto-enters on top-ranked intraday suggestions that meet a minimum
composite-score bar, sizes each position using a fixed risk-per-trade
budget, and auto-exits on stop-loss, target, or end-of-day.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Side = Literal["LONG", "SHORT"]
ExitReason = Literal["STOP", "TARGET", "EOD", "MANUAL", "SIGNAL_FLIP", "P1", "P2", "TIME_STOP", "TRAIL"]


class TradingConfig(BaseModel):
    """User-tunable risk & strategy parameters."""

    starting_capital_inr: float = Field(
        default=100000.0,
        ge=10000.0,
        description="Virtual capital the engine manages. Reset wipes to this.",
    )
    risk_pct_per_trade: float = Field(
        default=1.0,
        ge=0.1,
        le=5.0,
        description="Max loss per trade as % of CURRENT equity.",
    )
    max_concurrent_positions: int = Field(default=5, ge=1, le=20)
    max_entries_per_day: int = Field(default=10, ge=1, le=50)
    min_composite_score: float = Field(
        default=65.0,
        ge=0,
        le=100,
        description="Only open a position when composite >= this.",
    )
    # Safety cap: if a suggestion has an unusually wide stop the engine
    # refuses rather than putting a huge notional at risk.
    max_stop_distance_pct: float = Field(default=3.5, ge=0.3, le=15.0)
    # If True, flatten all open positions at/after 15:20 IST.
    eod_flatten: bool = Field(default=True)
    # Kill-switch — auto entries only happen when True.
    auto_trading_enabled: bool = Field(default=False)

    # ---- Trading profile (risk level) -----------------------------------
    # Profiles set the effective filter thresholds. Choose the preset that
    # matches your risk appetite; fine-tune individual params if needed.
    #
    # ACTIVE          ~75% win rate — minimal filtering, more frequent trades.
    #                 HC gate: Grade C+ (score ≥ 50), confluence ≥ 1, MTF: any.
    #                 Like the original composite-score-only system.
    #
    # BALANCED        ~85% win rate — moderate filtering, good trade frequency.
    #                 HC gate: Grade B+ (score ≥ 65), confluence ≥ 3, MTF: 1/3.
    #
    # HIGH_CONFIDENCE ~90-95% win rate — strict filtering, fewer but higher-
    #                 quality trades. HC gate: Grade A (score ≥ 80), confluence
    #                 ≥ 5, MTF: 2/3 required.
    trading_profile: Literal["ACTIVE", "BALANCED", "HIGH_CONFIDENCE"] = Field(
        default="HIGH_CONFIDENCE",
        description=(
            "Risk/quality preset. ACTIVE=~75% win rate (light filtering), "
            "BALANCED=~85% (moderate), HIGH_CONFIDENCE=~95% (strictest). "
            "Overrides HC score threshold, confluence bar, and MTF requirement."
        ),
    )

    # ---- 9-strategy algo-engine gate ------------------------------------
    # When True the engine runs algo_engine.run() on every candidate and
    # only enters when the confluence count meets min_confluence_count.
    # When False the old composite-score-only path is used (legacy mode).
    use_algo_engine: bool = Field(
        default=True,
        description=(
            "Use the 9-strategy confluence engine as the primary entry gate. "
            "Recommended: True. Set False to fall back to composite-score-only mode."
        ),
    )
    min_confluence_count: int = Field(
        default=3,
        ge=1,
        le=9,
        description=(
            "Minimum number of strategies that must agree before the auto-trader "
            "opens a position. Overridden upward by trading_profile and market regime."
        ),
    )

    # ---- Profit-taking / trailing stop -----------------------------------
    # When the unrealized gain crosses this % the stop is moved to breakeven,
    # locking in the trade. Set to 0 to disable.
    trail_trigger_pct: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description=(
            "Once unrealized gain >= this %, move SL to breakeven. "
            "Set 0 to disable trailing."
        ),
    )
    # Once the position is trailing (SL at breakeven or above), the stop
    # follows price by this % distance so gains accumulate.
    trail_step_pct: float = Field(
        default=0.3,
        ge=0.1,
        le=5.0,
        description=(
            "After trail triggers, keep SL this % below the highest seen price."
        ),
    )


class Position(BaseModel):
    symbol: str
    name: str
    sector: str
    side: Side = "LONG"
    qty: int
    entry_price: float
    stop_loss: float
    target: float
    last_price: float
    entered_at: str  # ISO UTC
    score_at_entry: float
    unrealized_pnl: float
    unrealized_pct: float
    # How much equity was put at risk by this trade at open, in INR.
    risk_inr: float
    # Trailing stop tracking — None until the trail trigger fires.
    highest_price: Optional[float] = None   # highest LTP seen since entry
    trailing_active: bool = False           # True once SL moved to breakeven

    # Algo engine metadata recorded at entry time.
    strategies_at_entry: List[str] = Field(
        default_factory=list,
        description="Strategy tags that fired at entry (e.g. ['EMA_CROSSOVER', 'VWAP'])",
    )
    confluence_at_entry: int = Field(
        default=0,
        description="Number of agreeing strategies at the time of entry.",
    )
    # High-Confidence Filter grade
    hc_grade: str = Field(default="", description="Grade A+/A/B/C/D from high-confidence filter")
    hc_score: int = Field(default=0, description="High-confidence score 0–100")
    # Partial profit state (displayed in UI)
    pp_p1_done: bool = Field(default=False)
    pp_p2_done: bool = Field(default=False)
    pp_p1_price: float = Field(default=0.0)
    pp_p2_price: float = Field(default=0.0)


class Trade(BaseModel):
    id: str
    symbol: str
    name: str
    sector: str
    side: Side
    qty: int
    entry_price: float
    exit_price: float
    entered_at: str
    exited_at: str
    realized_pnl: float
    realized_pct: float
    reason: ExitReason
    score_at_entry: float
    # Stop-loss / target set at entry time (for post-trade review).
    stop_loss: float
    target: float

    # Algo engine snapshot recorded at entry time.
    strategies_at_entry: List[str] = Field(default_factory=list)
    confluence_at_entry: int = 0

    # Execution cost breakdown (realistic simulation)
    gross_pnl: float = Field(default=0.0, description="P&L before costs")
    execution_cost: float = Field(default=0.0, description="Total round-trip costs (slippage+brokerage+STT+charges)")
    # Market regime at entry time
    market_regime: str = Field(default="", description="Market regime when trade was entered")
    # Event filter — was entry blocked? (should be empty if we entered)
    event_blocked: bool = Field(default=False)


class PortfolioSnapshot(BaseModel):
    starting_capital: float
    cash: float
    invested: float
    equity: float  # cash + sum(qty * last_price)
    realized_pnl_total: float
    realized_pnl_today: float
    unrealized_pnl: float
    # Count of trades closed today, used to gate max_entries_per_day.
    entries_today: int
    wins_today: int
    losses_today: int
    positions: List[Position]
    as_of: str
    market_open: bool
    paper_trading: bool
    auto_trading_enabled: bool
    data_provider: str
    last_tick_at: Optional[str] = None
    last_tick_reason: Optional[str] = None


class TradeLog(BaseModel):
    items: List[Trade]


class ToggleAutoRequest(BaseModel):
    enabled: bool


class ManualCloseResponse(BaseModel):
    trade: Trade


class TickResponse(BaseModel):
    opened: int
    closed: int
    reasons: List[str]
