"""Push notifications via ntfy.sh.

ntfy is a free, open-source pub/sub notification service.  Users subscribe
to a **topic** (any random string) and receive instant push notifications on
Android, iOS (via ntfy app), or the browser.

Setup (one-time):
  1. Install the "ntfy" app on your phone.
  2. Subscribe to a topic of your choice, e.g. ``naveen-trading-alerts``.
  3. Set in .env:
       NTFY_TOPIC=naveen-trading-alerts
       # optionally, for a self-hosted server:
       # NTFY_SERVER=https://ntfy.sh

  4. That's it — no account needed for ntfy.sh public topics.

Security note: anyone who knows your topic can subscribe to it.  Use a
long, random string (like a UUID) as the topic name for privacy.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_notification(
    title: str,
    message: str,
    priority: str = "default",   # min | low | default | high | urgent
    tags: Optional[list[str]] = None,
    actions: Optional[list[dict]] = None,
) -> bool:
    """Send a push notification via ntfy.sh (or self-hosted server).

    Returns True on success, False on any error (never raises so callers don't
    need try/except).
    """
    s = get_settings()
    if not s.ntfy_topic:
        logger.debug("ntfy: NTFY_TOPIC not set — skipping notification")
        return False

    server = (s.ntfy_server or "https://ntfy.sh").rstrip("/")
    url    = f"{server}/{s.ntfy_topic}"

    headers: dict[str, str] = {
        "Title":    title,
        "Priority": priority,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    # ntfy supports click-action buttons (for linking to your app URL, etc.)
    if actions:
        import json
        headers["Actions"] = json.dumps(actions)

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, content=message.encode(), headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "ntfy notification failed (%s): %s",
                resp.status_code, resp.text[:200],
            )
            return False
        logger.info("ntfy: notification sent to topic '%s'", s.ntfy_topic)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("ntfy: send_notification error: %s", exc)
        return False


def notify_login_required(app_url: Optional[str] = None) -> bool:
    """Send the 'Login required for live trading' morning alert."""
    s = get_settings()
    topic = s.ntfy_topic or ""
    if not topic:
        return False

    base_url = (app_url or "http://localhost:3000").rstrip("/")
    trading_url = f"{base_url}/trading"

    return send_notification(
        title="📈 Upstox Login Required",
        message=(
            "Your Upstox token has expired.\n\n"
            "Open the trading app and click 'Login' to enter today's OTP "
            "so live trading can continue."
        ),
        priority="high",
        tags=["warning", "chart_with_upwards_trend"],
        actions=[
            {
                "action": "view",
                "label":  "Open Trading App",
                "url":    trading_url,
                "clear":  True,
            }
        ],
    )
