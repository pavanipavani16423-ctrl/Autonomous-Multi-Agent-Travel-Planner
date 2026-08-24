# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A LangGraph multi-agent travel planner. A user submits a `TravelRequest` (origin,
destination, dates, budget, preferences); a fixed chain of specialist agents backed by
Groq-hosted Llama 3.3 70B produces a structured `TravelPlan` (route/itinerary, weather,
hotels, budget, food). Hybrid RAG (ChromaDB dense + BM25 sparse, merged by Reciprocal
Rank Fusion) supplies destination context; Pydantic schemas and guardrails validate every
hop; Langfuse traces the run; RAGAS optionally scores RAG quality.

Two entry points, both hitting the same pipeline:
- [app.py](app.py) — Streamlit UI (primary; heavy custom CSS, 6 result tabs)
- [main.py](main.py) — interactive CLI

## Commands

```bash
pip install -r requirements.txt      # pins are verified; see notes in the file
python -m rag.ingest                 # BUILD THE KNOWLEDGE BASE — do this first
streamlit run app.py                 # UI on :8501
python main.py                       # CLI
docker compose up --build            # containerised, :8501
```

Knowledge base (`rag/ingest.py`, Wikivoyage → chunks → Chroma + BM25):

```bash
python -m rag.ingest                     # default ~52 destinations
python -m rag.ingest --cities Osaka,Lima # add specific ones
python -m rag.ingest --list              # what is indexed, with chunk counts
python -m rag.ingest --check             # verify the grounding gate still separates
```

`--check` is the calibration harness for `rerank_min_score`. Run it after changing
the corpus, the rerank model, or the floor. It fails if an un-ingested destination
is reported as grounded.

Quality gate and memory (`eval/`, `memory/`):

```bash
python -m eval.harness               # 4-case gate; exit 1 on regression
python -m eval.harness --quick       # 1 case
python -m eval.harness --ragas       # + RAGAS faithfulness/relevancy (bypasses cache)
python -m eval.harness --compare     # metrics grouped by PROMPT_VERSION
python -m rag.ingest --backlog       # destinations asked for but not covered
```

There are no linters or CI; `eval/harness.py` is the release gate.

## Architecture

Request flow — `app.py`/`main.py` → `run_travel_pipeline()` → compiled `StateGraph`:

```
validate_input ──(fail)──> error ──> END
      │(pass)
   retrieval → tools → weather → route → hotels → budget → food
                                                            │
                              validate_outputs → final_planner → END
```

State is a plain `dict` (not a TypedDict) carrying `request`, `rag_contexts`,
`tool_data`, the five agent outputs, `final_plan`, `errors`, `warnings`. Every node
mutates and returns the whole dict. Checkpointing is `MemorySaver` (in-RAM), keyed by
`thread_id = trip_{destination}_{departure_date}`.

Module map — all live code is in the *package* directories:

| Path | Role |
|---|---|
| [config.py](config.py) | The only live config. Dataclass singletons: `llm_config`, `rag_config`, `api_config`, `guardrail_config`, `app_config`. |
| [models/models.py](models/models.py) | `get_llm()` ChatGroq factory plus every Pydantic output schema (`TravelRequest`, `TravelPlan`, `RouteOutput`, …). |
| [agents/agents.py](agents/agents.py) | `BaseAgent` plus 9 agents. Each specialist is an LCEL chain of prompt → llm → `StrOutputParser()`. |
| [graph/graph.py](graph/graph.py) | Node functions, conditional router, graph builder, `run_travel_pipeline()`. |
| [prompts/prompts.py](prompts/prompts.py) | All `ChatPromptTemplate`s with few-shot examples, one per agent. |
| [parsers/parser.py](parsers/parser.py) | JSON repair (strip fences, drop trailing commas, extract first `{...}`) then Pydantic validation; returns `None` on failure. |
| [guardrails/guardrails.py](guardrails/guardrails.py) | `GuardrailResult` plus input validation and per-output checks. |
| [tools/tools.py](tools/tools.py) | 5 `BaseTool`s (weather, maps, hotel, restaurant, flight) behind the `MCPToolRegistry` singleton `tool_registry`. |
| [rag/rag.py](rag/rag.py) | Chunking, Chroma store, BM25, RRF, **cross-encoder rerank + destination filter**, `HybridRetriever` / `get_retriever()`. |
| [rag/ingest.py](rag/ingest.py) | Wikivoyage ingestion CLI. Fetches articles, maps sections → `general`/`hotel`/`food`, tags every chunk with its destination, writes `data/corpus.jsonl` and rebuilds Chroma. |
| [langfuse_setup.py](langfuse_setup.py) | Langfuse **v2** tracing (`get_tracer()`, `.langchain_config()`, `.span()`, `.score_quality()`) plus a bolted-on RAGAS helper. |

