"use client";

import { Banknote, Bus, CheckSquare, IdCard, Lightbulb, MapPinned, Plane, ShieldAlert, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { ProvenancePill } from "@/components/ui/pills";
import { cn, formatMoney } from "@/lib/format";
import type { PreTrip } from "@/lib/types";
import { CitationList } from "./citations";

function Block({ icon, title, children, className }: { icon: React.ReactNode; title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("card p-5", className)}>
      <h4 className="flex items-center gap-2 text-sm font-bold">
        {icon}
        {title}
      </h4>
      <div className="mt-2.5 text-sm leading-relaxed text-ink-2">{children}</div>
    </section>
  );
}

function usePacking(tripId: string, count: number) {
  const key = `voyager.packing.${tripId}`;
  const [checked, setChecked] = useState<number[]>([]);
  useEffect(() => {
    let alive = true;
    queueMicrotask(() => {
      if (!alive) return;
      try {
        const raw = localStorage.getItem(key);
        if (raw) setChecked((JSON.parse(raw) as number[]).filter((n) => n < count));
      } catch {
        /* ignore */
      }
    });
    return () => {
      alive = false;
    };
  }, [key, count]);
  const toggle = (i: number) =>
    setChecked((prev) => {
      const next = prev.includes(i) ? prev.filter((n) => n !== i) : [...prev, i];
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  return { checked, toggle };
}

export function PreTripPanel({ pre, tripId }: { pre: PreTrip; tripId: string }) {
  const { checked, toggle } = usePacking(tripId, pre.packing.length);
  const done = checked.length;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <section className="card p-5 lg:col-span-2">
        <h4 className="flex items-center gap-2 text-sm font-bold">
          <Plane className="h-4 w-4 text-coral" aria-hidden /> Getting there
        </h4>
        <p className="mt-2 font-display text-2xl font-semibold leading-tight">{pre.getting_there.mode}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded-full bg-bg-2 px-2.5 py-1">{pre.getting_there.duration}</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-2 px-2.5 py-1">
            {formatMoney(pre.getting_there.cost)} <ProvenancePill value="estimate" />
          </span>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-ink-2">{pre.getting_there.note}</p>
      </section>

      <section className="card row-span-2 p-5" aria-labelledby="packing-title">
        <div className="flex items-center justify-between">
          <h4 id="packing-title" className="flex items-center gap-2 text-sm font-bold">
            <CheckSquare className="h-4 w-4 text-lagoon" aria-hidden /> Packing list
          </h4>
          <span className="tabular text-xs font-semibold text-ink-3">
            {done}/{pre.packing.length}
          </span>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bg-2" aria-hidden>
          <div className="h-full rounded-full bg-lagoon transition-[width] duration-500" style={{ width: `${pre.packing.length ? (done / pre.packing.length) * 100 : 0}%` }} />
        </div>
        <ul className="mt-3 space-y-1">
          {pre.packing.map((item, i) => {
            const on = checked.includes(i);
            return (
              <li key={item}>
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => toggle(i)}
                  className="flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-bg-2"
                >
                  {on ? <CheckSquare className="mt-0.5 h-4 w-4 shrink-0 text-lagoon" aria-hidden /> : <Square className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" aria-hidden />}
                  <span className={cn(on && "text-ink-3 line-through")}>{item}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[11px] text-ink-3">Saved on this device.</p>
      </section>

      <Block icon={<IdCard className="h-4 w-4 text-[var(--p-guide)]" aria-hidden />} title="Visa">
        {pre.visa}
      </Block>
      <Block icon={<Banknote className="h-4 w-4 text-[var(--p-live)]" aria-hidden />} title="Money">
        {pre.currency_note}
      </Block>
      <Block icon={<Bus className="h-4 w-4 text-ink-3" aria-hidden />} title="Getting around" className="lg:col-span-2">
        {pre.getting_around}
      </Block>
      <Block icon={<ShieldAlert className="h-4 w-4 text-coral" aria-hidden />} title="Stay safe">
        <ul className="list-disc space-y-1 pl-4">
          {pre.safety.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </Block>
      <Block icon={<Lightbulb className="h-4 w-4 text-sun" aria-hidden />} title="Local tips">
        <ul className="list-disc space-y-1 pl-4">
          {pre.local_tips.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </Block>
      <Block icon={<MapPinned className="h-4 w-4 text-lagoon" aria-hidden />} title="Best areas to base yourself">
        <ul className="flex flex-wrap gap-1.5">
          {pre.best_areas.map((a) => (
            <li key={a} className="rounded-full border border-line px-2.5 py-1 text-xs font-semibold text-ink">
              {a}
            </li>
          ))}
        </ul>
        {pre.citations.length > 0 && (
          <p className="mt-4 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            Sources <CitationList ids={pre.citations} />
          </p>
        )}
      </Block>
    </div>
  );
}
