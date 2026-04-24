"""Upstox integration.

Covers the market-data endpoints we actually call from the data provider:

  - GET /v2/historical-candle/{instrument_key}/{interval}/{to}/{from}
  - GET /v2/historical-candle/intraday/{instrument_key}/{interval}
  - GET /v2/market-quote/ltp

Trading endpoints (``place_order``) stay stubbed behind the
``PAPER_TRADING`` guard. Flip ``PAPER_TRADING=false`` *and* implement
``place_order`` before touching real capital.

Token handling
--------------
Upstox access tokens expire daily (~03:30 IST). We load the token in
this order:

  1. explicit constructor arg
  2. ``UPSTOX_ACCESS_TOKEN`` env var
  3. ``backend/upstox_token.json`` written by the OAuth callback router

Auto-refresh
------------
If UPSTOX_MOBILE + UPSTOX_PIN + UPSTOX_TOTP_SECRET are set in .env,
calling ``auto_login()`` will perform a headless OAuth flow (mobile →
PIN → TOTP → token exchange) and write the fresh token to
``upstox_token.json``.  The scheduler calls this at startup whenever
the stored token is expired.

Refer to ``app/routers/auth.py`` for the manual OAuth callback flow.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Login throttle — prevents multiple concurrent auto-login attempts.
# Only one login runs at a time; after failure, wait 5 min before retrying.
# ---------------------------------------------------------------------------
_login_lock = threading.Lock()
_last_login_attempt: float = 0.0          # epoch seconds of last attempt
_LOGIN_COOLDOWN_SECONDS = 300             # 5 minutes between retries
_cached_token: Optional[str] = None      # in-memory token cache


UPSTOX_BASE = "https://api.upstox.com/v2"

# Resolved relative to the backend/ working directory the API runs from.
TOKEN_FILE = Path("upstox_token.json")


class UpstoxAuthError(RuntimeError):
    """Raised when Upstox rejects the token (401/403). The caller should
    prompt the user to re-run the OAuth login flow."""


class UpstoxAPIError(RuntimeError):
    """Raised for any non-auth error from the Upstox API."""


@dataclass
class OrderRequest:
    symbol: str
    side: str        # "BUY" | "SELL"
    quantity: int
    order_type: str  # "MARKET" | "LIMIT"
    price: Optional[float] = None
    product: str = "I"  # I=Intraday, D=Delivery, CO=CoverOrder


@dataclass
class OrderResult:
    status: str
    broker_order_id: Optional[str]
    raw: Dict[str, Any]


def load_stored_token() -> Optional[str]:
    """Return the access token persisted by the OAuth callback, if any."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        tok = data.get("access_token")
        return tok if isinstance(tok, str) and tok else None
    except (json.JSONDecodeError, OSError):
        return None


