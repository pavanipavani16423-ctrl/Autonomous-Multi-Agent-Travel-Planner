"use client";

import { BookOpen, CloudRain, CloudSun, MessageSquareText, Network, Server, Sun, Umbrella } from "lucide-react";
import { motion } from "motion/react";
import { ProvenancePill, RatingPill } from "@/components/ui/pills";
import { cn } from "@/lib/format";

function Tile({ className, children, i }: { className?: string; children: React.ReactNode; i: number }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-8%" }}
      transition={{ duration: 0.6, delay: i * 0.07, ease: [0.16, 1, 0.3, 1] }}
      className={cn("card group relative flex flex-col overflow-hidden p-6 sm:p-7", className)}
    >
      {children}
    </motion.article>
  );
}

function TileText({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="mt-auto pt-6">
      <div className="flex items-center gap-2 text-ink-3">{icon}</div>
      <h3 className="mt-2 font-display text-2xl font-semibold leading-tight">{title}</h3>
      <p className="mt-2 text-[0.95rem] leading-relaxed text-ink-2">{body}</p>
    </div>
  );
}

const TOOL_ROWS = [
  { s: "weather", t: "forecast", sum: "Kyoto · 6–9 Apr · 9–20 °C", p: "live" as const },
  { s: "places", t: "search_pois", sum: "diet:vegetarian · 54 results", p: "live" as const },
  { s: "money", t: "convert", sum: "1 INR = 1.79 JPY", p: "live" as const },
  { s: "places", t: "route_estimate", sum: "KIX → Kyoto · 75 min", p: "estimate" as const },
];

