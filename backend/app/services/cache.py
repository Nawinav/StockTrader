"""Simple in-process TTL cache for suggestion lists."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self) -> None:
        self._store: Dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Tuple[Any, float]]:
        """Return (value, expires_at) if fresh, else None."""
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry.expires_at <= time.time():
                del self._store[key]
                return None
            return entry.value, entry.expires_at

    def set(self, key: str, value: Any, ttl_seconds: int) -> float:
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._store[key] = _Entry(value=value, expires_at=expires_at)
        return expires_at

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


cache = TTLCache()