def save_token(access_token: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """Persist the daily access token so the running server can pick it up
    without a restart. Written by ``/auth/upstox/callback``."""
    payload: Dict[str, Any] = {"access_token": access_token}
    if extra:
        payload.update(extra)
    TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def _decode_jwt_exp(token: str) -> Optional[int]:
    """Extract the ``exp`` claim from a JWT without verifying the signature."""
    try:
        import base64
        parts = token.split(".")
        if len(parts) < 2:
            return None
        # Add padding so base64 doesn't complain.
        payload_b64 = parts[1] + "=="
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return int(payload["exp"])
    except Exception:  # noqa: BLE001
        return None


def is_token_expired(token: Optional[str] = None) -> bool:
    """Return True if the stored/given Upstox token is missing or expired."""
    tok = token or load_stored_token()
    if not tok:
        return True
    exp = _decode_jwt_exp(tok)
    if exp is None:
        return True  # can't decode → treat as expired
    # Give a 5-minute buffer so we refresh before the server rejects us.
    return time.time() > (exp - 300)


def token_expiry_ist() -> Optional[str]:
    """Return a human-readable IST expiry string for the current token."""
    tok = load_stored_token()
    if not tok:
        return None
    exp = _decode_jwt_exp(tok)
    if exp is None:
        return None
    from datetime import timedelta
    dt_utc = datetime.fromtimestamp(exp, tz=timezone.utc)
    dt_ist = dt_utc + timedelta(hours=5, minutes=30)
    return dt_ist.strftime("%Y-%m-%d %H:%M IST")


# ---------------------------------------------------------------------------
# Headless auto-login  (Playwright via isolated subprocess)
# ---------------------------------------------------------------------------
# Playwright's sync_api cannot run inside FastAPI's asyncio event loop
# (NotImplementedError on Windows / Python 3.12).  The fix is to run the
# browser login in a *separate process* that has its own clean event loop.
# scripts/upstox_login.py contains the full Playwright logic.
# ---------------------------------------------------------------------------

def auto_login() -> str:
    """Perform a headless Upstox OAuth login and return the fresh access token.

    Launches ``scripts/upstox_login.py`` as a subprocess so Playwright gets
    its own clean asyncio event loop (required on Windows with Python ≥ 3.12).

    Requires UPSTOX_MOBILE, UPSTOX_PIN, UPSTOX_TOTP_SECRET,
    UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_REDIRECT_URI in .env.

    One-time setup:
        pip install playwright pyotp
        playwright install chromium
    """
    import subprocess
    import sys

    s = get_settings()
    missing = [n for n, v in [
        ("UPSTOX_MOBILE",      s.upstox_mobile),
        ("UPSTOX_PIN",         s.upstox_pin),
        ("UPSTOX_TOTP_SECRET", s.upstox_totp_secret),
        ("UPSTOX_API_KEY",     s.upstox_api_key),
        ("UPSTOX_API_SECRET",  s.upstox_api_secret),
        ("UPSTOX_REDIRECT_URI", s.upstox_redirect_uri),
    ] if not v]
    if missing:
        raise UpstoxAuthError(
            f"Cannot auto-login — missing in .env: {', '.join(missing)}"
        )

    # Resolve the login script relative to this file's package root.
    # upstox.py is at  backend/app/integrations/upstox.py
    # login script is  backend/scripts/upstox_login.py
    script_path = (
        Path(__file__).resolve().parent.parent.parent / "scripts" / "upstox_login.py"
    )
    if not script_path.exists():
        raise UpstoxAuthError(
            f"Login script not found at {script_path}. "
            "Make sure scripts/upstox_login.py exists in the backend folder."
        )

    token_file = str(TOKEN_FILE.resolve())

    cmd = [
        sys.executable, str(script_path),
        "--api-key",      s.upstox_api_key,
        "--api-secret",   s.upstox_api_secret,
        "--redirect-uri", s.upstox_redirect_uri,
        "--mobile",       s.upstox_mobile,
        "--pin",          s.upstox_pin,
        "--totp-secret",  s.upstox_totp_secret,
        "--token-file",   token_file,
    ]

    logger.info("Upstox auto-login: spawning login subprocess")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,          # 2-minute hard cap
        )
    except subprocess.TimeoutExpired:
        raise UpstoxAuthError("Upstox auto-login subprocess timed out (120 s).")
    except Exception as exc:  # noqa: BLE001
        raise UpstoxAuthError(f"Failed to launch login subprocess: {exc}") from exc

    # Forward subprocess output to our logger so it appears in uvicorn logs.
    for line in result.stdout.splitlines():
        logger.info("[login] %s", line)
    for line in result.stderr.splitlines():
        logger.warning("[login] %s", line)

    if result.returncode != 0:
        # stderr contains the ERROR: ... message from the script.
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise UpstoxAuthError(f"Upstox auto-login failed: {detail}")

    # Read the fresh token that the subprocess just wrote.
    fresh = load_stored_token()
    if not fresh:
        raise UpstoxAuthError(
            "Login subprocess succeeded but token file is empty."
        )

    logger.info("Upstox auto-login: SUCCESS — token valid until ~03:30 IST tomorrow")
    return fresh


