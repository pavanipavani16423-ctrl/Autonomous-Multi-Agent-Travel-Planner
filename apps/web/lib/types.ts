/**
 * Voyager API contract — mirrors docs/SPEC.md field-for-field.
 * The SPEC is authoritative: change it there first, then here.
 */

export type AgentId =
  | "guard"
  | "brief"
  | "destination"
  | "weather"
  | "stays"
  | "food"
  | "logistics"
  | "itinerary"
  | "budget"
  | "critic"
  | "finalize";

export type Provenance = "live" | "guidebook" | "estimate" | "cached" | "unavailable";

export interface Money {
  amount: number;
  currency: string; // ISO 4217, e.g. "INR"
}

export interface GeoPoint {
  lat: number;
  lon: number;
}

export type Pace = "relaxed" | "balanced" | "packed";
export type StayStyle = "budget" | "mid" | "luxury";

export interface TripRequest {
  origin?: string;
  destination: string;
  start_date: string; // "YYYY-MM-DD", inclusive; max 14 days
  end_date: string;
  adults: number; // ≥ 1
  children: number;
  budget: number; // total trip budget for the group
  currency: string;
  interests: string[];
  pace: Pace;
  diet: string[];
  stay_style: StayStyle;
  notes?: string;
  client_id?: string;
}

export type CitationSource = "wikivoyage" | "openstreetmap" | "open-meteo" | "frankfurter" | "budget-analyst";

export interface Citation {
  id: string;
  title: string;
  url: string;
  snippet: string;
  source: CitationSource;
}

export interface DailyWeather {
  date: string;
  t_min: number;
  t_max: number;
  precip_mm: number;
  precip_prob?: number;
  code: number; // WMO
  summary: string;
  provenance: Provenance;
}

export type ActivitySlot = "morning" | "afternoon" | "evening";
export type ActivityCategory =
  | "sight"
  | "food"
  | "activity"
  | "transit"
  | "shopping"
  | "nature"
  | "culture"
  | "nightlife";

export interface Activity {
  id: string;
  slot: ActivitySlot;
  time: string; // "09:30"
  duration_min: number;
  title: string;
  description: string;
  place?: string;
  location?: GeoPoint;
  category: ActivityCategory;
  cost: Money;
  indoor: boolean;
  citations: string[];
  tip?: string;
}

export interface DayPlan {
  day: number;
  date: string;
  title: string;
  theme: string;
  weather?: DailyWeather;
  activities: Activity[];
  day_cost: Money;
  walking_km?: number;
}

export interface Stay {
  name: string;
  kind: "hotel" | "hostel" | "guest_house" | "apartment" | "resort";
  area: string;
  location?: GeoPoint;
  price_per_night: Money;
  rating?: number;
  why: string;
  provenance: Provenance;
  url?: string;
  citations: string[];
}

export interface FoodPick {
  name: string;
  cuisine: string;
  area?: string;
  location?: GeoPoint;
  price_level: 1 | 2 | 3 | 4;
  must_try: string;
  diet_ok: string[];
  provenance: Provenance;
  citations: string[];
}

export type BudgetCategory = "stay" | "food" | "activities" | "transport" | "travel" | "misc";

export interface BudgetLine {
  category: BudgetCategory;
  amount: Money;
  note: string;
}

export interface Budget {
  total: Money;
  limit: Money;
  per_person: Money;
  lines: BudgetLine[];
  within_budget: boolean;
  utilisation: number; // total/limit
  savings_tips: string[];
  analyst: string; // "budget-analyst (A2A)" or "local fallback"
}

export interface PreTrip {
  getting_there: { mode: string; duration: string; cost: Money; note: string };
  getting_around: string;
  visa: string;
  currency_note: string;
  safety: string[];
  packing: string[];
  local_tips: string[];
  best_areas: string[];
  citations: string[];
}

export type Rating = "Good" | "OK" | "Weak";

export interface QualityScore {
  name: string;
  value: number; // 0-1
  rating: Rating;
  explain: string;
}

export interface Quality {
  confidence: number; // 0-1
  grounding_coverage: number; // 0-1
  guidebook: "covered" | "expanded" | "none";
  checks: { name: string; passed: boolean; detail: string }[];
  /** names: "Faithfulness","Answer relevancy","Context precision","Citation coverage","Budget fit","Overall" */
  scores: QualityScore[];
}

