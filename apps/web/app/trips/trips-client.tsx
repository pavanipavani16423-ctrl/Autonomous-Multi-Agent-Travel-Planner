"use client";

import { ArrowUpRight, CalendarDays, Loader2, Plus } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Photo } from "@/components/ui/photo";
import { WakingNotice } from "@/components/ui/waking";
import { ApiError, api, waitForApi } from "@/lib/api";
import { getClientId } from "@/lib/client-id";
import { DEMO_PLAN } from "@/lib/demo";
import { cn, formatDateRange } from "@/lib/format";
import type { TripSummary } from "@/lib/types";

type State = { status: "loading" } | { status: "waking"; elapsedMs: number; failed?: boolean } | { status: "ready"; trips: TripSummary[] } | { status: "error"; message: string };

const STATUS: Record<TripSummary["status"], { label: string; cls: string }> = {
  queued: { label: "Queued", cls: "bg-bg-2 text-ink-2" },
  running: { label: "Planning…", cls: "bg-coral text-white" },
  done: { label: "Ready", cls: "bg-[var(--p-live-bg)] text-[var(--p-live)]" },
  error: { label: "Failed", cls: "bg-[var(--p-na-bg)] text-[var(--p-na)]" },
};

const SAMPLE: TripSummary = {
  id: "demo",
  title: DEMO_PLAN.title,
  destination: DEMO_PLAN.destination.name,
  start_date: DEMO_PLAN.request.start_date,
  end_date: DEMO_PLAN.request.end_date,
  status: "done",
  image: DEMO_PLAN.destination.image,
  created_at: DEMO_PLAN.created_at,
};

function TripCard({ t, i, sample }: { t: TripSummary; i: number; sample?: boolean }) {
  const s = STATUS[t.status] ?? STATUS.queued;
  return (
    <motion.li initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06, ease: [0.16, 1, 0.3, 1], duration: 0.5 }}>
      <Link href={`/trip/${encodeURIComponent(t.id)}`} className="group card block overflow-hidden transition hover:-translate-y-1 hover:shadow-float">
        <div className="relative aspect-[4/3]">
          <Photo title={t.destination} src={t.image} alt={t.destination} className="absolute inset-0 transition-transform duration-700 group-hover:scale-[1.04]" sizes="(max-width: 768px) 100vw, 33vw" />
          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
          <span className={cn("absolute left-3 top-3 rounded-full px-2.5 py-1 text-[11px] font-bold", s.cls)}>{s.label}</span>
          {sample && <span className="absolute right-3 top-3 rounded-full bg-sun px-2.5 py-1 text-[11px] font-bold text-[#0f2430]">Sample</span>}
          <p className="absolute bottom-3 left-4 font-display text-2xl font-semibold text-white">{t.destination}</p>
        </div>
        <div className="flex items-start gap-3 p-4">
          <div className="min-w-0 flex-1">
            <p className="line-clamp-2 font-semibold leading-snug">{t.title}</p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-3">
              <CalendarDays className="h-3.5 w-3.5" aria-hidden /> {formatDateRange(t.start_date, t.end_date)}
            </p>
          </div>
          <ArrowUpRight className="h-5 w-5 shrink-0 text-ink-3 transition group-hover:text-coral" aria-hidden />
        </div>
      </Link>
    </motion.li>
  );
}

export function TripsClient() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    const run = async () => {
      const id = getClientId();
      for (let pass = 0; pass < 2; pass++) {
        try {
          const trips = id ? await api.listTrips(id) : [];
          if (!ctrl.signal.aborted) setState({ status: "ready", trips });
          return;
        } catch (err) {
          if (ctrl.signal.aborted) return;
          if (err instanceof ApiError && err.isOffline && pass === 0) {
            setState({ status: "waking", elapsedMs: 0 });
            const ok = await waitForApi({ signal: ctrl.signal, onTick: (ms) => setState({ status: "waking", elapsedMs: ms }) });
            if (ctrl.signal.aborted) return;
            if (ok) continue;
            setState({ status: "waking", elapsedMs: 0, failed: true });
            return;
          }
          setState({ status: "error", message: err instanceof Error ? err.message : "Couldn't load your trips." });
          return;
        }
      }
    };
    void run();
    return () => ctrl.abort();
  }, [attempt]);

  return (
    <div className="mt-10">
      {state.status === "waking" && (
        <div className="mb-8">
          <WakingNotice compact elapsedMs={state.elapsedMs} failed={state.failed} onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      )}
      {state.status === "error" && (
        <p role="alert" className="mb-8 rounded-xl bg-coral-soft px-4 py-3 text-sm font-semibold text-coral">
          {state.message}
        </p>
      )}
      {state.status === "loading" && (
        <p className="mb-8 flex items-center gap-2 text-sm text-ink-3" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading your trips…
        </p>
      )}
      <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <motion.li initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
          <Link
            href="/plan"
            className="flex h-full min-h-72 flex-col items-center justify-center gap-3 rounded-[1.25rem] border-2 border-dashed border-line-strong p-6 text-center transition hover:border-coral hover:bg-coral-soft"
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-ink text-bg">
              <Plus className="h-5 w-5" aria-hidden />
            </span>
            <span className="font-display text-xl font-semibold">Plan a new trip</span>
            <span className="text-sm text-ink-3">11 agents · about a minute</span>
          </Link>
        </motion.li>
        {state.status === "ready" && state.trips.map((t, i) => <TripCard key={t.id} t={t} i={i + 1} />)}
        <TripCard t={SAMPLE} i={state.status === "ready" ? state.trips.length + 1 : 1} sample />
      </ul>
      {state.status === "ready" && state.trips.length === 0 && <p className="mt-6 text-sm text-ink-3">No trips yet from this browser — the sample shows what you&apos;ll get.</p>}
    </div>
  );
}
