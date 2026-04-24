"use client";

import { useMemo } from "react";
import type { Trade } from "@/lib/api";

type Props = {
  startingCapital: number;
  currentEquity: number;
  trades: Trade[];
  height?: number;
};

/**
 * Minimal inline SVG equity curve.
 *
 * X-axis is trade sequence (oldest → newest), not time, to keep the
 * shape readable even with sparse data. Last point is the current live
 * equity so the curve always ends at "now".
 */
export function EquityChart({
  startingCapital,
  currentEquity,
  trades,
  height = 120,
}: Props) {
  const points = useMemo(() => {
    // trades arrive newest-first; reverse for cumulative math.
    const ordered = [...trades].reverse();
    const pts: number[] = [startingCapital];
    let running = startingCapital;
    for (const t of ordered) {
      running += t.realized_pnl;
      pts.push(running);
    }
    // Push current equity (may differ from running because of unrealized P&L).
    pts.push(currentEquity);
    return pts;
  }, [trades, startingCapital, currentEquity]);

  if (points.length < 2) {
    return (
      <div
        className="rounded-xl border border-dashed border-slate-300 dark:border-slate-800 flex items-center justify-center text-xs text-slate-500"
        style={{ height }}
      >
        Equity curve shows once trades close.
      </div>
    );
  }

  const w = 600;
  const h = height;
  const pad = 6;
  const min = Math.min(...points, startingCapital);
  const max = Math.max(...points, startingCapital);
  const range = Math.max(1, max - min);

  const step = (w - pad * 2) / (points.length - 1);
  const toY = (v: number) => pad + (1 - (v - min) / range) * (h - pad * 2);

  const path = points
    .map((v, i) => `${i === 0 ? "M" : "L"} ${pad + i * step},${toY(v)}`)
    .join(" ");

  const base = toY(startingCapital);
  const last = points[points.length - 1];
  const ended = points[points.length - 1];
  const up = ended >= startingCapital;
  const lineColor = up ? "#10b981" : "#ef4444";
  const fillColor = up ? "url(#grad-up)" : "url(#grad-down)";

  // Build an area path under the line for the gradient fill.
  const area = `${path} L ${pad + (points.length - 1) * step},${h - pad} L ${pad},${h - pad} Z`;

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3 relative">
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">
            Equity curve
          </div>
          <div className="text-sm font-bold tabular-nums">
            ₹{Math.round(last).toLocaleString("en-IN")}{" "}
            <span
              className={`text-xs font-semibold ${
                up
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {up ? "▲" : "▼"} ₹
              {Math.round(last - startingCapital).toLocaleString("en-IN")}
            </span>
          </div>
        </div>
        <div className="text-[11px] text-slate-500">
          {points.length - 1} {points.length === 2 ? "tick" : "trades"}
        </div>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
      >
        <defs>
          <linearGradient id="grad-up" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#10b981" stopOpacity="0.35" />
            <stop offset="1" stopColor="#10b981" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="grad-down" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ef4444" stopOpacity="0.35" />
            <stop offset="1" stopColor="#ef4444" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line
          x1={pad}
          x2={w - pad}
          y1={base}
          y2={base}
          stroke="currentColor"
          strokeDasharray="3 3"
          className="text-slate-300 dark:text-slate-700"
          strokeWidth="1"
        />
        <path d={area} fill={fillColor} />
        <path d={path} fill="none" stroke={lineColor} strokeWidth="2" />
      </svg>
    </div>
  );
}
