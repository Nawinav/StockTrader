"""Paper-trading engine.

Drives auto-entry, mark-to-market, and auto-exit for a simulated
portfolio.

Entry gate (when auto_trading_enabled=True)
-------------------------------------------
When ``cfg.use_algo_engine`` is True (the default), the engine runs the
full 9-strategy confluence engine on every candidate symbol and only
opens a position when:

  1. algo_engine action == "BUY"
  2. algo_engine confluence_count  >= cfg.min_confluence_count  (default 3)
  3. suggestion composite_score    >= cfg.min_composite_score   (secondary quality filter)
  4. algo pre-trade filters passed (volume, price, ATR, market-cap)

When ``cfg.use_algo_engine`` is False (legacy mode), only condition 3 is
checked — the old composite-score-only path.

The algo engine produces its own entry price, stop-loss, and targets which
are used directly for the position instead of the suggestion's ATR-based
estimates, giving tighter, strategy-aware risk levels.

Invariants
----------
* Paper only. No real orders ever placed.
* Deterministic sizing: qty = floor(risk_amount / (entry - stop)).
* One position per symbol — no stacking.
* Long-only entries (SELL signals exit; shorts not implemented yet).
* Resilient: per-symbol exceptions are caught so one bad symbol never
  halts the whole tick.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.config import get_settings
from app.data.universe import get_by_symbol
from app.models.schemas import Suggestion
from app.models.trading import (
    ExitReason,
    PortfolioSnapshot,
    Position,
    Trade,
    TradingConfig,
)
from app.services import algo_engine, indicators as ind
from app.services.data_provider import ist_now, get_provider, session_bounds
from app.services.execution_costs import apply_slippage, net_pnl as calc_net_pnl
from app.services import partial_profit_engine as ppe
from app.services.suggestions import get_suggestions
from app.services.trading_store import (
    load_state,
    roll_day_if_needed,
    save_state,
    today_key_ist,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────── trading profiles ────────────────────────
#
# Each profile is a dict of gate-override values applied inside _maybe_enter().
# They translate the user-facing risk appetite into concrete filter thresholds.
#
# Key             ACTIVE   BALANCED   HIGH_CONFIDENCE
# ─────────────── ──────── ────────── ────────────────
# hc_min_score      50       65           80
# hc_mtf_min         0        1            2
# min_conf           1        3            5  (lower-bounded by cfg.min_confluence_count & regime)
# require_confluence False   False         based on use_algo_engine

_PROFILES = {
    "ACTIVE": {
        "label":              "⚡ Active (~75% win rate)",
        # HC filter is SKIPPED entirely — composite score only, like the
        # original system.  More trades, accepts any Nifty direction.
        "skip_hc":            True,
        "hc_min_score":       50,   # not used when skip_hc=True
        "hc_mtf_min":          0,
        "hc_nifty_hard_block": False,
        "profile_min_conf":    1,   # very loose confluence bar
        "require_confluence": False,
        "description": (
            "Minimal filtering — like the original composite-score-only system. "
            "More frequent trades, smaller average winner, ~75% win rate. "
            "Best when the market is in a strong trend."
        ),
    },
    "BALANCED": {
        "label":              "⚖️ Balanced (~85% win rate)",
        "skip_hc":            False,
        "hc_min_score":       65,   # Grade B+ or better
        "hc_mtf_min":          1,   # at least 1/3 timeframes aligned
        # Nifty bearish scores 0 pts but does NOT hard-block in BALANCED —
        # a strong individual stock setup can still qualify.
        "hc_nifty_hard_block": False,
        "profile_min_conf":    3,   # medium conviction
        "require_confluence": False,
        "description": (
            "Moderate filtering. Filters obvious noise while still catching "
            "a reasonable number of opportunities. ~85% win rate. "
            "Good general-purpose setting."
        ),
    },
    "HIGH_CONFIDENCE": {
        "label":              "🎯 High-Confidence (~95% win rate)",
        "skip_hc":            False,
        "hc_min_score":       80,   # Grade A or A+ required
        "hc_mtf_min":          2,   # 2/3 timeframes must agree
        "hc_nifty_hard_block": True, # Nifty bearish is a hard block
        "profile_min_conf":    5,   # strong conviction required
        "require_confluence": None, # → determined by use_algo_engine setting
        "description": (
            "Strictest filtering — all gates active, Grade A/A+ HC score, "
            "strong multi-timeframe confluence. Fewest trades but highest quality. "
            "~90-95% win rate. Recommended when capital preservation is the priority."
        ),
    },
}


def _profile_params(cfg: "TradingConfig") -> dict:
    """Return gate-override values for the currently selected trading profile.

    Confluence handling per profile
    ────────────────────────────────
    ACTIVE          → override_conf=True: profile's min (1) replaces the user
                      setting and regime recommendation. The user chose ACTIVE
                      for light filtering — don't let defaults re-tighten it.
    BALANCED        → override_conf=False: take max(profile_min=3, user_setting,
                      regime recommendation). User/regime can tighten, can't loosen.
    HIGH_CONFIDENCE → same as BALANCED but profile_min=5.
    """
    profile = _PROFILES.get(cfg.trading_profile, _PROFILES["HIGH_CONFIDENCE"])
    # require_confluence: None → fall back to use_algo_engine setting
    req_conf = profile["require_confluence"]
    if req_conf is None:
        req_conf = cfg.use_algo_engine
    return {
        "skip_hc":             profile["skip_hc"],
        "hc_min_score":        profile["hc_min_score"],
        "hc_mtf_min":          profile["hc_mtf_min"],
        "hc_nifty_hard_block": profile["hc_nifty_hard_block"],
        "profile_min_conf":    profile["profile_min_conf"],
        # ACTIVE: profile value wins outright; others: max with user/regime.
        "override_conf":       cfg.trading_profile == "ACTIVE",
        "require_confluence":  req_conf,
    }


# ------------------------------------------------------------- market clock


def is_market_open(now: Optional[datetime] = None) -> bool:
    """NSE equity session: Mon–Fri, 09:15–15:30 IST."""
    now = now or ist_now()
    if now.weekday() >= 5:
        return False
    start, end = session_bounds(now)
    return start <= now < end


def minutes_to_close(now: Optional[datetime] = None) -> float:
    now = now or ist_now()
    _, end = session_bounds(now)
    return (end - now).total_seconds() / 60.0


# --------------------------------------------------------------- quotes


def _current_price(symbol: str, fallback: float) -> float:
    """Best-effort LTP. Falls back to ``fallback`` on any failure."""
    settings = get_settings()
    try:
        provider = get_provider(settings.data_provider)
        q = provider.get_quote(symbol)
        return float(q.close) if q and q.close else fallback
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning("LTP fetch failed for %s: %s", symbol, exc)
        return fallback


# -------------------------------------------------------------- sizing


def _size_position(
    entry: float, stop: float, equity: float, cash: float, cfg: TradingConfig
) -> Tuple[int, float]:
    """Return ``(qty, risk_inr)`` using fixed fractional risk.

    Returns ``(0, 0)`` if the trade can't be taken (e.g. stop wider than
    the cap, cash too low, or equity depleted).
    """
    if entry <= 0 or stop <= 0 or entry <= stop:
        return 0, 0.0
    stop_dist = entry - stop
    stop_pct = (stop_dist / entry) * 100
    if stop_pct > cfg.max_stop_distance_pct:
        return 0, 0.0
    risk_amount = equity * cfg.risk_pct_per_trade / 100.0
    qty = int(math.floor(risk_amount / stop_dist))
    if qty <= 0:
        return 0, 0.0
    notional = qty * entry
    # Don't allow a single position to exceed 50% of cash — keeps things
    # diversified even if the stop is tight.
    max_notional = min(cash, equity * 0.5)
    if notional > max_notional:
        qty = int(math.floor(max_notional / entry))
        if qty <= 0:
            return 0, 0.0
    risk_inr = qty * stop_dist
    return qty, risk_inr


# ---------------------------------------------------------- mark-to-market


def _mark_positions(state: Dict) -> None:
    """Update last_price / unrealized_pnl on every open position.

    Also advances the trailing stop when the position has crossed the
    configured profit trigger.
    """
    cfg = TradingConfig(**state["config"])

    for p in state["positions"]:
        entry = float(p["entry_price"])
        qty = int(p["qty"])
        ltp = _current_price(p["symbol"], entry)
        p["last_price"] = round(ltp, 2)
        pnl = (ltp - entry) * qty
        p["unrealized_pnl"] = round(pnl, 2)
        p["unrealized_pct"] = round(((ltp - entry) / entry) * 100, 2) if entry else 0.0

        # ---- Trailing stop ------------------------------------------------
        if cfg.trail_trigger_pct <= 0:
            continue  # feature disabled

        gain_pct = ((ltp - entry) / entry) * 100 if entry else 0.0

        # Track the highest seen price for this position.
        prev_high = float(p.get("highest_price") or entry)
        if ltp > prev_high:
            p["highest_price"] = round(ltp, 2)
            prev_high = ltp

        if gain_pct >= cfg.trail_trigger_pct:
            # Trail triggered — keep stop at (highest_price × (1 - trail_step_pct/100)).
            trail_sl = round(prev_high * (1 - cfg.trail_step_pct / 100), 2)
            current_sl = float(p["stop_loss"])

            # SL can only move UP (never tighten below current SL).
            if trail_sl > current_sl:
                p["stop_loss"] = trail_sl
                p["trailing_active"] = True


# ------------------------------------------------------------- close logic


def _avg_daily_vol_for(pos: Dict) -> float:
    """Best-effort avg daily volume for slippage calculation."""
    try:
        settings = get_settings()
        provider = get_provider(settings.data_provider)
        daily = provider.get_history(pos["symbol"], days=20)
        if daily:
            return float(sum(c.volume for c in daily) / len(daily))
    except Exception:
        pass
    return 500_000.0  # default: 5L shares (mid-tier slippage)


def _close_position(
    state: Dict,
    pos: Dict,
    exit_price: float,
    reason: ExitReason,
) -> Trade:
    entry = float(pos["entry_price"])
    qty = int(pos["qty"])

    # Apply sell-side slippage to exit price
    avg_vol = _avg_daily_vol_for(pos)
    from app.services.execution_costs import _slippage_pct
    slip = _slippage_pct(avg_vol)
    effective_exit = round(exit_price * (1 - slip), 2)

    gross = round((exit_price - entry) * qty, 2)
    net, costs = calc_net_pnl(gross, entry, exit_price, qty, avg_vol)
    realized_pct = ((effective_exit - entry) / entry) * 100 if entry else 0.0

    now_iso = datetime.now(timezone.utc).isoformat()
    trade = Trade(
        id=str(uuid.uuid4()),
        symbol=pos["symbol"],
        name=pos["name"],
        sector=pos["sector"],
        side=pos["side"],
        qty=qty,
        entry_price=round(entry, 2),
        exit_price=round(effective_exit, 2),
        entered_at=pos["entered_at"],
        exited_at=now_iso,
        realized_pnl=net,
        realized_pct=round(realized_pct, 2),
        reason=reason,
        score_at_entry=float(pos["score_at_entry"]),
        stop_loss=float(pos["stop_loss"]),
        target=float(pos["target"]),
        strategies_at_entry=pos.get("strategies_at_entry", []),
        confluence_at_entry=int(pos.get("confluence_at_entry", 0)),
        gross_pnl=gross,
        execution_cost=costs.total_cost,
        market_regime=pos.get("market_regime", ""),
    )

    # Return cash (notional at effective exit price).
    state["cash"] = round(state["cash"] + qty * effective_exit, 2)
    state["realized_pnl_total"] = round(state["realized_pnl_total"] + net, 2)
    roll_day_if_needed(state)
    state["day"]["realized_pnl"] = round(state["day"]["realized_pnl"] + net, 2)
    if net >= 0:
        state["day"]["wins"] += 1
    else:
        state["day"]["losses"] += 1

    # Remove position; prepend to trade log (newest first).
    state["positions"] = [p for p in state["positions"] if p["symbol"] != pos["symbol"]]
    state["trades"].insert(0, trade.model_dump())
    # Bound trade log in memory to the most recent 500.
    if len(state["trades"]) > 500:
        state["trades"] = state["trades"][:500]
    return trade


def _partial_close(state: Dict, pos: Dict, event: ppe.PartialExitEvent) -> Optional[Trade]:
    """Close a PARTIAL qty of a position for P1/P2/TIME_STOP/TRAIL events."""
    qty_to_close = min(event.qty_to_close, int(pos["qty"]))
    if qty_to_close <= 0:
        return None

    orig_qty = int(pos["qty"])
    entry    = float(pos["entry_price"])
    exit_p   = event.exit_price
    avg_vol  = 500_000.0  # use default; exact vol not critical for partial exits

    from app.services.execution_costs import _slippage_pct
    slip     = _slippage_pct(avg_vol)
    eff_exit = round(exit_p * (1 - slip), 2)

    gross    = round((exit_p - entry) * qty_to_close, 2)
    net, costs = calc_net_pnl(gross, entry, exit_p, qty_to_close, avg_vol)

    now_iso  = datetime.now(timezone.utc).isoformat()
    trade = Trade(
        id=str(uuid.uuid4()),
        symbol=pos["symbol"],
        name=pos["name"],
        sector=pos["sector"],
        side=pos["side"],
        qty=qty_to_close,
        entry_price=round(entry, 2),
        exit_price=round(eff_exit, 2),
        entered_at=pos["entered_at"],
        exited_at=now_iso,
        realized_pnl=net,
        realized_pct=round(((eff_exit - entry) / entry * 100) if entry else 0.0, 2),
        reason=event.reason,   # type: ignore[arg-type]
        score_at_entry=float(pos.get("score_at_entry", 0)),
        stop_loss=float(pos["stop_loss"]),
        target=float(pos["target"]),
        strategies_at_entry=pos.get("strategies_at_entry", []),
        confluence_at_entry=int(pos.get("confluence_at_entry", 0)),
        gross_pnl=gross,
        execution_cost=costs.total_cost,
        market_regime=pos.get("market_regime", ""),
        hc_grade=pos.get("hc_grade", ""),
        hc_score=int(pos.get("hc_score", 0)),
    )

    # Reduce position qty by the closed amount; return cash
    remaining = orig_qty - qty_to_close
    pos["qty"] = remaining

    # Return cash for closed portion
    state["cash"] = round(state["cash"] + qty_to_close * eff_exit, 2)
    state["realized_pnl_total"] = round(state["realized_pnl_total"] + net, 2)
    roll_day_if_needed(state)
    state["day"]["realized_pnl"] = round(state["day"]["realized_pnl"] + net, 2)

    if remaining <= 0:
        # Full position closed — remove from positions list
        state["positions"] = [p for p in state["positions"] if p["symbol"] != pos["symbol"]]
        if net >= 0:
            state["day"]["wins"] += 1
        else:
            state["day"]["losses"] += 1
    else:
        # Partial close — position continues with reduced qty
        # Re-mark unrealized P&L for the remaining size
        ltp = float(pos.get("last_price", entry))
        pos["unrealized_pnl"] = round((ltp - entry) * remaining, 2)
        pos["unrealized_pct"] = round(((ltp - entry) / entry * 100) if entry else 0.0, 2)
        # Count as partial win for today's stats
        if net >= 0:
            state["day"]["wins"] += 1

    state["trades"].insert(0, trade.model_dump())
    if len(state["trades"]) > 500:
        state["trades"] = state["trades"][:500]

    logger.info(
        "%s %s: closed %d/%d shares at ₹%.2f — net ₹%.2f",
        event.reason, pos["symbol"], qty_to_close, orig_qty, eff_exit, net,
    )
    return trade


def _run_partial_profits(state: Dict) -> List[Trade]:
    """Evaluate partial profit and time-stop events for all open positions."""
    partial_trades: List[Trade] = []
    for pos in list(state["positions"]):
        events = ppe.evaluate(pos)
        for event in events:
            t = _partial_close(state, pos, event)
            if t:
                partial_trades.append(t)
            # If position was fully closed by time-stop, stop processing it
            if not any(p["symbol"] == pos["symbol"] for p in state["positions"]):
                break
    return partial_trades


def _maybe_exit_all(state: Dict, cfg: TradingConfig) -> List[Trade]:
    """Evaluate stop / target / EoD rules for every open position."""
    closed: List[Trade] = []
    now = ist_now()
    eod_pending = cfg.eod_flatten and is_market_open(now) and minutes_to_close(now) <= 10.0
    for pos in list(state["positions"]):
        ltp = float(pos["last_price"])
        stop = float(pos["stop_loss"])   # may have been moved by partial profit engine
        target = float(pos["target"])
        if ltp <= stop:
            closed.append(_close_position(state, pos, ltp, "STOP"))
            continue
        if ltp >= target:
            closed.append(_close_position(state, pos, ltp, "TARGET"))
            continue
        if eod_pending:
            closed.append(_close_position(state, pos, ltp, "EOD"))
            continue
    return closed


# ---------------------------------------------------------- algo gate


def _run_algo_gate(
    symbol: str,
    ltp: float,
    cfg: TradingConfig,
) -> Optional[algo_engine.AlgoEngineResult]:
    """Run the 9-strategy engine on *symbol* and return the result if it
    passes the confluence gate; return None if it fails or errors.

    Uses the same data pipeline as the /api/signals endpoint but inlined
    here so no HTTP call is needed inside the trading loop.
    """
    settings = get_settings()
    try:
        provider = get_provider(settings.data_provider)
        meta = get_by_symbol(symbol)
        if meta is None:
            return None

        daily_candles = provider.get_history(symbol, days=260)
        m5_candles    = provider.get_intraday_history(symbol, "5m", 60)
        m15_candles   = provider.get_intraday_history(symbol, "15m", 40)

        if not daily_candles:
            return None

        # ── Data quality gate ────────────────────────────────────────
        from app.services.data_quality import is_tradeable as dq_check
        tradeable, dq_issues = dq_check(
            symbol,
            daily_candles,
            m5_candles,
            settings.data_provider,
        )
        if not tradeable:
            logger.info("%s failed data quality: %s", symbol, "; ".join(dq_issues))
            return None

        daily_ind = ind.build_daily(daily_candles)
        m5_ind    = ind.build_intraday(m5_candles)  if m5_candles  else ind.build_intraday(daily_candles[-60:])
        m15_ind   = ind.build_intraday(m15_candles) if m15_candles else ind.build_intraday(daily_candles[-40:])

        day_open   = float(m5_candles[0].open)  if m5_candles  else float(daily_candles[-1].open)
        prev_close = float(daily_candles[-2].close) if len(daily_candles) >= 2 else ltp
        levels     = ind.build_key_levels(daily_candles, m5_candles or [], day_open)

        avg_daily_vol = float(
            sum(c.volume for c in daily_candles[-20:]) / max(1, len(daily_candles[-20:]))
        )
        day_vol = sum(c.volume for c in (m5_candles or [])) or float(daily_candles[-1].volume)
        gap_pct  = (day_open - prev_close) / prev_close * 100 if prev_close else 0.0
        gap_type = (
            "gap_up"   if gap_pct >  0.15 else
            "gap_down" if gap_pct < -0.15 else
            "flat"
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
            capital=cfg.starting_capital_inr,
            risk_pct=cfg.risk_pct_per_trade,
        )

        result = algo_engine.run(
            symbol=symbol,
            m5=m5_ind,
            m15=m15_ind,
            daily=daily_ind,
            levels=levels,
            ctx=ctx,
            meta_market_cap_cr=float(meta.market_cap_cr or 10_000),
        )
        return result

    except Exception as exc:
        logger.warning("algo gate failed for %s: %s", symbol, exc)
        return None


# ------------------------------------------------------------ entry logic


def _equity(state: Dict) -> float:
    invested = sum(
        float(p["last_price"]) * int(p["qty"]) for p in state["positions"]
    )
    return round(float(state["cash"]) + invested, 2)


def _open_position_from(
    state: Dict,
    s: Suggestion,
    cfg: TradingConfig,
    algo_result: Optional[algo_engine.AlgoEngineResult] = None,
    hc_result=None,   # high_confidence_filter.HighConfidenceResult
) -> Optional[Position]:
    equity = _equity(state)

    # Prefer algo engine's tighter stop/target when available; fall back to
    # suggestion's ATR-based estimates for legacy mode.
    quoted_entry = algo_result.entry_price if algo_result else s.entry
    stop         = algo_result.stop_loss   if algo_result else s.stop_loss
    target       = algo_result.target_1    if algo_result else s.target

    # Apply buy-side slippage — effective entry is slightly higher than quoted.
    try:
        settings_obj = get_settings()
        provider_obj = get_provider(settings_obj.data_provider)
        daily_hist = provider_obj.get_history(s.symbol, days=20)
        avg_vol = float(sum(c.volume for c in daily_hist) / len(daily_hist)) if daily_hist else 500_000.0
    except Exception:
        avg_vol = 500_000.0

    from app.services.execution_costs import _slippage_pct
    slip = _slippage_pct(avg_vol)
    entry = round(quoted_entry * (1 + slip), 2)  # buy at slightly higher price

    qty, risk_inr = _size_position(
        entry=entry,
        stop=stop,
        equity=equity,
        cash=float(state["cash"]),
        cfg=cfg,
    )
    if qty <= 0:
        return None
    notional = qty * entry
    if notional > float(state["cash"]):
        return None

    # Get current market regime for recording on the position.
    market_regime_str = ""
    try:
        from app.services.market_regime import detect as detect_regime
        market_regime_str = detect_regime().regime
    except Exception:
        pass

    state["cash"] = round(float(state["cash"]) - notional, 2)

    pos_dict = Position(
        symbol=s.symbol,
        name=s.name,
        sector=s.sector,
        side="LONG",
        qty=qty,
        entry_price=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        last_price=round(entry, 2),
        entered_at=datetime.now(timezone.utc).isoformat(),
        score_at_entry=float(s.score.composite),
        unrealized_pnl=0.0,
        unrealized_pct=0.0,
        risk_inr=round(risk_inr, 2),
        strategies_at_entry=algo_result.strategies_triggered if algo_result else [],
        confluence_at_entry=algo_result.strategy_confluence_count if algo_result else 0,
    ).model_dump()

    # Store extra metadata on the dict (not in Pydantic model to avoid schema churn)
    pos_dict["market_regime"] = market_regime_str
    pos_dict["quoted_entry"]  = quoted_entry
    pos_dict["slippage_pct"]  = round(slip * 100, 4)

    # ── HC grade ──────────────────────────────────────────────────────
    if hc_result is not None:
        pos_dict["hc_grade"] = hc_result.grade
        pos_dict["hc_score"] = hc_result.total_score
    else:
        pos_dict["hc_grade"] = ""
        pos_dict["hc_score"] = 0

    # ── Partial profit state initialisation ──────────────────────────
    atr_val = 0.0
    try:
        settings_obj2 = get_settings()
        provider_obj2 = get_provider(settings_obj2.data_provider)
        m5_hist = provider_obj2.get_intraday_history(s.symbol, "5m", 20)
        if m5_hist:
            from app.services.indicators import build_intraday
            m5_ind_tmp = build_intraday(m5_hist)
            atr_val = m5_ind_tmp.atr14
    except Exception:
        pass

    ppe.initialise_partial_state(pos_dict, entry, stop, atr_val)

    state["positions"].append(pos_dict)
    roll_day_if_needed(state)
    state["day"]["entries"] += 1
    return Position(**{k: v for k, v in pos_dict.items() if k in Position.model_fields})


def _maybe_enter(state: Dict, cfg: TradingConfig) -> List[Position]:
    opened: List[Position] = []
    if not cfg.auto_trading_enabled:
        return opened
    if not is_market_open():
        return opened
    roll_day_if_needed(state)
    if state["day"]["entries"] >= cfg.max_entries_per_day:
        return opened
    if len(state["positions"]) >= cfg.max_concurrent_positions:
        return opened
    # Within the last 10 min of session, don't open new trades.
    if minutes_to_close() <= 10.0:
        return opened

    # ── Profile params (risk level overrides) ───────────────────────────
    prof = _profile_params(cfg)
    skip_hc             = prof["skip_hc"]          # ACTIVE: bypass HC filter entirely
    hc_min_score        = prof["hc_min_score"]
    hc_mtf_min          = prof["hc_mtf_min"]
    hc_nifty_hard_block = prof["hc_nifty_hard_block"]
    prof_require_conf   = prof["require_confluence"]
    # ACTIVE: profile min (1) wins outright — user chose ACTIVE for light filtering.
    # Others: take the max so user/regime can tighten but not loosen below profile floor.
    if prof["override_conf"]:
        profile_min_conf = prof["profile_min_conf"]   # ACTIVE: 1 always
    else:
        profile_min_conf = max(cfg.min_confluence_count, prof["profile_min_conf"])

    # ── Market Regime gate ───────────────────────────────────────────────
    try:
        from app.services.market_regime import detect as detect_regime
        regime = detect_regime()
        if regime.block_new_longs:
            logger.info("_maybe_enter: %s regime — no new longs", regime.regime)
            return opened
        # Tighten confluence threshold based on regime recommendation;
        # but never loosen below the profile floor.
        effective_min_conf = max(profile_min_conf, regime.recommended_min_confluence)
    except Exception as exc:
        logger.debug("Regime check skipped: %s", exc)
        regime = None
        effective_min_conf = profile_min_conf

    try:
        suggestions = get_suggestions("intraday")
    except Exception as exc:  # noqa: BLE001
        logger.warning("trading: failed to pull intraday suggestions: %s", exc)
        return opened

    held = {p["symbol"] for p in state["positions"]}

    for s in suggestions.items:
        if len(state["positions"]) >= cfg.max_concurrent_positions:
            break
        if state["day"]["entries"] >= cfg.max_entries_per_day:
            break
        if s.symbol in held:
            continue
        if s.action != "BUY":
            continue

        # ── Event filter gate ─────────────────────────────────────────
        try:
            from app.services.event_filter import check as check_events
            ev = check_events(s.symbol)
            if ev.blocked:
                logger.info(
                    "%s skipped — event filter: %s",
                    s.symbol, "; ".join(ev.reasons[:2]),
                )
                continue
        except Exception as exc:
            logger.debug("Event filter skipped for %s: %s", s.symbol, exc)

        # ── Gate 1: composite score (always checked) ──────────────────
        if s.score.composite < cfg.min_composite_score:
            logger.debug(
                "%s skipped — composite %.1f < min %.1f",
                s.symbol, s.score.composite, cfg.min_composite_score,
            )
            continue

        # ── Gate 2: 9-strategy confluence (when use_algo_engine=True) ──
        algo_result: Optional[algo_engine.AlgoEngineResult] = None
        ltp = _current_price(s.symbol, s.entry)

        if cfg.use_algo_engine:
            algo_result = _run_algo_gate(s.symbol, ltp, cfg)

            if algo_result is None:
                # Engine errored — fall back to composite-score-only entry
                logger.info(
                    "%s algo gate returned None — entering on composite score only",
                    s.symbol,
                )
            elif algo_result.action != "BUY":
                logger.info(
                    "%s skipped — algo engine says %s (confluence=%d)",
                    s.symbol, algo_result.action, algo_result.strategy_confluence_count,
                )
                continue
            elif algo_result.strategy_confluence_count < effective_min_conf:
                logger.info(
                    "%s skipped — confluence %d < min %d (regime-adjusted)",
                    s.symbol,
                    algo_result.strategy_confluence_count,
                    effective_min_conf,
                )
                continue
            elif not algo_result.pre_trade_filters_passed:
                logger.info(
                    "%s skipped — pre-trade filters failed: %s",
                    s.symbol, algo_result.filter_failures,
                )
                continue
            else:
                logger.info(
                    "%s PASSED algo gate — action=%s confluence=%d strategies=%s",
                    s.symbol,
                    algo_result.action,
                    algo_result.strategy_confluence_count,
                    algo_result.strategies_triggered,
                )
        else:
            # Algo gate disabled — still run engine silently to get confluence
            # count for the HC filter (no action/threshold enforced here).
            try:
                algo_result = _run_algo_gate(s.symbol, ltp, cfg)
            except Exception:
                algo_result = None

        # ── Gate 3: High-Confidence Filter ───────────────────────────────
        # ACTIVE profile: skip entirely — composite score is sufficient.
        # BALANCED: run HC but Nifty bearish is a score penalty, not a hard block.
        # HIGH_CONFIDENCE: full strict gate.
        hc_result = None
        if skip_hc:
            logger.debug(
                "%s HC filter skipped — ACTIVE profile uses composite score only",
                s.symbol,
            )
        else:
            try:
                from app.services.high_confidence_filter import score as hc_score
                from app.services.candle_patterns import scan as cp_scan
                from app.services.multi_timeframe import check_mtf, check_nifty, check_sector

                # Build indicators for HC scoring
                settings_hc = get_settings()
                provider_hc = get_provider(settings_hc.data_provider)
                daily_hc = provider_hc.get_history(s.symbol, days=260)
                m5_hc    = provider_hc.get_intraday_history(s.symbol, "5m", 60)
                m15_hc   = provider_hc.get_intraday_history(s.symbol, "15m", 40)

                # Need at least daily candles + a few 5m bars for meaningful scoring.
                # Early session (<15m of data): m5_hc may have <3 bars — skip HC gate
                # in that case so the composite score alone drives entry.
                if daily_hc and m5_hc and len(m5_hc) >= 3:
                    daily_ind_hc = ind.build_daily(daily_hc)
                    m5_ind_hc    = ind.build_intraday(m5_hc)
                    m15_ind_hc   = ind.build_intraday(m15_hc) if m15_hc and len(m15_hc) >= 3 else m5_ind_hc

                    entry_price  = algo_result.entry_price if algo_result else s.entry
                    stop_price   = algo_result.stop_loss if algo_result else s.stop_loss
                    target_price = algo_result.target_1 if algo_result else s.target
                    ltp_hc       = _current_price(s.symbol, entry_price)

                    confluence_for_hc = (
                        algo_result.strategy_confluence_count if algo_result else 0
                    )

                    mtf = check_mtf(m5_ind_hc, m15_ind_hc, daily_ind_hc, ltp_hc)
                    nifty = check_nifty("BUY")
                    sector = check_sector(s.technical.change_pct, s.sector)
                    patterns = cp_scan(m5_hc[-5:])

                    hc_result = hc_score(
                        symbol=s.symbol,
                        confluence_count=confluence_for_hc,
                        mtf_score=mtf.score,
                        nifty_aligned=nifty.aligned,
                        nifty_ema_bullish=nifty.ema_bullish,
                        vol_ratio=m5_ind_hc.vol_ratio,
                        entry=entry_price,
                        stop_loss=stop_price,
                        target1=target_price,
                        candle_bullish_score=patterns.bullish_score,
                        candle_bearish_score=patterns.bearish_score,
                        # Profile-driven gate thresholds:
                        require_confluence=prof_require_conf,
                        entry_min_score=hc_min_score,
                        mtf_min=hc_mtf_min,
                        nifty_hard_block=hc_nifty_hard_block,
                    )

                    if not hc_result.should_enter:
                        logger.info(
                            "%s skipped — HC score %d [%s]: %s",
                            s.symbol, hc_result.total_score, hc_result.grade,
                            "; ".join(hc_result.blocking_reasons[:2]),
                        )
                        continue

                    logger.info(
                        "%s PASSED HC filter — grade=%s score=%d/100",
                        s.symbol, hc_result.grade, hc_result.total_score,
                    )
                else:
                    logger.debug(
                        "%s HC filter skipped — insufficient intraday data (%d 5m bars)",
                        s.symbol, len(m5_hc) if m5_hc else 0,
                    )

            except Exception as exc:
                logger.warning("HC filter failed for %s (%s) — proceeding without it", s.symbol, exc)

        pos = _open_position_from(state, s, cfg, algo_result, hc_result)
        if pos is not None:
            opened.append(pos)
            held.add(s.symbol)

    return opened


# ----------------------------------------------------------------- tick


def tick(reason: str = "auto") -> Tuple[List[Position], List[Trade]]:
    """Run one engine step: mark-to-market → partial profits → exits → entries."""
    state = load_state()
    roll_day_if_needed(state)
    cfg = TradingConfig(**state["config"])

    # 1. Update LTP and trailing stops for all open positions
    _mark_positions(state)

    # 2. Partial profit bookings and time-based stops (run BEFORE hard stop/target)
    partial = _run_partial_profits(state)

    # 3. Full exits: stop, target, EOD
    closed = _maybe_exit_all(state, cfg)
    closed = partial + closed

    # 4. New entries (only Grade A/A+ setups)
    opened = _maybe_enter(state, cfg)

    # 5. Re-mark after any entries
    _mark_positions(state)

    state["last_tick_at"] = datetime.now(timezone.utc).isoformat()
    state["last_tick_reason"] = reason
    save_state(state)
    return opened, closed


def flatten_all(reason: ExitReason = "MANUAL") -> List[Trade]:
    state = load_state()
    _mark_positions(state)
    closed: List[Trade] = []
    for pos in list(state["positions"]):
        closed.append(_close_position(state, pos, float(pos["last_price"]), reason))
    state["last_tick_at"] = datetime.now(timezone.utc).isoformat()
    state["last_tick_reason"] = f"flatten:{reason.lower()}"
    save_state(state)
    return closed


def close_one(symbol: str, reason: ExitReason = "MANUAL") -> Optional[Trade]:
    symbol = symbol.upper().strip()
    state = load_state()
    _mark_positions(state)
    pos = next((p for p in state["positions"] if p["symbol"] == symbol), None)
    if not pos:
        return None
    trade = _close_position(state, pos, float(pos["last_price"]), reason)
    state["last_tick_at"] = datetime.now(timezone.utc).isoformat()
    state["last_tick_reason"] = f"manual:{symbol}"
    save_state(state)
    return trade


# ----------------------------------------------------------------- views


def snapshot() -> PortfolioSnapshot:
    state = load_state()
    _mark_positions(state)  # read-side: fresh P&L without persisting

    cfg = TradingConfig(**state["config"])
    positions = [Position(**p) for p in state["positions"]]
    invested = sum(p.qty * p.last_price for p in positions)
    unrealized = sum(p.unrealized_pnl for p in positions)
    equity = float(state["cash"]) + invested
    roll_day_if_needed(state)

    return PortfolioSnapshot(
        starting_capital=cfg.starting_capital_inr,
        cash=round(float(state["cash"]), 2),
        invested=round(invested, 2),
        equity=round(equity, 2),
        realized_pnl_total=round(float(state["realized_pnl_total"]), 2),
        realized_pnl_today=round(float(state["day"]["realized_pnl"]), 2),
        unrealized_pnl=round(unrealized, 2),
        entries_today=int(state["day"]["entries"]),
        wins_today=int(state["day"]["wins"]),
        losses_today=int(state["day"]["losses"]),
        positions=positions,
        as_of=datetime.now(timezone.utc).isoformat(),
        market_open=is_market_open(),
        paper_trading=get_settings().paper_trading,
        auto_trading_enabled=cfg.auto_trading_enabled,
        data_provider=get_settings().data_provider,
        last_tick_at=state.get("last_tick_at"),
        last_tick_reason=state.get("last_tick_reason"),
    )
