"""Corporate Event & News Filter.

Prevents the auto-trader from entering positions in the 2-day window before
or after high-impact events that invalidate technical setups:

  1. Earnings / board meeting for Q-results (NSE corporate actions API)
  2. Ex-dividend / ex-bonus / ex-split dates
  3. RBI Monetary Policy Committee (MPC) dates — hardcoded schedule
  4. Union Budget date — hardcoded annually
  5. Index rebalancing weeks (Nifty 50 / Nifty 500 semi-annual review)

The filter is intentionally conservative: "when in doubt, skip the trade."
A missed trade is far less costly than a loss caused by an announcement gap.

NSE API endpoint (corporate announcements, public):
  https://www.nseindia.com/api/corporate-announcements?index=equities

Cache duration: 4 hours (corporate calendars don't change intraday).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 4 * 3600   # 4 hours
EVENT_BLOCK_DAYS  = 2           # block ± N days around event


# ─────────────────────────────────── RBI / Budget calendar ──────────────────
# These dates are known well in advance.  Update at start of each fiscal year.
# Format: YYYY-MM-DD

RBI_MPC_DATES_2025_26: List[str] = [
    # FY 2025-26 MPC meeting dates (announced by RBI)
    "2025-04-07", "2025-04-09",   # April meeting
    "2025-06-04", "2025-06-06",   # June meeting
    "2025-08-05", "2025-08-07",   # August meeting
    "2025-10-07", "2025-10-09",   # October meeting
    "2025-12-03", "2025-12-05",   # December meeting
    "2026-02-04", "2026-02-06",   # February meeting
    # FY 2026-27
    "2026-04-07", "2026-04-09",
    "2026-06-03", "2026-06-05",
    "2026-08-04", "2026-08-06",
    "2026-10-06", "2026-10-08",
    "2026-12-02", "2026-12-04",
    "2027-02-03", "2027-02-05",
]

BUDGET_DATES: List[str] = [
    "2025-02-01",  # Union Budget FY 2025-26
    "2026-02-01",  # Union Budget FY 2026-27
]

# Nifty 50 semi-annual review months (Jan & Jul) — entire week is noisy.
NIFTY_REVIEW_MONTHS = {1, 7}  # Jan, Jul


# ─────────────────────────────────── models ─────────────────────────────────

@dataclass
class EventBlock:
    symbol: str        # NSE symbol, or "" for market-wide events
    event_date: date
    event_type: str    # "EARNINGS" | "EX_DIVIDEND" | "RBI_MPC" | "BUDGET" | "INDEX_REVIEW"
    description: str


@dataclass
class EventFilterResult:
    symbol: str
    blocked: bool
    reasons: List[str] = field(default_factory=list)


# ─────────────────────────────────── cache ───────────────────────────────────

_symbol_events: Dict[str, List[EventBlock]] = {}
_market_events: List[EventBlock] = []
_cache_ts: float = 0.0
_cache_valid: bool = False


def _cache_stale() -> bool:
    return not _cache_valid or (time.monotonic() - _cache_ts) > CACHE_TTL_SECONDS


def _mark_cache_valid() -> None:
    global _cache_ts, _cache_valid
    _cache_ts = time.monotonic()
    _cache_valid = True


# ─────────────────────────────── NSE fetch ──────────────────────────────────

def _fetch_nse_corporate_events() -> List[EventBlock]:
    """Fetch NSE corporate announcements.  Returns [] on any failure."""
    events: List[EventBlock] = []
    urls = [
        "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=&to_date=&symbol=&issuer=&subject=Board+Meeting",
        "https://www.nseindia.com/api/event-calendar",
    ]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    }

    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    continue
                raw = json.loads(resp.read())

            # Both endpoints share a similar shape: list of dicts with 'symbol', 'date'/'exDate'
            items = raw if isinstance(raw, list) else raw.get("data", [])
            for item in items:
                symbol = (item.get("symbol") or item.get("stock_symbol") or "").upper().strip()
                if not symbol:
                    continue
                # Try multiple date field names
                date_str = (
                    item.get("date")
                    or item.get("exDate")
                    or item.get("bm_date")
                    or item.get("recDate")
                    or ""
                )
                if not date_str:
                    continue
                try:
                    # NSE dates come as "DD-MMM-YYYY" or "YYYY-MM-DD"
                    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                        try:
                            ev_date = datetime.strptime(date_str[:11], fmt).date()
                            break
                        except ValueError:
                            continue
                    else:
                        continue
                except Exception:
                    continue

                subject = (item.get("subject") or item.get("purpose") or "").upper()
                etype = "EARNINGS" if any(
                    k in subject for k in ("BOARD MEETING", "FINANCIAL RESULT", "QUARTERLY")
                ) else "EX_DIVIDEND" if any(
                    k in subject for k in ("EX-DIVIDEND", "EX-BONUS", "EX-SPLIT", "EX-RIGHT")
                ) else "CORPORATE_ACTION"

                events.append(EventBlock(
                    symbol=symbol,
                    event_date=ev_date,
                    event_type=etype,
                    description=subject[:80],
                ))

        except Exception as exc:
            logger.debug("NSE corporate fetch from %s failed: %s", url, exc)

    return events


# ───────────────────────────── rebuild cache ─────────────────────────────────

def _rebuild_cache() -> None:
    global _symbol_events, _market_events

    new_symbol: Dict[str, List[EventBlock]] = {}
    new_market: List[EventBlock] = []

    # 1. NSE corporate events
    for ev in _fetch_nse_corporate_events():
        new_symbol.setdefault(ev.symbol, []).append(ev)

    # 2. RBI MPC dates
    today = date.today()
    for ds in RBI_MPC_DATES_2025_26:
        try:
            d = date.fromisoformat(ds)
            if abs((d - today).days) <= 30:  # only keep near-term events
                new_market.append(EventBlock(
                    symbol="",
                    event_date=d,
                    event_type="RBI_MPC",
                    description="RBI Monetary Policy Committee meeting",
                ))
        except ValueError:
            pass

    # 3. Budget dates
    for ds in BUDGET_DATES:
        try:
            d = date.fromisoformat(ds)
            if abs((d - today).days) <= 30:
                new_market.append(EventBlock(
                    symbol="",
                    event_date=d,
                    event_type="BUDGET",
                    description="Union Budget announcement",
                ))
        except ValueError:
            pass

    _symbol_events = new_symbol
    _market_events = new_market
    _mark_cache_valid()
    logger.info(
        "Event filter cache rebuilt: %d symbols, %d market events",
        len(_symbol_events), len(_market_events),
    )


def _ensure_cache() -> None:
    if _cache_stale():
        try:
            _rebuild_cache()
        except Exception as exc:
            logger.warning("Event filter cache rebuild failed: %s", exc)
            _mark_cache_valid()  # Don't retry every tick on persistent failure


# ─────────────────────────────────── public API ─────────────────────────────

def check(symbol: str, check_date: Optional[date] = None) -> EventFilterResult:
    """Return whether ``symbol`` should be blocked today due to a nearby event.

    Uses a ±EVENT_BLOCK_DAYS window around each event date.
    Market-wide events (RBI, Budget) block ALL symbols.
    """
    _ensure_cache()

    today = check_date or date.today()
    reasons: List[str] = []

    def _in_window(ev_date: date) -> bool:
        return abs((ev_date - today).days) <= EVENT_BLOCK_DAYS

    # Market-wide events
    for ev in _market_events:
        if _in_window(ev.event_date):
            delta = (ev.event_date - today).days
            direction = f"in {delta}d" if delta > 0 else f"{abs(delta)}d ago"
            reasons.append(
                f"{ev.event_type} {direction}: {ev.description}"
            )

    # Index rebalancing months — flag but don't hard-block (softer warning)
    if today.month in NIFTY_REVIEW_MONTHS and today.day <= 20:
        reasons.append("Nifty 50 semi-annual review month — reduced confidence")

    # Symbol-specific events
    for ev in _symbol_events.get(symbol.upper(), []):
        if _in_window(ev.event_date):
            delta = (ev.event_date - today).days
            direction = f"in {delta}d" if delta > 0 else f"{abs(delta)}d ago"
            reasons.append(
                f"{ev.event_type} {direction}: {ev.description}"
            )

    blocked = len(reasons) > 0
    return EventFilterResult(symbol=symbol, blocked=blocked, reasons=reasons)


def upcoming_events(symbol: str, days_ahead: int = 7) -> List[EventBlock]:
    """Return events for *symbol* within the next N days."""
    _ensure_cache()
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    result: List[EventBlock] = []
    for ev in _symbol_events.get(symbol.upper(), []) + _market_events:
        if today <= ev.event_date <= cutoff:
            result.append(ev)
    return sorted(result, key=lambda e: e.event_date)


def invalidate_cache() -> None:
    global _cache_valid
    _cache_valid = False
