"use client";

import {
  AlertTriangle,
  ArrowRight,
  BedDouble,
  BookOpen,
  CheckCircle2,
  Database,
  FastForward,
  Network,
  Radio,
  Server,
  SkipForward,
  UtensilsCrossed,
  Wallet,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { AgentGraph } from "@/components/agents/agent-graph";
import { Photo } from "@/components/ui/photo";
import { ProvenancePill } from "@/components/ui/pills";
import { AGENT_BY_ID, AGENTS, MCP_SERVERS } from "@/lib/agents";
import { cn, formatClock, formatDateRange, formatMoney, travellers } from "@/lib/format";
import type { LogItem, StreamState } from "@/lib/stream-state";
import type { TripRequest } from "@/lib/types";
import type { StreamPhase } from "@/lib/use-trip-stream";
import { WeatherStrip } from "./weather-strip";

export function Elapsed({ startedAt, running, className }: { startedAt: number | null; running: boolean; className?: string }) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(t);
  }, [running]);
  const secs = startedAt && now > startedAt ? (now - startedAt) / 1000 : 0;
  return <span className={cn("tabular font-mono", className)}>{formatClock(secs)}</span>;
}

function FeedRow({ item }: { item: LogItem }) {
  const ev = item.event;
  let tag = "";
  let tone = "text-ink-3";
  let body: React.ReactNode = null;
  switch (ev.type) {
    case "agent": {
      tag = AGENT_BY_ID[ev.data.agent]?.label ?? ev.data.agent;
      tone = ev.data.status === "started" ? "text-coral" : ev.data.status === "error" ? "text-[var(--p-na)]" : "text-lagoon";
      body = (
        <>
          <span className="text-ink-3">{ev.data.status === "started" ? "▶" : ev.data.status === "done" ? "✓" : ev.data.status === "error" ? "✕" : "↷"}</span> {ev.data.message}
          {ev.data.ms != null && <span className="text-ink-3"> · {(ev.data.ms / 1000).toFixed(1)}s</span>}
        </>
      );
      break;
    }
    case "tool":
      tag = `mcp/${ev.data.server}`;
      tone = "text-[var(--p-live)]";
      body = (
        <>
          <span className="font-semibold text-ink">{ev.data.tool}</span> {ev.data.summary} <span className="text-ink-3">· {ev.data.ms}ms</span>{" "}
          <ProvenancePill value={ev.data.provenance} className="align-middle" />
        </>
      );
      break;
    case "retrieval":
      tag = "rag";
      tone = "text-[var(--p-guide)]";
      body = (
        <>
          “{ev.data.query}” → <span className="font-semibold text-ink">{ev.data.hits} hits</span> · top {ev.data.top_score.toFixed(2)}
          {!ev.data.covered && <span className="text-[var(--p-est)]"> · not covered</span>}
        </>
      );
      break;
    case "a2a":
      tag = "a2a";
      tone = "text-coral";
      body = (
        <>
          <span className="font-semibold text-ink">{ev.data.status}</span> {ev.data.summary}
        </>
      );
      break;
    case "partial":
      tag = "partial";
      body = <>section “{ev.data.section}” ready</>;
      break;
    case "plan":
      tag = "plan";
      tone = "text-lagoon";
      body = <>TripPlan revision {ev.data.revision} assembled</>;
      break;
    case "error":
      tag = "error";
      tone = "text-[var(--p-na)]";
      body = <>{ev.data.message}</>;
      break;
    case "done":
      tag = "done";
      tone = "text-lagoon";
      body = <>run finished in {(ev.data.ms / 1000).toFixed(1)}s</>;
      break;
  }
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, x: -14 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 380, damping: 30 }}
      className="grid grid-cols-[5.5rem_1fr] gap-2 py-1.5 font-mono text-[11.5px] leading-snug"
    >
      <span className={cn("truncate font-semibold", tone)}>{tag}</span>
      <span className="min-w-0 break-words text-ink-2">{body}</span>
    </motion.li>
  );
}