Agent roster in [agents/agents.py](agents/agents.py): `RetrievalAgent` (3 RAG queries →
general/hotel/food context), `ToolAgent` (bundles all 5 API calls), then `WeatherAgent`
→ `RouteAgent` (weather-aware) → `HotelAgent` → `BudgetAgent` (consumes route+hotel
JSON) → `FoodAgent`, and finally `FinalPlannerAgent`, which synthesises the summary and
assembles the `TravelPlan` in Python from the request and the five sub-plans.

`SupervisorAgent` has a `run_full_pipeline()` that duplicates the whole sequence in
plain Python — **the graph never calls it**. It is an alternative orchestration path,
not the live one. Don't edit it expecting the app to change.

## Conventions

- **Adding an agent** means touching five files in step: schema in
  [models/models.py](models/models.py), prompt in [prompts/prompts.py](prompts/prompts.py),
  `parse_*` and `get_*_format_instructions` in [parsers/parser.py](parsers/parser.py),
  the agent class in [agents/agents.py](agents/agents.py), and a node plus edges in
  [graph/graph.py](graph/graph.py). Skipping the parser is the usual mistake.
- Format instructions are appended to the RAG context string, not to the system message
  — see how `WeatherAgent.run` builds `enriched_context`.
- Agents never raise. `BaseAgent._invoke_llm` swallows exceptions and returns an error
  JSON; parsers return `None`; nodes write `None` into state. Failures surface as a
  missing section in the final plan plus guardrail warnings, not a stack trace.
- Guardrails distinguish `fail()` (blocking, only enforced on *input*) from `warn()`
  (advisory). Output guardrail errors are downgraded to warnings in
  `validate_outputs_node` — the pipeline deliberately never aborts after the LLM work.
- Every module inside a package reaches root config via
  `sys.path.insert(0, dirname(dirname(__file__)))` then `from config import …`. Keep
  that preamble when adding files there.
- Logging is `loguru`, tagged `[AgentName]` / `[Graph:node]` / `[RAG]` / `[Guardrail]`.
- **Grounding.** `HybridRetriever.retrieve(query, destination=...)` runs RRF → cross
  encoder rerank → relevance floor, and drops chunks tagged with a *different*
  destination before scoring. It returns a `RetrievalResult` whose `.grounded` is True
  only when destination-specific knowledge survived; otherwise the context is
  `NO_CONTEXT_NOTICE`, which tells the model to use its own knowledge rather than
  another city's facts. New corpus documents MUST carry a `destination` metadata key
  (or `GENERAL_KNOWLEDGE` for advice that applies anywhere) or they will never be
  filtered correctly. `rerank_min_score` (-8.0) is calibrated against this corpus —
  measure before changing it; there is a harness pattern in the git history.
- **Tracing.** `BaseAgent._invoke_llm` attaches the Langfuse callback handler via
  `get_tracer().langchain_config(run_name=...)`; without it no LLM call is traced at
  all. Graph nodes are wrapped by `@traced_node(...)` in [graph/graph.py](graph/graph.py).
  A verified run produces ~34 observations (6 generations with token counts, 28 spans)
  plus `live_data_ratio` / `grounding_ratio` / `guardrail_warnings` / `latency_seconds`
  scores. Keep new chains going through `_invoke_llm` or they will be invisible.
