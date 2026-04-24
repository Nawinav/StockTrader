"use client";

import { useEffect, useState } from "react";
import { api, type TradingConfig, type TradingProfile } from "@/lib/api";

// ── Profile definitions (mirror backend _PROFILES) ───────────────────────────
const PROFILES: {
  id: TradingProfile;
  label: string;
  icon: string;
  winRate: string;
  description: string;
  hcMinScore: number;
  mtfMin: number;
  minConf: number;
  color: string;
  activeCls: string;
}[] = [
  {
    id: "ACTIVE",
    icon: "⚡",
    label: "Active",
    winRate: "~75% win rate",
    description:
      "Minimal filtering — like the original system. More frequent trades, smaller average winner. Best in strong trending markets.",
    hcMinScore: 50,
    mtfMin: 0,
    minConf: 1,
    color: "amber",
    activeCls:
      "border-amber-500 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-600",
  },
  {
    id: "BALANCED",
    icon: "⚖️",
    label: "Balanced",
    winRate: "~85% win rate",
    description:
      "Moderate filtering. Catches a good number of opportunities while avoiding obvious noise. All-round general purpose.",
    hcMinScore: 65,
    mtfMin: 1,
    minConf: 3,
    color: "blue",
    activeCls:
      "border-blue-500 bg-blue-50 dark:bg-blue-950/30 dark:border-blue-600",
  },
  {
    id: "HIGH_CONFIDENCE",
    icon: "🎯",
    label: "High Confidence",
    winRate: "~95% win rate",
    description:
      "Strictest filters — Grade A/A+ HC score, 2/3 timeframe confluence, strong strategy agreement. Fewest trades, highest quality.",
    hcMinScore: 80,
    mtfMin: 2,
    minConf: 5,
    color: "emerald",
    activeCls:
      "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-600",
  },
];

type Props = {
  open: boolean;
  initial: TradingConfig;
  onClose: () => void;
  onSaved: (cfg: TradingConfig) => void;
};