export function Bento() {
  return (
    <section className="py-24 sm:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div className="max-w-2xl">
            <p className="eyebrow">Under the hood</p>
            <h2 className="mt-3 font-display text-4xl font-semibold leading-[1.05] sm:text-5xl">
              Real data in. <span className="display-italic">Honest</span> plans out.
            </h2>
          </div>
          <p className="max-w-md text-ink-2">
            Every stay, meal, forecast and price carries where it came from. Estimates are labelled as estimates — never dressed up as live.
          </p>
        </div>

        <div className="mt-12 grid gap-4 lg:grid-cols-3">
          <Tile i={0} className="lg:col-span-2">
            <div className="space-y-2">
              {TOOL_ROWS.map((r, k) => (
                <motion.div
                  key={k}
                  initial={{ opacity: 0, x: -20 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.25 + k * 0.12, type: "spring", stiffness: 260, damping: 26 }}
                  className="flex items-center gap-3 rounded-xl border border-line bg-surface-2 px-3 py-2.5 font-mono text-xs"
                >
                  <Server className="h-3.5 w-3.5 shrink-0 text-lagoon" aria-hidden />
                  <span className="font-semibold">{r.s}</span>
                  <span className="text-ink-3">.{r.t}</span>
                  <span className="hidden min-w-0 flex-1 truncate text-ink-2 sm:block">{r.sum}</span>
                  <ProvenancePill value={r.p} className="ml-auto" />
                </motion.div>
              ))}
            </div>
            <TileText
              icon={<Server className="h-4 w-4" />}
              title="Live data via MCP"
              body="Three MCP tool servers — weather (Open-Meteo), places (OpenStreetMap) and money (Frankfurter) — give the agents fresh facts instead of model memory."
            />
          </Tile>

          <Tile i={1}>
            <div className="relative flex items-center justify-between rounded-2xl bg-bg-2/70 px-4 py-6">
              <div className="flex flex-col items-center gap-1.5">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-ink text-bg">
                  <span className="font-display text-sm font-bold">V</span>
                </span>
                <span className="font-mono text-[10px] text-ink-3">voyager</span>
              </div>
              <svg className="mx-2 h-6 flex-1" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden>
                <line x1="0" y1="5" x2="100" y2="5" stroke="var(--coral)" strokeWidth="1.5" className="dash-flow" vectorEffect="non-scaling-stroke" />
              </svg>
              <div className="flex flex-col items-center gap-1.5">
                <span className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-dashed border-coral text-coral">
                  <Network className="h-5 w-5" aria-hidden />
                </span>
                <span className="font-mono text-[10px] text-ink-3">budget-analyst</span>
              </div>
            </div>
            <ol className="mt-3 flex justify-between font-mono text-[10.5px] text-ink-3">
              <li>① agent card</li>
              <li>② message/send</li>
              <li>③ received</li>
            </ol>
            <TileText
              icon={<Network className="h-4 w-4" />}
              title="A2A budget analyst"
              body="Costing runs in a separate agent service, discovered by its agent card and called over the Agent2Agent protocol."
            />
          </Tile>

          <Tile i={2}>
            <p className="text-[0.95rem] leading-relaxed">
              Walk the Philosopher&apos;s Path from Ginkaku-ji to Nanzen-ji, lined with cherry trees
              <sup className="ml-0.5 rounded-md bg-[var(--p-guide-bg)] px-1 font-mono text-[10px] text-[var(--p-guide)]">c5</sup>, then graze Nishiki Market
              <sup className="ml-0.5 rounded-md bg-[var(--p-guide-bg)] px-1 font-mono text-[10px] text-[var(--p-guide)]">c7</sup>.
            </p>
            <div className="mt-3 rounded-xl border border-line bg-surface-2 p-3 text-xs text-ink-2">
              <p className="mb-1 flex items-center gap-1.5 font-semibold text-ink">
                <BookOpen className="h-3.5 w-3.5" aria-hidden /> Wikivoyage · Kyoto — Do
              </p>
              “A walk from Nanzen-ji to Ginkaku-ji along the Philosopher&apos;s Path, lined with cherry trees, is enjoyable…”
            </div>
            <TileText
              icon={<BookOpen className="h-4 w-4" />}
              title="Hybrid RAG with citations"
              body="BM25 + dense retrieval over 9,026 Wikivoyage passages. Unknown cities are fetched, chunked and indexed on demand."
            />
          </Tile>

          <Tile i={3}>
            <div className="grid grid-cols-4 gap-2">
              {[
                { d: "Tue", I: Sun, t: "19°" },
                { d: "Wed", I: CloudSun, t: "20°" },
                { d: "Thu", I: CloudRain, t: "16°", wet: true },
                { d: "Fri", I: Sun, t: "18°" },
              ].map(({ d, I, t, wet }) => (
                <div key={d} className={cn("flex flex-col items-center gap-1 rounded-xl py-3", wet ? "bg-[var(--p-guide-bg)]" : "bg-bg-2/70")}>
                  <span className="text-[11px] font-semibold text-ink-3">{d}</span>
                  <I className={cn("h-5 w-5", wet ? "text-[var(--p-guide)]" : "text-sun")} aria-hidden />
                  <span className="tabular text-sm font-bold">{t}</span>
                </div>
              ))}
            </div>
            <p className="mt-3 flex items-center gap-2 rounded-xl bg-sun-soft px-3 py-2 text-xs font-semibold">
              <Umbrella className="h-3.5 w-3.5" aria-hidden /> Thu: bamboo grove early, museums after noon
            </p>
            <TileText icon={<CloudSun className="h-4 w-4" />} title="Weather-aware days" body="Forecasts up to 16 days out, seasonal normals beyond — and rainy afternoons move indoors." />
          </Tile>

          <Tile i={4}>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-3">
                  <th className="pb-2 font-semibold">Score</th>
                  <th className="pb-2 font-semibold">Value</th>
                  <th className="pb-2 text-right font-semibold">Rating</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[
                  ["Faithfulness", 0.88, "Good"],
                  ["Context precision", 0.67, "OK"],
                  ["Budget fit", 0.94, "Good"],
                ].map(([n, v, r]) => (
                  <tr key={n as string}>
                    <td className="py-2 font-medium">{n}</td>
                    <td className="tabular py-2 font-mono text-xs">{(v as number).toFixed(2)}</td>
                    <td className="py-2 text-right">
                      <RatingPill rating={r as "Good" | "OK"} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <TileText icon={<span className="font-mono text-xs">◎</span>} title="Quality scores" body="Every run is traced in Langfuse and scored with Ragas metrics plus rule checks, right in the trip." />
          </Tile>

          <Tile i={5} className="lg:col-span-3">
            <div className="grid items-center gap-6 md:grid-cols-[1fr_1.1fr]">
              <div className="space-y-2.5">
                <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm text-bg">make day 2 more relaxed and swap the hotel for something cheaper</div>
                <div className="w-fit max-w-[90%] rounded-2xl rounded-bl-md border border-line bg-surface-2 px-4 py-2.5 text-sm">
                  <span className="mb-1 block font-mono text-[10.5px] text-ink-3">itinerary → budget (A2A) → critic → finalize</span>
                  Revision 2 ready: Day 2 drops the evening stop, stays re-sorted by price — saves ₹14,100.
                </div>
              </div>
              <TileText
                icon={<MessageSquareText className="h-4 w-4" />}
                title="Refine by chat"
                body="Human-in-the-loop: your feedback resumes the run from its checkpoint and re-runs only the agents that need to change. Changed cards animate so you can see what moved."
              />
            </div>
          </Tile>
        </div>
      </div>
    </section>
  );
}