- **Tool provenance.** Every tool payload carries `_source` (`live` / `curated` / `mock`)
  from [tools/tools.py](tools/tools.py). `ToolAgent.run` collects these into
  `tool_data["data_sources"]`, the graph forwards them to the output guardrails and the
  final planner, and they land on `TravelPlan.data_sources` (plus the `mocked_sources` /
  `is_fully_live` helpers). Any new tool MUST stamp its payload — `source_of()` fails
  closed to `mock`, so an unstamped tool is reported as fabricated.
- **The final planner does not author the whole plan.** The LLM returns only
  `PlanSynthesis` (summary, confidence, consistency warnings); the `TravelPlan` is always
  assembled in Python. Asking for the full nested schema made every run fail to parse and
  silently fall back to a canned summary. Keep that split.
- Config is read once at import as module-level singletons, so changing `.env` requires
  a process restart.
- **Embeddings run on ONNX, not PyTorch.** `get_embeddings()` in
  [rag/rag.py](rag/rag.py) uses chromadb's bundled ONNX build of
  all-MiniLM-L6-v2. Same model, same 384-dim L2-normalised vectors, but no
  torch: whole-app resident set is 455 MB instead of 1,025 MB, which is what
  makes the 1 GB free tiers viable. sentence-transformers is a *fallback* and
  is not in requirements. **An index built by one embedder must be queried by
  the same one** — switching means re-ingesting.
- **The reranker is optional; the destination filter is not.** With
  `RERANK_ENABLED=false` the cross-encoder is skipped and out-of-corpus
  destinations are *still* gated, because `filter_by_destination` runs first
  and independently (verified 18/18 gated). You lose ordering quality within
  a destination, not the grounding guarantee.
- **Watch the per-request token ceiling.** Groq's free tier allows 8,000 tokens per
  minute and counts reserved `max_tokens` toward a *single* request. A prompt that
  serialises whole Pydantic objects blows through it and returns HTTP 413 — which no
  retry can fix. `FinalPlannerAgent` therefore feeds the model `_digest_*()` summaries
  and reserves only 1,200 output tokens. Keep prompts fed with facts, not schemas.
- **Bump `PROMPT_VERSION`** in [prompts/prompts.py](prompts/prompts.py) whenever you
  change what the model sees. Stored run metrics are grouped by it, which is what makes
  `--compare` meaningful.

## Things that will bite you

- **Duplicated modules.** `graph.py`, `guardrails.py`, and `prompts.py` sit at the repo
  root *and* inside their packages. Python resolves the package directory first, so the
  root-level copies are dead. Root `parser.py` is dead too (code imports
  `parsers.parser`). Likewise every `<pkg>/config.py` is a byte-identical copy of root
  [config.py](config.py) that nothing imports. **Edit the package copy** — a change to
  root `graph.py` has no effect. Root `graph.py` even has Langfuse tracing imported that
  the live [graph/graph.py](graph/graph.py) lacks.
- **[langfuse_config.py](langfuse_config.py) is dead** — an abandoned Langfuse v3 port
  whose import line (`from langfuse_config import Langfuse, get_client`) imports itself
  and always fails. Nothing references it. The live file is
  [langfuse_setup.py](langfuse_setup.py).
- **requirements.txt is stale.** It pins `langfuse>=3.0.0`, but
  [langfuse_setup.py](langfuse_setup.py) uses the v2 API
  (`langfuse.callback.CallbackHandler`, `client.trace()`) that v3 removed — installing
  from requirements silently disables all tracing, since the ImportError is caught and
  only printed. The working local env is langfuse 2.60.10, langchain 0.3.25, langgraph
  0.2.76, chromadb 0.5.3 — none matching the pins. `ragas` and `datasets`, needed by the
  RAG Eval tab and [evaluation.py](evaluation.py), are absent from requirements
  entirely. Prefer the installed versions over the pinned ones when reasoning about
  behaviour. `loguru`, `langchain-chroma` and `pypdf` were missing from the local
  interpreter entirely and had to be installed by hand before anything would import.
