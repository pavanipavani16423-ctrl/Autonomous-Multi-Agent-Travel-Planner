# Voyager v2 — build contract

Voyager is the v2 of the Autonomous Multi-Agent Travel Planner: a production-grade multi-agent
trip planner. A traveller describes a trip (free text or a form); a LangGraph team of specialist
agents researches **in parallel** using live data from **MCP tool servers** and a **Qdrant hybrid-RAG**
guidebook, a remote **Budget Analyst agent over A2A** costs the plan, a critic checks it, and the user
gets a day-by-day itinerary with a map, stays, food, budget, pre-trip checklist, citations and quality
scores — streamed live to a **Next.js** workspace. Every run is traced in **Langfuse** and scored
(**Ragas** offline + online scores).

This file is the contract between `apps/api` (Python) and `apps/web` (Next.js). Field names here are
authoritative; both sides must match them exactly.

## Repo layout (monorepo)

```
apps/api/            FastAPI + LangGraph backend, python package `voyager` (Python 3.11)
apps/web/            Next.js 16 App Router + React 19 + TypeScript + Tailwind v4 + motion + MapLibre
data/corpus.jsonl    Wikivoyage guidebook, 9,026 passages, 65 cities (+ "__general__")
docs/                SPEC.md (this), architecture notes, eval results, screenshots
docker-compose.yml   api + a2a budget agent + qdrant + web
.github/workflows/   CI (ruff + pytest offline, web lint + typecheck + build)
```

Old Streamlit v1 code is preserved by the git tag `v1-streamlit`; v2 removes it from the tree.

Corpus record shape: `{"page_content": str, "metadata": {"source":"wikivoyage","destination":"kyoto",
"destination_name":"Kyoto","destination_alias":"","area":"general|hotel|food|...","section":"See|Eat|Sleep|Do|Get in|Get around|Stay safe|Understand|Buy|Drink|Cope|Connect","url":"https://en.wikivoyage.org/wiki/Kyoto"}}`

## Agents (ids used in SSE events and the UI)

| id | role | data |
|---|---|---|
| `guard` | input guardrails: prompt-injection, PII redaction, scope, date/budget sanity | rules |
| `brief` | normalises the request, geocodes destination, checks guidebook coverage; if the city is not covered it **expands the knowledge base on demand** (fetch Wikivoyage article → chunk → embed → upsert) | MCP places, RAG |
| `destination` | highlights, neighbourhoods, culture, cited facts | RAG |
| `weather` | daily forecast (≤16 days out) or same-dates-last-year historical normals | MCP weather |
| `stays` | 3–5 places to stay matched to style + budget | MCP places (OSM) + RAG "Sleep" |
| `food` | 5–8 food picks respecting diet | MCP places (OSM) + RAG "Eat"/"Drink" |
| `logistics` | getting there, getting around, visa/safety/packing (pre-trip), currency | MCP money + places, RAG "Get in/Get around/Stay safe" |
| `itinerary` | composes the day-by-day plan (weather-aware, pace-aware, geo-clustered) | LLM over the above |
| `budget` | **remote A2A agent** "Budget Analyst" — costs the plan, compares to the limit, suggests savings | A2A |
| `critic` | checks: day count, dates, budget fit, citation coverage, wrong-city leakage, geo sanity; one revision loop back to `itinerary` on failure | rules + LLM |
| `finalize` | assembles `TripPlan`, confidence, quality scores, Langfuse scores | — |

Graph: `guard → brief → [destination ‖ weather ‖ stays ‖ food ‖ logistics] → itinerary → budget(A2A) → critic →(fail, ≤1 retry) itinerary | finalize`.
Refinement (`POST /api/trips/{id}/refine`) resumes from the checkpoint with the user's feedback and re-runs
`itinerary → budget → critic → finalize` only (human-in-the-loop), incrementing `revision`.

## HTTP API (FastAPI, prefix `/api`, JSON)

