import { cn } from "@/lib/format";
import type { Provenance, Rating } from "@/lib/types";

const PROV: Record<Provenance, { label: string; color: string; bg: string; hint: string }> = {
  live: { label: "live", color: "var(--p-live)", bg: "var(--p-live-bg)", hint: "Fetched live from an MCP tool during this run" },
  guidebook: { label: "guidebook", color: "var(--p-guide)", bg: "var(--p-guide-bg)", hint: "Retrieved from the Wikivoyage guidebook (RAG)" },
  estimate: { label: "estimate", color: "var(--p-est)", bg: "var(--p-est-bg)", hint: "Estimated by the agents — not a live quote" },
  cached: { label: "cached", color: "var(--p-cache)", bg: "var(--p-cache-bg)", hint: "Served from a recent cached tool result" },
  unavailable: { label: "unavailable", color: "var(--p-na)", bg: "var(--p-na-bg)", hint: "The source was unavailable; shown without data" },
};

/** One consistent provenance language everywhere: live / guidebook / estimate / cached / unavailable. */
export function ProvenancePill({ value, className }: { value: Provenance; className?: string }) {
  const p = PROV[value] ?? PROV.estimate;
  return (
    <span
      title={p.hint}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-[3px] font-mono text-[10.5px] font-medium uppercase leading-none tracking-wider",
        className,
      )}
      style={{ color: p.color, background: p.bg }}
    >
      <span
        className={cn("h-1.5 w-1.5 rounded-full", value === "live" && "live-dot")}
        style={{ background: p.color }}
        aria-hidden
      />
      {p.label}
      <span className="sr-only">: {p.hint}</span>
    </span>
  );
}

export const PROVENANCE_META = PROV;

const RATING: Record<Rating, { color: string; bg: string }> = {
  Good: { color: "var(--p-live)", bg: "var(--p-live-bg)" },
  OK: { color: "var(--p-est)", bg: "var(--p-est-bg)" },
  Weak: { color: "var(--p-na)", bg: "var(--p-na-bg)" },
};

export function RatingPill({ rating, className }: { rating: Rating; className?: string }) {
  const r = RATING[rating] ?? RATING.OK;
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold leading-none", className)}
      style={{ color: r.color, background: r.bg }}
    >
      {rating}
    </span>
  );
}

export function Tag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold text-ink-2",
        className,
      )}
    >
      {children}
    </span>
  );
}
