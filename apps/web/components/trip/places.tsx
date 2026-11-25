"use client";

import { BedDouble, ExternalLink, Info, Leaf, MapPin, Star, UtensilsCrossed } from "lucide-react";
import { motion } from "motion/react";
import { ProvenancePill, Tag } from "@/components/ui/pills";
import { cn, currencySymbol, formatMoney } from "@/lib/format";
import type { FoodPick, Stay } from "@/lib/types";
import { CitationList } from "./citations";

const KIND: Record<Stay["kind"], string> = {
  hotel: "Hotel",
  hostel: "Hostel",
  guest_house: "Guest house",
  apartment: "Apartment",
  resort: "Resort",
};

function EstimateNote({ what }: { what: string }) {
  return (
    <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-ink-2">
      <Info className="mr-1.5 inline h-3.5 w-3.5 align-[-2px]" aria-hidden />
      {what} Names and locations marked <ProvenancePill value="live" /> come from OpenStreetMap during this run; prices are estimates unless a live quote was available.
    </p>
  );
}

export function StaysPanel({ stays, nights, focusId, onFocus }: { stays: Stay[]; nights: number; focusId: string | null; onFocus: (id: string | null) => void }) {
  if (!stays.length) return <p className="text-sm text-ink-3">No stays were found for this trip.</p>;
  return (
    <div>
      <EstimateNote what={`${stays.length} places matched to your stay style and budget.`} />
      <ul className="grid gap-3">
        {stays.map((s, i) => {
          const id = `stay-${i}`;
          return (
            <motion.li key={`${s.name}-${i}`} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
              <article
                tabIndex={0}
                data-pin-target={id}
                onMouseEnter={() => onFocus(id)}
                onMouseLeave={() => onFocus(null)}
                onFocus={() => onFocus(id)}
                className={cn("card flex gap-4 p-4 transition sm:p-5", focusId === id && "border-coral shadow-[0_0_0_3px_var(--coral-soft),var(--shadow-card)]")}
              >
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#0e4a5c] text-white">
                  <BedDouble className="h-5 w-5" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h4 className="font-display text-xl font-semibold leading-tight">{s.name}</h4>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
                        <span>{KIND[s.kind] ?? s.kind}</span>·
                        <span className="inline-flex items-center gap-1">
                          <MapPin className="h-3 w-3" aria-hidden />
                          {s.area}
                        </span>
                        {s.rating != null && (
                          <>
                            ·
                            <span className="inline-flex items-center gap-0.5 font-semibold text-ink-2">
                              <Star className="h-3 w-3 fill-sun text-sun" aria-hidden /> {s.rating.toFixed(1)}
                            </span>
                          </>
                        )}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="tabular font-display text-xl font-semibold">{formatMoney(s.price_per_night)}</p>
                      <p className="text-[11px] text-ink-3">
                        per night · ≈ {formatMoney({ ...s.price_per_night, amount: s.price_per_night.amount * nights })} total
                      </p>
                    </div>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-ink-2">{s.why}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <ProvenancePill value={s.provenance} />
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-ink-2 hover:text-coral">
                        View <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    )}
                    <CitationList ids={s.citations} className="ml-auto" />
                  </div>
                </div>
              </article>
            </motion.li>
          );
        })}
      </ul>
    </div>
  );
}

export function FoodPanel({
  food,
  diet,
  currency,
  focusId,
  onFocus,
}: {
  food: FoodPick[];
  diet: string[];
  currency: string;
  focusId: string | null;
  onFocus: (id: string | null) => void;
}) {
  const sym = currencySymbol(currency);
  if (!food.length) return <p className="text-sm text-ink-3">No food picks were found for this trip.</p>;
  return (
    <div>
      <EstimateNote what={`${food.length} picks${diet.length ? ` that work for ${diet.join(" + ")} diets` : ""}.`} />
      <ul className="grid gap-3 sm:grid-cols-2">
        {food.map((f, i) => {
          const id = `food-${i}`;
          return (
            <motion.li key={`${f.name}-${i}`} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <article
                tabIndex={0}
                data-pin-target={id}
                onMouseEnter={() => onFocus(id)}
                onMouseLeave={() => onFocus(null)}
                onFocus={() => onFocus(id)}
                className={cn("card flex h-full flex-col p-4 transition", focusId === id && "border-coral shadow-[0_0_0_3px_var(--coral-soft),var(--shadow-card)]")}
              >
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sun text-[#0f2430]">
                    <UtensilsCrossed className="h-4 w-4" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h4 className="font-display text-lg font-semibold leading-tight">{f.name}</h4>
                    <p className="text-xs text-ink-3">
                      {f.cuisine}
                      {f.area ? ` · ${f.area}` : ""}
                    </p>
                  </div>
                  <span className="tabular font-mono text-sm font-bold" aria-label={`Price level ${f.price_level} of 4`}>
                    {sym.repeat(f.price_level)}
                    <span className="text-ink-3/40">{sym.repeat(4 - f.price_level)}</span>
                  </span>
                </div>
                <p className="mt-3 text-sm leading-relaxed">
                  <span className="font-semibold">Must try: </span>
                  <span className="text-ink-2">{f.must_try}</span>
                </p>
                <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
                  {f.diet_ok.map((d) => (
                    <Tag key={d} className="!border-lagoon/30 !text-lagoon">
                      <Leaf className="h-3 w-3" aria-hidden /> {d}
                    </Tag>
                  ))}
                  <ProvenancePill value={f.provenance} />
                  <CitationList ids={f.citations} className="ml-auto" />
                </div>
              </article>
            </motion.li>
          );
        })}
      </ul>
    </div>
  );
}