export interface TripPlan {
  trip_id: string;
  revision: number;
  request: TripRequest;
  title: string;
  summary: string;
  destination: { name: string; country: string; location: GeoPoint; image?: string; blurb: string };
  weather_overview: string;
  days: DayPlan[];
  stays: Stay[];
  food: FoodPick[];
  budget: Budget;
  pre_trip: PreTrip;
  citations: Citation[];
  quality: Quality;
  timings: { agent: AgentId; ms: number }[];
  model: string;
  created_at: string;
}

export type TripStatus = "queued" | "running" | "done" | "error";

export interface Trip {
  id: string;
  status: TripStatus;
  revision: number;
  request: TripRequest;
  plan?: TripPlan;
  error?: string;
  created_at: string;
  updated_at: string;
}

export interface TripSummary {
  id: string;
  title: string;
  destination: string;
  start_date: string;
  end_date: string;
  status: Trip["status"];
  image?: string;
  created_at: string;
}

export interface CoveredDestination {
  name: string;
  country: string;
  passages: number;
}

export interface PlaceSuggestion {
  name: string;
  country: string;
  lat: number;
  lon: number;
  covered: boolean;
}

export interface HealthReady {
  llm: boolean;
  qdrant: boolean;
  langfuse: boolean;
  mcp: { weather: boolean; places: boolean; money: boolean };
  a2a: boolean;
  guidebook_cities: number;
}

// ---------------------------------------------------------------- SSE events

export type AgentStatus = "started" | "done" | "error" | "skipped";
export type McpServer = "weather" | "places" | "money";
export type PartialSection =
  | "destination"
  | "weather"
  | "stays"
  | "food"
  | "logistics"
  | "itinerary"
  | "budget"
  | "quality";

interface EventBase {
  ts: string; // ISO time
  seq: number; // increasing
}

export interface AgentEvent extends EventBase {
  agent: AgentId;
  status: AgentStatus;
  message: string;
  ms?: number;
}

export interface ToolEvent extends EventBase {
  agent: AgentId;
  server: McpServer;
  tool: string;
  provenance: Provenance;
  summary: string;
  ms: number;
}

export interface RetrievalEvent extends EventBase {
  agent: AgentId;
  query: string;
  hits: number;
  top_score: number;
  covered: boolean;
}

export interface A2AEvent extends EventBase {
  agent: "budget";
  peer: "budget-analyst";
  status: "card" | "sent" | "received" | "error";
  summary: string;
}

export interface PartialEvent extends EventBase {
  section: PartialSection;
  // The SPEC types this as `any`; the UI narrows it per section with type guards.
  payload: unknown;
}

export type PlanEvent = TripPlan & Partial<EventBase>;

export interface ErrorEvent extends EventBase {
  message: string;
  recoverable: boolean;
}

export interface DoneEvent extends EventBase {
  trip_id: string;
  revision: number;
  ms: number;
}

export type StreamEvent =
  | { type: "agent"; data: AgentEvent }
  | { type: "tool"; data: ToolEvent }
  | { type: "retrieval"; data: RetrievalEvent }
  | { type: "a2a"; data: A2AEvent }
  | { type: "partial"; data: PartialEvent }
  | { type: "plan"; data: PlanEvent }
  | { type: "error"; data: ErrorEvent }
  | { type: "done"; data: DoneEvent };

export type StreamEventType = StreamEvent["type"];

// ── POST /api/chat (the Voyager assistant) ────────────────────────────────────
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}
export type ChatActionType = "refine" | "plan";
export interface ChatAction {
  type: ChatActionType;
  message: string;
}
export interface ChatSources {
  citations: Citation[];
  /** "[n]" marker in the answer → citation id (only markers the answer actually used). */
  refs: Record<string, string>;
}
export interface ChatDone {
  intent: "answer" | "refine" | "plan" | "off_topic" | "refused" | "error";
  model: string;
  grounded: boolean;
  ms: number;
}
export type ChatEvent =
  | { type: "token"; data: { text: string } }
  | { type: "sources"; data: ChatSources }
  | { type: "action"; data: ChatAction }
  | { type: "done"; data: ChatDone }
  | { type: "error"; data: { message: string } };
