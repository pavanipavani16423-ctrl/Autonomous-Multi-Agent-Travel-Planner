"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { addDays, cn, daysBetweenInclusive, formatDateRange, parseISODate, toISODate } from "@/lib/format";
import { MAX_DAYS } from "@/lib/validate";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function monthGrid(year: number, month: number) {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7; // Monday-first
  const days = new Date(year, month + 1, 0).getDate();
  const cells: (Date | null)[] = Array.from({ length: offset }, () => null);
  for (let d = 1; d <= days; d++) cells.push(new Date(year, month, d));
  return cells;
}

/**
 * Inline range calendar (no popover, so it never clips inside a dialog). Max 14 days, no past dates,
 * arrow keys move by day/week.
 */
export function DateRange({
  start,
  end,
  onChange,
  invalid,
  describedBy,
}: {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
  invalid?: boolean;
  describedBy?: string;
}) {
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState<"start" | "end">("start");
  const [hover, setHover] = useState<string | null>(null);
  const initial = start ? parseISODate(start) : new Date();
  const [view, setView] = useState({ y: initial.getFullYear(), m: initial.getMonth() });
  const today = useMemo(() => toISODate(new Date()), []);
  const nights = start && end ? daysBetweenInclusive(start, end) : 0;

  const pick = (iso: string) => {
    if (picking === "start" || !start || iso < start) {
      onChange(iso, iso);
      setPicking("end");
      return;
    }
    let e = iso;
    if (daysBetweenInclusive(start, iso) > MAX_DAYS) e = toISODate(addDays(parseISODate(start), MAX_DAYS - 1));
    onChange(start, e);
    setPicking("start");
  };

  const shift = (dir: number) =>
    setView((v) => {
      const d = new Date(v.y, v.m + dir, 1);
      return { y: d.getFullYear(), m: d.getMonth() };
    });

  const months = [0, 1].map((k) => {
    const d = new Date(view.y, view.m + k, 1);
    return { y: d.getFullYear(), m: d.getMonth() };
  });
  const rangeEnd = picking === "end" && hover && start && hover >= start ? hover : end;

  const onGridKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const t = e.target as HTMLElement;
    const iso = t.dataset.date;
    if (!iso) return;
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (!delta) return;
    e.preventDefault();
    const next = toISODate(addDays(parseISODate(iso), delta));
    const el = e.currentTarget.querySelector<HTMLButtonElement>(`[data-date="${next}"]`);
    if (el && !el.disabled) el.focus();
    else if (next >= today) {
      shift(delta > 0 ? 1 : -1);
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-date="${next}"]`)?.focus());
    }
  };

  return (
    <div>
      <button
        type="button"
        id="dates"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="date-calendar"
        aria-describedby={describedBy}
        className={cn("field flex items-center gap-3 text-left", invalid && "!border-coral")}
      >
        <CalendarDays className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
        <span className="flex-1 font-semibold">{start && end ? formatDateRange(start, end) : "Choose dates"}</span>
        {nights > 0 && (
          <span className="rounded-full bg-sun-soft px-2 py-0.5 text-xs font-bold text-ink">
            {nights} day{nights === 1 ? "" : "s"}
          </span>
        )}
      </button>
      {open && (
        <div id="date-calendar" className="mt-2 rounded-2xl border border-line bg-surface p-3 shadow-card sm:p-4">
          <div className="mb-2 flex items-center justify-between">
            <button type="button" onClick={() => shift(-1)} className="rounded-full p-2 hover:bg-bg-2" aria-label="Previous month">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <p className="text-xs font-semibold text-ink-3" aria-live="polite">
              {picking === "start" ? "Pick the first day" : `Pick the last day (up to ${MAX_DAYS} days)`}
            </p>
            <button type="button" onClick={() => shift(1)} className="rounded-full p-2 hover:bg-bg-2" aria-label="Next month">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-5 sm:grid-cols-2" onKeyDown={onGridKey} onMouseLeave={() => setHover(null)}>
            {months.map(({ y, m }, k) => (
              <div key={`${y}-${m}`} className={cn(k === 1 && "hidden sm:block")}>
                <p className="mb-2 text-center font-display text-base font-semibold">
                  {new Date(y, m, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}
                </p>
                <div className="grid grid-cols-7 text-center text-[11px] font-bold uppercase text-ink-3" aria-hidden>
                  {WEEKDAYS.map((w) => (
                    <span key={w} className="py-1">
                      {w}
                    </span>
                  ))}
                </div>
                <div className="grid grid-cols-7 gap-y-0.5" role="grid" aria-label={new Date(y, m, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}>
                  {monthGrid(y, m).map((d, i) => {
                    if (!d) return <span key={`e${i}`} />;
                    const iso = toISODate(d);
                    const past = iso < today;
                    const isStart = iso === start;
                    const isEnd = iso === rangeEnd;
                    const inRange = start && rangeEnd && iso > start && iso < rangeEnd;
                    return (
                      <button
                        key={iso}
                        type="button"
                        data-date={iso}
                        disabled={past}
                        onClick={() => pick(iso)}
                        onMouseEnter={() => setHover(iso)}
                        aria-pressed={isStart || isEnd}
                        aria-label={d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
                        className={cn(
                          "tabular relative mx-auto flex h-9 w-full items-center justify-center text-sm transition",
                          past && "cursor-not-allowed text-ink-3/50 line-through decoration-ink-3/30",
                          inRange && "bg-sun-soft",
                          isStart && rangeEnd && rangeEnd !== start && "rounded-l-full bg-sun-soft",
                          isEnd && rangeEnd !== start && "rounded-r-full bg-sun-soft",
                          !past && !isStart && !isEnd && "hover:font-bold",
                        )}
                      >
                        <span
                          className={cn(
                            "flex h-9 w-9 items-center justify-center rounded-full",
                            (isStart || isEnd) && "bg-ink font-bold text-bg",
                            iso === today && !isStart && !isEnd && "ring-1 ring-line-strong",
                          )}
                        >
                          {d.getDate()}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex justify-end">
            <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
