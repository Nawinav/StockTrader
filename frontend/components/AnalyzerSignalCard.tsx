"use client";

import type { AnalyzerSignal } from "@/lib/api";

const ACTION_COLORS: Record<string, string> = {
  BUY: "bg-emerald-600 text-white",
  SELL: "bg-rose-600 text-white",
  HOLD: "bg-slate-500 text-white",
  EXIT: "bg-amber-600 text-white",
  AVOID: "bg-slate-700 text-white",
};

function ConfidenceBar({ value }: { value: number }) {
  const color =
    value >= 70 ? "bg-emerald-500" : value >= 50 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="w-full h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
      <div
        className={`h-full ${color} transition-all`}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 py-1.5 text-sm">
      <div className="text-slate-500 uppercase text-[11px] tracking-wide pt-0.5">
        {label}
      </div>
      <div className="text-slate-800 dark:text-slate-200">{children}</div>
    </div>
  );
}

export function AnalyzerSignalCard({ signal }: { signal: AnalyzerSignal }) {
  const s = signal;
  const actionClass = ACTION_COLORS[s.action] ?? ACTION_COLORS.HOLD;
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      {/* Header */}
      <div className="p-5 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-2xl font-bold">{s.symbol}</span>
              <span
                className={`px-2.5 py-1 rounded text-sm font-bold ${actionClass}`}
              >
                {s.action}
              </span>
              {s.meta_cached && (
                <span className="text-[10px] uppercase tracking-wide text-slate-500 border border-slate-300 dark:border-slate-700 rounded px-1.5 py-0.5">
                  cached
                </span>
              )}
            </div>
            <div className="text-sm text-slate-500 mt-1">{s.setup_name}</div>
            <div className="text-xs text-slate-400 mt-0.5">{s.timeframe_basis}</div>
            {/* Strategy confluence tags from Claude */}
            {s.strategies_triggered && s.strategies_triggered.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                <span className="text-[10px] text-slate-400 self-center">
                  {s.strategy_confluence_count} strategies:
                </span>
                {s.strategies_triggered.map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 font-medium"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {s.hold_period && (
              <div className="text-[11px] text-slate-500 mt-1">
                Hold: <span className="font-medium">{s.hold_period}</span>
              </div>
            )}
          </div>
          <div className="min-w-[200px] flex-1 max-w-xs">
            <div className="flex justify-between text-[10px] uppercase tracking-wide text-slate-500 mb-1">
              <span>Confidence</span>
              <span>{s.confidence}/100</span>
            </div>
            <ConfidenceBar value={s.confidence} />
            <div className="text-[10px] text-slate-400 mt-1 text-right">
              {s.timestamp_ist} ·{" "}
              {s.meta_provider ?? "?"}
              {s.meta_model ? ` · ${s.meta_model}` : ""}
              {typeof s.meta_latency_ms === "number"
                ? ` · ${s.meta_latency_ms}ms`
                : ""}
            </div>
          </div>
        </div>
      </div>

      {/* Trade plan */}
      <div className="p-5 grid sm:grid-cols-3 gap-4">
        <div className="rounded-lg border border-slate-200 dark:border-slate-800 p-3">
          <div className="text-[10px] uppercase text-slate-500">Entry</div>
          <div className="text-lg font-semibold">
            {s.entry.price !== null ? `₹${s.entry.price.toFixed(2)}` : "Market"}
          </div>
          <div className="text-xs text-slate-500">
            {s.entry.type} · valid till {s.entry.valid_until_ist}
          </div>
        </div>
        <div className="rounded-lg border border-rose-200 dark:border-rose-900/40 p-3">
          <div className="text-[10px] uppercase text-rose-500">Stop loss</div>
          <div className="text-lg font-semibold text-rose-600 dark:text-rose-400">
            ₹{s.stop_loss.price.toFixed(2)}
          </div>
          <div className="text-xs text-slate-500">
            {s.stop_loss.type} · {s.stop_loss.rationale}
          </div>
        </div>
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-900/40 p-3">
          <div className="text-[10px] uppercase text-emerald-600">Position size</div>
          <div className="text-lg font-semibold">
            {s.position_size.quantity} sh
          </div>
          <div className="text-xs text-slate-500">
            Risk ₹{s.position_size.rupee_risk.toFixed(0)} · Exp ₹
            {s.position_size.rupee_exposure.toFixed(0)}
          </div>
        </div>
      </div>

      {/* Targets */}
      <div className="px-5 pb-4">
        <div className="text-[10px] uppercase text-slate-500 mb-2">Targets</div>
        <div className="grid sm:grid-cols-3 gap-2">
          {s.targets.map((t) => (
            <div
              key={t.level}
              className="rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-900/40 p-3"
            >
              <div className="flex items-baseline justify-between">
                <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                  {t.level}
                </span>
                <span className="text-[11px] text-emerald-700 dark:text-emerald-400">
                  {t.rr.toFixed(2)}R
                </span>
              </div>
              <div className="text-lg font-semibold text-emerald-800 dark:text-emerald-200">
                ₹{t.price.toFixed(2)}
              </div>
              <div className="text-xs text-slate-500 leading-tight">
                {t.rationale}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Reasoning */}
      <div className="px-5 py-4 bg-slate-50 dark:bg-slate-950/40 border-t border-slate-100 dark:border-slate-800">
        <div className="text-[10px] uppercase text-slate-500 mb-2">Reasoning</div>
        <Row label="Market">{s.reasoning.market_context}</Row>
        <Row label="Trend align">{s.reasoning.trend_alignment}</Row>
        <Row label="Price action">{s.reasoning.price_action}</Row>
        <Row label="Indicators">{s.reasoning.indicator_confluence}</Row>
        <Row label="Volume">{s.reasoning.volume_confirmation}</Row>
        <Row label="Key levels">{s.reasoning.key_levels}</Row>
        <Row label="Time of day">{s.reasoning.time_of_day}</Row>
      </div>

      {/* Watch / invalidation / flags */}
      <div className="px-5 py-4 grid md:grid-cols-2 gap-4 border-t border-slate-100 dark:border-slate-800">
        <div>
          <div className="text-[10px] uppercase text-slate-500 mb-1">
            What to watch
          </div>
          <ul className="text-sm text-slate-700 dark:text-slate-300 space-y-0.5">
            {s.what_to_watch.map((w, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-slate-400">·</span>
                <span>{w}</span>
              </li>
            ))}
          </ul>
          {s.conflicting_signals.length > 0 && (
            <>
              <div className="text-[10px] uppercase text-slate-500 mt-3 mb-1">
                Conflicting signals
              </div>
              <ul className="text-sm text-amber-700 dark:text-amber-400 space-y-0.5">
                {s.conflicting_signals.map((c, i) => (
                  <li key={i} className="flex gap-2">
                    <span>!</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500 mb-1">Invalidation</div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {s.invalidation}
          </div>
          <div className="text-[10px] uppercase text-slate-500 mt-3 mb-1">
            Trail strategy
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {s.trail_strategy}
          </div>
          {s.risk_flags.length > 0 && (
            <>
              <div className="text-[10px] uppercase text-slate-500 mt-3 mb-1">
                Risk flags
              </div>
              <div className="flex flex-wrap gap-1.5">
                {s.risk_flags.map((f) => (
                  <span
                    key={f}
                    className="text-xs px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="px-5 py-3 bg-slate-100 dark:bg-slate-950 text-[11px] text-slate-500 border-t border-slate-200 dark:border-slate-800">
        Screening assistant output — not investment advice. Always verify
        against live market data before placing orders.
      </div>
    </div>
  );
}
