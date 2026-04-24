"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type PortfolioSnapshot } from "@/lib/api";

/**
 * Compact header widget with live portfolio state.
 *
 * Polls `/api/trading/state` every 30s. Silently hides if the endpoint
 * errors (e.g. backend down) to avoid spamming the header with errors.
 */
export function PortfolioPill() {
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [err, setErr] = useState(false);
  const prevEquityRef = useRef<number | null>(null);
  const [pulse, setPulse] = useState<"up" | "down" | null>(null);

  useEffect(() => {
    let stopped = false;
    async function load() {
      try {
        const s = await api.tradingState();
        if (stopped) return;
        setErr(false);
        // Flash equity up/down when it moves.
        if (prevEquityRef.current !== null) {
          const delta = s.equity - prevEquityRef.current;
          if (Math.abs(delta) > 0.5) {
            setPulse(delta >= 0 ? "up" : "down");
            setTimeout(() => setPulse(null), 900);
          }
        }
        prevEquityRef.current = s.equity;
        setSnap(s);
      } catch {
        if (!stopped) setErr(true);
      }
    }
    load();
    const id = setInterval(load, 30_000);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, []);

  if (err || !snap) return null;

  const dayPnl = snap.realized_pnl_today + snap.unrealized_pnl;
  const dayUp = dayPnl >= 0;
  const pulseBg =
    pulse === "up"
      ? "bg-emerald-50 dark:bg-emerald-950/40"
      : pulse === "down"
        ? "bg-rose-50 dark:bg-rose-950/40"
        : "";

  return (
    <Link
      href="/trading"
      title={`Paper trading · ${snap.auto_trading_enabled ? "AUTO ON" : "auto off"} · tick: ${snap.last_tick_at ? new Date(snap.last_tick_at).toLocaleTimeString() : "—"}`}
      className={`hidden sm:inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-slate-300 dark:border-slate-700 hover:border-brand-500 text-[11px] transition-colors ${pulseBg}`}
    >
      <span className="inline-flex items-center gap-1">
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full ${
            snap.auto_trading_enabled
              ? "bg-emerald-500 animate-pulse"
              : "bg-slate-400"
          }`}
        />
        <span className="uppercase font-bold tracking-wide text-slate-500">
          {snap.paper_trading ? "Paper" : "LIVE"}
        </span>
      </span>
      <span className="text-slate-400">·</span>
      <span className="font-semibold tabular-nums">
        ₹{Math.round(snap.equity).toLocaleString("en-IN")}
      </span>
      <span
        className={`font-semibold tabular-nums ${
          dayUp
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-rose-600 dark:text-rose-400"
        }`}
      >
        {dayUp ? "+" : ""}
        ₹{Math.round(dayPnl).toLocaleString("en-IN")}
      </span>
      {snap.positions.length > 0 && (
        <span className="text-slate-500">
          · {snap.positions.length} open
        </span>
      )}
    </Link>
  );
}
