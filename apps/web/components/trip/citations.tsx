"use client";

import { ExternalLink } from "lucide-react";
import { createContext, useContext, useEffect, useId, useRef, useState } from "react";
import { SOURCE } from "@/lib/categories";
import { cn } from "@/lib/format";
import type { Citation } from "@/lib/types";

interface Ctx {
  byId: Map<string, Citation>;
  showAll?: () => void;
}
const CitationCtx = createContext<Ctx>({ byId: new Map() });

export function CitationsProvider({ citations, onShowAll, children }: { citations: Citation[]; onShowAll?: () => void; children: React.ReactNode }) {
  const byId = new Map(citations.map((c) => [c.id, c]));
  return <CitationCtx.Provider value={{ byId, showAll: onShowAll }}>{children}</CitationCtx.Provider>;
}

/** A small chip per citation; click opens the passage and a link to the source. */
export function CitationChip({ id }: { id: string }) {
  const { byId, showAll } = useContext(CitationCtx);
  const c = byId.get(id);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const popId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!c) {
    return (
      <span className="inline-flex items-center rounded-md border border-dashed border-line-strong px-1.5 py-0.5 font-mono text-[10px] text-ink-3" title="Citation not found in this plan">
        {id}
      </span>
    );
  }
  const S = SOURCE[c.source] ?? SOURCE.wikivoyage;
  return (
    <span ref={ref} className="relative inline-flex">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        aria-controls={popId}
        aria-label={`Source ${c.id}: ${c.title}`}
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10.5px] font-medium transition",
          open ? "bg-ink text-bg" : "bg-[var(--p-guide-bg)] text-[var(--p-guide)] hover:bg-ink hover:text-bg",
        )}
      >
        <S.Icon className="h-3 w-3" aria-hidden />
        {c.id}
      </button>
      {open && (
        <span
          id={popId}
          role="dialog"
          aria-label={c.title}
          className="absolute bottom-[calc(100%+8px)] left-0 z-40 block w-72 rounded-2xl border border-line bg-surface p-3.5 text-left shadow-float"
          onClick={(e) => e.stopPropagation()}
        >
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
            <S.Icon className="h-3.5 w-3.5" aria-hidden /> {S.label}
          </span>
          <span className="mt-1 block text-sm font-bold leading-snug text-ink">{c.title}</span>
          <span className="mt-1.5 block text-[13px] leading-relaxed text-ink-2">“{c.snippet}”</span>
          <span className="mt-3 flex items-center justify-between gap-2">
            <a href={c.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-bold text-coral hover:underline">
              Open source <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
            {showAll && (
              <button
                type="button"
                className="text-xs font-semibold text-ink-3 hover:text-ink"
                onClick={() => {
                  setOpen(false);
                  showAll();
                }}
              >
                All sources →
              </button>
            )}
          </span>
        </span>
      )}
    </span>
  );
}

export function CitationList({ ids, className }: { ids: string[]; className?: string }) {
  if (!ids?.length) return null;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1", className)}>
      {ids.map((id) => (
        <CitationChip key={id} id={id} />
      ))}
    </span>
  );
}
