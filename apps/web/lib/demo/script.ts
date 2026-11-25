import { formatMoney } from "../format";
import type { AgentId, StreamEvent, TripPlan } from "../types";

/** An event without the transport fields; the player stamps `ts` and `seq` at replay time. */
type Bare<E> = E extends { type: infer T; data: infer D } ? { type: T; data: Omit<D, "ts" | "seq"> } : never;
export type DemoEvent = Bare<StreamEvent>;
export interface DemoStep {
  at: number; // ms from start
  event: DemoEvent;
}

/**
 * A scripted, realistic replay of one planning run (~27 s), derived from the plan itself so a
 * swapped-in fixture stays consistent. Mirrors the SPEC graph, including one critic → itinerary retry.
 */
export function buildDemoScript(plan: TripPlan): DemoStep[] {
  const steps: DemoStep[] = [];
  const t = { now: 0 };
  const at = (ms: number, event: DemoEvent) => {
    t.now = ms;
    steps.push({ at: ms, event });
  };
  const agent = (ms: number, id: AgentId, status: "started" | "done", message: string, took?: number) =>
    at(ms, { type: "agent", data: { agent: id, status, message, ...(took ? { ms: took } : {}) } });

  const d = plan.destination;
  const r = plan.request;
  const nights = Math.max(1, plan.days.length - 1);
  const ms = (id: AgentId) => plan.timings.find((x) => x.agent === id)?.ms ?? 1200;
  const weatherDays = plan.days.map((x) => x.weather).filter(Boolean);
  const wet = plan.days.find((x) => (x.weather?.precip_mm ?? 0) > 3);
  const money = (n: number) => formatMoney({ amount: n, currency: r.currency });

  agent(0, "guard", "started", "Screening the request");
  agent(700, "guard", "done", "No prompt injection or PII; dates and budget are sane", ms("guard"));

  agent(900, "brief", "started", `Normalising "${r.destination}" for ${r.adults + r.children} travellers`);
  at(1500, {
    type: "tool",
    data: { agent: "brief", server: "places", tool: "geocode", provenance: "live", summary: `${d.name}, ${d.country} → ${d.location.lat.toFixed(4)}, ${d.location.lon.toFixed(4)}`, ms: 238 },
  });
  at(2100, {
    type: "retrieval",
    data: { agent: "brief", query: `${d.name} guidebook coverage`, hits: 86, top_score: 0.93, covered: plan.quality.guidebook !== "none" },
  });
  at(2500, { type: "partial", data: { section: "destination", payload: d } });
  agent(2800, "brief", "done", plan.quality.guidebook === "expanded" ? `Expanded the guidebook with ${d.name}` : `${d.name} is in the guidebook (86 passages)`, ms("brief"));

  const parallel: AgentId[] = ["destination", "weather", "stays", "food", "logistics"];
  const msgs: Record<string, string> = {
    destination: "Pulling highlights and neighbourhoods",
    weather: "Fetching daily weather",
    stays: `Finding ${r.stay_style} stays`,
    food: r.diet.length ? `Finding ${r.diet.join(" + ")} food` : "Finding food picks",
    logistics: `Routing from ${r.origin ?? "home"}`,
  };
  parallel.forEach((id, i) => agent(3000 + i * 90, id, "started", msgs[id]));

  at(3700, {
    type: "tool",
    data: {
      agent: "weather",
      server: "weather",
      tool: weatherDays[0]?.provenance === "live" ? "forecast" : "historical_normals",
      provenance: "live",
      summary: `${weatherDays.length} days · ${Math.min(...weatherDays.map((w) => w!.t_min))}–${Math.max(...weatherDays.map((w) => w!.t_max))} °C${wet ? ` · rain on ${wet.date.slice(5)}` : ""}`,
      ms: 412,
    },
  });
  at(4200, { type: "retrieval", data: { agent: "destination", query: `${d.name} highlights temples neighbourhoods`, hits: 12, top_score: 0.88, covered: true } });
  at(4700, {
    type: "tool",
    data: { agent: "stays", server: "places", tool: "search_pois", provenance: "live", summary: `tourism=hotel|guest_house near ${plan.pre_trip.best_areas[0] ?? d.name} · 38 results`, ms: 690 },
  });
  at(5200, { type: "retrieval", data: { agent: "stays", query: `${d.name} Sleep ${r.stay_style}-range`, hits: 8, top_score: 0.81, covered: true } });
  at(5600, {
    type: "tool",
    data: { agent: "logistics", server: "money", tool: "convert", provenance: "live", summary: plan.pre_trip.currency_note.match(/1 [A-Z]{3} ≈ [\d.,]+ [A-Z]{3}/)?.[0] ?? `${r.currency} → local currency`, ms: 154 },
  });
  at(6000, { type: "retrieval", data: { agent: "food", query: `${d.name} Eat ${r.diet.join(" ") || "local"} specialities`, hits: 10, top_score: 0.84, covered: true } });
  at(6500, {
    type: "tool",
    data: { agent: "food", server: "places", tool: "search_pois", provenance: "live", summary: `amenity=restaurant${r.diet.includes("vegetarian") ? " diet:vegetarian" : ""} · 54 results`, ms: 731 },
  });
  at(7000, { type: "partial", data: { section: "weather", payload: weatherDays } });
  agent(7300, "weather", "done", `${weatherDays.length} days of weather${wet ? ", one wet day flagged" : ""}`, ms("weather"));
  at(8100, { type: "retrieval", data: { agent: "logistics", query: `${d.name} Get in Get around`, hits: 9, top_score: 0.86, covered: true } });
  at(8700, {
    type: "tool",
    data: { agent: "logistics", server: "places", tool: "route_estimate", provenance: "estimate", summary: plan.pre_trip.getting_there.mode, ms: 322 },
  });
  agent(9400, "destination", "done", "8 highlights with cited facts", ms("destination"));
  at(10100, { type: "partial", data: { section: "stays", payload: plan.stays } });
  agent(10300, "stays", "done", `${plan.stays.length} stays matched to style and budget`, ms("stays"));
  at(11000, { type: "partial", data: { section: "food", payload: plan.food } });
  agent(11200, "food", "done", `${plan.food.length} food picks`, ms("food"));
  at(11700, { type: "partial", data: { section: "logistics", payload: plan.pre_trip } });
  agent(11900, "logistics", "done", "Getting there, visa, currency and packing ready", ms("logistics"));

  agent(12300, "itinerary", "started", `Composing ${plan.days.length} ${r.pace} days, geo-clustered`);
  // First draft goes to the analyst and critic, who send it back once — the SPEC's single retry loop.
  agent(15600, "itinerary", "done", "Draft 1 ready", 3300);
  agent(15800, "budget", "started", "Handing the draft to the remote Budget Analyst");
  at(16200, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "card", summary: "Fetched /.well-known/agent-card.json · skills: cost_plan, savings_tips" } });
  at(17000, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "sent", summary: `message/send · ${plan.days.length} days, ${nights} nights, ${r.adults + r.children} pax, limit ${money(r.budget)}` } });
  at(18300, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "received", summary: `Total ${formatMoney(plan.budget.total)} · ${Math.round(plan.budget.utilisation * 100)}% of limit` } });
  agent(18500, "budget", "done", "Costed by Budget Analyst", 2700);
  agent(18700, "critic", "started", "Checking dates, budget, citations, geography");
  agent(19900, "critic", "done", wet ? `1 issue: too many outdoor stops on ${wet.date.slice(5)} (rain) → retry itinerary` : "1 issue: day 2 is over-packed for a relaxed pace → retry itinerary", 1200);

  agent(20100, "itinerary", "started", "Revising with the critic's notes");
  at(22200, { type: "partial", data: { section: "itinerary", payload: plan.days } });
  agent(22400, "itinerary", "done", `${plan.days.length} days, ${plan.days.reduce((n, x) => n + x.activities.length, 0)} stops`, 2100);
  agent(22500, "budget", "started", "Re-costing the revised plan");
  at(22700, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "sent", summary: "message/send · revised itinerary" } });
  at(23600, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "received", summary: `Total ${formatMoney(plan.budget.total)} · ${plan.budget.savings_tips.length} savings tips` } });
  at(23700, { type: "partial", data: { section: "budget", payload: plan.budget } });
  agent(23800, "budget", "done", plan.budget.within_budget ? "Within budget" : "Over budget — tips attached", 1100);
  agent(23900, "critic", "started", "Re-checking the revision");
  const passed = plan.quality.checks.filter((c) => c.passed).length;
  agent(25000, "critic", "done", `${passed}/${plan.quality.checks.length} checks passed`, 1100);
  agent(25100, "finalize", "started", "Assembling plan, confidence and scores");
  at(25700, { type: "partial", data: { section: "quality", payload: plan.quality } });
  agent(26200, "finalize", "done", `Confidence ${Math.round(plan.quality.confidence * 100)}% · scores sent to Langfuse`, ms("finalize"));
  at(26400, { type: "plan", data: plan });
  at(26600, { type: "done", data: { trip_id: plan.trip_id, revision: plan.revision, ms: 26600 } });
  return steps;
}

