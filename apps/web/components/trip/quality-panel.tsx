"use client";

import { CheckCircle2, Info, XCircle } from "lucide-react";
import { motion } from "motion/react";
import { Counter } from "@/components/ui/counter";
import { RatingPill } from "@/components/ui/pills";
import { AGENT_BY_ID } from "@/lib/agents";
import { cn, formatMs, ratingFor } from "@/lib/format";
import type { TripPlan } from "@/lib/types";

function Ring({ value, label }: { value: number; label: string }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 80 80" className="h-20 w-20 -rotate-90" aria-hidden>
        <circle cx="40" cy="40" r={r} fill="none" stroke="var(--bg-2)" strokeWidth="8" />
        <motion.circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke={value >= 0.7 ? "var(--p-live)" : value >= 0.4 ? "var(--p-est)" : "var(--p-na)"}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - value) }}
          transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
        />
      </svg>
      <div>
        <p className="eyebrow">{label}</p>
        <p className="font-display text-3xl font-semibold tabular">
          <Counter value={value * 100} format={(n) => `${Math.round(n)}%`} />
        </p>
      </div>
    </div>
  );
}

/** Quality as a plain Score | Value | Rating table, the critic's checks, and where the time went. */
export function QualityPanel({ plan }: { plan: TripPlan }) {
  const q = plan.quality;
  const maxMs = Math.max(1, ...plan.timings.map((t) => t.ms));
  const totalMs = plan.timings.reduce((n, t) => n + t.ms, 0);
  const passed = q.checks.filter((c) => c.passed).length;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <div className="card p-5">
          <Ring value={q.confidence} label="Confidence" />
        </div>
        <div className="card p-5">
          <Ring value={q.grounding_coverage} label="Grounding coverage" />
        </div>
        <div className="card flex flex-col justify-center p-5">
          <p className="eyebrow">Guidebook</p>
          <p className="mt-1 font-display text-2xl font-semibold capitalize">{q.guidebook}</p>
          <p className="mt-1 text-xs text-ink-3">
            {q.guidebook === "covered"
              ? "City was already in the Wikivoyage index."
              : q.guidebook === "expanded"
                ? "City was fetched and indexed on demand for this trip."
                : "No guidebook coverage — relied on live tools."}
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <section className="card overflow-hidden">
          <div className="border-b border-line px-5 py-4">
            <h4 className="text-sm font-bold">Scores</h4>
            <p className="text-xs text-ink-3">Ragas metrics and rule scores, sent to Langfuse with this run&apos;s trace. Good ≥ 0.70 · OK ≥ 0.40 · Weak &lt; 0.40</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-3">
                  <th scope="col" className="px-5 py-2.5 font-semibold">Score</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Value</th>
                  <th scope="col" className="px-5 py-2.5 text-right font-semibold">Rating</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {q.scores.map((s, i) => (
                  <tr key={s.name} className={cn(s.name === "Overall" && "bg-bg-2/60 font-semibold")}>
                    <th scope="row" className="px-5 py-3 text-left font-semibold">
                      {s.name}
                      <span className="mt-0.5 block max-w-xs text-xs font-normal text-ink-3">{s.explain}</span>
                    </th>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <span className="tabular w-10 font-mono text-[13px]">{s.value.toFixed(2)}</span>
                        <span className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-bg-2 sm:block" aria-hidden>
                          <motion.span
                            className="block h-full rounded-full bg-ink"
                            initial={{ width: 0 }}
                            animate={{ width: `${s.value * 100}%` }}
                            transition={{ delay: i * 0.06, duration: 0.8 }}
                          />
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-right">
                      <RatingPill rating={s.rating ?? ratingFor(s.value)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card p-5">
          <h4 className="flex items-center justify-between text-sm font-bold">
            Critic checks
            <span className="font-mono text-xs font-medium text-ink-3">
              {passed}/{q.checks.length} passed
            </span>
          </h4>
          <ul className="mt-3 space-y-2.5">
            {q.checks.map((c) => (
              <li key={c.name} className="flex gap-2.5">
                {c.passed ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--p-live)]" aria-label="Passed" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--p-na)]" aria-label="Failed" />
                )}
                <div className="text-sm">
                  <p className="font-semibold leading-tight">{c.name}</p>
                  <p className="text-xs text-ink-3">{c.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h4 className="text-sm font-bold">Time per agent</h4>
          <p className="text-xs text-ink-3">
            Σ {formatMs(totalMs)} of agent time · parallel branches overlap · model <span className="font-mono">{plan.model}</span>
          </p>
        </div>
        <ul className="mt-4 space-y-2">
          {plan.timings.map((t, i) => (
            <li key={`${t.agent}-${i}`} className="grid grid-cols-[6.5rem_1fr_4rem] items-center gap-3 text-xs">
              <span className="truncate font-semibold">{AGENT_BY_ID[t.agent]?.label ?? t.agent}</span>
              <span className="h-2.5 overflow-hidden rounded-full bg-bg-2">
                <motion.span
                  className={cn("block h-full rounded-full", t.agent === "budget" ? "bg-coral" : ["destination", "weather", "stays", "food", "logistics"].includes(t.agent) ? "bg-lagoon" : "bg-ink")}
                  initial={{ width: 0 }}
                  animate={{ width: `${(t.ms / maxMs) * 100}%` }}
                  transition={{ delay: i * 0.04, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                />
              </span>
              <span className="tabular text-right font-mono text-ink-2">{formatMs(t.ms)}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 flex items-center gap-1.5 text-[11px] text-ink-3">
          <Info className="h-3 w-3" aria-hidden /> Teal = parallel researchers · coral = remote A2A agent · ink = sequential steps
        </p>
      </section>
    </div>
  );
}
