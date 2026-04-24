"""Watchlist persistence — JSON file for MVP.

For production, replace with a real DB (Postgres on Render, Supabase,
Mongo). Keep the surface area small so the swap is trivial.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import List

from app.config import get_settings
from app.data.universe import get_by_symbol
from app.models.schemas import WatchlistItem


_lock = threading.Lock()


def _path() -> str:
    return get_settings().watchlist_path


def _read_all() -> List[dict]:
    path = _path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _write_all(items: List[dict]) -> None:
    path = _path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def list_items() -> List[WatchlistItem]:
    with _lock:
        return [WatchlistItem(**i) for i in _read_all()]


def add_item(symbol: str, note: str | None = None) -> WatchlistItem:
    symbol = symbol.upper().strip()
    if not get_by_symbol(symbol):
        raise ValueError(f"Unknown symbol: {symbol}")
    with _lock:
        items = _read_all()
        if any(i["symbol"] == symbol for i in items):
            raise ValueError(f"{symbol} already in watchlist")
        payload = {
            "symbol": symbol,
            "note": note,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        items.append(payload)
        _write_all(items)
        return WatchlistItem(**payload)


def remove_item(symbol: str) -> bool:
    symbol = symbol.upper().strip()
    with _lock:
        items = _read_all()
        new_items = [i for i in items if i["symbol"] != symbol]
        if len(new_items) == len(items):
            return False
        _write_all(new_items)
        return True
