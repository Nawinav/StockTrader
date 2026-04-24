"""Watchlist endpoints."""
from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    AddWatchlistRequest,
    WatchlistItem,
    WatchlistResponse,
)
from app.services import watchlist as wl_service

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=WatchlistResponse)
def list_watchlist() -> WatchlistResponse:
    return WatchlistResponse(items=wl_service.list_items())


@router.post("", response_model=WatchlistItem, status_code=201)
def add_to_watchlist(payload: AddWatchlistRequest) -> WatchlistItem:
    try:
        return wl_service.add_item(payload.symbol, payload.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{symbol}", status_code=204)
def remove_from_watchlist(symbol: str) -> None:
    removed = wl_service.remove_item(symbol)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
    return None
