"""JSON-file persistence for the paper-trading engine.

Holds everything the engine needs to survive a backend restart:
  * open positions
  * closed trade log
  * per-day counters (entries, wins/losses)
  * realised P&L to date
  * current ``TradingConfig``

For MVP this is a dict round-tripped to ``trading_state.json``. Swap for
a real DB when multi-process or multi-user is needed.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config import get_settings
from app.models.trading import Position, Trade, TradingConfig


_LOCK = threading.RLock()
_FILENAME = "trading_state.json"


def _path() -> str:
    # Keep next to watchlist.json. Settings doesn't expose a field so we
    # colocate in the same working directory as the backend.
    base = os.path.dirname(get_settings().watchlist_path) or "."
    return os.path.join(base, _FILENAME)


def _empty_state() -> Dict[str, Any]:
    cfg = TradingConfig().model_dump()
    return {
        "config": cfg,
        "cash": cfg["starting_capital_inr"],
        "realized_pnl_total": 0.0,
        "positions": [],      # list[Position dict]
        "trades": [],         # list[Trade dict] (closed)
        "day": {
            "date": "",
            "realized_pnl": 0.0,
            "entries": 0,
            "wins": 0,
            "losses": 0,
        },
        "last_tick_at": None,
        "last_tick_reason": None,
    }


def _read() -> Dict[str, Any]:
    path = _path()
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_state()
    # Back-fill any missing keys so older files keep working.
    base = _empty_state()
    for k, v in base.items():
        data.setdefault(k, v)
    # Config sub-keys: patch missing fields (e.g. when new settings are added).
    base_cfg = base["config"]
    for k, v in base_cfg.items():
        data["config"].setdefault(k, v)
    return data


def _write(state: Dict[str, Any]) -> None:
    path = _path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, path)


# ---------------------------------------------------------------- public API

def load_state() -> Dict[str, Any]:
    with _LOCK:
        return _read()


def save_state(state: Dict[str, Any]) -> None:
    with _LOCK:
        _write(state)


def get_config() -> TradingConfig:
    with _LOCK:
        return TradingConfig(**_read()["config"])


def set_config(cfg: TradingConfig) -> TradingConfig:
    with _LOCK:
        state = _read()
        old_capital = float(state["config"].get("starting_capital_inr", 0))
        state["config"] = cfg.model_dump()
        # If the user raised starting capital and there are no positions yet
        # (or it's never been traded), push the cash up too so the change is
        # visible immediately.
        if (
            not state["positions"]
            and state["realized_pnl_total"] == 0
            and cfg.starting_capital_inr != old_capital
        ):
            state["cash"] = cfg.starting_capital_inr
        _write(state)
        return cfg


def today_key_ist() -> str:
    # IST = UTC+5:30; compute using timezone-aware UTC then shift.
    from datetime import timedelta
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d")


def roll_day_if_needed(state: Dict[str, Any]) -> None:
    today = today_key_ist()
    if state["day"]["date"] != today:
        state["day"] = {
            "date": today,
            "realized_pnl": 0.0,
            "entries": 0,
            "wins": 0,
            "losses": 0,
        }


def positions_as_models(state: Dict[str, Any]) -> List[Position]:
    return [Position(**p) for p in state["positions"]]


def trades_as_models(state: Dict[str, Any]) -> List[Trade]:
    return [Trade(**t) for t in state["trades"]]


def reset_all() -> Dict[str, Any]:
    """Wipe state back to defaults (but keep the current config)."""
    with _LOCK:
        existing = _read()
        cfg = existing["config"]
        fresh = _empty_state()
        fresh["config"] = cfg
        fresh["cash"] = cfg["starting_capital_inr"]
        _write(fresh)
        return fresh
