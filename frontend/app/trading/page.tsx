"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type MarketRegime,
  type PortfolioSnapshot,
  type TickResponse,
  type Trade,
  type TradingConfig,
} from "@/lib/api";
import { StatCard } from "@/components/trading/StatCard";
import { PositionsTable } from "@/components/trading/PositionsTable";
import { TradesTable } from "@/components/trading/TradesTable";
import { EquityChart } from "@/components/trading/EquityChart";
import { ConfigDrawer } from "@/components/trading/ConfigDrawer";

const POLL_MS = 30_000; // refresh snapshot every 30s

function Toast({ message, tone }: { message: string; tone: "ok" | "warn" | "err" }) {
  const bg =
    tone === "ok"
      ? "bg-emerald-600"
      : tone === "warn"
        ? "bg-amber-600"
        : "bg-rose-600";
  return (
    <div
      className={`fixed right-4 bottom-4 z-40 px-4 py-2 rounded-lg text-white text-sm shadow-lg animate-fade-in-up ${bg}`}
    >
      {message}
    </div>
  );
}

function RegimeBadge({ regime }: { regime: MarketRegime }) {
  const colors: Record<string, string> = {
    BULL_TREND:     "bg-emerald-50 text-emerald-800 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700",
    BEAR_TREND:     "bg-rose-50 text-rose-800 border-rose-300 dark:bg-rose-900/30 dark:text-rose-300 dark:border-rose-700",
    RANGING:        "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700",
    HIGH_VOLATILITY:"bg-orange-50 text-orange-800 border-orange-300 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-700",
  };
  const cls = colors[regime.regime] || "bg-slate-100 text-slate-600 border-slate-300";
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[11px] font-semibold ${cls}`}>
      <span>{regime.label}</span>
      {regime.nifty_ltp > 0 && (
        <span className="font-normal opacity-80">
          Nifty {regime.nifty_ltp.toLocaleString("en-IN")}
          {" "}({regime.nifty_change_pct > 0 ? "+" : ""}{regime.nifty_change_pct.toFixed(2)}%)
          {" "}· VIX {regime.vix > 0 ? regime.vix.toFixed(1) : "—"}
          {" "}· confluence≥{regime.recommended_min_confluence}
        </span>
      )}
      {regime.block_new_longs && (
        <span className="ml-1 px-1.5 py-0.5 rounded bg-rose-600 text-white text-[10px]">
          NO NEW LONGS
        </span>
      )}
    </div>
  );
}

// ── Why-no-trades modal ──────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function WhyModal({ data, onClose }: { data: Record<string, any>; onClose: () => void }) {
  const pre = data.pre_conditions || {};
  const regime = data.regime || {};
  const sug = data.suggestions || {};
  const summary = data.summary || {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const stocks: any[] = data.stocks || [];

  const gateColor = (passed: boolean) =>
    passed
      ? "text-emerald-700 dark:text-emerald-400"
      : "text-rose-700 dark:text-rose-400 font-semibold";

  const verdictBg = (v: string) =>
    v === "PASS"
      ? "bg-emerald-50 border-emerald-200 dark:bg-emerald-950/20 dark:border-emerald-800"
      : "bg-rose-50 border-rose-200 dark:bg-rose-950/20 dark:border-rose-800";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm overflow-y-auto pt-8 pb-8"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-3xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700 sticky top-0 bg-white dark:bg-slate-900 z-10">
          <div>
            <h2 className="text-lg font-bold">Why No Trades?</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Gate-by-gate analysis for every BUY suggestion as of{" "}
              {data.as_of ? new Date(data.as_of).toLocaleTimeString() : "—"}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-2xl leading-none">×</button>
        </div>

        <div className="px-6 py-4 space-y-5 overflow-y-auto max-h-[calc(100vh-160px)]">

          {/* Pre-conditions */}
          <section>
            <h3 className="text-sm font-semibold mb-2">Pre-conditions</h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
              {[
                ["Market open", pre.market_open],
                ["Auto trading", pre.auto_trading],
                ["Entry capacity", pre.entries_capacity_ok],
                ["Position capacity", pre.positions_capacity_ok],
                ["EOD block", !pre.eod_block],
              ].map(([label, ok]) => (
                <div key={String(label)} className={`flex items-center gap-1.5 px-2 py-1 rounded border ${ok ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/20" : "border-rose-200 bg-rose-50 dark:border-rose-800 dark:bg-rose-950/20"}`}>
                  <span>{ok ? "✓" : "✗"}</span>
                  <span className={ok ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400 font-medium"}>{String(label)}</span>
                </div>
              ))}
            </div>
            {pre.blocking_reasons?.length > 0 && (
              <div className="mt-2 px-3 py-2 rounded-lg bg-rose-50 border border-rose-200 dark:bg-rose-950/20 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300">
                <span className="font-semibold">Blocked:</span> {pre.blocking_reasons.join(" · ")}
              </div>
            )}
            {pre.entries_today !== undefined && (
              <p className="text-xs text-slate-500 mt-1">
                Entries today: {pre.entries_today}/{pre.max_entries_per_day} ·
                Positions: {pre.open_positions}/{pre.max_positions} ·
                {pre.minutes_to_close != null ? ` ${pre.minutes_to_close}m left` : " market closed"}
              </p>
            )}
          </section>

          {/* Regime */}
          <section>
            <h3 className="text-sm font-semibold mb-2">Market Regime</h3>
            {regime.available ? (
              <div className="text-xs space-y-1">
                <p>
                  <span className="font-medium">{regime.label}</span>{" "}
                  {regime.nifty_ltp > 0 && <>· Nifty {regime.nifty_ltp?.toLocaleString("en-IN")} ({regime.nifty_change_pct > 0 ? "+" : ""}{regime.nifty_change_pct?.toFixed(2)}%)</>}
                  {" "}· ADX {regime.adx?.toFixed(1)} · VIX {regime.vix > 0 ? regime.vix?.toFixed(1) : "—"}
                </p>
                <p>
                  Min confluence: {regime.effective_min_confluence}
                  {regime.block_new_longs && <span className="ml-2 px-1.5 py-0.5 rounded bg-rose-600 text-white text-[10px]">BLOCKING NEW LONGS</span>}
                </p>
                {regime.disabled_strategies?.length > 0 && (
                  <p className="text-amber-600 dark:text-amber-400">Disabled strategies: {regime.disabled_strategies.join(", ")}</p>
                )}
              </div>
            ) : (
              <p className="text-xs text-rose-600">{regime.error || "Regime data unavailable"}</p>
            )}
          </section>

          {/* Config */}
          <section>
            <h3 className="text-sm font-semibold mb-2">Active Config</h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-slate-600 dark:text-slate-400">
              {Object.entries(data.config || {}).map(([k, v]) => (
                <div key={k} className="flex justify-between px-2 py-1 rounded bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                  <span className="text-slate-500">{k.replace(/_/g, " ")}</span>
                  <span className="font-medium text-slate-800 dark:text-slate-200">{String(v)}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Suggestions summary */}
          <section>
            <h3 className="text-sm font-semibold mb-2">Suggestions</h3>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Total: {sug.total} · BUY: {sug.buy_count} · Passing score gate: {sug.passing_score_gate ?? "—"} · Min score: {sug.min_composite_score}
              {sug.error && <span className="text-rose-600 ml-2">Error: {sug.error}</span>}
            </p>
          </section>

          {/* Summary */}
          <section className="px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
            <div className="flex gap-6 text-sm">
              <div><span className="text-slate-500 text-xs">Stocks analysed</span><br /><span className="text-2xl font-bold">{summary.stocks_analysed ?? 0}</span></div>
              <div><span className="text-slate-500 text-xs">Would enter</span><br /><span className="text-2xl font-bold text-emerald-600">{summary.would_enter ?? 0}</span></div>
              <div><span className="text-slate-500 text-xs">Blocked</span><br /><span className="text-2xl font-bold text-rose-600">{summary.blocked ?? 0}</span></div>
            </div>
            {Object.entries(summary.block_breakdown || {}).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(summary.block_breakdown || {}).map(([reason, count]) => (
                  <span key={reason} className="px-2 py-0.5 text-[11px] rounded-full bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800">
                    {reason}: {String(count)}
                  </span>
                ))}
              </div>
            )}
          </section>

          {/* Per-stock breakdown */}
          {stocks.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold mb-2">Stock-by-stock ({stocks.length})</h3>
              <div className="space-y-2">
                {stocks.map((stock) => (
                  <details key={stock.symbol} className={`rounded-lg border ${verdictBg(stock.verdict)}`}>
                    <summary className="px-3 py-2 cursor-pointer flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className={`font-bold ${stock.verdict === "PASS" ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
                          {stock.verdict === "PASS" ? "✓" : "✗"}
                        </span>
                        <span className="font-semibold">{stock.symbol}</span>
                        <span className="text-slate-500">{stock.name}</span>
                        <span className="text-slate-500">score: {stock.composite_score?.toFixed(1)}</span>
                      </div>
                      {stock.block_reason && (
                        <span className="text-rose-600 dark:text-rose-400 text-[11px] truncate max-w-xs">{stock.block_reason}</span>
                      )}
                    </summary>
                    <div className="px-3 pb-3 pt-1 space-y-1.5">
                      {/* Gates */}
                      {stock.gates?.map((g: {gate: string; passed: boolean; detail: string}, i: number) => (
                        <div key={i} className="flex items-start gap-2 text-[11px]">
                          <span className={`flex-shrink-0 font-mono ${gateColor(g.passed)}`}>{g.passed ? "✓" : "✗"}</span>
                          <span className="font-medium w-36 flex-shrink-0">{g.gate}</span>
                          <span className="text-slate-500 dark:text-slate-400">{g.detail}</span>
                        </div>
                      ))}
                      {/* HC filter detail */}
                      {stock.hc && stock.hc.ran && (
                        <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                          <p className="text-[11px] font-semibold mb-1">HC Score Breakdown — {stock.hc.grade} ({stock.hc.total_score}/100)</p>
                          <div className="space-y-0.5">
                            {stock.hc.dimensions?.map((d: {name: string; score: number; max: number; detail: string}, i: number) => (
                              <div key={i} className="flex items-center gap-2 text-[11px]">
                                <span className={`w-4 text-right font-mono flex-shrink-0 ${d.score > 0 ? "text-emerald-600" : d.score < 0 ? "text-rose-600" : "text-slate-400"}`}>{d.score > 0 ? `+${d.score}` : d.score}</span>
                                <span className="text-slate-400">/{d.max}</span>
                                <span className="text-slate-600 dark:text-slate-400">{d.detail}</span>
                              </div>
                            ))}
                          </div>
                          {stock.hc.blocking_reasons?.length > 0 && (
                            <p className="text-[11px] text-rose-600 mt-1">Blocked: {stock.hc.blocking_reasons.join(" · ")}</p>
                          )}
                        </div>
                      )}
                      {stock.hc && !stock.hc.ran && stock.hc.reason && (
                        <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1">{stock.hc.reason}</p>
                      )}
                      {/* Algo detail */}
                      {stock.algo?.ran && (
                        <div className="mt-1 text-[11px] text-slate-500">
                          Algo: {stock.algo.action} · confluence {stock.algo.confluence} · strategies: {(stock.algo.strategies || []).join(", ") || "none"}
                          {stock.algo.entry_price && ` · entry ₹${stock.algo.entry_price?.toFixed(2)} stop ₹${stock.algo.stop_loss?.toFixed(2)} t1 ₹${stock.algo.target_1?.toFixed(2)}`}
                        </div>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            </section>
          )}

          {stocks.length === 0 && !sug.error && (
            <p className="text-sm text-center text-slate-500 py-6">
              No BUY suggestions in the current intraday scan.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function TradingPage() {
  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [config, setConfig] = useState<TradingConfig | null>(null);
  const [regime, setRegime] = useState<MarketRegime | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "warn" | "err" } | null>(null);
  const [busy, setBusy] = useState<null | "tick" | "flatten" | "reset" | "auto">(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [whyData, setWhyData] = useState<Record<string, any> | null>(null);
  const [whyLoading, setWhyLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flashToast = useCallback((msg: string, tone: "ok" | "warn" | "err" = "ok") => {
    setToast({ msg, tone });
    setTimeout(() => setToast(null), 2500);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [s, t, c, r] = await Promise.all([
        api.tradingState(),
        api.tradingTrades(100),
        api.tradingConfig(),
        api.marketRegime().catch(() => null),
      ]);
      setSnap(s);
      setTrades(t.items);
      setConfig(c);
      setRegime(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while visible.
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(load, POLL_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [snap, load]);

  const toggleAuto = async (enabled: boolean) => {
    if (!config) return;
    setBusy("auto");
    try {
      const c = await api.tradingToggleAuto(enabled);
      setConfig(c);
      flashToast(enabled ? "Auto-trading ON" : "Auto-trading OFF", enabled ? "ok" : "warn");
      load();
    } catch (e) {
      flashToast(e instanceof Error ? e.message : "Toggle failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const runTick = async () => {
    setBusy("tick");
    try {
      const r: TickResponse = await api.tradingTick();
      const msg = r.opened || r.closed
        ? `Tick: opened ${r.opened}, closed ${r.closed}`
        : "Tick: nothing to do";
      flashToast(msg, r.opened || r.closed ? "ok" : "warn");
      load();
    } catch (e) {
      flashToast(e instanceof Error ? e.message : "Tick failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const flatten = async () => {
    if (!confirm("Close ALL open positions at current LTP?")) return;
    setBusy("flatten");
    try {
      const r = await api.tradingFlatten();
      flashToast(`Flattened ${r.closed} positions`, "ok");
      load();
    } catch (e) {
      flashToast(e instanceof Error ? e.message : "Flatten failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    if (!confirm("Reset engine? All positions and trade history will be wiped.")) return;
    setBusy("reset");
    try {
      await api.tradingReset();
      flashToast("Engine reset", "ok");
      load();
    } catch (e) {
      flashToast(e instanceof Error ? e.message : "Reset failed", "err");
    } finally {
      setBusy(null);
    }
  };

  const runWhy = async () => {
    setWhyLoading(true);
    try {
      const data = await api.tradingWhy();
      setWhyData(data);
    } catch (e) {
      flashToast(e instanceof Error ? e.message : "Why failed", "err");
    } finally {
      setWhyLoading(false);
    }
  };

  if (err) {
    return (
      <div className="p-4 rounded-lg border border-rose-300 bg-rose-50 text-rose-800 text-sm dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200">
        Failed to load trading state: {err}. Is the backend running?
      </div>
    );
  }

  if (!snap || !config) {
    return (
      <div className="space-y-3">
        <div className="h-24 rounded-xl bg-slate-200/60 dark:bg-slate-800/60 animate-pulse" />
        <div className="h-64 rounded-xl bg-slate-200/60 dark:bg-slate-800/60 animate-pulse" />
      </div>
    );
  }

  const dayPnl = snap.realized_pnl_today + snap.unrealized_pnl;
  const winRate =
    snap.wins_today + snap.losses_today > 0
      ? (snap.wins_today / (snap.wins_today + snap.losses_today)) * 100
      : 0;
  const autoOn = config.auto_trading_enabled;

  return (
    <div className="space-y-5">
      {/* Market regime + data source banner */}
      <div className="flex flex-wrap items-center gap-2">
        {regime && <RegimeBadge regime={regime} />}
        {snap.data_provider === "mock" && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700 text-[11px] text-amber-800 dark:text-amber-300 font-semibold">
            ⚠ MOCK DATA — synthetic OHLCV.{" "}
            <span className="font-normal">Connect Upstox for live signals.</span>
          </div>
        )}
        {snap.data_provider !== "mock" && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-emerald-300 bg-emerald-50 dark:bg-emerald-900/20 dark:border-emerald-700 text-[11px] text-emerald-700 dark:text-emerald-300 font-semibold">
            ✓ LIVE NSE data via {snap.data_provider}
          </div>
        )}
      </div>

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Paper Trading</h1>
          <span
            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-semibold tracking-wide ${
              snap.market_open
                ? "bg-emerald-50 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700"
                : "bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700"
            }`}
          >
            <span
              className={`inline-block w-1.5 h-1.5 rounded-full ${
                snap.market_open ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
              }`}
            />
            {snap.market_open ? "NSE OPEN" : "NSE CLOSED"}
          </span>
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-semibold tracking-wide bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700">
            PAPER
          </span>
          {config && (
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold tracking-wide ${
              config.trading_profile === "ACTIVE"
                ? "bg-amber-50 text-amber-700 border-amber-400 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-700"
                : config.trading_profile === "BALANCED"
                  ? "bg-blue-50 text-blue-700 border-blue-400 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-700"
                  : "bg-emerald-50 text-emerald-700 border-emerald-400 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-700"
            }`}>
              {config.trading_profile === "ACTIVE" ? "⚡ ACTIVE" : config.trading_profile === "BALANCED" ? "⚖️ BALANCED" : "🎯 HIGH CONF"}
            </span>
          )}
          {snap.last_tick_at && (
            <span className="text-xs text-slate-500">
              tick {new Date(snap.last_tick_at).toLocaleTimeString()}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Auto switch */}
          <button
            onClick={() => toggleAuto(!autoOn)}
            disabled={busy === "auto"}
            className={`inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-60 ${
              autoOn
                ? "border-emerald-500 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-700"
                : "border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
            }`}
          >
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                autoOn ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
              }`}
            />
            Auto {autoOn ? "ON" : "OFF"}
          </button>
          <button
            onClick={runTick}
            disabled={busy === "tick" || loading}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-60"
          >
            {busy === "tick" ? "Ticking…" : "Tick now"}
          </button>
          <button
            onClick={runWhy}
            disabled={whyLoading}
            title="Diagnose why no trades are being entered — shows gate-by-gate analysis for every BUY suggestion"
            className="text-xs px-3 py-1.5 rounded-lg border border-violet-300 text-violet-700 hover:bg-violet-50 dark:border-violet-700 dark:text-violet-300 dark:hover:bg-violet-950/30 disabled:opacity-60"
          >
            {whyLoading ? "Checking…" : "Why no trades?"}
          </button>
          <button
            onClick={flatten}
            disabled={busy === "flatten" || snap.positions.length === 0}
            className="text-xs px-3 py-1.5 rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-950/30 disabled:opacity-50"
          >
            {busy === "flatten" ? "Closing…" : "Flatten"}
          </button>
          <button
            onClick={() => setDrawerOpen(true)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Config
          </button>
          <button
            onClick={reset}
            disabled={busy === "reset"}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Summary stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Equity"
          value={snap.equity}
          sub={`from ₹${snap.starting_capital.toLocaleString("en-IN")} start`}
          tone={snap.equity >= snap.starting_capital ? "up" : "down"}
        />
        <StatCard
          label="Today P&L"
          value={dayPnl}
          sub={`realized ₹${snap.realized_pnl_today.toFixed(0)} · unrealized ₹${snap.unrealized_pnl.toFixed(0)}`}
          tone={dayPnl >= 0 ? "up" : "down"}
        />
        <StatCard
          label="Total P&L"
          value={snap.realized_pnl_total + snap.unrealized_pnl}
          sub={`closed ₹${snap.realized_pnl_total.toFixed(0)} + open ₹${snap.unrealized_pnl.toFixed(0)}`}
          tone={snap.realized_pnl_total + snap.unrealized_pnl >= 0 ? "up" : "down"}
        />
        <StatCard
          label="Today win %"
          value={winRate}
          sub={`${snap.wins_today}W / ${snap.losses_today}L · ${snap.entries_today} entries`}
          tone="brand"
          isCurrency={false}
          decimals={0}
        />
      </div>

      {/* Equity chart + cash/invested block */}
      <div className="grid lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2">
          <EquityChart
            startingCapital={snap.starting_capital}
            currentEquity={snap.equity}
            trades={trades}
            height={140}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <StatCard
            label="Cash"
            value={snap.cash}
            sub={`${((snap.cash / snap.equity) * 100).toFixed(0)}% of equity`}
            tone="neutral"
          />
          <StatCard
            label="Invested"
            value={snap.invested}
            sub={`${snap.positions.length} position${snap.positions.length === 1 ? "" : "s"}`}
            tone="neutral"
          />
        </div>
      </div>

      {/* Positions */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          Open positions ({snap.positions.length})
        </h2>
        <PositionsTable positions={snap.positions} onChanged={load} />
      </section>

      {/* Trades */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Recent trades
        </h2>
        <TradesTable trades={trades} />
      </section>

      <ConfigDrawer
        open={drawerOpen}
        initial={config}
        onClose={() => setDrawerOpen(false)}
        onSaved={(c) => {
          setConfig(c);
          flashToast("Config saved", "ok");
          load();
        }}
      />

      {toast && <Toast message={toast.msg} tone={toast.tone} />}
      {whyData && <WhyModal data={whyData} onClose={() => setWhyData(null)} />}
    </div>
  );
}
