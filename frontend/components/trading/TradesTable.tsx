"use client";

import Link from "next/link";
import type { Trade, ExitReason } from "@/lib/api";

type Props = {
  trades: Trade[];
};

const REASON_COLORS: Record<ExitReason, string> = {
  STOP:        "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  TARGET:      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  EOD:         "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  MANUAL:      "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  SIGNAL_FLIP: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  P1:          "bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300",
  P2:          "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300",
  TIME_STOP:   "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
  TRAIL:       "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
};

const REASON_LABEL: Partial<Record<ExitReason, string>> = {
  P1:        "Partial P1",
  P2:        "Partial P2",
  TIME_STOP: "Time Stop",
  TRAIL:     "Trail Stop",
};

const HC_GRADE_STYLE: Record<string, string> = {
  "A+": "bg-emerald-600 text-white",
  "A":  "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
  "B":  "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
  "C":  "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  "D":  "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}

function durationLabel(enteredIso: string, exitedIso: string): string {
  const ms = new Date(exitedIso).getTime() - new Date(enteredIso).getTime();
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function TradesTable({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-800 p-8 text-center text-sm text-slate-500 bg-white/50 dark:bg-slate-900/50">
        No closed trades yet.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Exited</th>
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Grade</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Entry → Exit</th>
              <th className="px-3 py-2 text-right">P&amp;L</th>
              <th className="px-3 py-2 text-left">Reason</th>
              <th className="px-3 py-2 text-left">Strategies</th>
              <th className="px-3 py-2 text-right">Held</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => {
              const up = t.realized_pnl >= 0;
              const grade = t.hc_grade || "";
              const gradeStyle = HC_GRADE_STYLE[grade] || "bg-slate-100 text-slate-500";
              return (
                <tr
                  key={t.id}
                  className="border-t border-slate-100 dark:border-slate-800 animate-fade-in-up"
                  style={{ animationDelay: `${Math.min(i, 20) * 15}ms` }}
                >
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">
                    {formatTime(t.exited_at)}
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/stocks/${encodeURIComponent(t.symbol)}`}
                      className="font-semibold hover:text-brand-600"
                    >
                      {t.symbol}
                    </Link>
                  </td>
                  {/* HC Grade */}
                  <td className="px-3 py-2">
                    {grade ? (
                      <div className="flex flex-col items-start gap-0.5">
                        <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${gradeStyle}`}>
                          {grade}
                        </span>
                        {t.hc_score !== undefined && t.hc_score > 0 && (
                          <span className="text-[10px] text-slate-400">{t.hc_score}/100</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.qty}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600 dark:text-slate-300">
                    ₹{t.entry_price.toFixed(2)} → ₹{t.exit_price.toFixed(2)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-semibold ${
                      up
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-rose-600 dark:text-rose-400"
                    }`}
                  >
                    {up ? "+" : ""}₹{t.realized_pnl.toFixed(2)}
                    <div className="text-[10px] font-normal opacity-80">
                      {up ? "+" : ""}
                      {t.realized_pct.toFixed(2)}%
                    </div>
                    {t.execution_cost !== undefined && t.execution_cost > 0 && (
                      <div className="text-[9px] text-slate-400 font-normal mt-0.5">
                        costs ₹{t.execution_cost.toFixed(0)}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[11px] font-semibold ${REASON_COLORS[t.reason]}`}
                    >
                      {REASON_LABEL[t.reason] ?? t.reason}
                    </span>
                    {t.market_regime && (
                      <div className="text-[9px] text-slate-400 mt-0.5">{t.market_regime}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-left">
                    {t.confluence_at_entry > 0 ? (
                      <div className="flex flex-col gap-0.5">
                        <span
                          className={`inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded w-fit ${
                            t.confluence_at_entry >= 6
                              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                              : t.confluence_at_entry >= 4
                              ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                              : "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                          }`}
                        >
                          {t.confluence_at_entry}/11
                        </span>
                        {t.strategies_at_entry.length > 0 && (
                          <div className="flex flex-wrap gap-0.5 max-w-[180px]">
                            {t.strategies_at_entry.slice(0, 3).map((s) => (
                              <span
                                key={s}
                                className="text-[9px] px-1 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 font-medium"
                              >
                                {s.replace(/_/g, " ")}
                              </span>
                            ))}
                            {t.strategies_at_entry.length > 3 && (
                              <span className="text-[9px] text-slate-500">
                                +{t.strategies_at_entry.length - 3}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-500 tabular-nums">
                    {durationLabel(t.entered_at, t.exited_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
