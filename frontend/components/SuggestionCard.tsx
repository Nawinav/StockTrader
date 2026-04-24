"use client";

import { useState } from "react";
import Link from "next/link";
import type { Suggestion, WatchlistItem } from "@/lib/api";
import { api } from "@/lib/api";

type Props = {
  suggestion: Suggestion;
  rank: number;
  onWatchlistChange?: (items: WatchlistItem[]) => void;
  inWatchlist?: boolean;
};

const ACTION_COLORS: Record<string, string> = {
  BUY: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  SELL: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
  HOLD: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
};

function scoreColor(score: number): string {
  if (score >= 70) return "text-emerald-600 dark:text-emerald-400";
  if (score <= 35) return "text-rose-600 dark:text-rose-400";
  return "text-amber-600 dark:text-amber-400";
}

export function SuggestionCard({
  suggestion: s,
  rank,
  onWatchlistChange,
  inWatchlist = false,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [watched, setWatched] = useState(inWatchlist);
  const [error, setError] = useState<string | null>(null);

  const toggleWatch = async () => {
    setAdding(true);
    setError(null);
    try {
      if (watched) {
        await api.removeWatchlist(s.symbol);
        setWatched(false);
      } else {
        await api.addWatchlist(s.symbol);
        setWatched(true);
      }
      if (onWatchlistChange) {
        const res = await api.listWatchlist();
        onWatchlistChange(res.items);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="group rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5 hover:border-slate-300 dark:hover:border-slate-700">
      <div className="p-4 flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-xs font-bold text-slate-600 dark:text-slate-300 shrink-0">
            {rank}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-lg">{s.symbol}</span>
              <span
                className={`px-2 py-0.5 rounded text-xs font-semibold ${ACTION_COLORS[s.action]}`}
              >
                {s.action}
              </span>
              <span className="text-xs text-slate-500">{s.sector}</span>
            </div>
            <div className="text-sm text-slate-600 dark:text-slate-400 truncate">
              {s.name}
            </div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className={`text-2xl font-bold ${scoreColor(s.score.composite)}`}>
            {s.score.composite.toFixed(0)}
          </div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            score
          </div>
        </div>
      </div>

      <div className="px-4 pb-3 grid grid-cols-3 gap-2 text-sm">
        <div>
          <div className="text-[10px] uppercase text-slate-500">Entry</div>
          <div className="font-semibold">₹{s.entry.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">Stop</div>
          <div className="font-semibold text-rose-600 dark:text-rose-400">
            ₹{s.stop_loss.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">Target</div>
          <div className="font-semibold text-emerald-600 dark:text-emerald-400">
            ₹{s.target.toFixed(2)}
          </div>
        </div>
      </div>

      <div className="px-4 pb-3 flex flex-wrap gap-3 text-xs text-slate-500 border-t border-slate-100 dark:border-slate-800 pt-3">
        <span>
          Tech <span className={`font-semibold ${scoreColor(s.score.technical)}`}>{s.score.technical.toFixed(0)}</span>
        </span>
        <span>
          Fund <span className={`font-semibold ${scoreColor(s.score.fundamental)}`}>{s.score.fundamental.toFixed(0)}</span>
        </span>
        <span>RSI {s.technical.rsi.toFixed(0)}</span>
        <span>Vol {s.technical.volume_ratio.toFixed(1)}x</span>
        <span
          className={
            s.expected_return_pct >= 0
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-rose-600 dark:text-rose-400"
          }
        >
          {s.expected_return_pct >= 0 ? "+" : ""}
          {s.expected_return_pct.toFixed(1)}%
        </span>
      </div>

      <div className="px-4 pb-4 flex gap-2 flex-wrap">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs px-3 py-1.5 rounded border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          {expanded ? "Hide signals" : "Show signals"}
        </button>
        <button
          onClick={toggleWatch}
          disabled={adding}
          className={`text-xs px-3 py-1.5 rounded border disabled:opacity-50 ${
            watched
              ? "border-amber-400 text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30"
              : "border-brand-500 text-brand-600 hover:bg-brand-50 dark:hover:bg-brand-950/30"
          }`}
        >
          {adding
            ? "…"
            : watched
              ? "★ In watchlist"
              : "☆ Add to watchlist"}
        </button>
        <Link
          href={`/analyze/${encodeURIComponent(s.symbol)}`}
          className="text-xs px-3 py-1.5 rounded border border-brand-500 text-brand-600 hover:bg-brand-50 dark:hover:bg-brand-950/30"
        >
          Analyze (Claude)
        </Link>
        {error && <span className="text-xs text-rose-600 self-center">{error}</span>}
      </div>

      {expanded && (
        <div className="px-4 pb-4 text-xs space-y-1 border-t border-slate-100 dark:border-slate-800 pt-3">
          <div className="font-semibold text-slate-700 dark:text-slate-300 mb-1">
            Signals
          </div>
          <ul className="list-disc ml-5 space-y-0.5 text-slate-600 dark:text-slate-400">
            {s.score.signals.map((sig, i) => (
              <li key={i}>{sig}</li>
            ))}
          </ul>
          <div className="font-semibold text-slate-700 dark:text-slate-300 mt-3 mb-1">
            Fundamentals
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-slate-600 dark:text-slate-400">
            <span>P/E: {s.fundamental.pe.toFixed(1)}</span>
            <span>P/B: {s.fundamental.pb.toFixed(1)}</span>
            <span>ROE: {s.fundamental.roe.toFixed(1)}%</span>
            <span>D/E: {s.fundamental.debt_to_equity.toFixed(2)}</span>
            <span>EPS g: {s.fundamental.eps_growth_3y.toFixed(1)}%</span>
            <span>Rev g: {s.fundamental.revenue_growth_3y.toFixed(1)}%</span>
            <span>Div Y: {s.fundamental.dividend_yield.toFixed(2)}%</span>
            <span>Prom: {s.fundamental.promoter_holding.toFixed(1)}%</span>
          </div>
        </div>
      )}
    </div>
  );
}
