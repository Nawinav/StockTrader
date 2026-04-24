"""Claude client abstraction for the intraday analyzer.

Two implementations share a single Protocol:

* ``StubClaudeClient`` — deterministic in-process response. Uses the
  actual payload (price, VWAP, EMA stack, ATR, ADX, etc.) to produce a
  *reasonable* signal so end-to-end tests exercise the JSON schema and
  the UI can be developed without API spend. NOT a trading model — it
  is a pipeline verifier.
* ``AnthropicClaudeClient`` — real API call using the ``anthropic`` SDK.
  Low temperature, strict "JSON only" reinforcement in the system
  message. Imports the SDK lazily so the stub works on machines where
  ``anthropic`` isn't installed.

Factory: ``get_claude_client(settings)`` picks between them based on
``settings.analyzer_provider``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Protocol

from app.config import Settings
from app.services.data_provider import ist_now


# ---------------------------------------------------------------------- protocol

class ClaudeClient(Protocol):
    provider_name: str
    model_name: str

    def analyze(self, system_prompt: str, user_prompt: str, payload_fill: Dict[str, Any]) -> str:
        """Return a JSON *string* matching the analyzer output schema.

        The orchestrator is responsible for parsing and validating it.
        """
        ...


# ---------------------------------------------------------------------- stub

class StubClaudeClient:
    """Deterministic analyzer stub — no API cost, no network.

    Produces an ``AnalyzerSignal`` JSON string derived from the payload.
    The logic is intentionally simple: it reads VWAP, EMA alignment, RSI
    and ADX from the supplied fill dict and composes a BUY / SELL / HOLD
    recommendation that is consistent with them. Use this for:

    - Developing the frontend without API spend
    - Running integration tests on the FastAPI endpoint
    - Verifying the full payload-render-parse loop end-to-end

    It is *not* a trading strategy. Flip to Anthropic for real signals.
    """

    provider_name = "stub"
    model_name = "stub-v1"

    def analyze(self, system_prompt: str, user_prompt: str, payload_fill: Dict[str, Any]) -> str:
        p = payload_fill
        ltp = float(p["ltp"])
        vwap = float(p.get("m5_vwap") or p.get("m15_vwap") or ltp)
        ema20_15 = float(p.get("m15_ema20", ltp))
        ema50_15 = float(p.get("m15_ema50", ltp))
        d_trend = str(p.get("d_trend_label", "sideways"))
        rsi15 = float(p.get("m15_rsi", 50.0))
        adx15 = float(p.get("m15_adx", 15.0))
        atr15 = float(p.get("m15_atr", max(ltp * 0.005, 0.1)))
        rvol = float(p.get("rvol", 1.0))
        mins_to_close = int(p.get("minutes_to_close", 60))
        mins_since_open = int(p.get("minutes_since_open", 60))
        capital = float(p["capital"])
        risk_pct = float(p["risk_pct"])
        pdh = float(p["pdh"])
        pdl = float(p["pdl"])
        orh = float(p["orh"])
        orl = float(p["orl"])
        pivot = float(p["pivot"])

        # ---- Regime: trendiness of the 15m chart + daily alignment
        bullish = (
            ltp > vwap
            and ema20_15 > ema50_15
            and d_trend in ("up", "strong_up")
            and rsi15 > 50
        )
        bearish = (
            ltp < vwap
            and ema20_15 < ema50_15
            and d_trend in ("down", "strong_down")
            and rsi15 < 50
        )

        risk_flags = []
        if rvol < 0.8:
            risk_flags.append("low_RVOL")
        if mins_to_close < 45:
            risk_flags.append("late_session")
        if p.get("is_expiry_day"):
            risk_flags.append("expiry_day")
        if mins_since_open < 15:
            risk_flags.append("opening_volatility")

        stand_aside = mins_since_open < 15 or mins_to_close < 30 or adx15 < 15

        if stand_aside or (not bullish and not bearish):
            action = "HOLD"
            setup = "No clean setup — signals mixed or session edges"
            confidence = 45 if adx15 < 15 else 55
        elif bullish:
            action = "BUY"
            setup = "VWAP reclaim + daily uptrend alignment"
            confidence = min(85, 55 + int(adx15 / 2) + (5 if rvol > 1.2 else 0))
        else:
            action = "SELL"
            setup = "Below-VWAP breakdown + daily downtrend alignment"
            confidence = min(85, 55 + int(adx15 / 2) + (5 if rvol > 1.2 else 0))

        # ---- Stop / targets derived from ATR
        sl_distance = max(atr15 * 1.2, ltp * 0.004)
        if action == "BUY":
            sl = round(ltp - sl_distance, 2)
            t1 = round(ltp + sl_distance * 1.5, 2)
            t2 = round(min(pdh, ltp + sl_distance * 2.5) if pdh > ltp else ltp + sl_distance * 2.5, 2)
            t3 = round(ltp + sl_distance * 4.0, 2)
        elif action == "SELL":
            sl = round(ltp + sl_distance, 2)
            t1 = round(ltp - sl_distance * 1.5, 2)
            t2 = round(max(pdl, ltp - sl_distance * 2.5) if pdl < ltp else ltp - sl_distance * 2.5, 2)
            t3 = round(ltp - sl_distance * 4.0, 2)
        else:
            sl = round(ltp - sl_distance, 2)
            t1 = round(ltp + sl_distance, 2)
            t2 = round(ltp + sl_distance * 2, 2)
            t3 = round(ltp + sl_distance * 3, 2)

        rupee_risk = capital * risk_pct / 100
        per_share_risk = abs(ltp - sl) or sl_distance
        qty = max(1, int(rupee_risk / per_share_risk)) if action in ("BUY", "SELL") else 0
        rupee_exposure = round(qty * ltp, 2)

        def _rr(target: float) -> float:
            risk = abs(ltp - sl) or 1e-9
            return round(abs(target - ltp) / risk, 2)

        now = ist_now()
        valid_until = (now + timedelta(minutes=20)).strftime("%H:%M")

        signal = {
            "symbol": p["symbol"],
            "timestamp_ist": now.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "confidence": int(confidence),
            "setup_name": setup,
            "timeframe_basis": f"Daily={d_trend}; 15m ADX {adx15}; 5m trigger",
            "entry": {
                "type": "MARKET" if action in ("BUY", "SELL") else "LIMIT",
                "price": None if action in ("BUY", "SELL") else round(ltp, 2),
                "valid_until_ist": valid_until,
            },
            "stop_loss": {
                "price": sl,
                "type": "ATR",
                "rationale": f"1.2x ATR(14) on 15m = ₹{round(sl_distance, 2)}",
            },
            "targets": [
                {"level": "T1", "price": t1, "rr": _rr(t1), "rationale": "1.5R — nearest liquidity"},
                {"level": "T2", "price": t2, "rr": _rr(t2), "rationale": f"Structural level near {'PDH' if action == 'BUY' else 'PDL'}"},
                {"level": "T3", "price": t3, "rr": _rr(t3), "rationale": "Extension target on continuation"},
            ],
            "position_size": {
                "quantity": qty,
                "rupee_risk": round(rupee_risk, 2),
                "rupee_exposure": rupee_exposure,
                "calc": f"capital ₹{capital} x {risk_pct}% / per-share risk ₹{round(per_share_risk, 2)} = {qty} shares",
            },
            "trail_strategy": "Trail SL to 20 EMA on 5m after T1 hits; exit remainder at T3 or 15:10 IST",
            "reasoning": {
                "market_context": f"Nifty {p.get('nifty_pct', 0)}%, VIX {p.get('vix_value')}, sector {p.get('sector_pct', 0)}%.",
                "trend_alignment": f"Daily {d_trend}; 15m EMA20 {ema20_15} vs EMA50 {ema50_15}; 5m EMA above/below VWAP.",
                "price_action": f"LTP {ltp} vs VWAP {vwap}; OR {orl}-{orh}; pivot {pivot}.",
                "indicator_confluence": f"RSI15 {rsi15}, ADX15 {adx15}, MACD15 {p.get('m15_macd')}.",
                "volume_confirmation": f"RVOL {rvol}; 5m vol ratio {p.get('m5_vol_ratio')}.",
                "key_levels": f"PDH {pdh}, PDL {pdl}, PDC {p['pdc']}; 52w {p['wk52_low']}-{p['wk52_high']}.",
                "time_of_day": f"{mins_since_open} min since open, {mins_to_close} min to close.",
            },
            "conflicting_signals": [] if (bullish or bearish) else ["Trend/momentum not aligned on 15m"],
            "invalidation": (
                f"Close below {sl} on 5m would invalidate the long thesis"
                if action == "BUY"
                else f"Close above {sl} on 5m would invalidate the short thesis"
                if action == "SELL"
                else "Break of today's range with volume flips the bias"
            ),
            "what_to_watch": [
                f"5m close vs VWAP ({vwap})",
                f"Reaction at {'PDH ' + str(pdh) if action == 'BUY' else 'PDL ' + str(pdl)}",
                f"ADX direction (currently {adx15})",
            ],
            "risk_flags": risk_flags,
            "disclaimer_acknowledged": True,
        }
        return json.dumps(signal)


# ---------------------------------------------------------------------- real

@dataclass
class AnthropicClaudeClient:
    """Real Anthropic-API-backed client.

    The ``anthropic`` SDK is imported lazily inside ``analyze`` so this
    module loads cleanly on environments that haven't installed it.
    """

    api_key: str
    model: str
    max_tokens: int = 2048
    temperature: float = 0.2

    provider_name: str = "anthropic"

    @property
    def model_name(self) -> str:
        return self.model

    def analyze(self, system_prompt: str, user_prompt: str, payload_fill: Dict[str, Any]) -> str:
        # Lazy import so environments without the SDK still run the stub.
        try:
            import anthropic  # type: ignore
        except ImportError as e:  # pragma: no cover - install-time guard
            raise RuntimeError(
                "anthropic SDK not installed. Add `anthropic>=0.39.0` to "
                "requirements.txt and install, or set ANALYZER_PROVIDER=stub."
            ) from e

        client = anthropic.Anthropic(api_key=self.api_key)
        # Reinforce JSON-only in the system prompt so the model doesn't
        # wrap the response in prose or markdown fences.
        system = system_prompt + (
            "\n\nIMPORTANT: Return ONLY the JSON object requested in the "
            "user message. No markdown fences, no commentary, no preamble."
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Response content is a list of blocks; concatenate text blocks.
        parts = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()


# ---------------------------------------------------------------------- factory

def get_claude_client(settings: Settings) -> ClaudeClient:
    kind = (settings.analyzer_provider or "stub").lower()
    if kind == "stub":
        return StubClaudeClient()
    if kind == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Either set it, or switch "
                "ANALYZER_PROVIDER back to 'stub'."
            )
        return AnthropicClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    raise ValueError(f"Unknown analyzer_provider: {settings.analyzer_provider}")
