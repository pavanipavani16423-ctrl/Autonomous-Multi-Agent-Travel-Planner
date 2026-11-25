"use client";

import { Droplets } from "lucide-react";
import { motion } from "motion/react";
import { ProvenancePill } from "@/components/ui/pills";
import { cn, parseISODate } from "@/lib/format";
import type { DailyWeather, Provenance } from "@/lib/types";
import { wmo } from "@/lib/wmo";

const TONE: Record<string, string> = {
  sun: "text-[#e0a020]",
  cloud: "text-ink-3",
  rain: "text-[var(--p-guide)]",
  snow: "text-[#7fb2d9]",
  storm: "text-[#8a4fb3]",
};

/** Daily weather from WMO codes, with the provenance of the numbers stated once for the strip. */
export function WeatherStrip({ days, compact, className }: { days: DailyWeather[]; compact?: boolean; className?: string }) {
  if (!days.length) return null;
  const provs = Array.from(new Set(days.map((d) => d.provenance))) as Provenance[];
  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="eyebrow">Weather</span>
        {provs.map((p) => (
          <ProvenancePill key={p} value={p} />
        ))}
        {provs.includes("estimate") && <span className="text-[11px] text-ink-3">seasonal normals — not a forecast</span>}
      </div>
      <ul className="scrollbar-none flex gap-2 overflow-x-auto pb-1">
        {days.map((d, i) => {
          const w = wmo(d.code);
          const date = parseISODate(d.date);
          return (
            <motion.li
              key={d.date}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              title={`${d.summary} · ${w.label}`}
              className={cn(
                // `relative` keeps the sr-only label inside the scroller (otherwise it widens the page).
                "relative flex shrink-0 items-center gap-2.5 rounded-2xl border border-line bg-surface px-3 py-2",
                compact ? "min-w-[7.5rem]" : "min-w-[9.5rem]",
                d.precip_mm > 3 && "border-[var(--p-guide)]/30 bg-[var(--p-guide-bg)]",
              )}
            >
              <w.Icon className={cn("h-6 w-6 shrink-0", TONE[w.tone])} aria-hidden />
              <div className="leading-tight">
                <p className="text-[11px] font-semibold text-ink-3">
                  {date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}
                </p>
                <p className="tabular text-sm font-bold">
                  {Math.round(d.t_max)}° <span className="font-medium text-ink-3">/ {Math.round(d.t_min)}°</span>
                </p>
                {!compact && (
                  <p className="flex items-center gap-1 text-[11px] text-ink-2">
                    <Droplets className="h-3 w-3" aria-hidden />
                    {d.precip_mm.toFixed(1)} mm{d.precip_prob != null ? ` · ${d.precip_prob}%` : ""}
                  </p>
                )}
                <span className="sr-only">{w.label}. {d.summary}</span>
              </div>
            </motion.li>
          );
        })}
      </ul>
    </div>
  );
}
