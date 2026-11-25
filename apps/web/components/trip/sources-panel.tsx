import { ExternalLink } from "lucide-react";
import { SOURCE } from "@/lib/categories";
import type { CitationSource, TripPlan } from "@/lib/types";

/** Every citation in the plan, grouped by source, with how many places in the plan rely on it. */
export function SourcesPanel({ plan }: { plan: TripPlan }) {
  const uses = new Map<string, number>();
  const bump = (ids: string[]) => ids.forEach((id) => uses.set(id, (uses.get(id) ?? 0) + 1));
  plan.days.forEach((d) => d.activities.forEach((a) => bump(a.citations)));
  plan.stays.forEach((s) => bump(s.citations));
  plan.food.forEach((f) => bump(f.citations));
  bump(plan.pre_trip.citations);

  const groups = new Map<CitationSource, typeof plan.citations>();
  plan.citations.forEach((c) => groups.set(c.source, [...(groups.get(c.source) ?? []), c]));

  return (
    <div className="space-y-6">
      <p className="text-sm text-ink-2">
        {plan.citations.length} sources back this plan. Grounding coverage is{" "}
        <span className="font-bold text-ink">{Math.round(plan.quality.grounding_coverage * 100)}%</span> — the share of plan items that cite at least one of them.
      </p>
      {Array.from(groups.entries()).map(([source, list]) => {
        const S = SOURCE[source] ?? SOURCE.wikivoyage;
        return (
          <section key={source}>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-bold">
              <S.Icon className="h-4 w-4 text-ink-3" aria-hidden /> {S.label}
              <span className="font-mono text-xs font-medium text-ink-3">{list.length}</span>
            </h4>
            <ul className="grid gap-2 md:grid-cols-2">
              {list.map((c) => (
                <li key={c.id} id={`cite-${c.id}`} className="card flex gap-3 p-4">
                  <span className="h-fit rounded-md bg-[var(--p-guide-bg)] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[var(--p-guide)]">{c.id}</span>
                  <div className="min-w-0 flex-1">
                    <a href={c.url} target="_blank" rel="noreferrer" className="group inline-flex items-center gap-1 text-sm font-bold hover:text-coral">
                      {c.title} <ExternalLink className="h-3 w-3 opacity-50 group-hover:opacity-100" aria-hidden />
                    </a>
                    <p className="mt-1 line-clamp-3 text-[13px] leading-relaxed text-ink-2">“{c.snippet}”</p>
                    <p className="mt-1.5 text-[11px] text-ink-3">
                      Cited {uses.get(c.id) ?? 0}× in this plan
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
