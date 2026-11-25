import { AGENTS } from "./agents";
import type {
  A2AEvent,
  AgentEvent,
  AgentId,
  AgentStatus,
  Budget,
  DailyWeather,
  DayPlan,
  DoneEvent,
  ErrorEvent,
  FoodPick,
  PreTrip,
  Quality,
  RetrievalEvent,
  Stay,
  StreamEvent,
  ToolEvent,
  TripPlan,
} from "./types";

export interface AgentState {
  status: AgentStatus | "idle";
  message: string;
  ms?: number;
  runs: number;
  startedAt?: number;
}

export interface Partials {
  destination?: TripPlan["destination"];
  weather?: DailyWeather[];
  stays?: Stay[];
  food?: FoodPick[];
  logistics?: Partial<PreTrip>;
  itinerary?: DayPlan[];
  budget?: Budget;
  quality?: Quality;
}

export interface LogItem {
  key: string;
  at: number; // client ms when received
  event: StreamEvent;
}

export interface StreamState {
  agents: Record<AgentId, AgentState>;
  tools: ToolEvent[];
  retrievals: RetrievalEvent[];
  a2a: A2AEvent[];
  log: LogItem[];
  partials: Partials;
  plan?: TripPlan;
  error?: ErrorEvent;
  done?: DoneEvent;
  seen: Set<string>;
  /** Plans/done events older than this revision are stale replays from before a refinement. */
  minRevision: number;
}

export function idleAgents(): Record<AgentId, AgentState> {
  return Object.fromEntries(AGENTS.map((a) => [a.id, { status: "idle", message: "", runs: 0 }])) as Record<
    AgentId,
    AgentState
  >;
}

export function initialStreamState(plan?: TripPlan): StreamState {
  return {
    agents: idleAgents(),
    tools: [],
    retrievals: [],
    a2a: [],
    log: [],
    partials: {},
    plan,
    seen: new Set(),
    minRevision: plan?.revision ?? 0,
  };
}

// ── payload guards: the SPEC types `partial.payload` as any, so narrow defensively ──
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const arrOf = <T>(v: unknown, key: string): T[] | undefined => {
  if (Array.isArray(v)) return v as T[];
  if (isObj(v) && Array.isArray(v[key])) return v[key] as T[];
  return undefined;
};

function applyPartial(p: Partials, section: string, payload: unknown): Partials {
  switch (section) {
    case "destination":
      return isObj(payload) && typeof payload.name === "string" ? { ...p, destination: payload as Partials["destination"] } : p;
    case "weather": {
      const w = arrOf<DailyWeather>(payload, "days") ?? arrOf<DailyWeather>(payload, "weather");
      return w ? { ...p, weather: w } : p;
    }
    case "stays": {
      const s = arrOf<Stay>(payload, "stays");
      return s ? { ...p, stays: s } : p;
    }
    case "food": {
      const f = arrOf<FoodPick>(payload, "food");
      return f ? { ...p, food: f } : p;
    }
    case "logistics":
      return isObj(payload) ? { ...p, logistics: (isObj(payload.pre_trip) ? payload.pre_trip : payload) as Partial<PreTrip> } : p;
    case "itinerary": {
      const d = arrOf<DayPlan>(payload, "days");
      return d ? { ...p, itinerary: d } : p;
    }
    case "budget":
      return isObj(payload) && isObj(payload.total) ? { ...p, budget: payload as unknown as Budget } : p;
    case "quality":
      return isObj(payload) && Array.isArray(payload.scores) ? { ...p, quality: payload as unknown as Quality } : p;
    default:
      return p;
  }
}

const LOG_MAX = 120;

/** Pure reducer shared by the live EventSource and the offline demo player. */
export function applyEvent(state: StreamState, ev: StreamEvent, now: number): StreamState {
  const d = ev.data as { seq?: number; ts?: string };
  // EventSource reconnects replay the whole stream: drop anything already applied.
  const key = d.seq != null ? `${ev.type}:${d.seq}:${d.ts ?? ""}` : "";
  if (key && state.seen.has(key)) return state;
  const seen = key ? new Set(state.seen).add(key) : state.seen;
  const log = [...state.log, { key: key || `${ev.type}:${now}:${state.log.length}`, at: now, event: ev }].slice(-LOG_MAX);
  const base = { ...state, seen, log };

  switch (ev.type) {
    case "agent": {
      const a: AgentEvent = ev.data;
      const prev = state.agents[a.agent] ?? { status: "idle", message: "", runs: 0 };
      return {
        ...base,
        agents: {
          ...state.agents,
          [a.agent]: {
            status: a.status,
            message: a.message,
            ms: a.ms ?? prev.ms,
            runs: a.status === "started" ? prev.runs + 1 : prev.runs,
            startedAt: a.status === "started" ? now : prev.startedAt,
          },
        },
      };
    }
    case "tool":
      return { ...base, tools: [...state.tools, ev.data] };
    case "retrieval":
      return { ...base, retrievals: [...state.retrievals, ev.data] };
    case "a2a":
      return { ...base, a2a: [...state.a2a, ev.data] };
    case "partial":
      return { ...base, partials: applyPartial(state.partials, ev.data.section, ev.data.payload) };
    case "plan": {
      if (ev.data.revision < state.minRevision) return base;
      return { ...base, plan: ev.data };
    }
    case "error":
      return { ...base, error: ev.data };
    case "done": {
      if (ev.data.revision < state.minRevision) return base;
      return { ...base, done: ev.data };
    }
    default:
      return base;
  }
}

/** Reset run-scoped state for a refinement while keeping the current plan on screen. */
export function beginRevision(state: StreamState, minRevision: number): StreamState {
  return {
    ...state,
    agents: idleAgents(),
    tools: [],
    retrievals: [],
    a2a: [],
    log: [],
    partials: {},
    error: undefined,
    done: undefined,
    minRevision,
  };
}
