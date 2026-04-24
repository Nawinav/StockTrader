"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { AnalyzerSignal, AlgoSignal, AnalyzeRequest } from "@/lib/api";
import { AnalyzerSignalCard } from "@/components/AnalyzerSignalCard";
import { AlgoSignalCard } from "@/components/AlgoSignalCard";

type Props = { params: { symbol: string } };

type Tab = "algo" | "claude";

export default function AnalyzePage({ params }: Props) {
  const symbol = decodeURIComponent(params.symbol).toUpperCase();
  const [activeTab, setActiveTab] = useState<Tab>("algo");

  // Algo signal state
  const [algoSignal, setAlgoSignal] = useState<AlgoSignal | null>(null);
  const [algoLoading, setAlgoLoading] = useState(false);
  const [algoErr, setAlgoErr] = useState<string | null>(null);

  // Claude signal state
  const [claudeSignal, setClaudeSignal] = useState<AnalyzerSignal | null>(null);
  const [claudeLoading, setClaudeLoading] = useState(false);
  const [claudeErr, setClaudeErr] = useState<string | null>(null);

  // Shared capital / risk inputs (used by both engines)
  const [capital, setCapital] = useState<string>("100000");
  const [riskPct, setRiskPct] = useState<string>("1.5");

  // ── Algo Engine (rule-based, fast) ────────────────────────────────────
  const loadAlgo = useCallback(
    async (bust: boolean) => {
      setAlgoLoading(true);
      setAlgoErr(null);
      try {
        const res = await api.algoSignal(symbol, {
          capital: Number(capital) || 100_000,
          risk_pct: Number(riskPct) || 1.5,
          bust_cache: bust,
        });
        setAlgoSignal(res);
      } catch (e) {
        setAlgoErr(e instanceof Error ? e.message : "Algo engine failed");
      } finally {
        setAlgoLoading(false);
      }
    },
    [symbol, capital, riskPct],
  );

  // ── Claude AI Analysis (rich reasoning) ───────────────────────────────
  const loadClaude = useCallback(
    async (bust: boolean) => {
      setClaudeLoading(true);
      setClaudeErr(null);
      try {
        const body: AnalyzeRequest = {
          account: {
            capital: Number(capital) || undefined,
            risk_pct: Number(riskPct) || undefined,
          },
          bust_cache: bust,
        };
        const res = await api.analyze(symbol, body);
        setClaudeSignal(res);
      } catch (e) {
        setClaudeErr(e instanceof Error ? e.message : "Claude analysis failed");
      } finally {
        setClaudeLoading(false);
      }
    },
    [symbol, capital, riskPct],
  );

  // Load algo signal on mount; Claude loads lazily when tab is switched
  useEffect(() => {
    loadAlgo(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    if (tab === "claude" && !claudeSignal && !claudeLoading) {
      loadClaude(false);
    }
  };

  const refreshCurrent = (bust: boolean) => {
    if (activeTab === "algo") loadAlgo(bust);
    else loadClaude(bust);
  };

  const isLoading = activeTab === "algo" ? algoLoading : claudeLoading;

  return (
    <div className="space-y-4">
      {/* ── Breadcrumb ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <Link
          href="/"
          className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
        >
          ← Dashboard
        </Link>
        <div className="h-4 w-px bg-slate-300 dark:bg-slate-700" />
        <h1 className="text-xl font-semibold">Trade Analysis — {symbol}</h1>
      </div>

      {/* ── Controls bar ─────────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex flex-wrap items-end gap-3">
        <div>
          <div className="text-[10px] uppercase text-slate-500">Symbol</div>
          <div className="text-lg font-bold">{symbol}</div>
        </div>
        <label className="flex flex-col">
          <span className="text-[10px] uppercase text-slate-500">Capital (₹)</span>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            className="rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1 text-sm w-32"
          />
        </label>
        <label className="flex flex-col">
          <span className="text-[10px] uppercase text-slate-500">Risk %</span>
          <input
            type="number"
            step="0.1"
            value={riskPct}
            onChange={(e) => setRiskPct(e.target.value)}
            className="rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-2 py-1 text-sm w-20"
          />
        </label>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => refreshCurrent(false)}
            disabled={isLoading}
            className="text-sm px-3 py-1.5 rounded border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            {isLoading ? "Running…" : "Re-apply"}
          </button>
          <button
            onClick={() => refreshCurrent(true)}
            disabled={isLoading}
            className="text-sm px-3 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {isLoading ? "…" : "Fresh run"}
          </button>
        </div>
      </div>

      {/* ── Tab switcher ─────────────────────────────────────────────── */}
      <div className="flex gap-1 p-1 rounded-xl bg-slate-100 dark:bg-slate-800 w-fit">
        <button
          onClick={() => handleTabChange("algo")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === "algo"
              ? "bg-white dark:bg-slate-900 shadow-sm text-slate-900 dark:text-white"
              : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          }`}
        >
          ⚡ Rule-Based Algo Signal
        </button>
        <button
          onClick={() => handleTabChange("claude")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === "claude"
              ? "bg-white dark:bg-slate-900 shadow-sm text-slate-900 dark:text-white"
              : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          }`}
        >
          🧠 Claude AI Analysis
        </button>
      </div>

      {/* ── Description strip ────────────────────────────────────────── */}
      <div className="text-xs text-slate-500 px-1">
        {activeTab === "algo" ? (
          <>
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Rule-Based Engine:
            </span>{" "}
            9 quantitative strategies evaluated simultaneously. Signal fires when ≥ 3
            agree. Deterministic, sub-100 ms, no AI involved.
          </>
        ) : (
          <>
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Claude AI Analysis:
            </span>{" "}
            Full multi-timeframe reasoning across all 9 strategies with market context,
            candlestick patterns, and narrative justification.
          </>
        )}
      </div>

      {/* ── Algo tab ─────────────────────────────────────────────────── */}
      {activeTab === "algo" && (
        <>
          {algoErr && (
            <div className="p-3 rounded border border-rose-300 bg-rose-50 text-rose-800 text-sm dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200">
              {algoErr}
            </div>
          )}
          {algoSignal && <AlgoSignalCard signal={algoSignal} />}
          {algoLoading && !algoSignal && (
            <div className="text-sm text-slate-500 animate-pulse py-4 text-center">
              Running 9-strategy confluence engine…
            </div>
          )}
        </>
      )}

      {/* ── Claude tab ───────────────────────────────────────────────── */}
      {activeTab === "claude" && (
        <>
          {claudeErr && (
            <div className="p-3 rounded border border-rose-300 bg-rose-50 text-rose-800 text-sm dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200">
              {claudeErr}
            </div>
          )}
          {claudeSignal && <AnalyzerSignalCard signal={claudeSignal} />}
          {claudeLoading && !claudeSignal && (
            <div className="text-sm text-slate-500 animate-pulse py-4 text-center">
              Running Claude AI analysis…
            </div>
          )}
          {!claudeSignal && !claudeLoading && !claudeErr && (
            <div className="text-sm text-slate-500 py-4 text-center">
              Click{" "}
              <button
                onClick={() => loadClaude(false)}
                className="text-indigo-600 underline"
              >
                Run Claude Analysis
              </button>{" "}
              to get AI-powered reasoning.
            </div>
          )}
        </>
      )}
    </div>
  );
}