/** A short refinement replay: only itinerary → budget → critic → finalize re-run (SPEC "refine"). */
export function buildRefineScript(next: TripPlan, message: string): DemoStep[] {
  const steps: DemoStep[] = [];
  const at = (ms: number, event: DemoEvent) => steps.push({ at: ms, event });
  at(0, { type: "agent", data: { agent: "itinerary", status: "started", message: `Applying: "${message}"` } });
  at(1800, { type: "agent", data: { agent: "itinerary", status: "done", message: "Revised days ready", ms: 1800 } });
  at(1900, { type: "agent", data: { agent: "budget", status: "started", message: "Re-costing via A2A" } });
  at(2200, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "sent", summary: "message/send · refined itinerary" } });
  at(3000, { type: "a2a", data: { agent: "budget", peer: "budget-analyst", status: "received", summary: `Total ${formatMoney(next.budget.total)}` } });
  at(3100, { type: "agent", data: { agent: "budget", status: "done", message: "Costed", ms: 1200 } });
  at(3200, { type: "agent", data: { agent: "critic", status: "started", message: "Checking the revision" } });
  at(4000, { type: "agent", data: { agent: "critic", status: "done", message: "All checks passed", ms: 800 } });
  at(4100, { type: "agent", data: { agent: "finalize", status: "started", message: "Assembling revision" } });
  at(4500, { type: "agent", data: { agent: "finalize", status: "done", message: `Revision ${next.revision} ready`, ms: 400 } });
  at(4600, { type: "plan", data: next });
  at(4700, { type: "done", data: { trip_id: next.trip_id, revision: next.revision, ms: 4700 } });
  return steps;
}

