import {
  BadgeCheck,
  CloudSun,
  Compass,
  Handshake,
  Landmark,
  Map as MapIcon,
  PackageCheck,
  Route,
  ShieldCheck,
  UtensilsCrossed,
  BedDouble,
  type LucideIcon,
} from "lucide-react";
import type { AgentId, McpServer } from "./types";

export type Resource = McpServer | "rag" | "a2a" | "llm" | "rules";

export interface AgentMeta {
  id: AgentId;
  label: string;
  role: string;
  Icon: LucideIcon;
  uses: Resource[];
  stage: number; // column in the graph
}

/** The 11 agents from docs/SPEC.md, in graph order. */
export const AGENTS: AgentMeta[] = [
  { id: "guard", label: "Guard", role: "Injection, PII and sanity checks", Icon: ShieldCheck, uses: ["rules"], stage: 0 },
  { id: "brief", label: "Brief", role: "Normalise, geocode, check guidebook", Icon: Compass, uses: ["places", "rag"], stage: 1 },
  { id: "destination", label: "Destination", role: "Highlights and cited facts", Icon: Landmark, uses: ["rag"], stage: 2 },
  { id: "weather", label: "Weather", role: "Forecast or seasonal normals", Icon: CloudSun, uses: ["weather"], stage: 2 },
  { id: "stays", label: "Stays", role: "Places to stay for your style", Icon: BedDouble, uses: ["places", "rag"], stage: 2 },
  { id: "food", label: "Food", role: "Picks that respect your diet", Icon: UtensilsCrossed, uses: ["places", "rag"], stage: 2 },
  { id: "logistics", label: "Logistics", role: "Getting there, visa, currency", Icon: MapIcon, uses: ["money", "places", "rag"], stage: 2 },
  { id: "itinerary", label: "Itinerary", role: "Weather- and pace-aware days", Icon: Route, uses: ["llm"], stage: 3 },
  { id: "budget", label: "Budget Analyst", role: "Remote agent, costs the plan", Icon: Handshake, uses: ["a2a"], stage: 4 },
  { id: "critic", label: "Critic", role: "Checks dates, budget, citations", Icon: BadgeCheck, uses: ["rules", "llm"], stage: 5 },
  { id: "finalize", label: "Finalize", role: "Assembles plan and scores", Icon: PackageCheck, uses: ["rules"], stage: 6 },
];

export const AGENT_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a])) as Record<AgentId, AgentMeta>;

export const PARALLEL: AgentId[] = ["destination", "weather", "stays", "food", "logistics"];

/** guard → brief → [5 parallel] → itinerary → budget (A2A) → critic → finalize, plus the critic retry loop. */
export const EDGES: [AgentId, AgentId][] = [
  ["guard", "brief"],
  ...PARALLEL.map((p) => ["brief", p] as [AgentId, AgentId]),
  ...PARALLEL.map((p) => [p, "itinerary"] as [AgentId, AgentId]),
  ["itinerary", "budget"],
  ["budget", "critic"],
  ["critic", "finalize"],
];

export const RESOURCE_LABEL: Record<Resource, string> = {
  weather: "MCP · weather",
  places: "MCP · places",
  money: "MCP · money",
  rag: "Qdrant RAG",
  a2a: "A2A",
  llm: "LLM",
  rules: "rules",
};

export const MCP_SERVERS: { id: McpServer; label: string; detail: string }[] = [
  { id: "weather", label: "weather", detail: "Open-Meteo forecast & archive" },
  { id: "places", label: "places", detail: "OpenStreetMap geocode & POIs" },
  { id: "money", label: "money", detail: "Frankfurter FX rates" },
];
