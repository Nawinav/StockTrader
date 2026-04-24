"""Build and cache top-10 suggestion lists per horizon."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from app.config import get_settings
from app.data.universe import get_universe
from app.models.schemas import Suggestion, SuggestionList
from app.services.cache import cache
from app.services.data_provider import get_provider
from app.services.scoring import build_suggestion

logger = logging.getLogger(__name__)


def _rank_for(horizon: str, top_n: int = 10) -> List[Suggestion]:
    settings = get_settings()
    provider = get_provider(settings.data_provider)
    suggestions: List[Suggestion] = []
    failures: list[tuple[str, str]] = []
    for meta in get_universe():
        try:
            candles = provider.get_history(meta.symbol, days=260)
            if not candles:
                failures.append((meta.symbol, "no candles returned"))
                continue
            suggestions.append(build_suggestion(meta, candles, horizon))
        except Exception as exc:
            # One bad symbol (stale ISIN, delisted, rate-limited, etc.)
            # must not take down the whole dashboard. Log and skip.
            failures.append((meta.symbol, str(exc)[:200]))
            logger.warning("suggestion build failed for %s: %s", meta.symbol, exc)
    if failures:
        logger.info(
            "suggestions (%s): %d ok, %d skipped. First failures: %s",
            horizon, len(suggestions), len(failures), failures[:5],
        )
    if not suggestions:
        # Surface a clear error instead of returning an empty list, so the
        # frontend can show a real message.
        raise RuntimeError(
            "No suggestions could be built — every provider call failed. "
            f"Sample failures: {failures[:3]}"
        )
    # For intraday we want the strongest directional signals (BUY or SELL),
    # so rank by |composite - 50|. For long-term we care about absolute
    # composite score (quality).
    if horizon == "intraday":
        suggestions.sort(key=lambda s: abs(s.score.composite - 50), reverse=True)
    else:
        suggestions.sort(key=lambda s: s.score.composite, reverse=True)
    return suggestions[:top_n]


def get_suggestions(horizon: str, bust_cache: bool = False) -> SuggestionList:
    settings = get_settings()
    cache_key = f"suggestions::{horizon}"
    if bust_cache:
        # Also drop cached provider candles so the rebuild truly uses fresh data.
        for k in list(getattr(cache, "_store", {}).keys()):
            if k.startswith("upstox:history:") or k.startswith("upstox:ltp:"):
                cache._store.pop(k, None)
    else:
        hit = cache.get(cache_key)
        if hit:
            payload, expires_at = hit
            return payload

    items = _rank_for(horizon)
    now = datetime.now(timezone.utc)
    expires_at = cache.set(cache_key, None, settings.suggestions_ttl_seconds)
    next_refresh = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    payload = SuggestionList(
        horizon=horizon,  # type: ignore[arg-type]
        generated_at=now.isoformat(),
        next_refresh_at=next_refresh.isoformat(),
        ttl_seconds=settings.suggestions_ttl_seconds,
        items=items,
        data_provider=settings.data_provider,
    )
    cache.set(cache_key, payload, settings.suggestions_ttl_seconds)
    return payload
