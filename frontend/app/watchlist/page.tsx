"use client";

import { useCallback, useEffect, useState } from "react";
import type { WatchlistItem } from "@/lib/api";
import { api } from "@/lib/api";

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [symbol, setSymbol] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.listWatchlist();
      setItems(res.items);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol.trim()) return;
    setErr(null);
    try {
      await api.addWatchlist(symbol.trim().toUpperCase(), note.trim() || undefined);
      setSymbol("");
      setNote("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to add");
    }
  };

  const onRemove = async (sym: string) => {
    try {
      await api.removeWatchlist(sym);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to remove");
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Watchlist</h1>
        <p className="text-sm text-slate-500">
          Quick-access list of stocks you want to track. Add any NSE symbol from
          the dashboard with one click, or manually here.
        </p>
      </div>

      <form
        onSubmit={onAdd}
        className="flex flex-wrap gap-2 items-end p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
      >
        <div>
          <label className="block text-xs font-medium text-slate-500 mb-1">
            Symbol (NSE)
          </label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="RELIANCE"
            className="px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-transparent text-sm w-40"
          />
        </div>
        <div className="flex-1 min-w-[180px]">
          <label className="block text-xs font-medium text-slate-500 mb-1">
            Note (optional)
          </label>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Earnings next week"
            className="px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-transparent text-sm w-full"
          />
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded bg-brand-500 text-white text-sm font-medium hover:bg-brand-600"
        >
          Add
        </button>
      </form>

      {err && (
        <div className="p-3 rounded border border-rose-300 bg-rose-50 text-rose-800 text-sm">
          {err}
        </div>
      )}

      {loading && <div className="text-sm text-slate-500">Loading…</div>}

      {!loading && items.length === 0 && (
        <div className="text-sm text-slate-500">
          Watchlist is empty. Add a symbol above or from the dashboard.
        </div>
      )}

      {items.length > 0 && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Symbol</th>
                <th className="px-4 py-2 font-medium">Note</th>
                <th className="px-4 py-2 font-medium">Added</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr
                  key={it.symbol}
                  className="border-t border-slate-100 dark:border-slate-800"
                >
                  <td className="px-4 py-2 font-semibold">{it.symbol}</td>
                  <td className="px-4 py-2 text-slate-600 dark:text-slate-400">
                    {it.note || <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-2 text-slate-500 text-xs">
                    {new Date(it.added_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => onRemove(it.symbol)}
                      className="text-xs text-rose-600 hover:underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
