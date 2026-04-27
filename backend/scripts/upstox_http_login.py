"""Upstox login via direct HTTP — no browser required.

Replicates the exact XHR calls the Upstox React SPA makes so we get a
token in 3-5 seconds instead of waiting 60+ s for Chromium to launch.

Flow
----
  Step 1 – POST mobile number          →  OTP SMS sent to phone
  Step 2 – POST SMS OTP (or skip)      →  session advances
  Step 3 – POST 6-digit PIN            →  session advances
  Step 4 – POST TOTP (pyotp.now())     →  302 redirect with ?code=
  Step 5 – POST code for access token  →  token JSON written to file

Exit codes:
    0  success
    1  error (message on stderr)

Same CLI interface as upstox_login.py so upstox.py can swap between them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs


# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Direct-HTTP Upstox OAuth login")
    p.add_argument("--api-key",      required=True)
    p.add_argument("--api-secret",   required=True)
    p.add_argument("--redirect-uri", required=True)
    p.add_argument("--mobile",       required=True)
    p.add_argument("--pin",          required=True)
    p.add_argument("--totp-secret",  required=True)
    p.add_argument("--token-file",   default="upstox_token.json")
    p.add_argument("--otp-mode",     default="gui", choices=["gui", "stdin"])
    return p.parse_args()


BASE        = "https://api.upstox.com"
AUTH_DIALOG = f"{BASE}/v2/login/authorization/dialog"
TOKEN_URL   = f"{BASE}/v2/login/authorization/token"

# Headers that make the server treat us like a real browser SPA request.
_COMMON_HEADERS = {
    "Accept":           "application/json, text/plain, */*",
    "Accept-Language":  "en-US,en;q=0.9",
    "Content-Type":     "application/x-www-form-urlencoded",
    "Origin":           "https://api.upstox.com",
    "Referer":          "https://api.upstox.com/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _code_from_url(url: str) -> str | None:
    """Extract ?code= from a redirect URL."""
    m = re.search(r"[?&]code=([^&]+)", url)
    return m.group(1) if m else None


def main() -> None:
    args = _parse_args()

    try:
        import httpx
    except ImportError:
        sys.exit("ERROR: httpx not installed. Run: pip install httpx")

    try:
        import pyotp
    except ImportError:
        sys.exit("ERROR: pyotp not installed. Run: pip install pyotp")

    print("upstox_http_login: starting direct-HTTP login (no browser)", flush=True)

    # Use a session so cookies are carried across all steps automatically.
    with httpx.Client(
        headers=_COMMON_HEADERS,
        follow_redirects=False,   # we want to inspect 302 Location headers
        timeout=20.0,
    ) as s:

        # ── Step 0: load login page (sets session / CSRF cookies) ──────────
        print("upstox_http_login: initialising session", flush=True)
        init = s.get(AUTH_DIALOG, params={
            "client_id":     args.api_key,
            "redirect_uri":  args.redirect_uri,
            "response_type": "code",
            "state":         "",
        }, follow_redirects=True)
        print(f"  init status={init.status_code}", flush=True)

        # ── Step 1: submit mobile number → triggers SMS ─────────────────────
        print("upstox_http_login: submitting mobile number", flush=True)
        r1 = s.post(AUTH_DIALOG, data={
            "mobileNum": args.mobile,
            "source":    "WEB",
        })
        print(f"  mobile status={r1.status_code}", flush=True)

        # Check if an OTP step is needed (status 200 means more input required;
        # some accounts skip SMS OTP when TOTP is enabled).
        need_sms_otp = r1.status_code == 200 and "otp" in r1.text.lower()

        if need_sms_otp:
            print("upstox_http_login: SMS OTP required", flush=True)
            if args.otp_mode == "stdin":
                print("OTP_REQUIRED", flush=True)
                sms_otp = sys.stdin.readline().strip()
                if not sms_otp:
                    sys.exit("ERROR: No OTP received on stdin.")
            else:
                print(
                    f"\n>>> Upstox sent an SMS OTP to +91-{args.mobile}. "
                    "Enter it here: ",
                    end="", flush=True,
                )
                sms_otp = input().strip()

            # ── Step 2: verify SMS OTP ──────────────────────────────────────
            print("upstox_http_login: submitting SMS OTP", flush=True)
            r2 = s.post(AUTH_DIALOG, data={
                "mobileNum": args.mobile,
                "otp":       sms_otp,
                "source":    "WEB",
            })
            print(f"  otp status={r2.status_code}", flush=True)
        else:
            print("upstox_http_login: SMS OTP step skipped", flush=True)

        # ── Step 3: submit PIN ──────────────────────────────────────────────
        print("upstox_http_login: submitting PIN", flush=True)
        r3 = s.post(AUTH_DIALOG, data={
            "pin":         args.pin,
            "clientId":    args.api_key,
            "redirectUri": args.redirect_uri,
            "apiVersion":  "2.0",
        })
        print(f"  pin status={r3.status_code}", flush=True)

        # ── Step 4: submit TOTP ────────────────────────────────────────────
        totp_code = pyotp.TOTP(args.totp_secret).now()
        print(f"upstox_http_login: submitting TOTP {totp_code}", flush=True)
        r4 = s.post(AUTH_DIALOG, data={
            "totp":        totp_code,
            "clientId":    args.api_key,
            "redirectUri": args.redirect_uri,
        })
        print(f"  totp status={r4.status_code}", flush=True)

        # The server should redirect to the callback URL with ?code=
        auth_code: str | None = None

        if r4.status_code in (301, 302, 303, 307, 308):
            location = r4.headers.get("location", "")
            print(f"  redirect → {location[:120]}", flush=True)
            auth_code = _code_from_url(location)

        # Some Upstox deployments return 200 with a JSON body containing
        # the redirect URL or auth code directly.
        if not auth_code and r4.status_code == 200:
            try:
                body = r4.json()
                # Try common field names
                auth_code = (
                    body.get("code")
                    or body.get("auth_code")
                    or body.get("authorization_code")
                )
                if not auth_code:
                    # Look for a redirect_url field
                    redirect_url = body.get("redirect_url") or body.get("redirectUrl") or ""
                    auth_code = _code_from_url(redirect_url)
            except Exception:
                pass

        if not auth_code:
            print(
                f"ERROR: No auth code found after TOTP step.\n"
                f"  status={r4.status_code}\n"
                f"  body={r4.text[:400]}",
                file=sys.stderr, flush=True,
            )
            sys.exit(1)

        print(f"upstox_http_login: auth code captured ({auth_code[:8]}…)", flush=True)

    # ── Step 5: exchange auth code for access token ────────────────────────
    print("upstox_http_login: exchanging code for access token", flush=True)
    import urllib.request, urllib.parse, urllib.error

    body = urllib.parse.urlencode({
        "code":          auth_code,
        "client_id":     args.api_key,
        "client_secret": args.api_secret,
        "redirect_uri":  args.redirect_uri,
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"ERROR: Token exchange HTTP {exc.code}: {exc.read()[:300]}")
    except Exception as exc:
        sys.exit(f"ERROR: Token exchange failed — {exc}")

    access_token = data.get("access_token")
    if not access_token:
        sys.exit(f"ERROR: No access_token in response: {data}")

    token_path = Path(args.token_file)
    token_path.write_text(json.dumps({
        "access_token":      access_token,
        "user_id":           data.get("user_id"),
        "user_name":         data.get("user_name"),
        "email":             data.get("email"),
        "broker":            data.get("broker"),
        "auto_refreshed_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass

    print("upstox_http_login: SUCCESS — token saved", flush=True)


if __name__ == "__main__":
    main()
