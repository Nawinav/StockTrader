"""Suggestion endpoints."""
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import SuggestionList
from app.services.suggestions import get_suggestions

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


@router.get("/intraday", response_model=SuggestionList)
def intraday(refresh: bool = Query(default=False)) -> SuggestionList:
    return get_suggestions("intraday", bust_cache=refresh)


@router.get("/longterm", response_model=SuggestionList)
def longterm(refresh: bool = Query(default=False)) -> SuggestionList:
    return get_suggestions("longterm", bust_cache=refresh)


@router.get("/{horizon}", response_model=SuggestionList)
def by_horizon(horizon: str, refresh: bool = Query(default=False)) -> SuggestionList:
    if horizon not in ("intraday", "longterm"):
        raise HTTPException(400, "horizon must be 'intraday' or 'longterm'")
    return get_suggestions(horizon, bust_cache=refresh)
