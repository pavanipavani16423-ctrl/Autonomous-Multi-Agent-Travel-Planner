"use client";

import { Clock, Footprints, Home, Lightbulb, MapPin, Sparkles, Sun as SunIcon, Wallet } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { ProvenancePill } from "@/components/ui/pills";
import { CATEGORY } from "@/lib/categories";
import { cn, formatDuration, formatMoney, parseISODate } from "@/lib/format";
import type { Activity, ActivitySlot, DayPlan } from "@/lib/types";
import { wmo } from "@/lib/wmo";
import { CitationList } from "./citations";

const SLOT_LABEL: Record<ActivitySlot, string> = { morning: "Morning", afternoon: "Afternoon", evening: "Evening" };

export function DayTabs({ days, value, onChange }: { days: DayPlan[]; value: number; onChange: (i: number) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Days"
      className="scrollbar-none -mx-1 flex gap-2 overflow-x-auto px-1 pb-1"
      onKeyDown={(e) => {
        const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!dir) return;
        e.preventDefault();
        const next = (value + dir + days.length) % days.length;
        onChange(next);
        requestAnimationFrame(() => document.getElementById(`day-tab-${next}`)?.focus());
      }}
    >
      {days.map((d, i) => {
        const on = i === value;
        const W = d.weather ? wmo(d.weather.code) : null;
        return (
          <button
            key={d.day}
            id={`day-tab-${i}`}
            role="tab"
            type="button"
            aria-selected={on}
            aria-controls="day-panel"
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(i)}
            className={cn(
              "flex shrink-0 items-center gap-2.5 rounded-2xl border px-3.5 py-2.5 text-left transition",
              on ? "border-ink bg-ink text-bg shadow-card" : "border-line bg-surface hover:border-line-strong",
            )}
          >
            <span className={cn("font-display text-2xl font-semibold leading-none", on ? "text-sun" : "text-ink-3")}>{d.day}</span>
            <span className="leading-tight">
              <span className="block text-[11px] font-semibold uppercase tracking-wider opacity-70">
                {parseISODate(d.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}
              </span>
              <span className="block max-w-[9rem] truncate text-sm font-bold">{d.theme.split(" · ")[0]}</span>
            </span>
            {W && <W.Icon className="h-4 w-4 shrink-0 opacity-80" aria-label={W.label} />}
          </button>
        );
      })}
    </div>
  );
}

