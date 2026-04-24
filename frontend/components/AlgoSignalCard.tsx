"use client";

import type { AlgoIndependentVote, AlgoSignal, AlgoStrategyDetail } from "@/lib/api";

// ─────────────────────────────────── colour palettes ────────────────────────

const ACTION_STYLE: Record<string, string> = {
  BUY:   "bg-emerald-600 text-white",
  SELL:  "bg-rose-600   text-white",
  HOLD:  "bg-amber-500  text-white",
  AVOID: "bg-slate-600  text-white",
};

const CONFIDENCE_STYLE: Record<string, string> = {
  HIGH:   "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700",
  MEDIUM: "bg-amber-100  text-amber-800  border-amber-300  dark:bg-amber-900/30  dark:text-amber-300  dark:border-amber-700",
  LOW:    "bg-slate-100  text-slate-700  border-slate-300  dark:bg-slate-800     dark:text-slate-400  dark:border-slate-600",
};

const DIR_DOT: Record<number, string> = {
  1:  "bg-emerald-500",
  "-1": "bg-rose-500",
  0:  "bg-slate-400",
};

// ─────────────────────────────────── sub-components ─────────────────────────

function PriceBox({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "green" | "red" | "slate" | "blue";
}) {
  const border =
    accent === "green"
      ? "border-emerald-300 dark:border-emerald-800"
      : accent === "red"
      ? "border-rose-300 dark:border-rose-800"
      : accent === "blue"
      ? "border-sky-300 dark:border-sky-800"
      : "border-slate-200 dark:border-slate-700";
  const text =
    accent === "green"
      ? "text-emerald-700 dark:text-emerald-300"
      : accent === "red"
      ? "text-rose-600 dark:text-rose-400"
      : accent === "blue"
      ? "text-sky-700 dark:text-sky-300"
      : "text-slate-800 dark:text-slate-200";
  const label_c =
    accent === "green"
      ? "text-emerald-600"
      : accent === "red"
      ? "text-rose-500"
      : accent === "blue"
      ? "text-sky-600"
      : "text-slate-500";

  return (
    <div className={`rounded-lg border ${border} p-3`}>
      <div className={`text-[10px] uppercase tracking-wide ${label_c}`}>{label}</div>
      <div className={`text-xl font-bold ${text}`}>₹{value.toFixed(2)}</div>
    </div>
  );
}

function StrategyRow({ s }: { s: AlgoStrategyDetail }) {
  const dotClass = DIR_DOT[s.direction] ?? DIR_DOT[0];
  const textClass =
    s.direction === 1
      ? "text-emerald-700 dark:text-emerald-400"
      : s.direction === -1
      ? "text-rose-600 dark:text-rose-400"
      : "text-slate-500";

  return (
    <div className="flex items-start gap-2.5 py-1.5 border-b border-slate-100 dark:border-slate-800 last:border-0">
      <span
        className={`mt-1 flex-shrink-0 w-2 h-2 rounded-full ${dotClass}`}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
            {s.name}
          </span>
          <span
            className={`text-[10px] font-bold uppercase tracking-wide ${textClass}`}
          >
            {s.direction_label}
          </span>
          <code className="text-[9px] px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
            {s.tag}
          </code>
        </div>
        <div className="text-xs text-slate-500 leading-snug mt-0.5">{s.reason}</div>
      </div>
    </div>
  );
}

function IndicatorPill({
  label,
  value,
}: {
  label: string;
  value: string | number | null;
}) {
  if (value === null || value === undefined) return null;
  return (
    <div className="flex flex-col items-center px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 min-w-[72px]">
      <span className="text-[9px] uppercase tracking-wide text-slate-400 text-center">
        {label}
      </span>
      <span className="text-sm font-semibold text-slate-800 dark:text-slate-200 mt-0.5">
        {typeof value === "number" ? value.toFixed(2) : value}
      </span>
    </div>
  );
}

function ConfluenceBar({ count }: { count: number }) {
  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: 9 }).map((_, i) => (
        <div
          key={i}
          className={`h-2 flex-1 rounded-full transition-colors ${
            i < count
              ? count >= 4
                ? "bg-emerald-500"
                : count >= 3
                ? "bg-amber-500"
                : "bg-slate-400"
              : "bg-slate-200 dark:bg-slate-700"
          }`}
        />
      ))}
      <span className="text-[11px] text-slate-500 ml-1 tabular-nums">
        {count}/9
      </span>
    </div>
  );
}

// ─────────────────────────────────── main card ──────────────────────────────

