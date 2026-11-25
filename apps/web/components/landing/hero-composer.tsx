"use client";

import { ArrowUp, Loader2, PlayCircle, SlidersHorizontal, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { TripForm } from "@/components/composer/trip-form";
import { Sheet } from "@/components/ui/sheet";
import { WakingNotice } from "@/components/ui/waking";
import { ApiError, api, waitForApi } from "@/lib/api";
import { COVERED_FALLBACK } from "@/lib/covered";
import { formatDateRange, travellers } from "@/lib/format";
import { onPlanRequest, takePendingPlan } from "@/lib/plan-handoff";
import type { TripRequest } from "@/lib/types";
import { useCreateTrip } from "@/lib/use-create-trip";
import { defaultRequest } from "@/lib/validate";

const SUGGESTIONS = [
  "5 relaxed days in Kyoto in April for 2, ₹1.5L, love food and temples",
  "Long weekend in Lisbon for 2 under €1,500 — trams, tiles and seafood",
  "6 days in Udaipur with my parents, vegetarian, ₹90k, palaces and lakes",
  "4 packed days in Reykjavík in March: northern lights and hot springs",
];

function guessDestination(text: string) {
  const t = text.toLowerCase();
  return COVERED_FALLBACK.find((c) => t.includes(c.name.toLowerCase()))?.name ?? "";
}

type ParseState = { status: "idle" } | { status: "parsing" } | { status: "waking"; elapsedMs: number; failed?: boolean } | { status: "error"; message: string };

/** Free text → POST /api/trips/parse → confirm/edit the structured request → POST /api/trips. */
export function HeroComposer() {
  const [text, setText] = useState("");
  const [parse, setParse] = useState<ParseState>({ status: "idle" });
  const [draft, setDraft] = useState<TripRequest | null>(null);
  const [fromText, setFromText] = useState(false);
  const { state: create, submit } = useCreateTrip();
  const taRef = useRef<HTMLTextAreaElement>(null);
  const wakeCtrl = useRef<AbortController | null>(null);

  const run = async (value: string) => {
    const q = value.trim();
    if (!q) {
      taRef.current?.focus();
      return;
    }
    setParse({ status: "parsing" });
    try {
      const parsed = await api.parseTrip(q);
      setParse({ status: "idle" });
      setFromText(true);
      setDraft(defaultRequest({ ...parsed, notes: parsed.notes ?? "" }));
    } catch (err) {
      if (err instanceof ApiError && err.isOffline) {
        wakeCtrl.current?.abort();
        const ctrl = new AbortController();
        wakeCtrl.current = ctrl;
        setParse({ status: "waking", elapsedMs: 0 });
        const ok = await waitForApi({ signal: ctrl.signal, onTick: (ms) => setParse({ status: "waking", elapsedMs: ms }) });
        if (ctrl.signal.aborted) return;
        if (ok) return run(q);
        setParse({ status: "waking", elapsedMs: 0, failed: true });
        return;
      }
      setParse({ status: "error", message: err instanceof ApiError ? err.message : "Couldn't read that — try the detailed form." });
    }
  };

  // The assistant's "Start planning" lands here: same text box, same parse → confirm sheet.
  const runRef = useRef(run);
  useEffect(() => {
    runRef.current = run;
  });
  useEffect(() => {
    const start = (value: string) => {
      setText(value);
      taRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      void runRef.current(value);
    };
    const pending = takePendingPlan();
    if (pending) queueMicrotask(() => start(pending));
    return onPlanRequest(start);
  }, []);

  const openForm = () => {
    setFromText(false);
    setDraft(defaultRequest({ destination: guessDestination(text) }));
  };

  const busy = parse.status === "parsing" || parse.status === "waking";
  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(text);
        }}
        className="group relative rounded-[1.6rem] border border-line-strong bg-surface p-2 shadow-float transition focus-within:border-coral focus-within:shadow-[0_0_0_5px_var(--coral-soft),var(--shadow-float)]"
      >
        <label htmlFor="trip-prompt" className="sr-only">
          Describe your trip
        </label>
        <textarea
          id="trip-prompt"
          ref={taRef}
          rows={3}
          value={text}
          maxLength={600}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void run(text);
            }
          }}
          placeholder="5 relaxed days in Kyoto in April for 2, ₹1.5L, love food and temples"
          className="block w-full resize-none bg-transparent px-4 pb-2 pt-3 text-[1.05rem] leading-relaxed text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center justify-between gap-2 px-2 pb-1">
          <button type="button" onClick={openForm} className="inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold text-ink-2 transition hover:bg-bg-2 hover:text-ink">
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
            <span>Fill in details</span>
          </button>
          <button type="submit" className="btn btn-primary !px-5" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
            <span>{parse.status === "parsing" ? "Reading…" : "Plan my trip"}</span>
            {!busy && <ArrowUp className="h-4 w-4 rotate-45" aria-hidden />}
          </button>
        </div>
      </form>

      <div className="mt-4 flex flex-wrap gap-2" aria-label="Example trips">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setText(s);
              taRef.current?.focus();
            }}
            className="rounded-full border border-line bg-surface/70 px-3 py-1.5 text-left text-[0.8rem] font-medium text-ink-2 backdrop-blur transition hover:border-ink-3 hover:text-ink"
          >
            {s.length > 46 ? `${s.slice(0, 44)}…` : s}
          </button>
        ))}
      </div>

      {parse.status === "waking" && (
        <div className="mt-4">
          <WakingNotice
            compact
            elapsedMs={parse.elapsedMs}
            failed={parse.failed}
            onRetry={() => void run(text)}
          />
        </div>
      )}
      {parse.status === "error" && (
        <p role="alert" className="mt-4 rounded-xl bg-coral-soft px-4 py-3 text-sm font-semibold text-coral">
          {parse.message}{" "}
          <button type="button" className="underline" onClick={openForm}>
            Use the detailed form
          </button>
        </p>
      )}

      <p className="mt-5 flex items-center gap-2 text-sm text-ink-3">
        <PlayCircle className="h-4 w-4" aria-hidden />
        No backend handy?{" "}
        <Link href="/trip/demo" className="font-semibold text-ink underline decoration-sun decoration-2 underline-offset-4 hover:decoration-coral">
          Watch a full sample run
        </Link>
      </p>

      <Sheet
        open={!!draft}
        onClose={() => setDraft(null)}
        title={fromText ? "Here's what we understood" : "Plan your trip"}
        subtitle={
          fromText && draft ? (
            <span>
              {draft.destination || "Somewhere"} · {formatDateRange(draft.start_date, draft.end_date)} · {travellers(draft.adults, draft.children)} — edit anything before
              the agents start.
            </span>
          ) : (
            "Tell the agents the essentials. Everything else is optional."
          )
        }
      >
        {draft && (
          <div className="space-y-4">
            {create.status === "waking" && <WakingNotice compact elapsedMs={create.elapsedMs} />}
            <TripForm
              key={JSON.stringify(draft)}
              initial={draft}
              compact
              onSubmit={submit}
              submitting={create.status === "submitting" || create.status === "waking"}
              serverError={create.status === "error" ? create.message : null}
            />
          </div>
        )}
      </Sheet>
    </div>
  );
}