| method | path | body / query | returns |
|---|---|---|---|
| GET | `/health` | | `{"status":"ok"}` |
| GET | `/health/ready` | | `{"llm":bool,"qdrant":bool,"langfuse":bool,"mcp":{"weather":bool,"places":bool,"money":bool},"a2a":bool,"guidebook_cities":int}` |
| POST | `/api/trips/parse` | `{"text": str}` | `TripRequest` (draft parsed from free text; dates resolved relative to today) |
| POST | `/api/trips` | `TripRequest` | `{"trip_id": str}` (202; run starts in background) |
| GET | `/api/trips/{id}/stream` | | `text/event-stream` (see events). Replays past events then live ones; ends with `done` |
| GET | `/api/trips/{id}` | | `Trip` |
| POST | `/api/trips/{id}/refine` | `{"message": str}` | `{"trip_id": str, "revision": int}` then stream again |
| GET | `/api/trips` | `?client_id=` | `TripSummary[]` (most recent first, max 20) |
| GET | `/api/destinations` | | `{"name":str,"country":str,"passages":int}[]` covered cities |
| GET | `/api/places/suggest` | `?q=` | `{"name":str,"country":str,"lat":number,"lon":number,"covered":bool}[]` (≤6) |
| POST | `/api/chat` | `ChatBody` (see Deviations) | `text/event-stream`: `token`, `sources`, `action`, `done`, `error` (addition) |

Errors: `{"detail": str}` with 4xx/5xx. Rate limit per IP (429 with `Retry-After`). CORS allows `WEB_ORIGIN`.

A2A Budget Analyst (separate ASGI app, port 9101 standalone or mounted at `/a2a/budget`):
`GET /.well-known/agent-card.json`, JSON-RPC `message/send` (a2a-sdk).

## SSE events (`GET /api/trips/{id}/stream`)

Each event is `event: <type>\ndata: <json>\n\n`. Every payload has `"ts"` (ISO time) and `"seq"` (int, increasing).

```ts
type AgentId = "guard"|"brief"|"destination"|"weather"|"stays"|"food"|"logistics"|"itinerary"|"budget"|"critic"|"finalize";
// event: agent
{ agent: AgentId; status: "started"|"done"|"error"|"skipped"; message: string; ms?: number }
// event: tool      (an MCP tool call made by an agent)
{ agent: AgentId; server: "weather"|"places"|"money"; tool: string; provenance: Provenance; summary: string; ms: number }
// event: retrieval (a RAG search)
{ agent: AgentId; query: string; hits: number; top_score: number; covered: boolean }
// event: a2a       (Budget Analyst handshake)
{ agent: "budget"; peer: "budget-analyst"; status: "card"|"sent"|"received"|"error"; summary: string }
// event: partial   (progressive results so the UI fills in while agents run)
{ section: "destination"|"weather"|"stays"|"food"|"logistics"|"itinerary"|"budget"|"quality"; payload: any }
// event: plan      → TripPlan (final, also on each refinement)
// event: error     → { message: string; recoverable: boolean }
// event: done      → { trip_id: string; revision: number; ms: number }
```

## Data shapes

