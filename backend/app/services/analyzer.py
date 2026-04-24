"""Analyzer orchestrator.

Wires together the pieces:

  provider + universe  ->  analyzer_payload.build_payload
                             |
                             v
                   analyzer_prompts.render_user_prompt
                             |
                             v
                     claude_client.analyze(...)   ->  JSON string
                             |
                             v
                  json.loads + AnalyzerSignal validation
                             |
                             v
                       return AnalyzerSignal

Retry behaviour:
- On JSON parse or pydantic validation failure the orchestrator calls
  the client ONE more time with a correction message appended, then
  surfaces an error if that still fails.

Caching:
- Signals are cached per (symbol, provider, minute-bucket) for
  ``settings.analyzer_ttl_seconds`` to avoid re-querying Claude on rapid
  UI interactions. ``bust_cache=True`` in the request bypasses it.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.integrations.claude_client import ClaudeClient, get_claude_client
from app.models.analyzer import AnalyzerSignal, AnalyzeRequest
from app.services.analyzer_payload import build_payload
from app.services.analyzer_prompts import SYSTEM_PROMPT, render_user_prompt
from app.services.cache import cache
from app.services.data_provider import DataProvider, get_provider


log = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """Pull the first top-level JSON object out of the response text.

    Claude is instructed to return pure JSON, but defensive parsing keeps
    the pipeline robust against accidental markdown fences or leading
    commentary from a future prompt tweak.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model response")
    return text[start : end + 1]


def _validate(raw: str) -> AnalyzerSignal:
    text = _extract_json(raw)
    data = json.loads(text)
    return AnalyzerSignal.model_validate(data)


class AnalyzerError(RuntimeError):
    pass


def _cache_key(symbol: str, provider: str) -> str:
    bucket = int(time.time() // 30)  # 30s granularity
    return f"analyzer::{provider}::{symbol.upper()}::{bucket}"


def analyze(
    symbol: str,
    request: Optional[AnalyzeRequest] = None,
    *,
    settings: Optional[Settings] = None,
    provider: Optional[DataProvider] = None,
    client: Optional[ClaudeClient] = None,
) -> AnalyzerSignal:
    """Run the full analyzer pipeline and return a validated signal."""
    settings = settings or get_settings()
    provider = provider or get_provider(settings.data_provider)
    client = client or get_claude_client(settings)
    req = request or AnalyzeRequest()

    # ---- Cache lookup -------------------------------------------------
    cache_key = _cache_key(symbol, client.provider_name)
    if not req.bust_cache:
        hit = cache.get(cache_key)
        if hit:
            cached, _ = hit
            if isinstance(cached, AnalyzerSignal):
                cached.meta_cached = True
                return cached

    # ---- Build payload ------------------------------------------------
    payload = build_payload(symbol, provider, settings, req)
    user_prompt = render_user_prompt(payload.fill)

    # ---- Call Claude --------------------------------------------------
    started = time.time()
    try:
        raw = client.analyze(SYSTEM_PROMPT, user_prompt, payload.fill)
    except Exception as e:
        log.exception("Claude client call failed for %s", symbol)
        raise AnalyzerError(f"Claude client call failed: {e}") from e

    try:
        signal = _validate(raw)
    except (ValueError, json.JSONDecodeError, ValidationError) as first_err:
        log.warning(
            "First response failed validation for %s: %s. Retrying with correction.",
            symbol,
            first_err,
        )
        correction = (
            user_prompt
            + "\n\nYour previous response was not valid JSON matching the schema. "
            "Return ONLY the JSON object described above — no markdown fences, "
            "no prose. Start with { and end with }."
        )
        try:
            raw = client.analyze(SYSTEM_PROMPT, correction, payload.fill)
            signal = _validate(raw)
        except Exception as second_err:
            log.error("Retry also failed for %s: %s", symbol, second_err)
            raise AnalyzerError(
                f"Analyzer returned unparseable JSON twice: {second_err}"
            ) from second_err

    latency_ms = int((time.time() - started) * 1000)
    signal.meta_provider = client.provider_name
    signal.meta_model = client.model_name
    signal.meta_cached = False
    signal.meta_latency_ms = latency_ms

    cache.set(cache_key, signal, settings.analyzer_ttl_seconds)
    return signal
