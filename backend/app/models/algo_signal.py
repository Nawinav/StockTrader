"""Pydantic schema for the rule-based algo-engine signal.

Matches the exact JSON output format specified in the Algo Trading
Master Prompt, with additional server-side metadata fields.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StrategyDetail(BaseModel):
    """Per-strategy evaluation result."""
    name: str
    tag: str
    direction: int = Field(..., description="1=bullish, -1=bearish, 0=neutral")
    direction_label: str  # BULLISH / BEARISH / NEUTRAL
    reason: str


class AlgoSignal(BaseModel):
    """Rule-based multi-strategy confluence signal.

    Field names are kept exactly as specified in the output format so the
    JSON serialisation matches the contract without any transformation.
    """
    # ── Core identification ──────────────────────────────────────────────
    stock: str = Field(..., description="NSE ticker symbol")
    date: str = Field(..., description="Signal date YYYY-MM-DD")
    time: str = Field(..., description="Signal time HH:MM IST")

    # ── Trade directive ──────────────────────────────────────────────────
    action: str = Field(
        ...,
        description="BUY | SELL | HOLD | AVOID",
        pattern=r"^(BUY|SELL|HOLD|AVOID)$",
    )
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    hold_period: str = Field(
        ...,
        description="Intraday | Swing 3-5 days | Positional 2-4 weeks",
    )

    # ── Signal quality ───────────────────────────────────────────────────
    confidence: str = Field(
        ...,
        description="HIGH | MEDIUM | LOW",
        pattern=r"^(HIGH|MEDIUM|LOW)$",
    )
    risk_reward_ratio: str = Field(..., description="e.g. 1:2.5")
    strategies_triggered: List[str] = Field(
        ...,
        description="Tags of strategies that agreed on direction",
    )
    strategy_confluence_count: int = Field(
        ...,
        ge=0, le=9,
        description="Number of strategies agreeing (3+ = valid signal)",
    )

    # ── Narrative ────────────────────────────────────────────────────────
    reason: str = Field(..., description="2-3 line technical justification")
    book_profit_instruction: str

    # ── Risk / sizing ────────────────────────────────────────────────────
    risk_per_trade_percent: float = Field(..., ge=0.0, le=5.0)
    suggested_position_size_units: int = Field(..., ge=0)

    # ── Pre-trade filter status ──────────────────────────────────────────
    pre_trade_filters_passed: bool
    filter_failures: List[str] = []

    # ── Full strategy breakdown (9 rows) ─────────────────────────────────
    strategy_details: List[StrategyDetail] = []

    # ── Live indicator snapshot ──────────────────────────────────────────
    indicators_snapshot: Dict[str, Any] = {}

    # ── Server-side metadata ─────────────────────────────────────────────
    meta_engine_version: str = "9-strategy-v1"
    meta_cached: Optional[bool] = None
    meta_latency_ms: Optional[int] = None
