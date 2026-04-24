"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type {
  ChartResponse,
  ExpertAnalysis,
} from "@/lib/api";
import { api } from "@/lib/api";
import { CandleChart } from "@/components/CandleChart";

type Props = { params: { symbol: string } };

const TIMEFRAMES = ["1M", "3M", "6M", "1Y", "2Y"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

function changeTone(pct: number): string {
  if (pct > 0) return "text-emerald-600 dark:text-emerald-400";
  if (pct < 0) return "text-rose-600 dark:text-rose-400";
  return "text-slate-500";
}

function scoreTone(score: number): string {
  if (score >= 70) return "text-emerald-600 dark:text-emerald-400";
  if (score <= 35) return "text-rose-600 dark:text-rose-400";
  return "text-amber-600 dark:text-amber-400";
}

export default function StockDetailPage({ params }: Props) {
  const symbol = decodeURIComponent(params.symbol).toUpperCase();
  const [analysis, setAnalysis] = useState<ExpertAnalysis | null>(null);
  const [chart, setChart] = useState<ChartResponse | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("3M");
  const [loading, setLoading] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadAnalysis = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.getAnalysis(symbol);
      setAnalysis(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load analysis");
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  const loadChart = useCallback(
    async (tf: Timeframe) => {
      setChartLoading(true);
      try {
        const res = await api.getChart(symbol, tf);
        setChart(res);
      } finally {
        setChartLoading(false);
      }
    },
    [symbol],
  );

  useEffect(() => {
    loadAnalysis();
  }, [loadAnalysis]);

  useEffect(() => {
    loadChart(timeframe);
  }, [loadChart, timeframe]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <Link
          href="/"
          className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
        >
          ← Dashboard
        </Link>
        <div className="h-4 w-px bg-slate-300 dark:bg-slate-700" />
        <h1 className="text-xl font-semibold">{symbol}</h1>
        {analysis && (
          <>
            <span className="text-slate-500">· {analysis.name}</span>
            <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border border-slate-300 dark:border-slate-700 text-slate-500">
              {analysis.sector}
            </span>
          </>
        )}
        <div className="ml-auto flex gap-2">
          <Link
            href={`/analyze/${symbol}`}
            className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            Claude deep-analyze
          </Link>
        </div>
      </div>

      {err && (
        <div className="p-3 rounded border border-rose-300 bg-rose-50 text-rose-800 text-sm animate-fade-in-up">
          {err}
        </div>
      )}

      {/* Price strip */}
      {analysis && (
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex flex-wrap items-end gap-6 animate-fade-in-up">
          <div>
            <div className="text-[10px] uppercase text-slate-500">Last Price</div>
            <div className="text-3xl font-bold tabular-nums">
              ₹{analysis.last_price.toFixed(2)}
            </div>
          </div>
          <Change label="1-Day" value={analysis.change_pct_1d} />
          <Change label="5-Day" value={analysis.change_pct_5d} />
          <Change label="1-Month" value={analysis.change_pct_20d} />
          <div className="h-10 w-px bg-slate-200 dark:bg-slate-800 mx-2" />
          <Stat label="RSI" value={analysis.rsi.toFixed(0)} />
          <Stat
            label="MACD Hist"
            value={analysis.macd_hist.toFixed(2)}
            tone={changeTone(analysis.macd_hist)}
          />
          <Stat
            label="ATR"
            value={`${analysis.atr_pct.toFixed(2)}%`}
            sub={analysis.volatility_label}
          />
          <Stat
            label="Volume vs Avg"
            value={`${analysis.volume_vs_avg_20d.toFixed(1)}×`}
          />
        </div>
      )}

      {/* Chart */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 space-y-3 animate-fade-in-up">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">Price & Volume</h2>
            {chartLoading && (
              <span className="text-[10px] text-slate-500">loading…</span>
            )}
          </div>
          <div className="flex gap-1 bg-slate-100 dark:bg-slate-800 rounded-lg p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  timeframe === tf
                    ? "bg-white dark:bg-slate-900 shadow font-semibold"
                    : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
        {chart && (
          <CandleChart
            candles={chart.candles}
            supports={analysis?.supports ?? []}
            resistances={analysis?.resistances ?? []}
            height={440}
          />
        )}
        {!chart && !chartLoading && (
          <div className="h-[440px] flex items-center justify-center text-slate-500 text-sm">
            No chart data
          </div>
        )}
      </div>

      {/* Expert analysis */}
      {analysis && (
        <div className="grid md:grid-cols-3 gap-4">
          <div className="md:col-span-2 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 space-y-3 animate-fade-in-up">
            <h2 className="text-sm font-semibold">Expert read</h2>
            <div className="flex flex-wrap gap-2 text-[11px]">
              <Pill label={`Trend: ${analysis.trend}`} />
              <Pill label={`Momentum: ${analysis.momentum}`} />
              <Pill label={`Vol: ${analysis.volatility_label}`} />
              <Pill
                label={`R:R ${analysis.risk_reward_ratio.toFixed(2)}`}
                tone={
                  analysis.risk_reward_ratio >= 2
                    ? "emerald"
                    : analysis.risk_reward_ratio <= 1
                    ? "rose"
                    : "slate"
                }
              />
            </div>
            <ul className="space-y-2 text-sm text-slate-700 dark:text-slate-300">
              {analysis.narrative.map((line, i) => (
                <li
                  key={i}
                  className="animate-fade-in-up"
                  style={{ animationDelay: `${i * 80}ms` }}
                >
                  <span className="text-slate-400 mr-2">•</span>
                  {line}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 space-y-3 animate-fade-in-up">
            <h2 className="text-sm font-semibold">Key levels</h2>
            <div>
              <div className="text-[10px] uppercase text-slate-500 mb-1">
                Resistance
              </div>
              <div className="flex flex-wrap gap-1">
                {analysis.resistances.map((r) => (
                  <span
                    key={r}
                    className="text-xs px-2 py-0.5 rounded border border-rose-200 dark:border-rose-900/60 text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/20"
                  >
                    ₹{r.toFixed(2)}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-500 mb-1">
                Support
              </div>
              <div className="flex flex-wrap gap-1">
                {analysis.supports.map((s) => (
                  <span
                    key={s}
                    className="text-xs px-2 py-0.5 rounded border border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/20"
                  >
                    ₹{s.toFixed(2)}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-slate-500 mb-1">
                Fibonacci (90-day swing)
              </div>
              <div className="space-y-1 text-xs">
                {Object.entries(analysis.fib_levels).map(([k, v]) => (
                  <div key={k} className="flex justify-between tabular-nums">
                    <span className="text-slate-500">{k}</span>
                    <span className="font-mono">₹{v.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Scores */}
      {analysis && (
        <div className="grid md:grid-cols-2 gap-4">
          <ScoreBlock title="Intraday score" score={analysis.intraday_score} />
          <ScoreBlock title="Long-term score" score={analysis.longterm_score} />
        </div>
      )}

      {loading && !analysis && (
        <div className="text-sm text-slate-500">Building analysis…</div>
      )}
    </div>
  );
}

function Change({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${changeTone(value)}`}>
        {value >= 0 ? "+" : ""}
        {value.toFixed(2)}%
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className={`text-base font-semibold tabular-nums ${tone ?? ""}`}>
        {value}
      </div>
      {sub && (
        <div className="text-[10px] text-slate-500 capitalize">{sub}</div>
      )}
    </div>
  );
}

function Pill({ label, tone = "slate" }: { label: string; tone?: string }) {
  const tones: Record<string, string> = {
    slate:
      "border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/40",
    emerald:
      "border-emerald-300 dark:border-emerald-700 text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/30",
    rose:
      "border-rose-300 dark:border-rose-700 text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/30",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full border capitalize ${tones[tone]}`}
    >
      {label}
    </span>
  );
}

function ScoreBlock({
  title,
  score,
}: {
  title: string;
  score: {
    technical: number;
    fundamental: number;
    composite: number;
    signals: string[];
  };
}) {
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 space-y-3 animate-fade-in-up">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <div className={`text-3xl font-bold tabular-nums ${scoreTone(score.composite)}`}>
          {score.composite.toFixed(0)}
        </div>
      </div>
      <div className="flex gap-3 text-xs text-slate-500">
        <span>Tech {score.technical.toFixed(0)}</span>
        <span>·</span>
        <span>Fund {score.fundamental.toFixed(0)}</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {score.signals.slice(0, 8).map((sig, i) => (
          <span
            key={i}
            className="text-[10px] px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-800 text-slate-500"
          >
            {sig}
          </span>
        ))}
      </div>
    </div>
  );
}
