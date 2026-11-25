"use client";

import { ArrowUp, Check, Loader2, MessageSquareText } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { cn } from "@/lib/format";
import type { StreamState } from "@/lib/stream-state";
import type { AgentId } from "@/lib/types";

const REFINE_AGENTS: { id: AgentId; label: string }[] = [
  { id: "itinerary", label: "Itinerary" },
  { id: "budget", label: "Budget (A2A)" },
  { id: "critic", label: "Critic" },
  { id: "finalize", label: "Finalize" },
];

/**
 * Human-in-the-loop refinement, pinned to the bottom of the workspace. Shows only the agents a
 * refinement re-runs (SPEC: itinerary → budget → critic → finalize) while it's in flight.
 */
export function RefineDock({
  revision,
  busy,
  state,
  error,
  suggestions,
  onSubmit,
}: {
  revision: number;
  busy: boolean;
  state: StreamState;
  error?: string | null;
  suggestions: string[];
  onSubmit: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const send = (m: string) => {
    const msg = m.trim();
    if (!msg || busy) return;
    onSubmit(msg);
    setText("");
  };
  return (
    <div className="no-print pointer-events-none fixed inset-x-0 bottom-0 z-30 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6">
      <div className="pointer-events-auto mx-auto max-w-3xl">
        <AnimatePresence>
          {busy && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              className="mb-2 flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-surface/95 px-4 py-2.5 shadow-float backdrop-blur"
              role="status"
              aria-live="polite"
            >
              <span className="text-xs font-bold">Revising → v{revision + 1}</span>
              {REFINE_AGENTS.map((a, i) => {
                const s = state.agents[a.id].status;
                return (
                  <span key={a.id} className="flex items-center gap-1.5">
                    {i > 0 && <span className="h-px w-3 bg-line-strong" aria-hidden />}
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] transition-colors",
                        s === "started" && "bg-coral text-white",
                        s === "done" && "bg-[var(--p-live-bg)] text-[var(--p-live)]",
                        s === "idle" && "bg-bg-2 text-ink-3",
                      )}
                    >
                      {s === "started" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
                      {s === "done" && <Check className="h-3 w-3" aria-hidden />}
                      {a.label}
                    </span>
                  </span>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>
        {error && (
          <p role="alert" className="mb-2 rounded-xl bg-[var(--p-na-bg)] px-3 py-2 text-xs font-semibold text-[var(--p-na)]">
            {error}
          </p>
        )}
        <AnimatePresence>
          {focused && !busy && !text && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }} className="mb-2 flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => send(s)}
                  className="rounded-full border border-line bg-surface/95 px-3 py-1.5 text-xs font-semibold text-ink-2 shadow-card backdrop-blur hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
          className="flex items-center gap-2 rounded-full border border-line-strong bg-surface/95 p-1.5 pl-4 shadow-float backdrop-blur-xl focus-within:border-coral"
        >
          <MessageSquareText className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
          <label htmlFor="refine" className="sr-only">
            Refine this trip
          </label>
          <input
            id="refine"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            disabled={busy}
            maxLength={400}
            placeholder={busy ? "The agents are revising your plan…" : "Refine: “make day 2 more relaxed”, “cheaper hotel”…"}
            className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none placeholder:text-ink-3"
          />
          <span className="hidden shrink-0 rounded-full bg-bg-2 px-2 py-1 font-mono text-[11px] text-ink-3 sm:inline">v{revision}</span>
          <button type="submit" className="btn btn-primary h-10 w-10 !p-0" disabled={busy || !text.trim()} aria-label="Send refinement">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ArrowUp className="h-4 w-4" aria-hidden />}
          </button>
        </form>
      </div>
    </div>
  );
}
