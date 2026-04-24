"""Suggestion endpoints."""
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import SuggestionList
from app.services.suggestions import get_suggestions

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


def _safe_get(horizon: str, bust_cache: bool) -> SuggestionList:
    try:
        return get_suggestions(horizon, bust_cache=bust_cache)
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, detail=f"Suggestion engine error: {exc}") from exc


@router.get("/intraday", response_model=SuggestionList)
def intraday(refresh: bool = Query(default=False)) -> SuggestionList:
    return _safe_get("intraday", bust_cache=refresh)


@router.get("/longterm", response_model=SuggestionList)
def longterm(refresh: bool = Query(default=False)) -> SuggestionList:
    return _safe_get("longterm", bust_cache=refresh)


@router.get("/{horizon}", response_model=SuggestionList)
def by_horizon(horizon: str, refresh: bool = Query(default=False)) -> SuggestionList:
    if horizon not in ("intraday", "longterm"):
        raise HTTPException(400, "horizon must be 'intraday' or 'longterm'")
    return _safe_get(horizon, bust_cache=refresh)
