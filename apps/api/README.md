# Voyager API (apps/api)

FastAPI + LangGraph backend of Voyager v2. Contract: [`docs/SPEC.md`](../../docs/SPEC.md) (endpoints, SSE events,
every JSON field). Python package `voyager`, Python 3.11, managed with `uv`.

```
guard → brief → [destination ‖ weather ‖ stays ‖ food ‖ logistics] → itinerary → budget (A2A) → critic ─┬→ finalize
                 (on-demand guidebook expansion)                         ↑                              │
                                                                         └──── fail, ≤ 1 retry ─────────┘
refine: checkpoint → itinerary → budget → critic → finalize   (revision + 1)
```

## Run

```bash
cd apps/api
cp .env.example .env                      # add GROQ_API_KEY (+ Langfuse keys if you have them)
uv sync --extra eval                      # or: python -m venv .venv && pip install -e ".[eval]" pytest ruff
uv run python -m voyager.rag.ingest --warm   # download models + index data/corpus.jsonl (idempotent, resumable)
uv run uvicorn voyager.main:app --port 8000
```

Other entry points:

| command | what |
|---|---|
| `python -m voyager.a2a.budget_server --port 9101` | the A2A Budget Analyst as its own service (`A2A_BUDGET_URL=http://localhost:9101`) |
| `python -m voyager.mcp.servers.{weather,places,money} [--transport stdio\|streamable-http --port N]` | each MCP server standalone |
| `python -m voyager.rag.ingest --expand "Ljubljana"` | fetch + index one more Wikivoyage city now |
| `python -m voyager.rag.ingest --copy-to http://qdrant:6333` | move the embedded index to a Qdrant server without re-embedding |
| `python -m voyager.eval.run [--only id,..] [--fresh] [--skip-ragas]` | offline evaluation → `docs/eval-results.md` |
| `VOYAGER_OFFLINE=1 pytest` | the offline test suite (fake LLM, mocked tools, in-memory Qdrant) |
| `docker build -f apps/api/Dockerfile .` (repo root) | image with models + index baked in |

## Layout

```
voyager/
  config.py            env-driven settings (pydantic-settings), graceful degradation
  schemas.py           Pydantic v2 mirror of the SPEC TypeScript types
  main.py              app factory, lifespan (DB → MCP hub → guidebook → graph + AsyncSqliteSaver), /health
  api/                 routes (SPEC endpoints, SSE), per-IP rate limiter
  graph/               LangGraph: state, workflow, run context, nodes/{intake,research,itinerary,review}.py
  llm/gateway.py       structured output (JSON mode → json-repair → validate → 1 repair turn → rules fallback),
                       client-side token bucket per model (Groq free tier 8K TPM), spill-to-small-model
  mcp/                 3 MCP servers (weather, places, money), shared HTTP fetcher with SQLite TTL cache,
                       hub with per-agent tool allow-lists, curated cost table
  a2a/                 Budget Analyst agent (a2a-sdk server + card), A2A client, standalone server
  rag/                 Qdrant guidebook (dense + sparse named vectors, RRF, rerank, grounding gate), ingest,
                       Wikivoyage on-demand expansion, fastembed models
  guardrails/          prompt injection, PII redaction, scope, date/budget sanity
  memory/              trips / events / preference profiles / plan cache (SQLAlchemy async)
  services/            run manager (background runs, Langfuse trace per run, cache), SSE event bus, parse, images
  observability/       Langfuse v5 tracing + scores (PII-masked)
  eval/                online quality scores, golden set, retrieval eval, Ragas adapters, harness
tests/                 74 offline tests (~15 s)
```

## How the pieces talk

* **MCP** – three `MCPServer` (FastMCP) servers, each runnable over stdio or streamable HTTP. The API holds one
  long-lived MCP client session per server; by default the transport is the SDK's in-memory transport (the
  full JSON-RPC protocol: initialize → tools/list → tools/call, without three extra Python processes on a
  512 MB box). `MCP_TRANSPORT=stdio` spawns them as subprocesses instead. Agents get a `Toolbox` restricted by
  `AGENT_TOOLS` (e.g. `food` may only call `places.search_places`). Every call emits a `tool` SSE event and a
  Langfuse tool span. Failures never raise: the result is `provenance: "unavailable"` + a note.
