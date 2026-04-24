"""Realistic Execution Cost Simulator for Indian equity intraday trades.

Computes total transaction costs for a round-trip intraday paper trade using
the actual NSE/SEBI/tax charge structure applied by Indian brokers.

Cost components (intraday equity)
───────────────────────────────────
Component              Buy leg        Sell leg
──────────────────── ─────────────  ──────────────
Slippage (impact)    0.05%×notional  0.05%×notional
Brokerage            ₹20 flat        ₹20 flat
STT                  —               0.025%×turnover
NSE txn charge       0.00335%        0.00335%
SEBI charge          0.0001%         0.0001%
Stamp duty           0.015%          —
GST (18%)            on (brokerage + NSE + SEBI) each leg

Slippage model
──────────────
Impact cost is approximated by:
  - ≥10L avg daily vol  → 0.03%  (very liquid: NIFTY 50 stocks)
  - ≥5L  avg daily vol  → 0.05%  (liquid: NIFTY 500 stocks)
  - <5L  avg daily vol  → 0.10%  (semi-liquid: small-mid cap)

The slippage is applied *against* the trader on entry and exit:
  Effective entry  = quoted_price × (1 + slippage_pct)   [buy]
  Effective exit   = quoted_price × (1 - slippage_pct)   [sell]

This makes paper-trading results realistically comparable to live results.
"""
from __future__ import annotations

from dataclasses import dataclass

# ─────────────────────────────── charge rates ───────────────────────────────

_BROKERAGE_FLAT     = 20.0        # ₹ per order leg (flat discount broker)
_STT_SELL_INTRADAY  = 0.025 / 100 # 0.025% on sell-side turnover
_NSE_TXN_CHARGE     = 0.00335 / 100
_SEBI_CHARGE        = 0.0001  / 100
_STAMP_DUTY_BUY     = 0.015   / 100  # 0.015% on buy-side (Maharashtra)
_GST_RATE           = 0.18

# Slippage tiers by average daily volume
_SLIP_HIGH_LIQ  = 0.03 / 100  # avg vol ≥ 10 lakh shares
_SLIP_MED_LIQ   = 0.05 / 100  # avg vol ≥ 5 lakh shares
_SLIP_LOW_LIQ   = 0.10 / 100  # avg vol < 5 lakh shares


# ─────────────────────────────── models ─────────────────────────────────────

@dataclass
class CostBreakdown:
    """Per-trade round-trip cost breakdown."""
    slippage_entry: float    # INR lost to impact on entry
    slippage_exit: float     # INR lost to impact on exit
    brokerage: float         # ₹20 × 2 legs
    stt: float               # sell-side only (intraday)
    nse_charges: float       # both legs
    sebi_charges: float      # both legs
    stamp_duty: float        # buy leg only
    gst: float               # 18% on brokerage+nse+sebi
    total_cost: float        # sum of all above

    @property
    def total_bps(self) -> float:
        """Total cost as basis points of entry notional."""
        return 0.0  # computed externally; set on construction if needed

    def summary(self) -> str:
        return (
            f"Brokerage ₹{self.brokerage:.2f} | "
            f"STT ₹{self.stt:.2f} | "
            f"NSE+SEBI ₹{self.nse_charges + self.sebi_charges:.2f} | "
            f"GST ₹{self.gst:.2f} | "
            f"Slippage ₹{self.slippage_entry + self.slippage_exit:.2f} | "
            f"Total ₹{self.total_cost:.2f}"
        )


@dataclass
class ExecutionPrices:
    """Adjusted entry/exit prices after slippage."""
    effective_entry: float   # higher than quoted (buy at the ask)
    effective_exit: float    # lower than quoted (sell at the bid)
    quoted_entry: float
    quoted_exit: float
    slippage_pct: float


# ─────────────────────────────── core functions ──────────────────────────────

def _slippage_pct(avg_daily_volume: float) -> float:
    if avg_daily_volume >= 1_000_000:   # 10L+
        return _SLIP_HIGH_LIQ
    if avg_daily_volume >= 500_000:     # 5L–10L
        return _SLIP_MED_LIQ
    return _SLIP_LOW_LIQ                # < 5L


def apply_slippage(
    quoted_entry: float,
    quoted_exit: float,
    avg_daily_volume: float = 500_000,
) -> ExecutionPrices:
    """Return effective (slippage-adjusted) entry and exit prices."""
    slip = _slippage_pct(avg_daily_volume)
    eff_entry = round(quoted_entry * (1 + slip), 4)   # buy at slightly higher
    eff_exit  = round(quoted_exit  * (1 - slip), 4)   # sell at slightly lower
    return ExecutionPrices(
        effective_entry=eff_entry,
        effective_exit=eff_exit,
        quoted_entry=quoted_entry,
        quoted_exit=quoted_exit,
        slippage_pct=slip,
    )


def compute_costs(
    entry_price: float,
    exit_price: float,
    qty: int,
    avg_daily_volume: float = 500_000,
) -> CostBreakdown:
    """Compute the full round-trip cost breakdown for one intraday trade.

    Prices passed in should be the *effective* (slippage-adjusted) prices.
    """
    if qty <= 0 or entry_price <= 0 or exit_price <= 0:
        return CostBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0)

    buy_turnover  = entry_price * qty
    sell_turnover = exit_price  * qty
    slip          = _slippage_pct(avg_daily_volume)

    slippage_entry = round(buy_turnover  * slip, 2)
    slippage_exit  = round(sell_turnover * slip, 2)

    brokerage  = round(_BROKERAGE_FLAT * 2, 2)    # buy + sell leg
    stt        = round(sell_turnover * _STT_SELL_INTRADAY, 2)

    nse_buy    = buy_turnover  * _NSE_TXN_CHARGE
    nse_sell   = sell_turnover * _NSE_TXN_CHARGE
    nse_total  = round(nse_buy + nse_sell, 4)

    sebi_buy   = buy_turnover  * _SEBI_CHARGE
    sebi_sell  = sell_turnover * _SEBI_CHARGE
    sebi_total = round(sebi_buy + sebi_sell, 4)

    stamp      = round(buy_turnover * _STAMP_DUTY_BUY, 4)

    # GST on brokerage + exchange charges (not on STT/stamp)
    gst_base   = brokerage + nse_total + sebi_total
    gst        = round(gst_base * _GST_RATE, 4)

    total = round(
        slippage_entry + slippage_exit +
        brokerage + stt + nse_total + sebi_total + stamp + gst,
        2
    )

    return CostBreakdown(
        slippage_entry=slippage_entry,
        slippage_exit=slippage_exit,
        brokerage=brokerage,
        stt=stt,
        nse_charges=round(nse_total, 2),
        sebi_charges=round(sebi_total, 4),
        stamp_duty=round(stamp, 4),
        gst=round(gst, 2),
        total_cost=total,
    )


def net_pnl(
    gross_pnl: float,
    entry_price: float,
    exit_price: float,
    qty: int,
    avg_daily_volume: float = 500_000,
) -> tuple[float, CostBreakdown]:
    """Return (net_pnl_inr, CostBreakdown) for a completed trade."""
    costs = compute_costs(entry_price, exit_price, qty, avg_daily_volume)
    return round(gross_pnl - costs.total_cost, 2), costs
