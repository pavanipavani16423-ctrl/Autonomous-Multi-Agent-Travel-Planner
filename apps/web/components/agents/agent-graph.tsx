"use client";

import { Check, Network, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { AGENTS, AGENT_BY_ID, EDGES, PARALLEL, type AgentMeta } from "@/lib/agents";
import { cn } from "@/lib/format";
import type { AgentState } from "@/lib/stream-state";
import type { A2AEvent, AgentId, ToolEvent } from "@/lib/types";

/** Node centres in % of the desktop canvas. */
const POS: Record<AgentId, [number, number]> = {
  guard: [7, 50],
  brief: [20, 50],
  destination: [37, 10],
  weather: [37, 30],
  stays: [37, 50],
  food: [37, 70],
  logistics: [37, 90],
  itinerary: [54.5, 50],
  budget: [69, 50],
  critic: [81.5, 50],
  finalize: [93, 50],
};
const PEER: [number, number] = [69, 13];

type EdgeState = "idle" | "flow" | "done";
function edgeState(a: AgentState, b: AgentState): EdgeState {
  if (b.status === "started") return "flow";
  if ((b.status === "done" || b.status === "skipped") && a.status !== "idle") return "done";
  return "idle";
}

function curve([x1, y1]: [number, number], [x2, y2]: [number, number]) {
  const dx = (x2 - x1) * 0.5;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function NodeBadge({ meta, s, size = "md" }: { meta: AgentMeta; s: AgentState; size?: "sm" | "md" }) {
  const Icon = meta.Icon;
  const dim = size === "md" ? "h-[46px] w-[46px]" : "h-9 w-9";
  return (
    <span className={cn("relative inline-flex shrink-0 items-center justify-center rounded-full", dim)}>
      {s.status === "started" && <span className="pulse-ring absolute inset-0 rounded-full border-2 border-coral" aria-hidden />}
      <motion.span
        layout={false}
        animate={{ scale: s.status === "started" ? 1.08 : 1 }}
        transition={{ type: "spring", stiffness: 400, damping: 20 }}
        className={cn(
          "relative inline-flex items-center justify-center rounded-full border transition-colors duration-300",
          dim,
          s.status === "idle" && "border-line-strong bg-surface text-ink-3",
          s.status === "started" && "border-coral bg-coral text-white shadow-[0_0_24px_-2px_var(--coral)]",
          s.status === "done" && "border-ink bg-ink text-bg",
          s.status === "error" && "border-[var(--p-na)] bg-[var(--p-na-bg)] text-[var(--p-na)]",
          s.status === "skipped" && "border-dashed border-line-strong bg-transparent text-ink-3",
        )}
      >
        <Icon className={size === "md" ? "h-5 w-5" : "h-4 w-4"} aria-hidden />
      </motion.span>
      {s.status === "done" && (
        <motion.span
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          className="absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full border-2 border-surface bg-lagoon text-white"
        >
          <Check className="h-2.5 w-2.5" strokeWidth={3.5} aria-hidden />
        </motion.span>
      )}
      {s.status === "error" && (
        <span className="absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full border-2 border-surface bg-[var(--p-na)] text-white">
          <X className="h-2.5 w-2.5" strokeWidth={3.5} aria-hidden />
        </span>
      )}
      {s.runs > 1 && (
        <span className="absolute -right-2 -top-1.5 rounded-full bg-sun px-1 font-mono text-[9px] font-bold text-[#0f2430]" title="Re-run by the critic loop">
          ×{s.runs}
        </span>
      )}
    </span>
  );
}

function statusText(s: AgentState) {
  if (s.status === "idle") return "waiting";
  if (s.status === "started") return "working";
  return s.status;
}

/**
 * The live LangGraph topology from the SPEC. Lights up from `agent` events; parallel branches pulse
 * together; MCP tool calls pop out of the calling node; the A2A handshake travels to the remote peer.
 */
export function AgentGraph({
  agents,
  tools = [],
  a2a = [],
  className,
}: {
  agents: Record<AgentId, AgentState>;
  tools?: ToolEvent[];
  a2a?: A2AEvent[];
  className?: string;
}) {
  const lastA2A = a2a[a2a.length - 1];
  const recentTools = tools.slice(-4);
  const budget = agents.budget;
  const peerActive = budget.status === "started" || !!lastA2A;

  return (
    <div className={className}>
      {/* desktop canvas */}
      <div className="relative hidden aspect-[1000/560] w-full md:block">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden>
          {EDGES.map(([a, b]) => {
            const st = edgeState(agents[a], agents[b]);
            return (
              <path
                key={`${a}-${b}`}
                d={curve(POS[a], POS[b])}
                fill="none"
                vectorEffect="non-scaling-stroke"
                strokeWidth={st === "flow" ? 2 : 1.4}
                className={cn("transition-[stroke] duration-500", st === "flow" && "dash-flow")}
                stroke={st === "flow" ? "var(--coral)" : st === "done" ? "var(--ink-3)" : "var(--line-strong)"}
              />
            );
          })}
          {/* critic → itinerary retry loop */}
          <path
            d={`M ${POS.critic[0]} ${POS.critic[1] + 10} C ${POS.critic[0]} 84, ${POS.itinerary[0]} 84, ${POS.itinerary[0]} ${POS.itinerary[1] + 10}`}
            fill="none"
            vectorEffect="non-scaling-stroke"
            strokeWidth={1.2}
            strokeDasharray="3 4"
            stroke={agents.itinerary.runs > 1 ? "var(--sun)" : "var(--line-strong)"}
          />
          {/* A2A link to the remote peer */}
          <line
            x1={PEER[0]}
            y1={PEER[1] + 7}
            x2={POS.budget[0]}
            y2={POS.budget[1] - 7}
            vectorEffect="non-scaling-stroke"
            strokeWidth={1.5}
            strokeDasharray="4 4"
            className={peerActive ? "dash-flow" : ""}
            stroke={peerActive ? "var(--coral)" : "var(--line-strong)"}
          />
        </svg>

        <span className="absolute font-mono text-[10px] uppercase tracking-wider text-ink-3" style={{ left: `${(POS.critic[0] + POS.itinerary[0]) / 2}%`, top: "80%", transform: "translateX(-50%)" }}>
          critic retry ≤ 1
        </span>
        <span className="absolute rounded bg-bg px-1 font-mono text-[10px] uppercase tracking-wider text-ink-3" style={{ left: `${PEER[0] + 1}%`, top: "27%" }}>
          A2A · JSON-RPC
        </span>
        <span className="absolute font-mono text-[10px] uppercase tracking-wider text-ink-3" style={{ left: `${POS.destination[0]}%`, top: "-3%", transform: "translateX(-50%)" }}>
          parallel fan-out
        </span>

        {/* remote peer card */}
        <div className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: `${PEER[0]}%`, top: `${PEER[1]}%` }}>
          <div
            className={cn(
              "flex items-center gap-2 rounded-2xl border px-3 py-2 text-left transition-colors duration-500",
              peerActive ? "border-coral bg-coral-soft" : "border-dashed border-line-strong bg-surface",
            )}
          >
            <Network className={cn("h-4 w-4", peerActive ? "text-coral" : "text-ink-3")} aria-hidden />
            <div className="leading-tight">
              <p className="text-[11px] font-bold">Budget Analyst</p>
              <p className="font-mono text-[9.5px] text-ink-3">remote agent · {lastA2A ? lastA2A.status : "idle"}</p>
            </div>
          </div>
        </div>
        {/* handshake packet */}
        <AnimatePresence>
          {lastA2A && (lastA2A.status === "sent" || lastA2A.status === "received" || lastA2A.status === "card") && (
            <motion.span
              key={`${a2a.length}`}
              className="absolute h-2.5 w-2.5 -translate-x-1/2 rounded-full bg-coral shadow-[0_0_12px_var(--coral)]"
              style={{ left: `${PEER[0]}%` }}
              initial={{ top: lastA2A.status === "received" ? `${PEER[1] + 7}%` : `${POS.budget[1] - 8}%`, opacity: 0 }}
              animate={{ top: lastA2A.status === "received" ? `${POS.budget[1] - 8}%` : `${PEER[1] + 7}%`, opacity: [0, 1, 1, 0] }}
              transition={{ duration: 0.9, ease: "easeInOut" }}
              aria-hidden
            />
          )}
        </AnimatePresence>

        {AGENTS.map((meta) => {
          const s = agents[meta.id];
          const [x, y] = POS[meta.id];
          return (
            <div
              key={meta.id}
              className="absolute flex w-28 -translate-x-1/2 flex-col items-center text-center"
              style={{ left: `${x}%`, top: `${y}%`, transform: "translate(-50%, -23px)" }}
            >
              <NodeBadge meta={meta} s={s} />
              <span className={cn("mt-1 text-[12px] leading-tight", s.status === "idle" ? "font-semibold text-ink-2" : "font-bold text-ink")}>{meta.label}</span>
              <span className="sr-only">: {statusText(s)}. {s.message}</span>
              {s.status === "started" && s.message && !PARALLEL.includes(meta.id) && (
                <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-0.5 line-clamp-2 max-w-[8.5rem] text-[10.5px] leading-tight text-ink-3" aria-hidden>
                  {s.message}
                </motion.span>
              )}
            </div>
          );
        })}

        {/* MCP tool chips pop out of the calling node */}
        {recentTools.map((t) => {
          const [x, y] = POS[t.agent] ?? POS.brief;
          return (
            <motion.span
              key={`${t.seq}-${t.tool}`}
              className="pointer-events-none absolute z-10 whitespace-nowrap rounded-full border border-line bg-surface px-2 py-1 font-mono text-[10px] shadow-card"
              style={{ left: `${x + 3}%`, top: `${y}%` }}
              initial={{ opacity: 0, x: -6, y: -14, scale: 0.8 }}
              animate={{ opacity: [0, 1, 1, 0], x: 6, y: -34, scale: 1 }}
              transition={{ duration: 2.8, times: [0, 0.12, 0.75, 1], ease: "easeOut" }}
              aria-hidden
            >
              <span className="font-semibold text-ink">{t.server}</span>
              <span className="text-ink-3">.{t.tool}</span>
            </motion.span>
          );
        })}
      </div>

      {/* phone: stacked stages */}
      <ol className="space-y-2 md:hidden">
        {[["guard"], ["brief"], PARALLEL, ["itinerary"], ["budget"], ["critic"], ["finalize"]].map((stage, i) => (
          <li key={i} className="relative">
            {i > 0 && <span className="absolute -top-2 left-[18px] h-2 w-px bg-line-strong" aria-hidden />}
            <div className={cn("grid gap-2", stage.length > 1 && "grid-cols-2 rounded-2xl border border-dashed border-line-strong p-2")}>
              {stage.map((id) => {
                const meta = AGENT_BY_ID[id as AgentId];
                const s = agents[meta.id];
                return (
                  <div key={id} className="flex min-w-0 items-center gap-2.5">
                    <NodeBadge meta={meta} s={s} size="sm" />
                    <div className="min-w-0 leading-tight">
                      <p className="truncate text-[13px] font-bold">
                        {meta.label}
                        {id === "budget" && <span className="ml-1 font-mono text-[10px] font-medium text-coral">A2A</span>}
                      </p>
                      <p className="truncate text-[11px] text-ink-3">{s.message || meta.role}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