# ---------------------------------------------------------------------------
# Web-triggered login session (used by the /auth/upstox/start-login endpoint)
# ---------------------------------------------------------------------------
# When the user clicks "Login" in the web app we start the Playwright subprocess
# in --otp-mode stdin so it pauses mid-flow and waits for the SMS OTP to be
# piped in.  We store the Popen handle between the two HTTP requests.
# ---------------------------------------------------------------------------

import uuid as _uuid

_login_sessions: dict[str, "subprocess.Popen[str]"] = {}  # session_id → Popen
_sessions_lock = threading.Lock()


def start_login_session() -> tuple[str, str]:
    """Launch the login subprocess in stdin-OTP mode.

    Returns:
        ("otp_required", session_id)  — subprocess paused waiting for OTP
        ("success", "")               — login completed without needing SMS OTP
                                        (shouldn't normally happen, but handled)

    Raises:
        UpstoxAuthError on misconfiguration or early failure.
    """
    import subprocess, sys

    s = get_settings()
    missing = [n for n, v in [
        ("UPSTOX_MOBILE",       s.upstox_mobile),
        ("UPSTOX_PIN",          s.upstox_pin),
        ("UPSTOX_TOTP_SECRET",  s.upstox_totp_secret),
        ("UPSTOX_API_KEY",      s.upstox_api_key),
        ("UPSTOX_API_SECRET",   s.upstox_api_secret),
        ("UPSTOX_REDIRECT_URI", s.upstox_redirect_uri),
    ] if not v]
    if missing:
        raise UpstoxAuthError(
            f"Cannot login — missing in .env: {', '.join(missing)}"
        )

    script_path = (
        Path(__file__).resolve().parent.parent.parent / "scripts" / "upstox_login.py"
    )
    if not script_path.exists():
        raise UpstoxAuthError(f"Login script not found at {script_path}.")

    token_file = str(TOKEN_FILE.resolve())
    cmd = [
        sys.executable, str(script_path),
        "--api-key",      s.upstox_api_key,
        "--api-secret",   s.upstox_api_secret,
        "--redirect-uri", s.upstox_redirect_uri,
        "--mobile",       s.upstox_mobile,
        "--pin",          s.upstox_pin,
        "--totp-secret",  s.upstox_totp_secret,
        "--token-file",   token_file,
        "--otp-mode",     "stdin",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise UpstoxAuthError(f"Failed to start login process: {exc}") from exc

    global _cached_token  # declared here so all branches can assign it

    # Read output lines until we hit OTP_REQUIRED or the process finishes.
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        logger.info("[login-session] %s", line)
        if line == "OTP_REQUIRED":
            session_id = _uuid.uuid4().hex
            with _sessions_lock:
                _login_sessions[session_id] = proc
            return ("otp_required", session_id)
        if "SUCCESS" in line:
            proc.wait()
            fresh = load_stored_token()
            if fresh:
                _cached_token = fresh
            return ("success", "")
        if line.startswith("ERROR"):
            proc.wait()
            stderr = proc.stderr.read() if proc.stderr else ""
            raise UpstoxAuthError(f"Login error: {line} {stderr[:200]}")

    # Process ended without OTP_REQUIRED or SUCCESS.
    proc.wait()
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.returncode == 0:
        fresh = load_stored_token()
        if fresh:
            _cached_token = fresh
        return ("success", "")
    raise UpstoxAuthError(
        f"Login subprocess exited {proc.returncode}: {stderr.strip()[:300]}"
    )


def submit_otp(session_id: str, otp: str) -> str:
    """Send the SMS OTP to the waiting login subprocess.

    Returns the new token expiry string on success.
    Raises UpstoxAuthError on failure.
    """
    global _cached_token  # declared at top so it's valid throughout the function

    with _sessions_lock:
        proc = _login_sessions.pop(session_id, None)

    if proc is None:
        raise UpstoxAuthError(
            f"Login session '{session_id}' not found or already completed."
        )

    assert proc.stdin is not None and proc.stdout is not None

    # Send the OTP to the subprocess.
    try:
        proc.stdin.write(otp + "\n")
        proc.stdin.flush()
    except OSError as exc:
        raise UpstoxAuthError(f"Could not send OTP to login process: {exc}") from exc

    # Read remaining output until SUCCESS or ERROR.
    for raw_line in proc.stdout:
        line = raw_line.strip()
        logger.info("[login-session] %s", line)
        if "SUCCESS" in line:
            break
        if line.startswith("ERROR"):
            proc.wait()
            raise UpstoxAuthError(f"Login failed after OTP: {line}")

    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise UpstoxAuthError(
            f"Login process exited {proc.returncode}: {stderr.strip()[:300]}"
        )

    fresh = load_stored_token()
    if not fresh:
        raise UpstoxAuthError("Login succeeded but token file is empty.")

    _cached_token = fresh
    logger.info("Upstox web-login: SUCCESS — token saved")
    return token_expiry_ist() or "unknown"


class UpstoxClient:
    """Thin wrapper around Upstox v2 REST endpoints."""

    def __init__(self, access_token: Optional[str] = None) -> None:
        settings = get_settings()
        self.access_token = (
            access_token
            or settings.upstox_access_token
            or load_stored_token()
        )
        self._client = httpx.Client(
            base_url=UPSTOX_BASE,
            headers=self._headers(),
            timeout=15.0,
        )

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def _require_token(self) -> None:
        """Ensure we have a valid, non-expired token — auto-refresh if possible.

        Uses a module-level lock so only ONE login attempt runs at a time,
        and a 5-minute cooldown so a failed attempt doesn't spawn a new
        browser for every subsequent price fetch.
        """
        global _cached_token, _last_login_attempt

        # Fast path: in-memory cached token is still valid.
        if _cached_token and not is_token_expired(_cached_token):
            self.access_token = _cached_token
            self._client.headers.update(self._headers())
            return

        # Check the instance token.
        if self.access_token and not is_token_expired(self.access_token):
            _cached_token = self.access_token
            return

        # Check the token file (written by a concurrent refresh or manual login).
        fresh = load_stored_token()
        if fresh and not is_token_expired(fresh):
            _cached_token = fresh
            self.access_token = fresh
            self._client.headers.update(self._headers())
            return

        # Token is expired.  Check if auto-login credentials are available.
        s = get_settings()
        if not (s.upstox_mobile and s.upstox_pin and s.upstox_totp_secret):
            raise UpstoxAuthError(
                "Upstox token expired. Visit /auth/upstox/login to log in manually, "
                "or set UPSTOX_MOBILE / UPSTOX_PIN / UPSTOX_TOTP_SECRET in .env "
                "for automatic daily refresh."
            )

        # Enforce cooldown — don't spawn a new browser while one might still be
        # running or after a recent failure.
        now = time.time()
        if now - _last_login_attempt < _LOGIN_COOLDOWN_SECONDS:
            remaining = int(_LOGIN_COOLDOWN_SECONDS - (now - _last_login_attempt))
            raise UpstoxAuthError(
                f"Upstox token expired — auto-refresh in cooldown "
                f"({remaining}s remaining). Prices temporarily unavailable."
            )

        # Acquire lock so only one thread attempts login at a time.
        acquired = _login_lock.acquire(blocking=False)
        if not acquired:
            raise UpstoxAuthError(
                "Upstox token refresh already in progress on another thread."
            )

        _last_login_attempt = now
        try:
            logger.info("Upstox token expired — attempting headless auto-refresh")
            new_token = auto_login()
            _cached_token = new_token
            self.access_token = new_token
            self._client.headers.update(self._headers())
        except UpstoxAuthError as exc:
            logger.error("Upstox auto-refresh failed: %s", exc)
            raise
        finally:
            _login_lock.release()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._require_token()
        try:
            resp = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise UpstoxAPIError(f"Upstox request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise UpstoxAuthError(
                f"Upstox auth failed ({resp.status_code}). Re-login at /auth/upstox/login."
            )
        if resp.status_code >= 400:
            raise UpstoxAPIError(
                f"Upstox {path} returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise UpstoxAPIError(f"Upstox {path} non-JSON response") from exc

    # ---- Market data --------------------------------------------------

    def get_historical_candles(
        self,
        instrument_key: str,
        interval: str,
        to_date: str,
        from_date: str,
    ) -> List[List[Any]]:
        """Return the raw ``candles`` array from Upstox.

        Each candle is ``[timestamp, open, high, low, close, volume, oi]``
        with the newest candle first. ``interval`` is one of
        ``day``/``week``/``month`` (Upstox v2 historical-candle only
        supports those three; intraday is a separate endpoint).
        """
        # Upstox requires the instrument_key to be URL-encoded because the
        # default path contains a ``|``. httpx handles this when we use
        # the ``/`` style path with proper escaping via the client.
        from urllib.parse import quote
        path = (
            f"/historical-candle/"
            f"{quote(instrument_key, safe='')}/"
            f"{interval}/{to_date}/{from_date}"
        )
        data = self._get(path)
        return list(data.get("data", {}).get("candles", []))

    def get_intraday_candles(
        self,
        instrument_key: str,
        interval: str = "1minute",
    ) -> List[List[Any]]:
        """Return same-day candles at ``1minute`` or ``30minute``."""
        from urllib.parse import quote
        path = (
            f"/historical-candle/intraday/"
            f"{quote(instrument_key, safe='')}/{interval}"
        )
        data = self._get(path)
        return list(data.get("data", {}).get("candles", []))

    def get_ltp(self, instrument_keys: List[str]) -> Dict[str, Dict[str, Any]]:
        """GET /market-quote/ltp -> ``{instrument_key: {last_price, ...}}``."""
        if not instrument_keys:
            return {}
        # Upstox accepts up to 500 instrument keys per call; split if needed.
        MAX_PER_CALL = 100
        result: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(instrument_keys), MAX_PER_CALL):
            batch = instrument_keys[i : i + MAX_PER_CALL]
            data = self._get(
                "/market-quote/ltp",
                params={"instrument_key": ",".join(batch)},
            )
            result.update(data.get("data", {}))
        return result

    def test_connection(self) -> Dict[str, Any]:
        """Make a minimal API call to verify connectivity and token validity.

        Returns a dict with ``ok``, ``nifty_ltp``, and ``error`` keys.
        Never raises — callers can always inspect the result dict.
        """
        try:
            self._require_token()
            nifty_key = "NSE_INDEX|Nifty 50"
            data = self._get(
                "/market-quote/ltp",
                params={"instrument_key": nifty_key},
            )
            entries = data.get("data", {})
            ltp: Optional[float] = None
            if entries:
                entry = next(iter(entries.values()))
                ltp = float(entry.get("last_price") or entry.get("ltp") or 0)
            return {"ok": True, "nifty_ltp": ltp, "error": None}
        except UpstoxAuthError as exc:
            return {"ok": False, "nifty_ltp": None, "error": f"Auth error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "nifty_ltp": None, "error": str(exc)}

    # ---- Trading -------------------------------------------------------

    def place_order(self, order: OrderRequest) -> OrderResult:
        """POST /order/place — intentionally gated until live trading is enabled."""
        settings = get_settings()
        if settings.paper_trading:
            raise RuntimeError(
                "Refusing to call Upstox place_order while PAPER_TRADING=true. "
                "Use PaperBroker instead (see PaperBroker in future milestone)."
            )
        raise NotImplementedError("Wire up Upstox place_order")

    def close(self) -> None:
        self._client.close()
