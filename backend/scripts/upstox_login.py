"""Standalone Upstox headless login script.

Run as a subprocess so Playwright gets its own asyncio event loop
(required on Windows / Python 3.12 — cannot nest event loops).

Upstox login flow
-----------------
  Step 1 – Mobile number  →  "Get OTP"  →  SMS sent to phone
  Step 2 – Enter SMS OTP  (we show a GUI dialog for this)
  Step 3 – Enter 6-digit PIN  (automated)
  Step 4 – Enter TOTP from authenticator  (automated via pyotp)
  Step 5 – Exchange auth code for access token

Only Step 2 needs human input — a small popup appears on screen asking
for the 6-digit SMS code.  Everything else is fully automated.

Exit codes:
    0  success  (token written to --token-file)
    1  error    (error message on stderr)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Headless Upstox OAuth login")
    p.add_argument("--api-key",      required=True)
    p.add_argument("--api-secret",   required=True)
    p.add_argument("--redirect-uri", required=True)
    p.add_argument("--mobile",       required=True)
    p.add_argument("--pin",          required=True)
    p.add_argument("--totp-secret",  required=True)
    p.add_argument("--token-file",   default="upstox_token.json")
    # otp-mode controls how SMS OTP is collected:
    #   "gui"   — tkinter popup (default; fine when running locally with a display)
    #   "stdin" — print "OTP_REQUIRED\n" to stdout, then block on stdin.readline()
    #             Used by the web API so the browser UI can supply the OTP.
    p.add_argument("--otp-mode",     default="gui", choices=["gui", "stdin"])
    return p.parse_args()


def _ask_sms_otp_gui(mobile: str) -> str:
    """Show a small always-on-top dialog asking for the SMS OTP.
    Falls back to terminal input if tkinter is unavailable."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)   # bring above other windows
        otp = simpledialog.askstring(
            "Upstox Login — SMS OTP required",
            f"An OTP was sent to +91-{mobile}.\n\nPaste it here:",
            parent=root,
        )
        root.destroy()
        if otp is None:
            sys.exit("ERROR: SMS OTP dialog cancelled by user.")
        return otp.strip()
    except Exception:
        # Fallback for headless / non-GUI environments
        print(
            f"\n>>> Upstox sent an SMS OTP to +91-{mobile}. "
            "Enter it here and press Enter: ",
            end="",
            flush=True,
        )
        return input().strip()


def _click_button(page, hints: list[str], timeout: int = 4_000) -> bool:
    """Click the first visible button whose text matches any hint."""
    for hint in hints:
        for sel in [
            f"button:has-text('{hint}')",
            f"input[value='{hint}']",
            f"a:has-text('{hint}')",
        ]:
            try:
                el = page.locator(sel).first
                el.wait_for(state="visible", timeout=timeout)
                el.click()
                return True
            except Exception:
                continue
    # Last resort — any visible submit button
    try:
        page.locator("button[type='submit']:visible").first.click(timeout=timeout)
        return True
    except Exception:
        return False