- **[evaluation.py](evaluation.py) is orphaned.** A full `EvaluationService` for RAGAS
  0.4.x that nothing imports; the Streamlit RAG Eval tab re-implements evaluation inline
  against a hardcoded 5-question set and falls back to canned demo scores on any
  exception.
- **[langfuse_setup.py](langfuse_setup.py) is two files concatenated** — the tracer,
  then a `ragas_eval.py` section (from ~line 222) that re-imports its own module.
  `evaluate_travel_plan_rag()` there references `route.summary` and
  `food.must_try_dishes`, which are not fields on `RouteOutput`/`FoodOutput`.
- **Tools degrade to mocks, not errors.** Missing API keys, or any request failure, make
  every tool return `_mock_response()` fixtures. Since the provenance work (below) this
  is now *visible* rather than silent, but it is still the default: with `demo` keys in
  `.env` all five tools return fixtures, so weather/prices/flights in the plan are
  placeholders. Real data needs real keys.
- **The corpus is generated, not committed.** `data/corpus.jsonl` and `chroma_db/` are
  both gitignored build artefacts — a fresh clone has neither, and
  `HybridRetriever._load_documents` falls back to 12 synthetic chunks until you run
  `python -m rag.ingest`. If grounding looks broken, check that first.
  `chroma_db/` is still tracked from the initial commit; untrack it with
  `git rm -r --cached chroma_db` on the next commit.
- **Corpus and index must come from the same source.** BM25 is built in-process from
  `self.documents` while Chroma reads its own on-disk index. Both now load
  `data/corpus.jsonl`; if you add another document source, feed it to both or the
  hybrid will fuse two rankings computed over different corpora.
- **Wikivoyage full-text extracts are one article per request.** `exlimit` is only
  honoured alongside `exintro`, so batching titles returns one populated extract and
  silently blanks the rest. `fetch_articles` therefore loops, and stays within rate
  limits via `Retry-After` backoff and `maxlag` rather than by batching.
- **Chroma rejects inserts above ~5.4k records** (a SQLite variable limit), so
  `build_vector_store` adds documents in batches of 2000. A real corpus is well past
  that ceiling.
- **The committed `chroma_db/` was unreadable by the installed chromadb 0.5.3** (written
  by a newer version; `max_seq_id.seq_id` is INTEGER where 0.5.3 expects a BLOB, so every
  query raised `TypeError: object of type 'int' has no len()`). Because `retrieve()`
  catches that, dense search silently returned nothing and "hybrid" RAG was BM25-only.
  `build_vector_store` now probes compatibility with plain sqlite3 *before* opening a
  Chroma client and rebuilds the store when it cannot be read. Do not "fix" that probe
  by catching the exception instead — chromadb caches its client per path and holds the
  sqlite file open, which leaves the directory only half-deletable.
- Each graph node constructs a fresh agent, so one run creates ~7 `ChatGroq` clients.
  The RAG retriever and tool registry are singletons, so only the first construction is
  expensive.
- The Streamlit progress bar is a `threading.Thread` on a fixed timer, unrelated to real
  agent progress.
- Streamlit selectboxes default to placeholder strings ("Select Purpose",
  "Select Dietary Preference", "Select Accommodation") that pass through into
  `TravelRequest` verbatim if the user does not change them.

## Environment

Only `GROQ_API_KEY` is required; everything else has a default or degrades to mocks.
Put these in `.env` (gitignored, not committed).

```
GROQ_API_KEY=              # required
LLM_MODEL=llama-3.3-70b-versatile
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=4096
OPENWEATHER_API_KEY=       # omit -> mock weather
GOOGLE_MAPS_API_KEY=       # omit -> mock distances
AMADEUS_API_KEY=           # omit -> mock flights/hotels
AMADEUS_API_SECRET=
LANGFUSE_PUBLIC_KEY=       # omit -> tracing off
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
CHROMA_PERSIST_DIR=./chroma_db
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RAG_TOP_K=5
RAG_SCORE_THRESHOLD=0.3
MAX_BUDGET_USD=100000
MIN_TRIP_DAYS=1
MAX_TRIP_DAYS=90
```
