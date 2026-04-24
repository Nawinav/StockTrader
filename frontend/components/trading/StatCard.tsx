"use client";

import { useEffect, useRef, useState } from "react";

type Tone = "neutral" | "up" | "down" | "brand";

type Props = {
  label: string;
  value: number;
  /** Smaller second-line text, e.g. "today" or "cash" */
  sub?: string;
  tone?: Tone;
  isCurrency?: boolean;
  decimals?: number;
};

function format(value: number, isCurrency: boolean, decimals: number): string {
  const n = value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return isCurrency ? `₹${n}` : n;
}

/**
 * Flashes briefly when the value changes, to signal live data.
 */
export function StatCard({
  label,
  value,
  sub,
  tone = "neutral",
  isCurrency = true,
  decimals = 0,
}: Props) {
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);

  useEffect(() => {
    if (prev.current !== null) {
      const delta = value - prev.current;
      if (Math.abs(delta) > 0.01) {
        setFlash(delta >= 0 ? "up" : "down");
        const id = setTimeout(() => setFlash(null), 700);
        return () => clearTimeout(id);
      }
    }
    prev.current = value;
  }, [value]);

  const baseColor =
    tone === "up"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "down"
        ? "text-rose-600 dark:text-rose-400"
        : tone === "brand"
          ? "text-brand-600 dark:text-brand-500"
          : "text-slate-800 dark:text-slate-100";

  const flashBg =
    flash === "up"
      ? "ring-emerald-400/60 bg-emerald-50/60 dark:bg-emerald-950/30"
      : flash === "down"
        ? "ring-rose-400/60 bg-rose-50/60 dark:bg-rose-950/30"
        : "ring-transparent";

  return (
    <div
      className={`rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3 transition-all duration-300 ring-1 ${flashBg}`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">
        {label}
      </div>
      <div className={`text-2xl font-bold tabular-nums ${baseColor}`}>
        {format(value, isCurrency, decimals)}
      </div>
      {sub && (
        <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>
      )}
    </div>
  );
}