def _find_input(page, selectors: list[str], timeout: int = 5_000):
    """Return the first visible input matched by any of the selectors."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout)
            return el
        except Exception:
            continue
    return None


def _screenshot(page, tag: str) -> None:
    try:
        page.screenshot(path=f"upstox_login_debug_{tag}.png")
        print(f"[debug] screenshot → upstox_login_debug_{tag}.png", flush=True)
    except Exception:
        pass


def main() -> None:
    args = _parse_args()

    try:
        import pyotp
    except ImportError:
        sys.exit("ERROR: pyotp not installed. Run: pip install pyotp")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        sys.exit(
            "ERROR: playwright not installed.\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    redirect_uri = args.redirect_uri
    _AUTH_URL  = "https://api.upstox.com/v2/login/authorization/dialog"
    _TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

    auth_code: str | None = None

    print("upstox_login: starting headless Chromium", flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_context().new_page()

        # Intercept any request to the callback URL to capture the auth code.
        def _on_request(req):
            nonlocal auth_code
            if req.url.startswith(redirect_uri) and "code=" in req.url:
                m = re.search(r"[?&]code=([^&]+)", req.url)
                if m and not auth_code:
                    auth_code = m.group(1)
                    print("upstox_login: auth code captured", flush=True)

        page.on("request", _on_request)

        try:
            url = (
                f"{_AUTH_URL}"
                f"?client_id={args.api_key}"
                f"&redirect_uri={redirect_uri}"
                f"&response_type=code&state="
            )
            print("upstox_login: navigating to Upstox login page", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_500)   # let React render

            # ── Step 1: mobile number ─────────────────────────────────────
            print("upstox_login: filling mobile number", flush=True)
            mobile_input = _find_input(page, [
                "input[id='mobileNum']",
                "input[name='mobileNum']",
                "input[type='tel']",
                "input[placeholder*='mobile' i]",
                "input[placeholder*='Mobile' i]",
                "input[placeholder*='number' i]",
                "input[placeholder*='phone' i]",
            ])
            if mobile_input is None:
                _screenshot(page, "no_mobile_input")
                sys.exit("ERROR: Could not find mobile number input.")

            mobile_input.fill(args.mobile)
            page.wait_for_timeout(400)
            _click_button(page, ["Get OTP", "Continue", "Send OTP", "Next"])
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
            page.wait_for_timeout(2_000)
            _screenshot(page, "after_mobile")

            # ── Step 2: SMS OTP  (user must paste this from their phone) ──
            # Check if an OTP input is now visible.
            sms_otp_input = _find_input(page, [
                "input[id='otpNum']",
                "input[name='otpNum']",
                "input[name='otp']",
                "input[placeholder*='OTP' i]",
                "input[placeholder*='one-time' i]",
                "input[placeholder*='Enter OTP' i]",
                "input[maxlength='6'][type='text']",
                "input[maxlength='6'][type='number']",
                "input[maxlength='6']",
            ])

            if sms_otp_input is not None:
                # Upstox sent an SMS — ask the user for the code.
                print("upstox_login: SMS OTP step detected — prompting user", flush=True)
                if args.otp_mode == "stdin":
                    # Signal the parent process that we're waiting for the OTP.
                    print("OTP_REQUIRED", flush=True)
                    sms_code = sys.stdin.readline().strip()
                    if not sms_code:
                        sys.exit("ERROR: No OTP received on stdin.")
                else:
                    sms_code = _ask_sms_otp_gui(args.mobile)
                sms_otp_input.fill(sms_code)
                page.wait_for_timeout(400)
                _click_button(page, ["Verify", "Continue", "Submit", "Next"])
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
                page.wait_for_timeout(2_000)
                _screenshot(page, "after_sms_otp")
            else:
                print("upstox_login: no SMS OTP step — proceeding to PIN", flush=True)

            # ── Step 3: 6-digit PIN  (automated) ──────────────────────────
            print("upstox_login: filling PIN", flush=True)
            pin_input = _find_input(page, [
                "input[id='pinCode']",
                "input[name='pinCode']",
                "input[name='pin']",
                "input[type='password']",
                "input[placeholder*='PIN' i]",
                "input[placeholder*='pin' i]",
                "input[placeholder*='password' i]",
                "input[placeholder*='passcode' i]",
            ])
            if pin_input is None:
                _screenshot(page, "no_pin_input")
                sys.exit("ERROR: Could not find PIN input field.")

            pin_input.fill(args.pin)
            page.wait_for_timeout(400)
            _click_button(page, ["Continue", "Verify", "Submit", "Next", "Login"])
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
            page.wait_for_timeout(2_000)
            _screenshot(page, "after_pin")

            # ── Step 4: TOTP from authenticator app  (automated) ──────────
            totp_code = pyotp.TOTP(args.totp_secret).now()
            print(f"upstox_login: filling TOTP {totp_code}", flush=True)
            totp_input = _find_input(page, [
                "input[id='otpNum']",
                "input[name='otpNum']",
                "input[name='otp']",
                "input[maxlength='6'][type='text']",
                "input[maxlength='6'][type='number']",
                "input[maxlength='6']",
                "input[placeholder*='TOTP' i]",
                "input[placeholder*='authenticator' i]",
                "input[placeholder*='OTP' i]",
                "input[placeholder*='code' i]",
            ])
            if totp_input is None:
                _screenshot(page, "no_totp_input")
                # TOTP might not be enabled — check if we're already redirected.
                if auth_code:
                    print("upstox_login: TOTP step skipped (already have auth code)", flush=True)
                else:
                    print("upstox_login: TOTP input not found — current URL:", page.url, flush=True)
                    sys.exit("ERROR: Could not find TOTP input field.")
            else:
                totp_input.fill(totp_code)
                page.wait_for_timeout(400)
                _click_button(page, ["Continue", "Verify", "Submit", "Login"])

            # Wait for redirect to callback URL.
            if not auth_code:
                try:
                    page.wait_for_url(f"{redirect_uri}*", timeout=20_000)
                    m = re.search(r"[?&]code=([^&]+)", page.url)
                    if m:
                        auth_code = m.group(1)
                except PWTimeout:
                    _screenshot(page, "timeout_after_totp")
                    if not auth_code:
                        raise

        except PWTimeout:
            _screenshot(page, "timeout")
            browser.close()
            sys.exit(
                f"ERROR: Login timed out. Last URL: {page.url!r}. "
                "Check upstox_login_debug_*.png screenshots for details."
            )
        except SystemExit:
            browser.close()
            raise
        except Exception as exc:
            _screenshot(page, "error")
            browser.close()
            sys.exit(f"ERROR: {exc}")

        browser.close()

    if not auth_code:
        sys.exit("ERROR: Login completed but no auth code received.")

    # ── Step 5: exchange auth code for access token ────────────────────────
    print("upstox_login: exchanging code for access token", flush=True)
    import urllib.request, urllib.parse, urllib.error

    body = urllib.parse.urlencode({
        "code":          auth_code,
        "client_id":     args.api_key,
        "client_secret": args.api_secret,
        "redirect_uri":  redirect_uri,
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(
        _TOKEN_URL, data=body,
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

    print("upstox_login: SUCCESS — token saved", flush=True)


if __name__ == "__main__":
    main()
