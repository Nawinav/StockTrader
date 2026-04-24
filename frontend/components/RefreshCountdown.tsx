"use client";

import { useEffect, useState } from "react";

type Props = {
  nextRefreshAt: string; // ISO
  onTick?: () => void;
};

export function RefreshCountdown({ nextRefreshAt, onTick }: Props) {
  const target = new Date(nextRefreshAt).getTime();
  const [remaining, setRemaining] = useState(target - Date.now());

  useEffect(() => {
    setRemaining(target - Date.now());
    const id = setInterval(() => {
      const r = target - Date.now();
      setRemaining(r);
      if (r <= 0 && onTick) onTick();
    }, 1000);
    return () => clearInterval(id);
  }, [target, onTick]);

  if (remaining <= 0) {
    return <span className="text-xs text-amber-600">Refreshing…</span>;
  }

  const mins = Math.floor(remaining / 60000);
  const secs = Math.floor((remaining % 60000) / 1000);
  return (
    <span className="text-xs text-slate-500">
      next refresh in <span className="font-mono">{mins}:{secs.toString().padStart(2, "0")}</span>
    </span>
  );
}