```ts
type Provenance = "live" | "guidebook" | "estimate" | "cached" | "unavailable";
interface Money { amount: number; currency: string }           // ISO 4217, e.g. "INR"
interface GeoPoint { lat: number; lon: number }

interface TripRequest {
  origin?: string; destination: string;
  start_date: string; end_date: string;          // "YYYY-MM-DD", inclusive; max 14 days
  adults: number; children: number;             // adults ≥ 1
  budget: number; currency: string;             // total trip budget for the group
  interests: string[];                          // e.g. ["food","temples","nature","nightlife","art","shopping","history","adventure"]
  pace: "relaxed" | "balanced" | "packed";
  diet: string[];                               // e.g. ["vegetarian","halal","vegan","jain"]
  stay_style: "budget" | "mid" | "luxury";
  notes?: string; client_id?: string;
}

interface Citation { id: string; title: string; url: string; snippet: string; source: "wikivoyage"|"openstreetmap"|"open-meteo"|"frankfurter"|"budget-analyst" }

interface DailyWeather { date: string; t_min: number; t_max: number; precip_mm: number; precip_prob?: number;
  code: number /* WMO */; summary: string; provenance: Provenance }

interface Activity {
  id: string; slot: "morning"|"afternoon"|"evening"; time: string /* "09:30" */; duration_min: number;
  title: string; description: string; place?: string; location?: GeoPoint;
  category: "sight"|"food"|"activity"|"transit"|"shopping"|"nature"|"culture"|"nightlife";
  cost: Money; indoor: boolean; citations: string[]; tip?: string;
}
interface DayPlan { day: number; date: string; title: string; theme: string; weather?: DailyWeather;
  activities: Activity[]; day_cost: Money; walking_km?: number }

interface Stay { name: string; kind: "hotel"|"hostel"|"guest_house"|"apartment"|"resort"; area: string;
  location?: GeoPoint; price_per_night: Money; rating?: number; why: string; provenance: Provenance;
  url?: string; citations: string[] }

interface FoodPick { name: string; cuisine: string; area?: string; location?: GeoPoint; price_level: 1|2|3|4;
  must_try: string; diet_ok: string[]; provenance: Provenance; citations: string[] }

interface BudgetLine { category: "stay"|"food"|"activities"|"transport"|"travel"|"misc"; amount: Money; note: string }
interface Budget { total: Money; limit: Money; per_person: Money; lines: BudgetLine[]; within_budget: boolean;
  utilisation: number /* total/limit */; savings_tips: string[]; analyst: string /* "budget-analyst (A2A)" or "local fallback" */ }

interface PreTrip { getting_there: { mode: string; duration: string; cost: Money; note: string };
  getting_around: string; visa: string; currency_note: string; safety: string[]; packing: string[];
  local_tips: string[]; best_areas: string[]; citations: string[] }

interface QualityScore { name: string; value: number /*0-1*/; rating: "Good"|"OK"|"Weak"; explain: string }
interface Quality { confidence: number /*0-1*/; grounding_coverage: number /*0-1*/;
  guidebook: "covered"|"expanded"|"none";
  checks: { name: string; passed: boolean; detail: string }[];
  scores: QualityScore[]  /* names: "Faithfulness","Answer relevancy","Context precision","Citation coverage","Budget fit","Overall" */ }

interface TripPlan {
  trip_id: string; revision: number; request: TripRequest;
  title: string; summary: string;
  destination: { name: string; country: string; location: GeoPoint; image?: string; blurb: string };
  weather_overview: string;
  days: DayPlan[]; stays: Stay[]; food: FoodPick[]; budget: Budget; pre_trip: PreTrip;
  citations: Citation[]; quality: Quality;
  timings: { agent: AgentId; ms: number }[]; model: string; created_at: string;
}

interface Trip { id: string; status: "queued"|"running"|"done"|"error"; revision: number;
  request: TripRequest; plan?: TripPlan; error?: string; created_at: string; updated_at: string }
interface TripSummary { id: string; title: string; destination: string; start_date: string; end_date: string;
  status: Trip["status"]; image?: string; created_at: string }
```

Ratings: Good ≥ 0.70, OK ≥ 0.40, Weak < 0.40.
`destination.image`: a Wikipedia/Wikimedia thumbnail URL (REST `page/summary`), optional.

## Non-negotiables

- **No fabricated data shown as real.** Every stay/food/weather/cost carries `provenance`. Mock data is never labelled `live`.
- **Grounding:** itinerary activities cite guidebook passages (`citations` → `TripPlan.citations[].id`) or OSM/tool sources.
- **Graceful degradation:** a missing key or a failed tool becomes `unavailable` + a note, never a crash. Langfuse off → no-op.
- **Config through env** (`apps/api/.env`, `.env.example` tracked, `.env` never committed).
- **Offline tests:** `VOYAGER_OFFLINE=1` uses a deterministic fake LLM, no network; CI runs only offline tests.
- Numbers in the README are measured, not invented.