/**
 * Offline stand-in for the backend's human-in-the-loop refinement: a deterministic, visible tweak so the
 * demo can show changed cards animating. Real refinements come from POST /api/trips/{id}/refine.
 */
export function applyDemoRefinement(plan: TripPlan, message: string): TripPlan {
  const next: TripPlan = structuredClone(plan);
  next.revision = plan.revision + 1;
  const m = message.toLowerCase();
  const dayMatch = m.match(/day\s*(\d+)/);
  const dayIdx = dayMatch ? Math.min(Math.max(Number(dayMatch[1]) - 1, 0), next.days.length - 1) : -1;

  if (/cheap|budget|save|afford/.test(m) && /hotel|stay|room|ryokan|hostel/.test(m)) {
    next.stays = [...next.stays].sort((a, b) => a.price_per_night.amount - b.price_per_night.amount);
    const stayLine = next.budget.lines.find((l) => l.category === "stay");
    if (stayLine) {
      const nights = Math.max(1, next.days.length - 1);
      const newAmt = next.stays[0].price_per_night.amount * nights;
      const delta = stayLine.amount.amount - newAmt;
      stayLine.amount = { ...stayLine.amount, amount: newAmt };
      stayLine.note = `${nights} nights at ${next.stays[0].name} (refined: cheapest option first)`;
      next.budget.total = { ...next.budget.total, amount: next.budget.total.amount - delta };
      next.budget.per_person = { ...next.budget.per_person, amount: Math.round(next.budget.total.amount / (next.request.adults + next.request.children)) };
      next.budget.utilisation = next.budget.total.amount / next.budget.limit.amount;
    }
    next.summary = `${plan.summary} Revised to lead with the most affordable stay.`;
    return next;
  }

  // Default: make the chosen day (or the busiest one) more relaxed — drop its last non-transit stop.
  const idx = dayIdx >= 0 ? dayIdx : next.days.reduce((best, d, i, arr) => (d.activities.length > arr[best].activities.length ? i : best), 0);
  const day = next.days[idx];
  const dropAt = [...day.activities].reverse().findIndex((a) => a.category !== "transit");
  if (dropAt >= 0 && day.activities.length > 2) {
    const realIdx = day.activities.length - 1 - dropAt;
    const [removed] = day.activities.splice(realIdx, 1);
    day.day_cost = { ...day.day_cost, amount: day.day_cost.amount - removed.cost.amount };
  }
  day.activities = day.activities.map((a, i) =>
    i === 0 ? { ...a, id: `${a.id}-r${next.revision}`, duration_min: a.duration_min + 30, tip: a.tip ?? "Revised: more time here, no rush." } : a,
  );
  day.theme = `${day.theme} · slower`;
  next.summary = `${plan.summary} Day ${day.day} is now lighter, with more time at each stop.`;
  return next;
}
