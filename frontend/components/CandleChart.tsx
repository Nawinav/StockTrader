"use client";

import { useEffect, useRef } from "react";
import type { UTCTimestamp } from "lightweight-charts";
import type { ChartCandle } from "@/lib/api";

type Props = {
  candles: ChartCandle[];
  supports?: number[];
  resistances?: number[];
  height?: number;
};

/**
 * Candlestick chart with volume histogram, overlaid support/resistance lines.
 * Uses lightweight-charts; rendered client-side only.
 */
export function CandleChart({
  candles,
  supports = [],
  resistances = [],
  height = 420,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;
    let disposed = false;

    let dispose: (() => void) | null = null;

    (async () => {
      // Dynamic import keeps the library out of the initial bundle.
      const lwc = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;

      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const chart = lwc.createChart(containerRef.current, {
        layout: {
          background: { color: "transparent" },
          textColor: dark ? "#cbd5e1" : "#334155",
        },
        grid: {
          vertLines: { color: dark ? "#1e293b" : "#e2e8f0" },
          horzLines: { color: dark ? "#1e293b" : "#e2e8f0" },
        },
        rightPriceScale: { borderColor: dark ? "#334155" : "#cbd5e1" },
        timeScale: {
          borderColor: dark ? "#334155" : "#cbd5e1",
          timeVisible: true,
          secondsVisible: false,
        },
        crosshair: { mode: 1 }, // magnet
        height,
      });

      const candleSeries = chart.addCandlestickSeries({
        upColor: "#10b981",
        downColor: "#ef4444",
        borderUpColor: "#10b981",
        borderDownColor: "#ef4444",
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
      });
      candleSeries.setData(
        candles.map((c) => ({
          time: c.time as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })),
      );

      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "",
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeries.setData(
        candles.map((c) => ({
          time: c.time as UTCTimestamp,
          value: c.volume,
          color: c.close >= c.open ? "#10b98155" : "#ef444455",
        })),
      );

      // Overlay horizontal lines for S/R.
      supports.forEach((lvl) =>
        candleSeries.createPriceLine({
          price: lvl,
          color: "#10b981",
          lineWidth: 1,
          lineStyle: lwc.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `S ${lvl.toFixed(2)}`,
        }),
      );
      resistances.forEach((lvl) =>
        candleSeries.createPriceLine({
          price: lvl,
          color: "#ef4444",
          lineWidth: 1,
          lineStyle: lwc.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `R ${lvl.toFixed(2)}`,
        }),
      );

      chart.timeScale().fitContent();

      const onResize = () => {
        if (containerRef.current) {
          chart.applyOptions({ width: containerRef.current.clientWidth });
        }
      };
      window.addEventListener("resize", onResize);
      onResize();

      dispose = () => {
        window.removeEventListener("resize", onResize);
        chart.remove();
      };
    })();

    return () => {
      disposed = true;
      if (dispose) dispose();
    };
  }, [candles, supports, resistances, height]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
