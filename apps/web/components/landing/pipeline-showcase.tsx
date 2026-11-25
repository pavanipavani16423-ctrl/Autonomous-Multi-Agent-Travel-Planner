"use client";

import { Database, Network, Server } from "lucide-react";
import { motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { AgentGraph } from "@/components/agents/agent-graph";
import { MCP_SERVERS } from "@/lib/agents";
import { DEMO_PLAN } from "@/lib/demo";
import { buildDemoScript } from "@/lib/demo/script";
import { applyEvent, initialStreamState, type StreamState } from "@/lib/stream-state";
import type { StreamEvent } from "@/lib/types";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";

const SCRIPT = buildDemoScript(DEMO_PLAN).filter((s) => s.event.type === "agent" || s.event.type === "tool" || s.event.type === "a2a");
const END = SCRIPT[SCRIPT.length - 1].at;

function finalState(): StreamState {
  let s = initialStreamState();
  SCRIPT.forEach((step, i) => {
    s = applyEvent(s, { type: step.event.type, data: { ...step.event.data, ts: "", seq: i + 1 } } as StreamEvent, 0);
  });
  return s;
}

/** "Watch the agents work": the real graph component, looping a compressed replay while on screen. */
export function PipelineShowcase() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-15% 0px" });
  const reduce = usePrefersReducedMotion();
  const [state, setState] = useState<StreamState>(() => initialStreamState());
  const [staticState] = useState(finalState);

  useEffect(() => {
    if (!inView || reduce) return;
    let i = 0;
    let virtual = 0;
    let last = performance.now();
    let seq = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const now = performance.now();
      virtual += (now - last) * 1.7;
      last = now;
      const batch: StreamEvent[] = [];
      while (i < SCRIPT.length && SCRIPT[i].at <= virtual) {
        seq += 1;
        batch.push({ type: SCRIPT[i].event.type, data: { ...SCRIPT[i].event.data, ts: String(seq), seq } } as StreamEvent);
        i += 1;
      }
      if (batch.length) setState((s) => batch.reduce((acc, ev) => applyEvent(acc, ev, now), s));
      if (virtual > END + 4500) {
        i = 0;
        virtual = 0;
        setState(initialStreamState());
      }
      timer = setTimeout(tick, 80);
    };
    timer = setTimeout(tick, 300);
    return () => clearTimeout(timer);
  }, [inView, reduce]);

  const s = reduce ? staticState : state;
  const mcpCalls = (id: string) => s.tools.filter((t) => t.server === id).length;

  return (
    <section id="agents" className="relative scroll-mt-20 py-24 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-10%" }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
          className="max-w-3xl"
        >
          <p className="eyebrow">Watch the agents work</p>
          <h2 className="mt-3 font-display text-4xl font-semibold leading-[1.05] sm:text-5xl">
            Eleven specialists, <span className="display-italic text-coral">one plan</span>.
          </h2>
          <p className="mt-4 text-lg text-ink-2">
            A LangGraph supervisor fans out five researchers in parallel, each pulling live data from MCP tool servers and a
            Qdrant guidebook. A remote Budget Analyst costs the draft over A2A, and a critic sends it back once if anything is off.
          </p>
        </motion.div>

        <motion.div
          ref={ref}
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-10%" }}
          transition={{ duration: 0.8, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          className="card relative mt-12 overflow-hidden p-5 pt-10 sm:p-8 sm:pt-14"
        >
          <div className="pointer-events-none absolute inset-0 opacity-60 [background-image:radial-gradient(var(--line-strong)_1px,transparent_1px)] [background-size:22px_22px]" aria-hidden />
          <AgentGraph agents={s.agents} tools={s.tools} a2a={s.a2a} className="relative" />
          <div className="relative mt-8 grid gap-3 border-t border-line pt-6 sm:grid-cols-2 lg:grid-cols-5">
            {MCP_SERVERS.map((m) => (
              <div key={m.id} className="flex items-center gap-3 rounded-xl bg-bg-2/70 px-3 py-2.5">
                <Server className="h-4 w-4 shrink-0 text-lagoon" aria-hidden />
                <div className="min-w-0 flex-1 leading-tight">
                  <p className="font-mono text-xs font-semibold">mcp/{m.label}</p>
                  <p className="truncate text-[11px] text-ink-3">{m.detail}</p>
                </div>
                <span className="tabular font-mono text-xs text-ink-2">{mcpCalls(m.id)}</span>
              </div>
            ))}
            <div className="flex items-center gap-3 rounded-xl bg-bg-2/70 px-3 py-2.5">
              <Database className="h-4 w-4 shrink-0 text-[var(--p-guide)]" aria-hidden />
              <div className="leading-tight">
                <p className="font-mono text-xs font-semibold">qdrant/guidebook</p>
                <p className="text-[11px] text-ink-3">9,026 passages · 65 cities</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-xl bg-bg-2/70 px-3 py-2.5">
              <Network className="h-4 w-4 shrink-0 text-coral" aria-hidden />
              <div className="leading-tight">
                <p className="font-mono text-xs font-semibold">a2a/budget-analyst</p>
                <p className="text-[11px] text-ink-3">separate service · agent card</p>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
