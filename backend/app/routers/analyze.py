"""Analyzer endpoint — intraday Claude-powered signal.

POST /api/analyze/{symbol}
    body: AnalyzeRequest (optional) — override position / account / bust_cache
    returns: AnalyzerSignal

GET  /api/analyze/{symbol}
    Convenience form with no body (uses defaults). Handy for curl / browser.
"""
from fastapi import APIRouter, HTTPException

from app.data.universe import get_by_symbol
from app.models.analyzer import AnalyzerSignal, AnalyzeRequest
from app.services.analyzer import AnalyzerError, analyze


router = APIRouter(prefix="/api/analyze", tags=["analyzer"])


def _check_symbol(symbol: str) -> str:
    s = symbol.upper()
    if get_by_symbol(s) is None:
        raise HTTPException(404, f"Unknown symbol: {s}")
    return s


@router.get("/{symbol}", response_model=AnalyzerSignal)
def analyze_get(symbol: str) -> AnalyzerSignal:
    s = _check_symbol(symbol)
    try:
        return analyze(s, None)
    except AnalyzerError as e:
        raise HTTPException(502, f"Analyzer error: {e}")


@router.post("/{symbol}", response_model=AnalyzerSignal)
def analyze_post(symbol: str, body: AnalyzeRequest | None = None) -> AnalyzerSignal:
    s = _check_symbol(symbol)
    try:
        return analyze(s, body)
    except AnalyzerError as e:
        raise HTTPException(502, f"Analyzer error: {e}")
