"use client";

import {
  ArrowRight,
  BedDouble,
  Building2,
  Coffee,
  Crown,
  Footprints,
  Gauge,
  Landmark,
  Loader2,
  Mountain,
  Palette,
  ScrollText,
  ShoppingBag,
  Sparkles,
  Tent,
  UtensilsCrossed,
  Wine,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { currencySymbol, formatMoney } from "@/lib/format";
import type { TripRequest } from "@/lib/types";
import { validateRequest } from "@/lib/validate";
import { DateRange } from "./date-range";
import { ChipGroup, FieldError, Segmented, Stepper } from "./fields";
import { PlaceInput } from "./place-input";

const INTERESTS = [
  { value: "food", label: "Food", icon: <UtensilsCrossed className="h-3.5 w-3.5" /> },
  { value: "temples", label: "Temples", icon: <Landmark className="h-3.5 w-3.5" /> },
  { value: "nature", label: "Nature", icon: <Mountain className="h-3.5 w-3.5" /> },
  { value: "history", label: "History", icon: <ScrollText className="h-3.5 w-3.5" /> },
  { value: "art", label: "Art", icon: <Palette className="h-3.5 w-3.5" /> },
  { value: "shopping", label: "Shopping", icon: <ShoppingBag className="h-3.5 w-3.5" /> },
  { value: "nightlife", label: "Nightlife", icon: <Wine className="h-3.5 w-3.5" /> },
  { value: "adventure", label: "Adventure", icon: <Tent className="h-3.5 w-3.5" /> },
];
const DIETS = ["vegetarian", "vegan", "halal", "jain", "gluten-free"].map((d) => ({ value: d, label: d[0].toUpperCase() + d.slice(1) }));

/** Rough INR multipliers only to scale the slider range per currency — the agents use live FX. */
const CURRENCIES: { code: string; perInr: number }[] = [
  { code: "INR", perInr: 1 },
  { code: "USD", perInr: 0.012 },
  { code: "EUR", perInr: 0.011 },
  { code: "GBP", perInr: 0.0094 },
  { code: "JPY", perInr: 1.79 },
  { code: "AED", perInr: 0.044 },
  { code: "SGD", perInr: 0.016 },
  { code: "THB", perInr: 0.41 },
  { code: "AUD", perInr: 0.018 },
];

function niceStep(n: number) {
  const p = 10 ** Math.floor(Math.log10(n));
  return p / 2;
}

export function TripForm({
  initial,
  onSubmit,
  submitting,
  submitLabel = "Start planning",
  serverError,
  compact,
}: {
  initial: TripRequest;
  onSubmit: (req: TripRequest) => void;
  submitting?: boolean;
  submitLabel?: string;
  serverError?: string | null;
  compact?: boolean;
}) {
  const [req, setReq] = useState<TripRequest>(initial);
  const [touched, setTouched] = useState(false);
  const errors = validateRequest(req);
  const shown = touched ? errors : {};
  const set = <K extends keyof TripRequest>(k: K, v: TripRequest[K]) => setReq((r) => ({ ...r, [k]: v }));

  const cur = CURRENCIES.find((c) => c.code === req.currency) ?? CURRENCIES[0];
  const min = Math.round(20000 * cur.perInr);
  const max = Math.round(1000000 * cur.perInr);
  const step = niceStep(max / 100);

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (Object.keys(errors).length) {
          const first = Object.keys(errors)[0];
          document.getElementById(first === "start_date" ? "dates" : first)?.focus();
          return;
        }
        onSubmit({ ...req, origin: req.origin?.trim() || undefined, notes: req.notes?.trim() || undefined });
      }}
      className="space-y-6"
    >
      <div className={compact ? "grid gap-5" : "grid gap-5 md:grid-cols-[1.4fr_1fr]"}>
        <div>
          <label className="label" htmlFor="destination">
            Destination
          </label>
          <PlaceInput
            value={req.destination}
            onChange={(v) => set("destination", v)}
            invalid={!!shown.destination}
            describedBy={shown.destination ? "err-destination" : undefined}
          />
          <FieldError id="err-destination" message={shown.destination} />
        </div>
        <div>
          <label className="label" htmlFor="origin">
            Travelling from <span className="font-medium text-ink-3">(optional)</span>
          </label>
          <input
            id="origin"
            className="field"
            placeholder="Bengaluru"
            value={req.origin ?? ""}
            onChange={(e) => set("origin", e.target.value)}
            autoComplete="address-level2"
          />
        </div>
      </div>

      <div>
        <span className="label" id="dates-label">
          Dates
        </span>
        <DateRange
          start={req.start_date}
          end={req.end_date}
          onChange={(s, e) => setReq((r) => ({ ...r, start_date: s, end_date: e }))}
          invalid={!!shown.start_date}
          describedBy={shown.start_date ? "err-dates" : "dates-label"}
        />
        <FieldError id="err-dates" message={shown.start_date} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Stepper label="Adults" value={req.adults} min={1} max={12} onChange={(n) => set("adults", n)} />
        <Stepper label="Children" value={req.children} min={0} max={10} onChange={(n) => set("children", n)} hint="Under 12" />
      </div>

      <div>
        <div className="flex items-end justify-between gap-3">
          <label className="label" htmlFor="budget">
            Total budget for the group
          </label>
          <span className="mb-1.5 font-display text-xl font-semibold tabular">{formatMoney({ amount: req.budget, currency: req.currency })}</span>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            aria-label="Budget slider"
            min={min}
            max={max}
            step={step}
            value={Math.min(max, Math.max(min, req.budget))}
            onChange={(e) => set("budget", Number(e.target.value))}
            className="h-2 flex-1"
          />
          <div className="relative w-36">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-ink-3">{currencySymbol(req.currency)}</span>
            <input
              id="budget"
              inputMode="numeric"
              className="field tabular !pl-8 !pr-2"
              value={req.budget ? String(req.budget) : ""}
              onChange={(e) => set("budget", Number(e.target.value.replace(/[^\d]/g, "")) || 0)}
              aria-invalid={!!shown.budget || undefined}
              aria-describedby={shown.budget ? "err-budget" : undefined}
            />
          </div>
          <label className="sr-only" htmlFor="currency">
            Currency
          </label>
          <select
            id="currency"
            className="field !w-24 !px-2"
            value={req.currency}
            onChange={(e) => {
              const next = CURRENCIES.find((c) => c.code === e.target.value) ?? CURRENCIES[0];
              const lo = Math.round(20000 * next.perInr);
              const hi = Math.round(1000000 * next.perInr);
              setReq((r) => ({
                ...r,
                currency: next.code,
                budget: r.budget < lo || r.budget > hi ? Math.round((150000 * next.perInr) / niceStep(hi / 100)) * niceStep(hi / 100) : r.budget,
              }));
            }}
          >
            {CURRENCIES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code}
              </option>
            ))}
          </select>
        </div>
        <FieldError id="err-budget" message={shown.budget} />
      </div>

      <ChipGroup label="What do you love?" options={INTERESTS} value={req.interests} onChange={(v) => set("interests", v)} />

      <div className={compact ? "grid gap-5" : "grid gap-5 md:grid-cols-2"}>
        <Segmented
          label="Pace"
          value={req.pace}
          onChange={(v) => set("pace", v)}
          options={[
            { value: "relaxed", label: "Relaxed", icon: <Coffee className="h-3.5 w-3.5" />, hint: "2–3 stops" },
            { value: "balanced", label: "Balanced", icon: <Footprints className="h-3.5 w-3.5" />, hint: "3–4 stops" },
            { value: "packed", label: "Packed", icon: <Zap className="h-3.5 w-3.5" />, hint: "5+ stops" },
          ]}
        />
        <Segmented
          label="Stay style"
          value={req.stay_style}
          onChange={(v) => set("stay_style", v)}
          options={[
            { value: "budget", label: "Budget", icon: <BedDouble className="h-3.5 w-3.5" />, hint: "hostels, guest houses" },
            { value: "mid", label: "Mid", icon: <Building2 className="h-3.5 w-3.5" />, hint: "comfy hotels" },
            { value: "luxury", label: "Luxury", icon: <Crown className="h-3.5 w-3.5" />, hint: "splurge" },
          ]}
        />
      </div>

      <ChipGroup label="Dietary needs" options={DIETS} value={req.diet} onChange={(v) => set("diet", v)} />

      <div>
        <label className="label" htmlFor="notes">
          Anything else? <span className="font-medium text-ink-3">(optional)</span>
        </label>
        <textarea
          id="notes"
          rows={2}
          className="field resize-none"
          placeholder="Anniversary trip, avoid long hikes, one of us loves tea…"
          value={req.notes ?? ""}
          maxLength={500}
          onChange={(e) => set("notes", e.target.value)}
        />
      </div>

      {serverError && (
        <p role="alert" className="rounded-xl bg-coral-soft px-4 py-3 text-sm font-semibold text-coral">
          {serverError}
        </p>
      )}

      <div className="flex flex-col-reverse items-stretch justify-between gap-3 border-t border-line pt-5 sm:flex-row sm:items-center">
        <p className="flex items-center gap-2 text-xs text-ink-3">
          <Gauge className="h-3.5 w-3.5" aria-hidden /> 11 agents · usually 30–60 s · every claim cited
        </p>
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
          {submitting ? "Starting the agents…" : submitLabel}
          {!submitting && <ArrowRight className="h-4 w-4" aria-hidden />}
        </button>
      </div>
    </form>
  );
}