function EventFeed({ log }: { log: LogItem[] }) {
  const ref = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [log.length]);
  return (
    <div className="card flex min-h-0 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <p className="flex items-center gap-2 text-sm font-bold">
          <Radio className="h-4 w-4 text-coral" aria-hidden /> Event stream
        </p>
        <span className="font-mono text-[11px] text-ink-3">SSE · {log.length} events</span>
      </div>
      <ol ref={ref} className="h-[22rem] divide-y divide-line overflow-y-auto px-4 lg:h-[27rem]" aria-live="polite" aria-relevant="additions">
        {log.length === 0 && <li className="py-6 text-center text-sm text-ink-3">Waiting for the first event…</li>}
        {log.map((item) => (
          <FeedRow key={item.key} item={item} />
        ))}
      </ol>
    </div>
  );
}

function ResourceRail({ state }: { state: StreamState }) {
  const lastRetrieval = state.retrievals[state.retrievals.length - 1];
  const a2a = state.a2a;
  const steps: { id: "card" | "sent" | "received"; label: string }[] = [
    { id: "card", label: "Agent card" },
    { id: "sent", label: "message/send" },
    { id: "received", label: "Received" },
  ];
  const seen = new Set(a2a.map((e) => e.status));
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {MCP_SERVERS.map((m) => {
        const calls = state.tools.filter((t) => t.server === m.id);
        const last = calls[calls.length - 1];
        return (
          <motion.div
            key={`${m.id}-${calls.length}`}
            initial={last ? { boxShadow: "0 0 0 2px var(--coral)" } : false}
            animate={{ boxShadow: "0 0 0 0px var(--coral)" }}
            transition={{ duration: 1.2 }}
            className="rounded-2xl border border-line bg-surface p-3.5"
          >
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-lagoon" aria-hidden />
              <p className="font-mono text-xs font-bold">mcp/{m.label}</p>
              <span className="ml-auto rounded-full bg-bg-2 px-2 py-0.5 font-mono text-[11px] tabular">{calls.length} calls</span>
            </div>
            <p className="mt-2 truncate text-xs text-ink-2">{last ? `${last.tool} · ${last.summary}` : m.detail}</p>
          </motion.div>
        );
      })}
      <div className="rounded-2xl border border-line bg-surface p-3.5">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-[var(--p-guide)]" aria-hidden />
          <p className="font-mono text-xs font-bold">qdrant/guidebook</p>
          <span className="ml-auto rounded-full bg-bg-2 px-2 py-0.5 font-mono text-[11px] tabular">{state.retrievals.length} searches</span>
        </div>
        <p className="mt-2 truncate text-xs text-ink-2">{lastRetrieval ? `“${lastRetrieval.query}” → ${lastRetrieval.hits} hits` : "Hybrid BM25 + dense, re-ranked"}</p>
      </div>
      <div className="rounded-2xl border border-line bg-surface p-3.5 sm:col-span-2 xl:col-span-4">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-coral" aria-hidden />
          <p className="font-mono text-xs font-bold">a2a/budget-analyst</p>
          <span className="ml-1 text-[11px] text-ink-3">remote agent over the Agent2Agent protocol</span>
        </div>
        <ol className="mt-3 flex items-center gap-2">
          {steps.map((s, i) => {
            const on = seen.has(s.id);
            return (
              <li key={s.id} className="flex flex-1 items-center gap-2">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold transition-colors duration-500",
                    on ? "border-coral bg-coral text-white" : "border-line-strong text-ink-3",
                  )}
                >
                  {i + 1}
                </span>
                <span className={cn("text-xs font-semibold", on ? "text-ink" : "text-ink-3")}>{s.label}</span>
                {i < steps.length - 1 && <span className={cn("h-px flex-1", on ? "bg-coral" : "bg-line-strong")} aria-hidden />}
              </li>
            );
          })}
        </ol>
        <p className="mt-2 truncate font-mono text-[11px] text-ink-2">{a2a.length ? a2a[a2a.length - 1].summary : "waiting for the itinerary draft"}</p>
      </div>
    </div>
  );
}

function Reveal({ children, k }: { children: React.ReactNode; k: string }) {
  return (
    <motion.div key={k} layout initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 28 }}>
      {children}
    </motion.div>
  );
}