* **OpenStreetMap** – `search_places` uses a provider chain with circuit breakers and one 30 s deadline:
  Overpass (3 mirrors raced) → Photon → Nominatim (≤ 1 request/s). All three are OSM data; the tool note says
  which answered. (During development Overpass was at capacity and Photon unreachable from this network, so
  most live runs were served by Nominatim/Photon-cache; that is why OSM search dominates specialist latency.)
* **A2A** – the `budget` node fetches the Budget Analyst's Agent Card, sends `SendMessage` (JSON-RPC, a2a-sdk)
  with a data part `{"skill":"trip-costing","input":…}` and the Langfuse trace id in the message metadata,
  and reads back an itemised `Budget`. The agent itself calls the money MCP server. If the agent is
  unreachable the same costing runs locally and is labelled `analyst: "local fallback"`.
* **RAG** – Qdrant collection `guidebook` with named vectors `dense` (bge-small, cosine) and `sparse` (BM25,
  IDF modifier); one Query API call: payload pre-filter on `destination` → prefetch dense 30 + sparse 30 →
  RRF fusion → MiniLM cross-encoder rerank → grounding gate. Passages that read like instructions are
  quarantined (indirect injection). Citation ids (`wv-…`) are stable hashes of the passage text.

## Measured (this machine: Windows 11, 8 cores; Groq free tier; numbers from real runs)

Real end-to-end runs through `POST /api/trips` + the SSE stream (A2A over real HTTP to the mounted agent,
live MCP tools, Langfuse on):

| run | wall clock | notes |
|---|---|---|
| Kyoto, 4 days (covered city) | **32.7 s** | 6 LLM calls, 12.3K tokens; confidence 0.89, 31 citations, 14/14 activities cited and mapped |
| Kyoto, identical request again | **0.7 s** | plan cache hit, live data relabelled `cached` |
| Kyoto refine ("slower day 2, kaiseki dinner") | 54.3 s | only itinerary → budget → critic → finalize; 41.7 s of it was waiting for Groq's 8K tokens/min window because it ran right after the full plan |
| Hoi An, 3 days (uncovered city) | **57.6 s** | brief fetched + indexed 72 Wikivoyage passages on demand (11.3 s); OSM providers degraded (Overpass 502, Photon down) |

Per-agent wall time, Kyoto 4 days (ms): guard 0 · brief 119 · destination 9,852 · weather 821 · stays 21,995 ·
food 15,356 · logistics 9,061 (the five run in parallel; OSM search is the long pole) · itinerary 4,828 ·
budget (A2A round trip) 331 · critic 1,853 · finalize 16. LLM calls themselves take 0.5–6.7 s each.

Memory (peak working set of the uvicorn process during runs, Windows): **~700–750 MB** with the embedded
Qdrant index. Breakdown measured by loading components one at a time: Python + imports 181 MB, embedded
Qdrant with 9,026 points 214 MB, bge-small 120 MB, MiniLM reranker 95 MB (after disabling the ONNX arena and
truncating rerank inputs; it was 167 MB). So **the embedded mode does not fit a 512 MB instance**; with
`QDRANT_URL` (Qdrant server/Cloud) the in-process index goes away (≈ 490 MB, derived from the breakdown, not
measured end-to-end because no Qdrant server was available here) and `VOYAGER_RERANK=false` saves ~95 MB more.

Indexing the 9,026-passage corpus: ~18 min on this laptop's CPU (bge-small ONNX, ~8 passages/s with all cores);
it is done at image build time and is resumable.

See [`docs/eval-results.md`](../../docs/eval-results.md) for Ragas, retrieval and golden-set numbers.

## Environment variables

See [`.env.example`](.env.example). Required: `GROQ_API_KEY`. Optional: `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `QDRANT_URL`, `QDRANT_API_KEY`, `DATABASE_URL`, `A2A_BUDGET_URL`,
`PUBLIC_BASE_URL`, `WEB_ORIGIN`, `PORT`, `VOYAGER_MODEL_LARGE`, `VOYAGER_MODEL_SMALL`, `RAGAS_JUDGE_MODEL`,
`VOYAGER_USER_AGENT`, `VOYAGER_EMBED_THREADS`, `VOYAGER_RERANK`, `VOYAGER_INGEST_ON_BOOT`,
`VOYAGER_PLAN_CACHE_TTL`, `RATE_LIMIT_WRITE_PER_MIN`, `RATE_LIMIT_READ_PER_MIN`, `MCP_TRANSPORT`,
`VOYAGER_OFFLINE` (tests).