export function AlgoSignalCard({ signal }: { signal: AlgoSignal }) {
  const s = signal;
  const actionClass = ACTION_STYLE[s.action] ?? ACTION_STYLE.AVOID;
  const confClass   = CONFIDENCE_STYLE[s.confidence] ?? CONFIDENCE_STYLE.LOW;
  const snap = s.indicators_snapshot ?? {};

  const bullishCount = s.strategy_details.filter((d) => d.direction === 1).length;
  const bearishCount = s.strategy_details.filter((d) => d.direction === -1).length;

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-sm">

      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="p-5 border-b border-slate-100 dark:border-slate-800 bg-gradient-to-r from-slate-50 dark:from-slate-900 to-transparent">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          {/* Left: symbol + action */}
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-2xl font-bold tracking-tight">{s.stock}</span>
              <span className={`px-3 py-1 rounded-lg text-sm font-bold ${actionClass}`}>
                {s.action}
              </span>
              <span
                className={`px-2 py-0.5 rounded border text-[11px] font-semibold ${confClass}`}
              >
                {s.confidence}
              </span>
              {s.meta_cached && (
                <span className="text-[10px] uppercase tracking-wide text-slate-400 border border-slate-300 dark:border-slate-600 rounded px-1.5 py-0.5">
                  cached
                </span>
              )}
            </div>
            <div className="text-xs text-slate-500 mt-1.5">
              {s.hold_period} &middot; R:R {s.risk_reward_ratio} &middot;{" "}
              {s.date} {s.time} IST
              {typeof s.meta_latency_ms === "number" &&
                ` · ${s.meta_latency_ms}ms`}
            </div>
          </div>
          {/* Right: confluence bar */}
          <div className="min-w-[200px] flex-1 max-w-xs">
            <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">
              Strategy Confluence ({s.strategy_confluence_count} agreeing)
            </div>
            <ConfluenceBar count={s.strategy_confluence_count} />
            <div className="flex gap-3 mt-1.5 text-[10px] text-slate-500">
              <span className="text-emerald-600">▲ {bullishCount} bullish</span>
              <span className="text-rose-500">▼ {bearishCount} bearish</span>
              <span>{9 - bullishCount - bearishCount} neutral</span>
            </div>
          </div>
        </div>

        {/* Strategy tags */}
        {s.strategies_triggered.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {s.strategies_triggered.map((tag) => (
              <span
                key={tag}
                className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                  s.action === "BUY"
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800"
                    : s.action === "SELL"
                    ? "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/20 dark:text-rose-300 dark:border-rose-800"
                    : "bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400"
                }`}
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ── Price levels ──────────────────────────────────────────────── */}
      <div className="p-5 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <PriceBox label="Entry" value={s.entry_price} accent="slate" />
        <PriceBox label="Stop Loss" value={s.stop_loss} accent="red" />
        <PriceBox label="Target 1 · 50%" value={s.target_1} accent="green" />
        <PriceBox label="Target 2 · 50%" value={s.target_2} accent="blue" />
      </div>

      {/* ── Position sizing ───────────────────────────────────────────── */}
      <div className="px-5 pb-4">
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 bg-slate-50 dark:bg-slate-800/40">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-[10px] uppercase text-slate-400 mb-0.5">Quantity</div>
              <div className="font-bold text-base">{s.suggested_position_size_units} sh</div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-400 mb-0.5">Risk %</div>
              <div className="font-bold text-base">{s.risk_per_trade_percent}%</div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-400 mb-0.5">Risk ₹</div>
              <div className="font-bold text-base">
                ₹{(s.suggested_position_size_units * Math.abs(s.entry_price - s.stop_loss)).toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-400 mb-0.5">Exposure ₹</div>
              <div className="font-bold text-base">
                ₹{(s.suggested_position_size_units * s.entry_price).toFixed(0)}
              </div>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700 text-xs text-slate-600 dark:text-slate-400">
            <span className="font-medium">Book Profit: </span>
            {s.book_profit_instruction}
          </div>
        </div>
      </div>

      {/* ── Reason ────────────────────────────────────────────────────── */}
      <div className="px-5 pb-4">
        <div className="text-[10px] uppercase text-slate-400 mb-1.5">Signal Reason</div>
        <div className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
          {s.reason}
        </div>
      </div>

      {/* ── Live indicator snapshot ───────────────────────────────────── */}
      {Object.keys(snap).length > 0 && (
        <div className="px-5 pb-4">
          <div className="text-[10px] uppercase text-slate-400 mb-2">
            Live Indicators
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { label: "LTP", key: "ltp" },
              { label: "VWAP", key: "vwap" },
              { label: "RSI 15m", key: "rsi_15m" },
              { label: "ADX 15m", key: "adx_15m" },
              { label: "Vol×", key: "vol_ratio_5m" },
              { label: "MFI", key: "mfi_5m" },
              { label: "BB %B", key: "bb_pctb_15m" },
              { label: "MACD H", key: "macd_hist_15m" },
              { label: "Gap%", key: "gap_pct" },
            ].map(({ label, key }) =>
              snap[key] !== undefined ? (
                <IndicatorPill key={key} label={label} value={snap[key] as number} />
              ) : null
            )}
            {snap["gap_type"] && (
              <IndicatorPill label="Gap" value={snap["gap_type"] as string} />
            )}
            {snap["daily_trend"] && (
              <IndicatorPill label="Daily trend" value={snap["daily_trend"] as string} />
            )}
          </div>
        </div>
      )}

      {/* ── 9-Strategy breakdown ─────────────────────────────────────── */}
      {s.strategy_details.length > 0 && (
        <div className="px-5 pb-4">
          <div className="text-[10px] uppercase text-slate-400 mb-2">
            All 9 Strategies
          </div>
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {s.strategy_details.map((detail) => (
                <div key={detail.tag} className="px-3 py-0.5">
                  <StrategyRow s={detail} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Market Regime & Enhancement Layers ───────────────────────── */}
      {(s.market_regime || (s.independent_votes && s.independent_votes.length > 0) || s.event_blocked) && (
        <div className="px-5 pb-4 space-y-3">
          {/* Regime */}
          {s.market_regime && s.market_regime !== "UNKNOWN" && (
            <div>
              <div className="text-[10px] uppercase text-slate-400 mb-1.5">Market Regime</div>
              <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[11px] font-semibold ${
                s.market_regime === "BULL_TREND"
                  ? "bg-emerald-50 text-emerald-800 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700"
                  : s.market_regime === "BEAR_TREND"
                  ? "bg-rose-50 text-rose-800 border-rose-300 dark:bg-rose-900/30 dark:text-rose-300 dark:border-rose-700"
                  : s.market_regime === "HIGH_VOLATILITY"
                  ? "bg-orange-50 text-orange-800 border-orange-300 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-700"
                  : "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700"
              }`}>
                {s.market_regime.replace("_", " ")}
                {s.regime_min_confluence && s.regime_min_confluence > 3 && (
                  <span className="font-normal opacity-80">
                    · confluence raised to ≥{s.regime_min_confluence}
                  </span>
                )}
                {s.regime_disabled_strategies && s.regime_disabled_strategies.length > 0 && (
                  <span className="font-normal opacity-70 text-[10px]">
                    · disabled: {s.regime_disabled_strategies.join(", ")}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Independent votes */}
          {s.independent_votes && s.independent_votes.length > 0 && (
            <div>
              <div className="text-[10px] uppercase text-slate-400 mb-1.5">
                Independent Signals (non-OHLCV)
              </div>
              <div className="rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
                {s.independent_votes.map((v: AlgoIndependentVote) => (
                  <div key={v.tag} className="flex items-start gap-3 px-3 py-2 border-b last:border-b-0 border-slate-100 dark:border-slate-800">
                    <span className={`mt-0.5 inline-block w-2 h-2 rounded-full flex-shrink-0 ${
                      v.direction === 1 ? "bg-emerald-500" : v.direction === -1 ? "bg-rose-500" : "bg-slate-400"
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">{v.name}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                          v.direction === 1
                            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                            : v.direction === -1
                            ? "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300"
                            : "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-400"
                        }`}>{v.direction_label}</span>
                        {!v.data_available && (
                          <span className="text-[10px] text-slate-400">· live data unavailable</span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{v.reason}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Event filter */}
          {s.event_blocked && s.event_reasons && s.event_reasons.length > 0 && (
            <div className="rounded-xl border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-900/20 p-4">
              <div className="text-[10px] uppercase font-semibold text-rose-700 dark:text-rose-300 mb-1.5">
                🚫 Entry Blocked — Corporate/Market Event
              </div>
              <ul className="space-y-1">
                {s.event_reasons.map((r: string, i: number) => (
                  <li key={i} className="text-xs text-rose-800 dark:text-rose-300 flex gap-2">
                    <span>·</span><span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ── Pre-trade filter status ───────────────────────────────────── */}
      {!s.pre_trade_filters_passed && s.filter_failures.length > 0 && (
        <div className="px-5 pb-4">
          <div className="rounded-xl border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4">
            <div className="text-[10px] uppercase font-semibold text-amber-700 dark:text-amber-400 mb-2">
              ⚠ Pre-trade Filter Failures
            </div>
            <ul className="space-y-1">
              {s.filter_failures.map((f, i) => (
                <li key={i} className="text-xs text-amber-800 dark:text-amber-300 flex gap-2">
                  <span>·</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* ── Footer ────────────────────────────────────────────────────── */}
      <div className="px-5 py-3 bg-slate-50 dark:bg-slate-950 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between flex-wrap gap-2">
        <span className="text-[11px] text-slate-400">
          Rule-based engine {s.meta_engine_version ?? ""} · Not investment advice
        </span>
        {s.pre_trade_filters_passed ? (
          <span className="text-[11px] text-emerald-600 font-medium">
            ✓ All pre-trade filters passed
          </span>
        ) : (
          <span className="text-[11px] text-amber-600 font-medium">
            ⚠ Filter warnings — review before trading
          </span>
        )}
      </div>
    </div>
  );
}
