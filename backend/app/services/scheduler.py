"""Async background loop that ticks the paper-trading engine.

FastAPI ``lifespan`` starts three background tasks at app boot:

1. **trading loop** — ticks every 60 s while the NSE session is open,
   every 5 min outside hours.
2. **token watchdog** — checks the Upstox token once per hour. If expired
   and TOTP credentials are available it auto-refreshes; otherwise it logs
   a warning.
3. **morning notifier** — at 09:00 IST each trading day, if the Upstox token
   is expired it sends a push notification via ntfy.sh asking the user to
   open the app and enter their SMS OTP.

All loops swallow every exception so a bad tick / bad refresh never
kills the process.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.services import trading_engine as engine

logger = logging.getLogger(__name__)


_TICK_SECONDS_OPEN   = 60    # 1 min — check prices / stops every minute
_TICK_SECONDS_CLOSED = 300   # 5 min — keep snapshot.as_of moving
_TOKEN_CHECK_SECONDS = 3600  # 1 hour — token watchdog interval
_NOTIFY_CHECK_SECS   = 60    # how often the morning-notifier loop wakes up


# ---------------------------------------------------------------------------
# Token watchdog
# ---------------------------------------------------------------------------

async def _token_watchdog() -> None:
    """Periodically check the Upstox token and auto-refresh when expired."""
    from app.config import get_settings
    from app.integrations.upstox import auto_login, is_token_expired, token_expiry_ist

    logger.info("token watchdog: starting")

    # Immediate check at startup.
    await asyncio.sleep(2)

    while True:
        try:
            s = get_settings()
            if s.data_provider == "upstox":
                if is_token_expired():
                    if s.upstox_mobile and s.upstox_pin and s.upstox_totp_secret:
                        # Check pyotp is available before attempting
                        try:
                            import pyotp  # noqa: F401
                        except ImportError:
                            logger.error(
                                "token watchdog: pyotp is not installed — "
                                "run `pip install pyotp` inside your backend venv, "
                                "then restart the server."
                            )
                            try:
                                await asyncio.sleep(_TOKEN_CHECK_SECONDS)
                            except asyncio.CancelledError:
                                raise
                            continue

                        logger.info(
                            "token watchdog: token expired — starting headless refresh"
                        )
                        try:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, auto_login)
                            logger.info(
                                "token watchdog: refresh OK — next expiry %s",
                                token_expiry_ist(),
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.error(
                                "token watchdog: auto-refresh FAILED: %s — "
                                "visit /auth/upstox/login to log in manually",
                                exc,
                            )
                    else:
                        logger.warning(
                            "token watchdog: Upstox token is EXPIRED and auto-login "
                            "credentials are not set. Prices will be stale. "
                            "Set UPSTOX_MOBILE / UPSTOX_PIN / UPSTOX_TOTP_SECRET "
                            "in .env, or visit /auth/upstox/login."
                        )
                else:
                    logger.debug(
                        "token watchdog: token valid until %s", token_expiry_ist()
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("token watchdog error: %s", exc)

        try:
            await asyncio.sleep(_TOKEN_CHECK_SECONDS)
        except asyncio.CancelledError:
            raise


# ---------------------------------------------------------------------------
# Morning notifier — fires a push notification at 09:00 IST on weekdays
# when the Upstox token is expired so the user knows to log in.
# ---------------------------------------------------------------------------

async def _morning_notifier() -> None:
    """Send a 09:00 IST push notification on days the token needs refreshing."""
    from datetime import timedelta

    from app.config import get_settings
    from app.integrations.upstox import is_token_expired
    from app.services.notifier import notify_login_required

    logger.info("morning notifier: starting")

    _notified_today: set[str] = set()  # dates (YYYY-MM-DD IST) already notified

    while True:
        try:
            s = get_settings()
            if s.data_provider == "upstox" and s.ntfy_topic:
                # Current time in IST (UTC+5:30)
                now_utc = asyncio.get_event_loop().time  # monotonic — use datetime
                import datetime as _dt
                now_ist = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=5, minutes=30)
                today_str = now_ist.strftime("%Y-%m-%d")
                hour_min  = (now_ist.hour, now_ist.minute)

                # Fire once at or after 09:00 IST (and not yet notified today).
                if hour_min >= (9, 0) and today_str not in _notified_today:
                    if is_token_expired():
                        logger.info(
                            "morning notifier: 09:00 IST — token expired, sending notification"
                        )
                        sent = notify_login_required(app_url=s.app_frontend_url)
                        if sent:
                            _notified_today.add(today_str)
                            logger.info("morning notifier: notification sent for %s", today_str)
                    else:
                        # Token valid — mark as notified so we don't spam later.
                        _notified_today.add(today_str)
                        logger.debug("morning notifier: token valid at 09:00 — no alert needed")

                # Prune old dates to prevent unbounded set growth.
                _notified_today = {d for d in _notified_today if d >= today_str}

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("morning notifier error: %s", exc)

        try:
            await asyncio.sleep(_NOTIFY_CHECK_SECS)
        except asyncio.CancelledError:
            raise


# ---------------------------------------------------------------------------
# Trading loop
# ---------------------------------------------------------------------------

async def _run_loop() -> None:
    logger.info("paper-trading scheduler: starting")
    while True:
        try:
            opened, closed = engine.tick(reason="scheduler")
            if opened or closed:
                logger.info(
                    "tick: opened=%d closed=%d",
                    len(opened),
                    len(closed),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("scheduler tick failed: %s", exc)

        sleep_for = (
            _TICK_SECONDS_OPEN if engine.is_market_open() else _TICK_SECONDS_CLOSED
        )
        try:
            await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    trade_task  = asyncio.create_task(_run_loop(),         name="paper-trading-scheduler")
    token_task  = asyncio.create_task(_token_watchdog(),   name="upstox-token-watchdog")
    notify_task = asyncio.create_task(_morning_notifier(), name="upstox-morning-notifier")
    try:
        yield
    finally:
        for task in (trade_task, token_task, notify_task):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
