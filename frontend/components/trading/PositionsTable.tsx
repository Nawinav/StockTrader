"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type Position } from "@/lib/api";

type Props = {
  positions: Position[];
  onChanged: () => void;
};

function pct(p: number): string {
  const sign = p >= 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
}

const HC_GRADE_STYLE: Record<string, string> = {
  "A+": "bg-emerald-600 text-white",
  "A":  "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
  "B":  "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
  "C":  "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
  "D":  "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
};

function PartialProgress({ p }: { p: Position }) {
  const p1Done = p.pp_p1_done ?? false;
  const p2Done = p.pp_p2_done ?? false;
  const p1Price = p.pp_p1_price;
  const p2Price = p.pp_p2_price;

  if (!p1Price && !p2Price) return null;

  return (
    <div className="flex items-center gap-1 mt-1">
      {/* P1 segment */}
      <div
        title={p1Price ? `P1 target ₹${p1Price.toFixed(2)} (book 40%)` : "P1"}
        className={`h-1.5 w-6 rounded-full ${
          p1Done
            ? "bg-emerald-500"
            : "bg-slate-200 dark:bg-slate-700"
        }`}
      />
      {/* P2 segment */}
      <div
        title={p2Price ? `P2 target ₹${p2Price.toFixed(2)} (book 30%)` : "P2"}
        className={`h-1.5 w-6 rounded-full ${
          p2Done
            ? "bg-emerald-500"
            : p1Done
            ? "bg-emerald-200 dark:bg-emerald-900/40"
            : "bg-slate-200 dark:bg-slate-700"
        }`}
      />
      {/* Trail segment */}
      <div
        title="Trail 30% to T2"
        className="h-1.5 w-6 rounded-full bg-slate-200 dark:bg-slate-700"
      />
      <span className="text-[9px] text-slate-400 ml-0.5">
        {p1Done && p2Done ? "trailing" : p1Done ? "P2→" : "P1→"}
      </span>
    </div>
  );
}

export function PositionsTable({ positions, onChanged }: Props) {
  const [closing, setClosing] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const closeOne = async (symbol: string) => {
    setClosing(symbol);
    setErr(null);
    try {
      await api.tradingClose(symbol);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setClosing(null);
    }
  };

  if (positions.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-800 p-8 text-center text-sm text-slate-500 bg-white/50 dark:bg-slate-900/50">
        No open positions. Flip auto-trading on and the engine will enter only
        Grade A / A+ setups scoring ≥ 80/100.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      {err && (
        <div className="px-4 py-2 text-xs text-rose-700 bg-rose-50 dark:bg-rose-950/30 dark:text-rose-300 border-b border-rose-200 dark:border-rose-900">
          {err}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900/80 text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Grade</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">LTP</th>
              <th className="px-3 py-2 text-right">Stop</th>
              <th className="px-3 py-2 text-right">Target</th>
              <th className="px-3 py-2 text-right">P&amp;L</th>
              <th className="px-3 py-2 text-left">Partial Profit</th>
              <th className="px-3 py-2 text-left">Strategies</th>
              <th className="px-3 py-2 text-right"> </th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => {
              const up = p.unrealized_pnl >= 0;
              const grade = p.hc_grade || "";
              const gradeStyle = HC_GRADE_STYLE[grade] || "bg-slate-100 text-slate-500";

              return (
                <tr
                  key={p.symbol}
                  className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50/70 dark:hover:bg-slate-800/50 animate-fade-in-up"
                  style={{ animationDelay: `${i * 25}ms` }}
                >
                  {/* Symbol */}
                  <td className="px-3 py-2">
                    <Link
                      href={`/stocks/${encodeURIComponent(p.symbol)}`}
                      className="font-semibold hover:text-brand-600"
                    >
                      {p.symbol}
                    </Link>
                    <div className="text-[11px] text-slate-500 truncate max-w-[140px]">
                      {p.name}
                    </div>
                  </td>

                  {/* HC Grade */}
                  <td className="px-3 py-2">
                    {grade ? (
                      <div className="flex flex-col items-start gap-0.5">
                        <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${gradeStyle}`}>
                          {grade}
                        </span>
                        {p.hc_score !== undefined && p.hc_score > 0 && (
                          <span className="text-[10px] text-slate-400">{p.hc_score}/100</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>

                  {/* Qty */}
                  <td className="px-3 py-2 text-right tabular-nums">{p.qty}</td>

                  {/* Entry */}
                  <td className="px-3 py-2 text-right tabular-nums">
                    ₹{p.entry_price.toFixed(2)}
                  </td>

                  {/* LTP */}
                  <td className="px-3 py-2 text-right tabular-nums font-semibold">
                    ₹{p.last_price.toFixed(2)}
                  </td>

                  {/* Stop */}
                  <td className="px-3 py-2 text-right tabular-nums text-rose-600 dark:text-rose-400">
                    ₹{p.stop_loss.toFixed(2)}
                  </td>

                  {/* Target */}
                  <td className="px-3 py-2 text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                    ₹{p.target.toFixed(2)}
                  </td>

                  {/* P&L */}
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-semibold ${
                      up
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-rose-600 dark:text-rose-400"
                    }`}
                  >
                    {up ? "+" : ""}₹{p.unrealized_pnl.toFixed(2)}
                    <div className="text-[10px] font-normal opacity-80">
                      {pct(p.unrealized_pct)}
                    </div>
                  </td>

                  {/* Partial profit progress */}
                  <td className="px-3 py-2 text-left">
                    <PartialProgress p={p} />
                  </td>

                  {/* Strategies + confluence */}
                  <td className="px-3 py-2 text-left">
                    {p.confluence_at_entry > 0 ? (
                      <div className="flex flex-col gap-0.5">
                        <span
                          className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded w-fit ${
                            p.confluence_at_entry >= 6
                              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                              : p.confluence_at_entry >= 4
                              ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                              : "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                          }`}
                        >
                          {p.confluence_at_entry}/11
                        </span>
                        {p.strategies_at_entry.length > 0 && (
                          <div className="flex flex-wrap gap-0.5 max-w-[180px]">
                            {p.strategies_at_entry.slice(0, 3).map((s) => (
                              <span
                                key={s}
                                className="text-[9px] px-1 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 font-medium"
                              >
                                {s.replace(/_/g, " ")}
                              </span>
                            ))}
                            {p.strategies_at_entry.length > 3 && (
                              <span className="text-[9px] text-slate-500">
                                +{p.strategies_at_entry.length - 3}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>

                  {/* Close button */}
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => closeOne(p.symbol)}
                      disabled={closing === p.symbol}
                      className="text-[11px] px-2 py-1 rounded border border-slate-300 dark:border-slate-700 hover:bg-rose-50 hover:border-rose-400 dark:hover:bg-rose-950/30 disabled:opacity-50"
                    >
                      {closing === p.symbol ? "…" : "Close"}
                    </button>
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
