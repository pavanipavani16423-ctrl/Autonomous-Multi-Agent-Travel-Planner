"use client";

import { BookOpenCheck, Loader2, MapPin, Telescope } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import { COVERED_FALLBACK } from "@/lib/covered";
import { cn } from "@/lib/format";
import type { PlaceSuggestion } from "@/lib/types";

function offlineSuggest(q: string): PlaceSuggestion[] {
  const s = q.trim().toLowerCase();
  if (!s) return [];
  return COVERED_FALLBACK.filter((c) => c.name.toLowerCase().startsWith(s) || c.name.toLowerCase().includes(` ${s}`))
    .slice(0, 6)
    .map((c) => ({ name: c.name, country: c.country, lat: 0, lon: 0, covered: true }));
}

/**
 * Destination combobox backed by GET /api/places/suggest. Each option says whether the city is already
 * in the guidebook or will be researched live (the brief agent expands the knowledge base on demand).
 */
export function PlaceInput({
  value,
  onChange,
  invalid,
  describedBy,
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  invalid?: boolean;
  describedBy?: string;
  autoFocus?: boolean;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<PlaceSuggestion[]>([]);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [offline, setOffline] = useState(false);
  const [query, setQuery] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (query === null) return;
    const q = query.trim();
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      if (q.length < 2) {
        setItems([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      api
        .suggest(q, ctrl.signal)
        .then((res) => {
          setItems(res.slice(0, 6));
          setOffline(false);
        })
        .catch((err: unknown) => {
          if (ctrl.signal.aborted) return;
          void err;
          setItems(offlineSuggest(q));
          setOffline(true);
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setLoading(false);
        });
    }, 220);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [query]);

  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  const choose = (s: PlaceSuggestion) => {
    onChange(s.name);
    setOpen(false);
    setActive(-1);
  };

  const showList = open && (items.length > 0 || loading);
  return (
    <div ref={wrapRef} className="relative">
      <MapPin className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
      <input
        id="destination"
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder="Kyoto, Lisbon, Udaipur…"
        className="field !pl-10"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setQuery(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => value.length >= 2 && setOpen(true)}
        onKeyDown={(e) => {
          if (!showList) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(items.length - 1, a + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (e.key === "Enter" && active >= 0) {
            e.preventDefault();
            choose(items[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {loading && <Loader2 className="absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-ink-3" aria-hidden />}
      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 top-[calc(100%+6px)] z-30 overflow-hidden rounded-2xl border border-line bg-surface p-1.5 shadow-float"
        >
          {items.map((s, i) => (
            <li
              key={`${s.name}-${s.country}-${i}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onPointerDown={(e) => {
                e.preventDefault();
                choose(s);
              }}
              onMouseEnter={() => setActive(i)}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm",
                i === active ? "bg-bg-2" : "hover:bg-bg-2",
              )}
            >
              <MapPin className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
              <span className="min-w-0 flex-1 truncate">
                <span className="font-semibold">{s.name}</span>
                <span className="text-ink-3">, {s.country}</span>
              </span>
              {s.covered ? (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-lagoon-soft px-2 py-0.5 text-[11px] font-bold text-lagoon">
                  <BookOpenCheck className="h-3 w-3" aria-hidden /> In guidebook
                </span>
              ) : (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-sun-soft px-2 py-0.5 text-[11px] font-bold text-ink-2">
                  <Telescope className="h-3 w-3" aria-hidden /> Will research live
                </span>
              )}
            </li>
          ))}
          {offline && items.length > 0 && (
            <li className="px-3 pb-1 pt-2 text-[11px] text-ink-3" role="presentation">
              Showing guidebook cities offline — any city works once the planner is awake.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