function ProgressiveResults({ state, request }: { state: StreamState; request?: TripRequest }) {
  const p = state.partials;
  const nothing = !p.destination && !p.weather && !p.stays && !p.food && !p.itinerary && !p.budget;
  return (
    <div className="space-y-4">
      <h2 className="eyebrow">Filling in as agents report back</h2>
      {nothing && (
        <div className="grid gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-28 rounded-2xl" />
          ))}
        </div>
      )}
      <AnimatePresence>
        {p.destination && (
          <Reveal key="dest" k="dest">
            <div className="card grid overflow-hidden sm:grid-cols-[14rem_1fr]">
              <Photo title={p.destination.name} src={p.destination.image} alt={p.destination.name} className="h-40 sm:h-full" sizes="224px" />
              <div className="p-5">
                <p className="font-display text-2xl font-semibold">
                  {p.destination.name}
                  <span className="text-ink-3">, {p.destination.country}</span>
                </p>
                {request && (
                  <p className="mt-1 text-sm text-ink-3">
                    {formatDateRange(request.start_date, request.end_date)} · {travellers(request.adults, request.children)}
                  </p>
                )}
                <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-ink-2">{p.destination.blurb}</p>
              </div>
            </div>
          </Reveal>
        )}
        {p.weather && (
          <Reveal key="weather" k="weather">
            <WeatherStrip days={p.weather} compact />
          </Reveal>
        )}
        {(p.stays || p.food) && (
          <Reveal key="sf" k="sf">
            <div className="grid gap-3 md:grid-cols-2">
              {p.stays && (
                <div className="card p-4">
                  <p className="mb-2 flex items-center gap-2 text-sm font-bold">
                    <BedDouble className="h-4 w-4 text-coral" aria-hidden /> {p.stays.length} stays shortlisted
                  </p>
                  <ul className="space-y-1.5">
                    {p.stays.slice(0, 4).map((s, i) => (
                      <motion.li key={`${s.name}-${i}`} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }} className="flex items-center gap-2 text-sm">
                        <span className="min-w-0 flex-1 truncate">{s.name}</span>
                        <span className="tabular text-xs text-ink-3">{formatMoney(s.price_per_night)}/n</span>
                        <ProvenancePill value={s.provenance} />
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}
              {p.food && (
                <div className="card p-4">
                  <p className="mb-2 flex items-center gap-2 text-sm font-bold">
                    <UtensilsCrossed className="h-4 w-4 text-sun" aria-hidden /> {p.food.length} food picks
                  </p>
                  <ul className="space-y-1.5">
                    {p.food.slice(0, 4).map((f, i) => (
                      <motion.li key={`${f.name}-${i}`} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }} className="flex items-center gap-2 text-sm">
                        <span className="min-w-0 flex-1 truncate">{f.name}</span>
                        <span className="text-xs text-ink-3">{f.cuisine.split(" (")[0]}</span>
                        <ProvenancePill value={f.provenance} />
                      </motion.li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Reveal>
        )}
        {p.itinerary && (
          <Reveal key="itin" k="itin">
            <div className="card p-4">
              <p className="mb-3 flex items-center gap-2 text-sm font-bold">
                <BookOpen className="h-4 w-4 text-[var(--p-guide)]" aria-hidden /> {p.itinerary.length} days drafted
              </p>
              <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {p.itinerary.map((d, i) => (
                  <motion.li key={d.day} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }} className="rounded-xl bg-bg-2/70 p-3">
                    <p className="font-mono text-[11px] text-ink-3">Day {d.day}</p>
                    <p className="text-sm font-bold leading-snug">{d.title}</p>
                    <p className="mt-1 text-xs text-ink-3">{d.activities.length} stops</p>
                  </motion.li>
                ))}
              </ol>
            </div>
          </Reveal>
        )}
        {p.budget && (
          <Reveal key="budget" k="budget">
            <div className="card flex flex-wrap items-center gap-4 p-4">
              <Wallet className="h-5 w-5 text-lagoon" aria-hidden />
              <p className="text-sm">
                <span className="font-bold">{formatMoney(p.budget.total)}</span> of {formatMoney(p.budget.limit)} ·{" "}
                <span className={p.budget.within_budget ? "text-lagoon" : "text-coral"}>{Math.round(p.budget.utilisation * 100)}% used</span>
              </p>
              <span className="ml-auto font-mono text-[11px] text-ink-3">{p.budget.analyst}</span>
            </div>
          </Reveal>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * "Mission control" while a plan is generating: the live agent graph, MCP/RAG/A2A activity, the raw
 * event stream, and results filling in from `partial` events.
 */
export function MissionControl({
  state,
  phase,
  startedAt,
  request,
  title,
  demo,
  onSkip,
  speed,
  onSpeed,
  onOpen,
}: {
  state: StreamState;
  phase: StreamPhase;
  startedAt: number | null;
  request?: TripRequest;
  title: string;
  demo?: boolean;
  onSkip?: () => void;
  speed?: number;
  onSpeed?: (n: number) => void;
  onOpen: () => void;
}) {
  const doneCount = AGENTS.filter((a) => state.agents[a.id].status === "done" || state.agents[a.id].status === "skipped").length;
  const active = AGENTS.filter((a) => state.agents[a.id].status === "started");
  const finished = phase === "done" && !!state.plan;

  useEffect(() => {
    if (!finished) return;
    const t = setTimeout(onOpen, 1800);
    return () => clearTimeout(t);
  }, [finished, onOpen]);

  return (
    <div className="mx-auto max-w-7xl px-4 pb-20 pt-6 sm:px-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="eyebrow flex items-center gap-2">
            {finished ? <CheckCircle2 className="h-3.5 w-3.5 text-lagoon" aria-hidden /> : <span className="live-dot h-2 w-2 rounded-full bg-coral" aria-hidden />}
            {finished ? "Plan ready" : phase === "reconnecting" ? "Reconnecting to the stream…" : "Mission control · live"}
            {demo && <span className="rounded-full bg-sun-soft px-2 py-0.5 font-sans text-[10px] font-bold normal-case tracking-normal text-ink">Sample replay</span>}
          </p>
          <h1 className="mt-2 font-display text-3xl font-semibold leading-tight sm:text-4xl">{title}</h1>
          <p className="mt-1 text-sm text-ink-2" aria-live="polite">
            {finished
              ? "All agents reported back. Opening your workspace…"
              : active.length
                ? `${active.map((a) => a.label).join(" · ")} ${active.length > 1 ? "are" : "is"} working`
                : "Connecting to the agents…"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-3 rounded-full border border-line bg-surface px-4 py-2">
            <Elapsed startedAt={startedAt} running={!finished} className="text-sm font-semibold" />
            <span className="h-4 w-px bg-line" aria-hidden />
            <span className="text-sm text-ink-2">
              <span className="tabular font-bold text-ink">{doneCount}</span>/11 agents
            </span>
          </div>
          {demo && !finished && onSpeed && (
            <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={() => onSpeed(speed === 1 ? 3 : 1)} aria-pressed={speed !== 1}>
              <FastForward className="h-4 w-4" aria-hidden /> {speed === 1 ? "3× speed" : "1× speed"}
            </button>
          )}
          {demo && !finished && onSkip && (
            <button type="button" className="btn btn-ghost !py-2 text-sm" onClick={onSkip}>
              <SkipForward className="h-4 w-4" aria-hidden /> Skip to plan
            </button>
          )}
          {finished && (
            <button type="button" className="btn btn-primary !py-2 text-sm" onClick={onOpen}>
              Open workspace <ArrowRight className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 h-1 overflow-hidden rounded-full bg-bg-2" aria-hidden>
        <motion.div className="h-full rounded-full bg-gradient-to-r from-sun via-coral to-coral" animate={{ width: `${(doneCount / 11) * 100}%` }} transition={{ type: "spring", stiffness: 80, damping: 20 }} />
      </div>

      {state.error && (
        <div role="alert" className="mt-4 flex items-start gap-3 rounded-2xl border border-[var(--p-na)]/30 bg-[var(--p-na-bg)] px-4 py-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--p-na)]" aria-hidden />
          <p>
            <span className="font-bold">{state.error.recoverable ? "A step hit a snag — the agents are carrying on." : "The run stopped."}</span> {state.error.message}
          </p>
        </div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <div className="card relative overflow-hidden p-4 pt-8 sm:p-6 sm:pt-10">
          <div className="pointer-events-none absolute inset-0 opacity-50 [background-image:radial-gradient(var(--line-strong)_1px,transparent_1px)] [background-size:22px_22px]" aria-hidden />
          <AgentGraph agents={state.agents} tools={state.tools} a2a={state.a2a} className="relative" />
        </div>
        <EventFeed log={state.log} />
      </div>

      <div className="mt-4">
        <ResourceRail state={state} />
      </div>

      <div className="mt-8">
        <ProgressiveResults state={state} request={request} />
      </div>
    </div>
  );
}