export function ConfigDrawer({ open, initial, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<TradingConfig>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft(initial);
      setErr(null);
    }
  }, [open, initial]);

  const setField = <K extends keyof TradingConfig>(
    key: K,
    value: TradingConfig[K],
  ) => setDraft((d) => ({ ...d, [key]: value }));

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const saved = await api.tradingUpdateConfig(draft);
      onSaved(saved);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const inputCls =
    "w-full px-2.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent tabular-nums focus:outline-none focus:ring-2 focus:ring-brand-500/40";

  return (
    <div
      className="fixed inset-0 z-30 bg-slate-900/40 backdrop-blur-sm animate-fade-in-up"
      onClick={onClose}
    >
      <div
        className="absolute right-0 top-0 h-full w-full max-w-md bg-white dark:bg-slate-950 border-l border-slate-200 dark:border-slate-800 shadow-2xl p-5 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Trading config</h2>
          <button
            onClick={onClose}
            className="text-xs px-2 py-1 rounded border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 text-sm">

          {/* ── Trading Profile selector ─────────────────────────────── */}
          <div className="pt-1 pb-2">
            <div className="text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-2">
              Risk Profile
            </div>
            <div className="space-y-2">
              {PROFILES.map((p) => {
                const active = draft.trading_profile === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setField("trading_profile", p.id)}
                    className={`w-full text-left rounded-xl border-2 px-4 py-3 transition-all ${
                      active
                        ? p.activeCls
                        : "border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="font-semibold text-sm">
                        {p.icon} {p.label}
                      </span>
                      <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                        active
                          ? p.color === "amber"
                            ? "bg-amber-200 text-amber-800 dark:bg-amber-800/40 dark:text-amber-200"
                            : p.color === "blue"
                              ? "bg-blue-200 text-blue-800 dark:bg-blue-800/40 dark:text-blue-200"
                              : "bg-emerald-200 text-emerald-800 dark:bg-emerald-800/40 dark:text-emerald-200"
                          : "bg-slate-100 dark:bg-slate-800 text-slate-500"
                      }`}>
                        {p.winRate}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
                      {p.description}
                    </p>
                    {active && (
                      <div className="mt-2 flex gap-3 text-[11px] font-medium text-slate-600 dark:text-slate-300">
                        <span>HC ≥ {p.hcMinScore}</span>
                        <span>·</span>
                        <span>MTF {p.mtfMin}/3</span>
                        <span>·</span>
                        <span>Confluence ≥ {p.minConf}</span>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="border-t border-slate-200 dark:border-slate-800 pt-3">
            <div className="text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-3">
              Position & Risk Settings
            </div>
          </div>

          <Field
            label="Starting capital (₹)"
            help="Virtual cash the engine manages. Changes reflect on next reset."
          >
            <input
              type="number"
              min={10000}
              step={5000}
              value={draft.starting_capital_inr}
              onChange={(e) =>
                setField("starting_capital_inr", Number(e.target.value))
              }
              className={inputCls}
            />
          </Field>

          <Field
            label="Risk per trade (%)"
            help="Max loss per trade as a % of current equity."
          >
            <input
              type="number"
              min={0.1}
              max={5}
              step={0.1}
              value={draft.risk_pct_per_trade}
              onChange={(e) =>
                setField("risk_pct_per_trade", Number(e.target.value))
              }
              className={inputCls}
            />
          </Field>

          <Field
            label="Min composite score"
            help="Engine only enters when a suggestion's composite ≥ this."
          >
            <input
              type="number"
              min={50}
              max={95}
              step={1}
              value={draft.min_composite_score}
              onChange={(e) =>
                setField("min_composite_score", Number(e.target.value))
              }
              className={inputCls}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Max concurrent positions">
              <input
                type="number"
                min={1}
                max={20}
                step={1}
                value={draft.max_concurrent_positions}
                onChange={(e) =>
                  setField("max_concurrent_positions", Number(e.target.value))
                }
                className={inputCls}
              />
            </Field>

            <Field label="Max entries / day">
              <input
                type="number"
                min={1}
                max={50}
                step={1}
                value={draft.max_entries_per_day}
                onChange={(e) =>
                  setField("max_entries_per_day", Number(e.target.value))
                }
                className={inputCls}
              />
            </Field>
          </div>

          <Field
            label="Max stop distance (%)"
            help="Refuse trades whose stop is wider than this."
          >
            <input
              type="number"
              min={0.3}
              max={15}
              step={0.1}
              value={draft.max_stop_distance_pct}
              onChange={(e) =>
                setField("max_stop_distance_pct", Number(e.target.value))
              }
              className={inputCls}
            />
          </Field>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={draft.eod_flatten}
              onChange={(e) => setField("eod_flatten", e.target.checked)}
              className="w-4 h-4"
            />
            <span className="text-sm">Flatten all positions near EOD (15:20 IST)</span>
          </label>

          {/* ── Trailing Stop ───────────────────────────────────────── */}
          <div className="pt-2 border-t border-slate-200 dark:border-slate-800">
            <div className="text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-3">
              Trailing Stop
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Trail trigger (%)"
                help="Move SL to breakeven once gain ≥ this. 0 = disabled."
              >
                <input
                  type="number"
                  min={0}
                  max={10}
                  step={0.1}
                  value={draft.trail_trigger_pct}
                  onChange={(e) =>
                    setField("trail_trigger_pct", Number(e.target.value))
                  }
                  className={inputCls}
                />
              </Field>
              <Field
                label="Trail step (%)"
                help="After trail fires, keep SL this % below the highest price."
              >
                <input
                  type="number"
                  min={0.1}
                  max={5}
                  step={0.1}
                  value={draft.trail_step_pct}
                  onChange={(e) =>
                    setField("trail_step_pct", Number(e.target.value))
                  }
                  className={inputCls}
                />
              </Field>
            </div>
          </div>

          {/* ── 9-Strategy Algo Engine Gate ─────────────────────────── */}
          <div className="pt-2 border-t border-slate-200 dark:border-slate-800">
            <div className="text-[11px] uppercase tracking-wide font-semibold text-indigo-600 dark:text-indigo-400 mb-3">
              9-Strategy Algo Engine Gate
            </div>

            <label className="flex items-start gap-2 cursor-pointer select-none mb-3">
              <input
                type="checkbox"
                checked={draft.use_algo_engine}
                onChange={(e) => setField("use_algo_engine", e.target.checked)}
                className="w-4 h-4 mt-0.5"
              />
              <span className="text-sm">
                <span className="font-semibold">Use 9-strategy engine as entry gate</span>
                <span className="block text-[11px] text-slate-500 mt-0.5">
                  When ON, the auto-trader runs all 9 strategies and only enters
                  when the confluence count meets the minimum below. Recommended: ON.
                </span>
              </span>
            </label>

            <Field
              label="Min confluence count"
              help="Strategies that must agree before a trade is opened. 3=MEDIUM, 4=HIGH, 5=very high conviction."
            >
              <input
                type="number"
                min={1}
                max={9}
                step={1}
                disabled={!draft.use_algo_engine}
                value={draft.min_confluence_count}
                onChange={(e) =>
                  setField("min_confluence_count", Number(e.target.value))
                }
                className={inputCls + (draft.use_algo_engine ? "" : " opacity-40 cursor-not-allowed")}
              />
            </Field>

            {draft.use_algo_engine && (
              <div className="mt-2 text-[11px] rounded-lg border border-indigo-200 dark:border-indigo-900 bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 px-3 py-2">
                Entry requires: composite score ≥ {draft.min_composite_score}{" "}
                <strong>AND</strong> algo confluence ≥ {draft.min_confluence_count}/9{" "}
                <strong>AND</strong> all pre-trade filters pass
              </div>
            )}
          </div>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={draft.auto_trading_enabled}
              onChange={(e) =>
                setField("auto_trading_enabled", e.target.checked)
              }
              className="w-4 h-4"
            />
            <span className="text-sm font-semibold">
              Auto-trading enabled
            </span>
          </label>
        </div>

        {err && (
          <div className="mt-4 p-2 rounded bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900 text-xs text-rose-700 dark:text-rose-300">
            {err}
          </div>
        )}

        <div className="mt-6 flex gap-2">
          <button
            onClick={save}
            disabled={saving}
            className="flex-1 text-sm px-4 py-2 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            onClick={onClose}
            className="text-sm px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Cancel
          </button>
        </div>

      </div>
    </div>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 font-semibold mb-1">
        {label}
      </div>
      {children}
      {help && (
        <div className="text-[11px] text-slate-500 mt-1">{help}</div>
      )}
    </label>
  );
}
