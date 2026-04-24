"""Build and cache top-10 suggestion lists per horizon."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from app.config import get_settings
from app.data.universe import get_universe
from app.models.schemas import Suggestion, SuggestionList
from app.services.cache import cache
from app.services.data_provider import MockProvider, get_provider
from app.services.scoring import build_suggestion

logger = logging.getLogger(__name__)


def _build_suggestions(provider, horizon: str) -> tuple[list[Suggestion], list[tuple[str, str]]]:
    """Run scoring for every stock in the universe with the given provider.

    Returns (suggestions, failures).  All per-symbol exceptions are caught
    so one bad symbol never kills the whole response.
    """
    suggestions: list[Suggestion] = []
    failures: list[tuple[str, str]] = []
    for meta in get_universe():
        try:
            candles = provider.get_history(meta.symbol, days=260)
            if not candles:
                failures.append((meta.symbol, "no candles returned"))
                continue
            suggestions.append(build_suggestion(meta, candles, horizon))
        except Exception as exc:  # noqa: BLE001
            failures.append((meta.symbol, str(exc)[:200]))
            logger.warning("suggestion build failed for %s: %s", meta.symbol, exc)
    return suggestions, failures


def _rank_for(horizon: str, top_n: int = 10) -> tuple[list[Suggestion], str]:
    """Return (top_n suggestions, provider_name_used).

    Falls back to MockProvider automatically when:
      * The configured provider can't be instantiated (bad proxy, missing dep), OR
      * Every live-data call fails (expired token, rate-limit, network error).
    """
    settings = get_settings()
    configured = settings.data_provider

    # ── Step 1: try the configured provider ─────────────────────────────────
    provider = None
    try:
        provider = get_provider(configured)
    except Exception as exc:
        logger.warning("get_provider(%s) init failed — falling back to mock: %s", configured, exc)

    if provider is not None and configured != "mock":
        suggestions, failures = _build_suggestions(provider, horizon)
        if suggestions:
            if failures:
                logger.info(
                    "suggestions (%s) via %s: %d ok, %d skipped. First failures: %s",
                    horizon, configured, len(suggestions), len(failures), failures[:3],
                )
            _sort(suggestions, horizon)
            return suggestions[:top_n], configured

        # Every call failed — log and fall through to mock fallback.
        logger.warning(
            "suggestions (%s) via %s: ALL %d symbols failed — falling back to mock. "
            "First failures: %s",
            horizon, configured, len(failures), failures[:3],
        )

    # ── Step 2: mock fallback (always works, deterministic synthetic data) ──
    mock = MockProvider()
    suggestions, failures = _build_suggestions(mock, horizon)
    if not suggestions:
        raise RuntimeError(
            "No suggestions could be built even with MockProvider. "
            f"Sample failures: {failures[:3]}"
        )
    if failures:
        logger.info(
            "suggestions (%s) via mock fallback: %d ok, %d skipped.",
            horizon, len(suggestions), len(failures),
        )
    _sort(suggestions, horizon)
    return suggestions[:top_n], "mock (fallback)"


def _sort(suggestions: list[Suggestion], horizon: str) -> None:
    """Sort in-place: intraday by strongest signal, longterm by quality."""
    if horizon == "intraday":
        suggestions.sort(key=lambda s: abs(s.score.composite - 50), reverse=True)
    else:
        suggestions.sort(key=lambda s: s.score.composite, reverse=True)


def get_suggestions(horizon: str, bust_cache: bool = False) -> SuggestionList:
    settings = get_settings()
    cache_key = f"suggestions::{horizon}"
    if bust_cache:
        # Also drop cached provider candles so the rebuild uses fresh data.
        for k in list(getattr(cache, "_store", {}).keys()):
            if k.startswith("upstox:history:") or k.startswith("upstox:ltp:"):
                cache._store.pop(k, None)
    else:
        hit = cache.get(cache_key)
        if hit:
            payload, _expires_at = hit
            return payload

    items, provider_used = _rank_for(horizon)
    now = datetime.now(timezone.utc)
    expires_at = cache.set(cache_key, None, settings.suggestions_ttl_seconds)
    next_refresh = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    payload = SuggestionList(
        horizon=horizon,  # type: ignore[arg-type]
        generated_at=now.isoformat(),
        next_refresh_at=next_refresh.isoformat(),
        ttl_seconds=settings.suggestions_ttl_seconds,
        items=items,
        data_provider=provider_used,
    )
    cache.set(cache_key, payload, settings.suggestions_ttl_seconds)
    return payload