## Deviations (backend, documented)

Additive or clarifying only; every SPEC field name and shape is implemented as written.

- **`POST /api/trips/parse`** also accepts an optional `client_id` in the body (`{"text", "client_id"?}`) so
  the preference profile (diet, pace, style, interests, currency, origin) pre-fills fields the text didn't state.
- **A2A method name.** a2a-sdk 1.x speaks A2A 1.0, whose JSON-RPC method is `SendMessage` at `<base>/rpc`.
  The v0.3 name `message/send` is also accepted (compat mode enabled). Agent card:
  `<base>/.well-known/agent-card.json` (`/a2a/budget/...` when mounted). The orchestrator passes its Langfuse
  trace id in the message metadata so the remote agent's span joins the run's trace.
- **SSE.** Each event also carries an SSE `id:` equal to `seq`; `Last-Event-ID` resumes after that seq.
  Keep-alive comments every 15 s. A stream covers the trip's *current* revision (after a refine, subscribe again).
  `brief` may emit a second `agent`/`started` event ("not in the guidebook yet: fetching its Wikivoyage article").
- **`tool.provenance`** is `cached` when the call was answered from the tool TTL cache (the underlying data is
  still the live API's response).
- **`Stay.provenance`** describes the place itself: `live` = found on OpenStreetMap, `guidebook` = named in a cited
  Wikivoyage passage. `price_per_night` is always an estimate from the curated cost table (country tier x style x
  property type); the budget line notes say so. Places that are neither on OSM nor named in a cited passage are
  dropped, never shown.
- **Citation ids**: `wv-<10 hex>` (guidebook passage), `osm-<node|way|relation>-<id>`, `open-meteo`,
  `frankfurter`, `budget-analyst`.
- **`/health/ready.llm`** is true when a Groq key is configured (and not offline).
- **docker-compose**: `qdrant` is an optional profile; by default the API uses the embedded Qdrant index baked
  into its image. The `budget` service runs the A2A agent standalone and the API calls it over HTTP.
- **`POST /api/chat` (addition: the Voyager assistant).** Body
  `{"message": str (1-1000), "history": [{"role": "user"|"assistant", "content": str}], "trip_id"?: str, "client_id"?: str}`;
  only the last 10 history turns are used, each re-checked server-side (PII redacted, injection-looking turns
  dropped). Response is `text/event-stream`, events in order:
  `token {text}` (many; the reply streamed) → `sources {citations: Citation[], refs: {"<n>": citation_id}}`
  (only guidebook passages the answer actually cited as `[n]`) → `action {type: "refine"|"plan", message}` (optional)
  → `done {intent: "answer"|"refine"|"plan"|"off_topic"|"refused", model, grounded, ms}`; `error {message}` precedes
  `done` on a failure. Pipeline: input guardrails (injection → refusal, PII redaction, scope → polite refusal) →
  context = a compact digest of the trip's plan from the store (`trip_id` `demo` reads the bundled sample plan) +
  hybrid-RAG passages for the trip's destination or a city named in the message (numbered for citation) + a static
  note on how Voyager works → intent (plain questions skip the model; otherwise the small model via the gateway's
  `structured()`, rules as fallback) → answer streamed from `model_chain("small")` (moves past daily-exhausted
  models). `action: refine` is only an offer: the client calls `POST /api/trips/{id}/refine` when the user presses
  "Apply to my plan" (human in the loop). `action: plan` hands the text to the web app's parse → confirm flow.
  Offline (`VOYAGER_OFFLINE=1`), with no Groq key, or when every model fails before the first token, the reply is
  deterministic (plan facts + cited passages) and `done.model` is `offline` / `rules`. Counted as a write by the
  per-IP rate limiter. One Langfuse trace per message (`chat`, session = trip id or client id) with
  `chat.guard` / `chat.intent` / `rag.search` / `chat.answer` spans and a `Chat citations` score.
