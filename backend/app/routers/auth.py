"""Upstox OAuth2 login/callback routes.

Upstox access tokens expire around 03:30 IST every day, so this flow
needs to run at least once per trading day. Usage:

  1. Open ``http://localhost:8000/auth/upstox/login`` in a browser.
  2. Log in on Upstox and approve.
  3. Upstox redirects back to ``/auth/upstox/callback?code=...``.
  4. This handler exchanges the code for an access token and writes it
     to ``backend/upstox_token.json``. The running server picks it up
     on the next Upstox call — no restart required.
"""
from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.config import get_settings
from app.integrations.upstox import save_token

router = APIRouter(prefix="/auth/upstox", tags=["auth"])


UPSTOX_AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def _require_oauth_config() -> tuple[str, str, str]:
    s = get_settings()
    missing = [
        name for name, val in (
            ("UPSTOX_API_KEY", s.upstox_api_key),
            ("UPSTOX_API_SECRET", s.upstox_api_secret),
            ("UPSTOX_REDIRECT_URI", s.upstox_redirect_uri),
        ) if not val
    ]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Upstox OAuth config: {', '.join(missing)}",
        )
    return s.upstox_api_key, s.upstox_api_secret, s.upstox_redirect_uri  # type: ignore[return-value]


@router.get("/login")
def login() -> RedirectResponse:
    """Redirect to Upstox's login/authorization dialog."""
    api_key, _, redirect_uri = _require_oauth_config()
    qs = urlencode({
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
    })
    return RedirectResponse(url=f"{UPSTOX_AUTHORIZE_URL}?{qs}", status_code=302)


@router.get("/callback", response_class=HTMLResponse)
def callback(
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Exchange the authorization ``code`` for an access token."""
    if error:
        raise HTTPException(status_code=400, detail=f"Upstox returned error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code from Upstox")

    api_key, api_secret, redirect_uri = _require_oauth_config()
    body = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                UPSTOX_TOKEN_URL,
                data=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstox token exchange failed: {exc}")

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Upstox token exchange failed ({resp.status_code}): {resp.text[:300]}",
        )

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail=f"Upstox response missing access_token: {data}")

    save_token(access_token, extra={
        "user_id": data.get("user_id"),
        "user_name": data.get("user_name"),
        "email": data.get("email"),
        "broker": data.get("broker"),
        "issued_at": data.get("issued_at"),
    })

    return HTMLResponse(
        """
        <html><head><title>Upstox connected</title></head>
        <body style="font-family:system-ui;padding:2rem;max-width:640px;margin:auto">
          <h2 style="color:#0a7">Upstox connected.</h2>
          <p>Your access token has been saved to <code>backend/upstox_token.json</code>
             and will be used by the API on the next request.</p>
          <p>This token expires around 03:30 IST tomorrow — visit
             <a href="/auth/upstox/login">/auth/upstox/login</a> again after that.</p>
          <p><a href="/docs">Back to API docs</a></p>
        </body></html>
        """
    )


@router.get("/status")
def status() -> dict:
    """Report whether a token is currently loaded and whether it has expired."""
    from app.integrations.upstox import (
        is_token_expired,
        load_stored_token,
        token_expiry_ist,
    )
    settings = get_settings()
    has_env    = bool(settings.upstox_access_token)
    has_file   = bool(load_stored_token())
    expired    = is_token_expired()
    can_auto   = bool(
        settings.upstox_mobile
        and settings.upstox_pin
        and settings.upstox_totp_secret
    )
    return {
        "has_env_token": has_env,
        "has_file_token": has_file,
        "token_expired": expired,
        "token_expires_at": token_expiry_ist(),
        "auto_refresh_configured": can_auto,
        "ready": (has_env or has_file) and not expired,
    }


@router.post("/auto-refresh")
def auto_refresh() -> dict:
    """Trigger a headless TOTP-based token refresh immediately.

    Requires UPSTOX_MOBILE, UPSTOX_PIN, and UPSTOX_TOTP_SECRET to be set
    in .env.  Returns the new expiry time on success.
    """
    from app.integrations.upstox import UpstoxAuthError, auto_login, token_expiry_ist
    try:
        auto_login()
    except UpstoxAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "status": "refreshed",
        "token_expires_at": token_expiry_ist(),
    }


class OtpSubmit(BaseModel):
    session_id: str
    otp: str


@router.post("/start-login")
def start_login() -> dict:
    """Launch a headless browser login session in stdin-OTP mode.

    The subprocess navigates to Upstox, fills in the mobile number and clicks
    "Get OTP".  When the SMS OTP field appears the process pauses and returns
    ``{"status": "otp_required", "session_id": "..."}`` so the frontend can
    show an OTP entry dialog.

    If SMS OTP is not required (rare) it completes immediately and returns
    ``{"status": "success"}``.
    """
    from app.integrations.upstox import UpstoxAuthError, start_login_session, token_expiry_ist
    try:
        status, session_id = start_login_session()
    except UpstoxAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if status == "otp_required":
        return {"status": "otp_required", "session_id": session_id}
    return {"status": "success", "token_expires_at": token_expiry_ist()}


@router.post("/submit-otp")
def submit_otp_endpoint(body: OtpSubmit) -> dict:
    """Submit the SMS OTP to a waiting login session.

    After ``/start-login`` returns ``otp_required``, the user pastes the SMS
    code here.  The subprocess continues: fills in PIN + TOTP automatically,
    exchanges the auth code for a token, and saves it.
    """
    from app.integrations.upstox import UpstoxAuthError, submit_otp, token_expiry_ist
    try:
        expiry = submit_otp(body.session_id, body.otp.strip())
    except UpstoxAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "token_expires_at": expiry}


@router.get("/test")
def test_connection() -> dict:
    """Make a live Upstox API call (Nifty 50 LTP) and report whether it succeeds.

    Use this to confirm the token + credentials are working end-to-end.
    Returns ``{"ok": true, "nifty_ltp": 24350.5, "error": null}`` on success.
    """
    from app.config import get_settings
    from app.integrations.upstox import UpstoxClient

    settings = get_settings()
    if settings.data_provider != "upstox":
        return {
            "ok": False,
            "nifty_ltp": None,
            "error": f"DATA_PROVIDER is '{settings.data_provider}', not 'upstox'. Set DATA_PROVIDER=upstox in .env.",
        }
    client = UpstoxClient()
    return client.test_connection()


@router.post("/refresh-instruments")
def refresh_instruments() -> dict:
    """Force a re-download of the Upstox instruments feed.

    Run this if a symbol starts returning ``UDAPI100011 Invalid Instrument
    key`` — it pulls the latest ISIN mappings from Upstox's CDN.
    """
    from app.data.instruments import refresh_instruments as _refresh
    count = _refresh()
    return {"loaded_symbols": count}
