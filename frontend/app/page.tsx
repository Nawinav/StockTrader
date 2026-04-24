"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SuggestionList, WatchlistItem } from "@/lib/api";
import { api } from "@/lib/api";
import { SuggestionCard } from "@/components/SuggestionCard";

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

function DataSourceBadge({ provider }: { provider?: string }) {
  const isLive = provider === "upstox";
  const label = isLive ? "LIVE · Upstox" : "MOCK DATA";
  const tone = isLive
    ? "bg-emerald-50 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700"
    : "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700";
  const title = isLive
    ? "Prices & technicals are live NSE data via Upstox v2. Fundamentals remain static."
    : "Prices are synthetic. Set DATA_PROVIDER=upstox in backend/.env to go live.";
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-semibold tracking-wide ${tone}`}
    >
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${
          isLive ? "bg-emerald-500 animate-pulse" : "bg-amber-500"
        }`}
      />
      {label}
    </span>
  );
}

function Countdown({ nextRunAt }: { nextRunAt: number }) {
  const [left, setLeft] = useState(Math.max(0, nextRunAt - Date.now()));
  useEffect(() => {
    const id = setInterval(() => {
      setLeft(Math.max(0, nextRunAt - Date.now()));
    }, 1000);
    return () => clearInterval(id);
  }, [nextRunAt]);
  const mins = Math.floor(left / 60000);
  const secs = Math.floor((left % 60000) / 1000);
  return (
    <span className="text-xs text-slate-500 tabular-nums">
      Next refresh in {mins}:{secs.toString().padStart(2, "0")}
    </span>
  );
}

interface SectionProps {
  title: string;
  subtitle: string;
  accent: "rose" | "sky";
  data: SuggestionList | null;
  watchSymbols: Set<string>;
  onWatchlistChange: (items: WatchlistItem[]) => void;
  loading: boolean;
}

function Section({
  title,
  subtitle,
  accent,
  data,
  watchSymbols,
  onWatchlistChange,
  loading,
}: SectionProps) {
  const tone =
    accent === "rose"
      ? "from-rose-500/10 to-transparent border-rose-200 dark:border-rose-900/40"
      : "from-sky-500/10 to-transparent border-sky-200 dark:border-sky-900/40";
  const dot = accent === "rose" ? "bg-rose-500" : "bg-sky-500";
  return (
    <section
      className={`rounded-2xl border bg-gradient-to-b ${tone} p-4 space-y-3 transition-all`}
    >
      <div className="flex items-center gap-2">
        <span className={`inline-block w-2 h-2 rounded-full ${dot} animate-pulse`} />
        <h2 className="text-base font-semibold">{title}</h2>
        <span className="text-[11px] text-slate-500 ml-auto">{subtitle}</span>
      </div>
      {!data && loading && (
        <div className="space-y-2 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-20 rounded-lg bg-slate-200/50 dark:bg-slate-800/60"
            />
          ))}
        </div>
      )}
      {data && (
        <div className="grid gap-2">
          {data.items.map((s, idx) => (
            <div
              key={s.symbol}
              className="animate-fade-in-up"
              style={{ animationDelay: `${idx * 30}ms` }}
            >
              <SuggestionCard
                suggestion={s}
                rank={idx + 1}
                inWatchlist={watchSymbols.has(s.symbol)}
                onWatchlistChange={onWatchlistChange}
              />
            </div>
          ))}
        </div>
      )}
      {data && data.items.length === 0 && (
        <div className="text-sm text-slate-500 p-4 text-center">
          No suggestions right now.
        </div>
      )}
    </section>
  );
}

export default function DashboardPage() {
  const [intraday, setIntraday] = useState<SuggestionList | null>(null);
  const [longterm, setLongterm] = useState<SuggestionList | null>(null);
  const [watchSymbols, setWatchSymbols] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [nextRunAt, setNextRunAt] = useState<number>(Date.now() + REFRESH_MS);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    setLoading(true);
    setErr(null);
    try {
      const [intra, long, wl] = await Promise.all([
        api.getSuggestions("intraday", refresh),
        api.getSuggestions("longterm", refresh),
        api.listWatchlist().catch(() => ({ items: [] as WatchlistItem[] })),
      ]);
      setIntraday(intra);
      setLongterm(long);
      setWatchSymbols(new Set(wl.items.map((i) => i.symbol)));
      setNextRunAt(Date.now() + REFRESH_MS);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + auto-refresh every 5 min.
  useEffect(() => {
    load(false);
  }, [load]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => load(false), REFRESH_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [nextRunAt, load]);

  const provider =
    intraday?.data_provider ||
    longterm?.data_provider ||
    undefined;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Stock Dashboard</h1>
          <DataSourceBadge provider={provider} />
        </div>
        <div className="flex items-center gap-3">
          <Countdown nextRunAt={nextRunAt} />
          <button
            onClick={() => load(true)}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            <span
              className={`inline-block w-3 h-3 ${loading ? "animate-spin" : ""}`}
            >
              ↻
            </span>
            {loading ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </div>

      {err && (
        <div className="p-3 rounded border border-rose-300 bg-rose-50 text-rose-800 text-sm dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200 animate-fade-in-up">
          {err}. Is the backend running at{" "}
          <code className="font-mono text-xs">
            {process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}
          </code>
          ?
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-4">
        <Section
          title="Intraday"
          subtitle="Top 10 · 80% technical + 20% fundamental"
          accent="rose"
          data={intraday}
          watchSymbols={watchSymbols}
          onWatchlistChange={(items) =>
            setWatchSymbols(new Set(items.map((i) => i.symbol)))
          }
          loading={loading}
        />
        <Section
          title="Long-term"
          subtitle="Top 10 · 35% technical + 65% fundamental"
          accent="sky"
          data={longterm}
          watchSymbols={watchSymbols}
          onWatchlistChange={(items) =>
            setWatchSymbols(new Set(items.map((i) => i.symbol)))
          }
          loading={loading}
        />
      </div>
    </div>
  );
}