function ActivityCard({
  a,
  n,
  focused,
  changed,
  onFocus,
}: {
  a: Activity;
  n: number;
  focused: boolean;
  changed: boolean;
  onFocus: (id: string | null) => void;
}) {
  const C = CATEGORY[a.category] ?? CATEGORY.sight;
  return (
    <motion.li
      layout
      initial={changed ? { opacity: 0, scale: 0.96, y: 10 } : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, x: -30, transition: { duration: 0.25 } }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="relative pl-12"
    >
      <span
        className="absolute left-0 top-5 flex h-8 w-8 items-center justify-center rounded-full border-[2.5px] border-surface text-[13px] font-bold text-white shadow-card"
        style={{ background: C.color }}
        aria-hidden
      >
        {n}
      </span>
      <article
        tabIndex={0}
        data-pin-target={a.id}
        onMouseEnter={() => onFocus(a.id)}
        onMouseLeave={() => onFocus(null)}
        onFocus={() => onFocus(a.id)}
        onClick={() => onFocus(a.id)}
        aria-label={`Stop ${n}: ${a.title} at ${a.time}`}
        className={cn(
          "card group relative cursor-pointer p-4 transition-[box-shadow,border-color,transform] duration-300 hover:-translate-y-0.5 sm:p-5",
          focused && "border-coral shadow-[0_0_0_3px_var(--coral-soft),var(--shadow-card)]",
          changed && "ring-2 ring-sun ring-offset-2 ring-offset-bg",
        )}
      >
        {changed && (
          <span className="absolute -top-2.5 right-4 inline-flex items-center gap-1 rounded-full bg-sun px-2 py-0.5 text-[10.5px] font-bold text-[#0f2430]">
            <Sparkles className="h-3 w-3" aria-hidden /> Updated
          </span>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-semibold text-ink-3">
          <span className="tabular font-mono text-[13px] font-bold text-ink">{a.time}</span>
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" aria-hidden /> {formatDuration(a.duration_min)}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5" style={{ color: C.color, background: `${C.color}1a` }}>
            <C.Icon className="h-3.5 w-3.5" aria-hidden /> {C.label}
          </span>
          <span className="inline-flex items-center gap-1">
            {a.indoor ? <Home className="h-3.5 w-3.5" aria-hidden /> : <SunIcon className="h-3.5 w-3.5" aria-hidden />}
            {a.indoor ? "Indoor" : "Outdoor"}
          </span>
          <span className="ml-auto inline-flex items-center gap-1 text-ink">
            <Wallet className="h-3.5 w-3.5 text-ink-3" aria-hidden />
            <span className="tabular">{a.cost.amount === 0 ? "Free" : formatMoney(a.cost)}</span>
          </span>
        </div>
        <h4 className="mt-2 font-display text-[1.3rem] font-semibold leading-snug">{a.title}</h4>
        <p className="mt-1.5 text-[0.93rem] leading-relaxed text-ink-2">{a.description}</p>
        {a.tip && (
          <p className="mt-3 flex gap-2 rounded-xl bg-sun-soft px-3 py-2 text-[13px] leading-snug">
            <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {a.tip}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {a.place && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-ink-3">
              <MapPin className="h-3.5 w-3.5" aria-hidden /> {a.place}
            </span>
          )}
          <CitationList ids={a.citations} className="ml-auto" />
        </div>
      </article>
    </motion.li>
  );
}

/** One day: header (weather, walking, cost) and a timeline of activity cards numbered like the map pins. */
export function DayView({
  day,
  focusId,
  changedIds,
  onFocus,
}: {
  day: DayPlan;
  focusId: string | null;
  changedIds: Set<string>;
  onFocus: (id: string | null) => void;
}) {
  const W = day.weather ? wmo(day.weather.code) : null;
  return (
    <section id="day-panel" role="tabpanel" aria-labelledby={`day-tab-${day.day - 1}`} className="mt-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">
            Day {day.day} · {parseISODate(day.date).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h3 className="mt-1 font-display text-3xl font-semibold leading-tight">{day.title}</h3>
          <p className="mt-0.5 text-sm text-ink-2">{day.theme}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
          {day.weather && W && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1.5">
              <W.Icon className="h-4 w-4" aria-hidden />
              {Math.round(day.weather.t_max)}°/{Math.round(day.weather.t_min)}° · {day.weather.summary}
              <ProvenancePill value={day.weather.provenance} />
            </span>
          )}
          {day.walking_km != null && (
            <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1.5">
              <Footprints className="h-3.5 w-3.5" aria-hidden /> {day.walking_km.toFixed(1)} km
            </span>
          )}
          <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1.5">
            <Wallet className="h-3.5 w-3.5" aria-hidden /> {formatMoney(day.day_cost)}
            <ProvenancePill value="estimate" />
          </span>
        </div>
      </div>

      <ol className="relative mt-6 space-y-4 before:absolute before:bottom-4 before:left-4 before:top-4 before:w-px before:bg-line-strong">
        <AnimatePresence initial={false} mode="popLayout">
          {day.activities.flatMap((a, i) => {
            const header = i === 0 || day.activities[i - 1].slot !== a.slot ? SLOT_LABEL[a.slot] : null;
            return [
              header && (
                <motion.li layout key={`slot-${a.slot}`} className="relative pl-12 pt-1">
                  <span className="absolute left-[11px] top-2.5 h-2.5 w-2.5 rounded-full border-2 border-bg bg-ink-3" aria-hidden />
                  <span className="eyebrow">{header}</span>
                </motion.li>
              ),
              <ActivityCard key={a.id} a={a} n={i + 1} focused={focusId === a.id} changed={changedIds.has(a.id)} onFocus={onFocus} />,
            ].filter(Boolean);
          })}
        </AnimatePresence>
      </ol>
    </section>
  );
}
