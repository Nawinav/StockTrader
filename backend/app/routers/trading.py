"""REST endpoints for the paper-trading engine.

Everything under ``/api/trading``. No real orders are ever placed —
``settings.paper_trading`` must stay True; if it's ever flipped to False
every mutating endpoint refuses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.models.trading import (
    ManualCloseResponse,
    PortfolioSnapshot,
    TickResponse,
    ToggleAutoRequest,
    Trade,
    TradeLog,
    TradingConfig,
)
from app.services import trading_engine as engine
from app.services.trading_store import get_config, reset_all, set_config

router = APIRouter(prefix="/api/trading", tags=["trading"])


def _require_paper() -> None:
    if not get_settings().paper_trading:
        raise HTTPException(
            503,
            "Trading endpoints are paper-only for this build. "
            "Set PAPER_TRADING=true to re-enable.",
        )


# ---------------------------------------------------------------- reads


@router.get("/state", response_model=PortfolioSnapshot)
def state() -> PortfolioSnapshot:
    return engine.snapshot()


@router.get("/positions")
def positions() -> dict:
    snap = engine.snapshot()
    return {"items": [p.model_dump() for p in snap.positions], "as_of": snap.as_of}


@router.get("/trades", response_model=TradeLog)
def trades(limit: int = Query(default=50, ge=1, le=500)) -> TradeLog:
    from app.services.trading_store import load_state
    state = load_state()
    items: List[Trade] = [Trade(**t) for t in state["trades"][:limit]]
    return TradeLog(items=items)


@router.get("/config", response_model=TradingConfig)
def config() -> TradingConfig:
    return get_config()


# ---------------------------------------------------------------- writes


@router.post("/config", response_model=TradingConfig)
def update_config(cfg: TradingConfig) -> TradingConfig:
    _require_paper()
    return set_config(cfg)


@router.post("/auto", response_model=TradingConfig)
def toggle_auto(req: ToggleAutoRequest) -> TradingConfig:
    _require_paper()
    current = get_config()
    current.auto_trading_enabled = req.enabled
    return set_config(current)


@router.post("/tick", response_model=TickResponse)
def run_tick() -> TickResponse:
    _require_paper()
    opened, closed = engine.tick(reason="manual")
    reasons = [f"OPEN {p.symbol} qty={p.qty} @ {p.entry_price}" for p in opened]
    reasons += [
        f"CLOSE {t.symbol} @ {t.exit_price} ({t.reason}, pnl={t.realized_pnl:+.2f})"
        for t in closed
    ]
    return TickResponse(opened=len(opened), closed=len(closed), reasons=reasons)


@router.post("/flatten", response_model=TickResponse)
def flatten() -> TickResponse:
    _require_paper()
    closed = engine.flatten_all(reason="MANUAL")
    reasons = [
        f"FLAT {t.symbol} @ {t.exit_price} (pnl={t.realized_pnl:+.2f})" for t in closed
    ]
    return TickResponse(opened=0, closed=len(closed), reasons=reasons)


@router.post("/positions/{symbol}/close", response_model=ManualCloseResponse)
def close_one(symbol: str) -> ManualCloseResponse:
    _require_paper()
    trade = engine.close_one(symbol, reason="MANUAL")
    if not trade:
        raise HTTPException(404, f"No open position for {symbol}")
    return ManualCloseResponse(trade=trade)


@router.post("/reset")
def reset() -> dict:
    _require_paper()
    reset_all()
    return {"ok": True, "state": engine.snapshot().model_dump()}


# ---------------------------------------------------------------- debug


@router.get("/why")
def why_no_trades() -> Dict[str, Any]:
    """Debug endpoint — explains exactly why no trades are being opened.

    Runs the complete ``_maybe_enter`` logic for every BUY suggestion but
    does **not** open any positions. Returns a structured report:

    * ``pre_conditions`` — market open, auto enabled, capacity checks.
    * ``regime`` — current Nifty regime + any blocking.
    * ``suggestions_total`` — how many intraday BUY suggestions exist.
    * ``stocks`` — per-symbol gate-by-gate pass/fail breakdown.
    """
    from app.services import algo_engine, indicators as ind
    from app.services.data_provider import get_provider, ist_now, session_bounds
    from app.services.suggestions import get_suggestions
    from app.services.trading_store import load_state, roll_day_if_needed
    from app.services.trading_engine import _profile_params, _PROFILES

    settings = get_settings()
    cfg = get_config()
    state = load_state()
    roll_day_if_needed(state)
    now = ist_now()

    # ── Profile overrides ─────────────────────────────────────────────────
    prof = _profile_params(cfg)
    skip_hc             = prof["skip_hc"]
    hc_min_score        = prof["hc_min_score"]
    hc_mtf_min          = prof["hc_mtf_min"]
    hc_nifty_hard_block = prof["hc_nifty_hard_block"]
    prof_require_conf   = prof["require_confluence"]
    if prof["override_conf"]:
        profile_min_conf = prof["profile_min_conf"]   # ACTIVE: 1 always
    else:
        profile_min_conf = max(cfg.min_confluence_count, prof["profile_min_conf"])

    # ── Pre-condition checks ──────────────────────────────────────────────
    def _market_open() -> bool:
        if now.weekday() >= 5:
            return False
        start, end = session_bounds(now)
        return start <= now < end

    def _minutes_to_close() -> float:
        _, end = session_bounds(now)
        return (end - now).total_seconds() / 60.0

    market_open      = _market_open()
    auto_enabled     = cfg.auto_trading_enabled
    entries_today    = int(state["day"]["entries"])
    max_entries      = cfg.max_entries_per_day
    open_positions   = len(state["positions"])
    max_positions    = cfg.max_concurrent_positions
    mins_left        = _minutes_to_close() if market_open else None
    eod_block        = market_open and mins_left is not None and mins_left <= 10.0

    pre_conditions: Dict[str, Any] = {
        "market_open":        market_open,
        "auto_trading":       auto_enabled,
        "entries_today":      entries_today,
        "max_entries_per_day": max_entries,
        "entries_capacity_ok": entries_today < max_entries,
        "open_positions":     open_positions,
        "max_positions":      max_positions,
        "positions_capacity_ok": open_positions < max_positions,
        "minutes_to_close":   round(mins_left, 1) if mins_left is not None else None,
        "eod_block":          eod_block,
    }

    blocking_pre = []
    if not market_open:
        blocking_pre.append("Market is closed")
    if not auto_enabled:
        blocking_pre.append("auto_trading_enabled = false")
    if entries_today >= max_entries:
        blocking_pre.append(f"Max entries reached ({entries_today}/{max_entries})")
    if open_positions >= max_positions:
        blocking_pre.append(f"Max positions reached ({open_positions}/{max_positions})")
    if eod_block:
        blocking_pre.append(f"EOD block — only {mins_left:.1f} min left")

    pre_conditions["blocking_reasons"] = blocking_pre
    pre_conditions["would_run"] = len(blocking_pre) == 0

    # ── Market regime ────────────────────────────────────────────────────
    regime_info: Dict[str, Any] = {"available": False}
    effective_min_conf = profile_min_conf
    try:
        from app.services.market_regime import detect as detect_regime
        regime = detect_regime()
        effective_min_conf = max(profile_min_conf, regime.recommended_min_confluence)
        regime_info = {
            "available":          True,
            "regime":             regime.regime,
            "label":              regime.label,
            "nifty_ltp":          regime.nifty_ltp,
            "nifty_change_pct":   regime.nifty_change_pct,
            "adx":                regime.adx,
            "vix":                regime.vix,
            "block_new_longs":    regime.block_new_longs,
            "recommended_min_confluence": regime.recommended_min_confluence,
            "effective_min_confluence":  effective_min_conf,
            "disabled_strategies": list(regime.disabled_strategies),
        }
        if regime.block_new_longs:
            blocking_pre.append(f"Regime {regime.regime} blocks new longs")
            pre_conditions["would_run"] = False
    except Exception as exc:
        regime_info["error"] = str(exc)

    # ── Suggestions ──────────────────────────────────────────────────────
    suggestions_info: Dict[str, Any] = {"total": 0, "buy_count": 0, "error": None}
    suggestions = []
    try:
        result = get_suggestions("intraday")
        suggestions = result.items
        buy_sug = [s for s in suggestions if s.action == "BUY"]
        suggestions_info["total"]     = len(suggestions)
        suggestions_info["buy_count"] = len(buy_sug)
        suggestions_info["min_composite_score"] = cfg.min_composite_score
        passing_score = [s for s in buy_sug if s.score.composite >= cfg.min_composite_score]
        suggestions_info["passing_score_gate"] = len(passing_score)
    except Exception as exc:
        suggestions_info["error"] = str(exc)

    # ── Per-stock analysis ───────────────────────────────────────────────
    held = {p["symbol"] for p in state["positions"]}
    stocks: List[Dict[str, Any]] = []

    provider = get_provider(settings.data_provider)

    for s in suggestions:
        if s.action != "BUY":
            continue

        stock: Dict[str, Any] = {
            "symbol":          s.symbol,
            "name":            s.name,
            "action":          s.action,
            "composite_score": float(s.score.composite),
            "gates":           [],
            "verdict":         "PASS",
            "block_reason":    None,
        }

        def _gate(name: str, passed: bool, detail: str) -> bool:
            stock["gates"].append({"gate": name, "passed": passed, "detail": detail})
            if not passed:
                stock["verdict"]      = "BLOCK"
                stock["block_reason"] = stock["block_reason"] or f"{name}: {detail}"
            return passed

        # Gate 0: already held
        if not _gate("Already held", s.symbol not in held,
                     "Symbol already in open positions" if s.symbol in held else "Not currently held"):
            stocks.append(stock)
            continue

        # Gate 0b: event filter
        try:
            from app.services.event_filter import check as check_events
            ev = check_events(s.symbol)
            if not _gate("Event filter", not ev.blocked,
                         "; ".join(ev.reasons[:2]) if ev.blocked else "No upcoming events"):
                stocks.append(stock)
                continue
        except Exception as exc:
            stock["gates"].append({"gate": "Event filter", "passed": True, "detail": f"Skipped ({exc})"})

        # Gate 1: composite score
        score_ok = s.score.composite >= cfg.min_composite_score
        if not _gate("Composite score",
                     score_ok,
                     f"{s.score.composite:.1f} {'≥' if score_ok else '<'} min {cfg.min_composite_score}"):
            stocks.append(stock)
            continue

        # Gate 2: algo engine
        ltp = float(s.entry)
        try:
            ltp = float(provider.get_quote(s.symbol).close or s.entry)
        except Exception:
            pass

        algo_result: Optional[algo_engine.AlgoEngineResult] = None
        try:
            algo_result = engine._run_algo_gate(s.symbol, ltp, cfg)
        except Exception as exc:
            stock["gates"].append({"gate": "Algo engine (run)", "passed": True,
                                   "detail": f"Error (treating as None): {exc}"})

        algo_info: Dict[str, Any] = {
            "ran": algo_result is not None,
            "action":     algo_result.action if algo_result else None,
            "confluence": algo_result.strategy_confluence_count if algo_result else None,
            "strategies": algo_result.strategies_triggered if algo_result else [],
            "pre_trade_filters_passed": algo_result.pre_trade_filters_passed if algo_result else None,
            "filter_failures": algo_result.filter_failures if algo_result else [],
            "entry_price":  algo_result.entry_price if algo_result else None,
            "stop_loss":    algo_result.stop_loss if algo_result else None,
            "target_1":     algo_result.target_1 if algo_result else None,
        }
        stock["algo"] = algo_info

        if cfg.use_algo_engine:
            if algo_result is None:
                _gate("Algo engine (action)", True, "None — falling back to composite score")
            elif algo_result.action != "BUY":
                if not _gate("Algo engine (action)", False,
                             f"Action={algo_result.action} (need BUY)"):
                    stocks.append(stock)
                    continue
            elif algo_result.strategy_confluence_count < effective_min_conf:
                if not _gate("Algo engine (confluence)", False,
                             f"{algo_result.strategy_confluence_count} < min {effective_min_conf} (regime-adjusted)"):
                    stocks.append(stock)
                    continue
            elif not algo_result.pre_trade_filters_passed:
                if not _gate("Algo engine (pre-trade filters)", False,
                             "; ".join(algo_result.filter_failures[:3])):
                    stocks.append(stock)
                    continue
            else:
                _gate("Algo engine", True,
                      f"BUY, confluence={algo_result.strategy_confluence_count}, strategies={algo_result.strategies_triggered}")
        else:
            _gate("Algo engine", True,
                  f"Disabled — silent run: confluence={algo_result.strategy_confluence_count if algo_result else 'N/A'}")

        # Gate 3: HC filter
        hc_info: Dict[str, Any] = {"ran": False}
        if skip_hc:
            # ACTIVE profile — bypass HC, composite score is the only gate
            hc_info["skipped"] = True
            hc_info["reason"]  = "ACTIVE profile: HC filter bypassed — composite score only"
            _gate("HC filter", True, "⚡ ACTIVE profile — HC bypassed, composite score only")
        else:
            try:
                from app.services.high_confidence_filter import score as hc_score
                from app.services.candle_patterns import scan as cp_scan
                from app.services.multi_timeframe import check_mtf, check_nifty, check_sector

                daily_hc = provider.get_history(s.symbol, days=260)
                m5_hc    = provider.get_intraday_history(s.symbol, "5m", 60)
                m15_hc   = provider.get_intraday_history(s.symbol, "15m", 40)

                hc_info["daily_bars"] = len(daily_hc) if daily_hc else 0
                hc_info["m5_bars"]    = len(m5_hc) if m5_hc else 0
                hc_info["m15_bars"]   = len(m15_hc) if m15_hc else 0

                if daily_hc and m5_hc and len(m5_hc) >= 3:
                    hc_info["ran"] = True
                    daily_ind_hc = ind.build_daily(daily_hc)
                    m5_ind_hc    = ind.build_intraday(m5_hc)
                    m15_ind_hc   = ind.build_intraday(m15_hc) if m15_hc and len(m15_hc) >= 3 else m5_ind_hc

                    entry_price  = algo_result.entry_price if algo_result else s.entry
                    stop_price   = algo_result.stop_loss   if algo_result else s.stop_loss
                    target_price = algo_result.target_1    if algo_result else s.target
                    confluence_for_hc = algo_result.strategy_confluence_count if algo_result else 0

                    mtf     = check_mtf(m5_ind_hc, m15_ind_hc, daily_ind_hc, ltp)
                    nifty   = check_nifty("BUY")
                    sector  = check_sector(s.technical.change_pct, s.sector)
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
                        require_confluence=prof_require_conf,
                        entry_min_score=hc_min_score,
                        mtf_min=hc_mtf_min,
                        nifty_hard_block=hc_nifty_hard_block,
                    )

                    hc_info["total_score"]       = hc_result.total_score
                    hc_info["grade"]             = hc_result.grade
                    hc_info["should_enter"]       = hc_result.should_enter
                    hc_info["blocking_reasons"]  = hc_result.blocking_reasons
                    hc_info["mtf_score"]         = mtf.score
                    hc_info["nifty_aligned"]     = nifty.aligned
                    hc_info["nifty_ema_bullish"] = nifty.ema_bullish
                    hc_info["nifty_hard_block"]  = hc_nifty_hard_block
                    hc_info["vol_ratio"]         = round(m5_ind_hc.vol_ratio, 2)
                    hc_info["candle_bullish"]    = patterns.bullish_score
                    hc_info["candle_bearish"]    = patterns.bearish_score
                    hc_info["dimensions"]        = [
                        {"name": d.name, "score": d.score, "max": d.max_score, "detail": d.detail}
                        for d in hc_result.dimensions
                    ]

                    if not _gate("HC filter",
                                 hc_result.should_enter,
                                 f"Grade {hc_result.grade} ({hc_result.total_score}/100) — " +
                                 ("; ".join(hc_result.blocking_reasons[:2]) if hc_result.blocking_reasons
                                  else f"score {hc_result.total_score} below min {hc_min_score}")):
                        stock["hc"] = hc_info
                        stocks.append(stock)
                        continue
                    else:
                        _gate("HC filter", True,
                              f"Grade {hc_result.grade} ({hc_result.total_score}/100) — PASS")
                else:
                    hc_info["ran"]    = False
                    hc_info["reason"] = f"Insufficient intraday data ({hc_info['m5_bars']} 5m bars, need ≥3)"
                    _gate("HC filter", True, hc_info["reason"] + " — skipped (not blocking)")

            except Exception as exc:
                hc_info["error"] = str(exc)
                _gate("HC filter", True, f"Error — skipped: {exc}")

        stock["hc"] = hc_info

        # Gate 4: position sizing
        equity = float(state["cash"]) + sum(
            float(p.get("last_price", p["entry_price"])) * int(p["qty"])
            for p in state["positions"]
        )
        entry_p = (algo_result.entry_price if algo_result else s.entry) or ltp
        stop_p  = (algo_result.stop_loss   if algo_result else s.stop_loss) or (entry_p * 0.97)
        from app.services.trading_engine import _size_position
        qty, risk_inr = _size_position(entry_p, stop_p, equity, float(state["cash"]), cfg)
        size_ok = qty > 0 and (qty * entry_p) <= float(state["cash"])
        _gate("Position sizing",
              size_ok,
              f"qty={qty}, notional=₹{qty*entry_p:,.0f}, cash=₹{state['cash']:,.0f}" if size_ok
              else f"qty={qty} (entry={entry_p:.2f} stop={stop_p:.2f} cash=₹{state['cash']:,.0f})")

        stocks.append(stock)

    # ── Summary ──────────────────────────────────────────────────────────
    passing = [s for s in stocks if s["verdict"] == "PASS"]
    blocked = [s for s in stocks if s["verdict"] == "BLOCK"]
    block_summary: Dict[str, int] = {}
    for s in blocked:
        key = (s.get("block_reason") or "Unknown").split(":")[0].strip()
        block_summary[key] = block_summary.get(key, 0) + 1

    return {
        "as_of":            now.isoformat(),
        "pre_conditions":   pre_conditions,
        "regime":           regime_info,
        "suggestions":      suggestions_info,
        "config": {
            "trading_profile":       cfg.trading_profile,
            "profile_label":         _PROFILES.get(cfg.trading_profile, {}).get("label", cfg.trading_profile),
            "hc_filter_active":      not skip_hc,
            "hc_nifty_hard_block":   hc_nifty_hard_block,
            "hc_min_score":          hc_min_score,
            "hc_mtf_min":            hc_mtf_min,
            "use_algo_engine":       cfg.use_algo_engine,
            "min_composite_score":   cfg.min_composite_score,
            "min_confluence_count":  cfg.min_confluence_count,
            "effective_min_confluence": effective_min_conf,
            "max_entries_per_day":   cfg.max_entries_per_day,
            "max_concurrent_positions": cfg.max_concurrent_positions,
            "risk_pct_per_trade":    cfg.risk_pct_per_trade,
        },
        "summary": {
            "stocks_analysed":  len(stocks),
            "would_enter":      len(passing),
            "blocked":          len(blocked),
            "block_breakdown":  block_summary,
        },
        "stocks": stocks,
    }
