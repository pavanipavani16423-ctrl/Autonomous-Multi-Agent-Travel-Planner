# Voyager evaluation results

Generated 2026-11-24T02:45:14+00:00 by `python -m voyager.eval.run` against the real stack: Groq (gpt-oss-120b itinerary + critic, gpt-oss-20b specialists), live MCP tools (Open-Meteo, OpenStreetMap via Overpass/Photon, Frankfurter), embedded Qdrant hybrid RAG, and the A2A Budget Analyst (A2A HTTP protocol served in-process via ASGI). All numbers below are measured; nothing is hand-entered.

**Golden set:** 10 trips (10 produced a plan): 8 guidebook-covered cities, 1 uncovered city (Ljubljana: on-demand Wikivoyage expansion), 1 prompt-injection + PII attempt.

## Ragas (LLM-judged, reference-free unless noted)

Judge: qwen/qwen3.8-27b, openai/gpt-oss-20b - 103 calls, 172464 tokens, 43 failed attempts

| Metric | Mean | Trips scored |
|---|---|---|
| Faithfulness | 0.26 | 10 |
| Answer Relevancy | 0.64 | 10 |
| Context Precision | 0.45 | 10 |
| Context Recall | 0.00 | 3 |

Response = the plan's factual content (place + what the plan says about it; day/time scheduling is a recommendation, not a checkable claim). Contexts = the guidebook passages the plan cites (<= 5, 900 chars) + one block of the OpenStreetMap listings it cites. Context precision = Ragas *ContextUtilization* (no reference needed). Context recall only for trips with a short hand-written reference (Kyoto, Paris, Bangkok).

## Online quality scores (computed on every run, mean)

| Score | Mean |
|---|---|
| Faithfulness | 0.76 |
| Answer relevancy | 0.85 |
| Context precision | 0.60 |
| Citation coverage | 0.96 |
| Budget fit | 0.87 |
| Overall | 0.81 |

## Deterministic checks (pass rate)

| Check | Pass rate |
|---|---|
| a2a_round_trip | 0% |
| budget_fit_10pct | 80% |
| citation_coverage_60pct | 100% |
| dates | 100% |
| day_count | 100% |
| geo_within_60km | 100% |
| guidebook_status | 90% |
| injection_neutralised | 100% |
| no_wrong_city | 100% |
| pii_redacted | 100% |
| plan_produced | 100% |

## Retrieval (20 labelled queries; relevant = right city AND expected section)

| Pipeline | Hit@5 | MRR@10 | Precision@5 | Wrong city@5 | Avg ms |
|---|---|---|---|---|---|
| dense | 1.00 | 0.97 | 0.86 | 0.00 | 390.4 |
| sparse | 1.00 | 0.85 | 0.62 | 0.00 | 682.1 |
| hybrid | 1.00 | 0.97 | 0.76 | 0.00 | 985.7 |
| hybrid_rerank | 1.00 | 1.00 | 0.80 | 0.00 | 3325.9 |
| hybrid_rerank_nofilter | 1.00 | 1.00 | 0.76 | 0.02 | 1813.4 |

`hybrid_rerank` is the production path (destination pre-filter -> dense + BM25 prefetch -> RRF -> MiniLM cross-encoder). `hybrid_rerank_nofilter` drops the payload filter to show what it prevents.

## Latency

End-to-end per trip: p50 60151 ms, mean 58524 ms, max 116295 ms. Mean LLM tokens per trip: 11500. Critic-requested revisions: 0. LLM fallbacks: 0.

| Agent | Mean ms |
|---|---|
| stays | 44607 |
| food | 38328 |
| logistics | 35027 |
| destination | 34907 |
| itinerary | 5109 |
| critic | 2220 |
| weather | 326 |
| brief | 170 |
| budget | 6 |
| finalize | 1 |
| guard | 0 |

Specialists (destination, weather, stays, food, logistics) run in parallel, so the wall clock is roughly guard + brief + max(specialists) + itinerary + budget + critic + finalize.

## Per trip

| Trip | ms | Guidebook | Confidence | Faithfulness | Relevancy | Ctx precision | Checks passed | LLM calls | Fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| kyoto-temples | 29280 | covered | 0.84 | 0.25 | 0.70 | 0.17 | 7/9 | 6 | 0 |
| paris-art | 63530 | covered | 0.84 | 0.08 | 0.65 | 0.17 | 8/9 | 6 | 0 |
| bangkok-food | 60566 | covered | 0.85 | 0.47 | 0.63 | 0.72 | 8/9 | 6 | 0 |
| jaipur-history | 60200 | covered | 0.55 | 0.12 | 0.65 | 0.33 | 7/9 | 6 | 0 |
| lisbon-relaxed | 53998 | covered | 0.92 | 0.10 | 0.64 | 0.27 | 8/9 | 6 | 0 |
| istanbul | 60151 | covered | 0.79 | 0.00 | 0.63 | 0.67 | 8/9 | 6 | 0 |
| singapore-family | 56027 | covered | 0.85 | 0.38 | 0.52 | 0.17 | 8/9 | 6 | 0 |
| rome-luxury | 29408 | covered | 0.77 | 0.50 | 0.58 | 0.67 | 8/9 | 6 | 0 |
| ljubljana-expansion | 116295 | covered | 0.88 | 0.62 | 0.71 | 0.92 | 7/9 | 6 | 0 |
| barcelona-injection | 55793 | covered | 0.85 | 0.09 | 0.66 | 0.42 | 10/11 | 6 | 0 |

Raw numbers: `docs/eval-results.json`. Per-trip plans and Ragas scores: `data/eval/` (not committed).

## Notes on this run (read before quoting numbers)

- **`a2a_round_trip 0%` is a harness bug, not an A2A failure.** In this run the harness mounted the in-process
  Budget Analyst without the `/a2a/budget` path prefix, so every trip got a 404 for the agent card and the
  `budget` node used its labelled `local fallback` (same costing code; budget mean 6 ms). Fixed afterwards in
  `voyager/eval/run.py` and verified (card -> sent -> received). The real A2A path over HTTP was exercised in all
  live API runs (see `apps/api/README.md`).
- **`guidebook_status 90%`**: Ljubljana was expanded on demand (Wikivoyage fetch -> chunk -> embed -> upsert) during
  an earlier pass of this harness the same evening, so in this run it was already `covered`. On-demand
  expansion was also verified live through the API for Hampi (59 passages) and Hoi An (72 passages).
- **Ragas faithfulness is low (0.26) while the online judge says 0.76.** Ragas judges every statement in the
  activity descriptions against only the cited evidence (<= 5 guidebook passages + OSM listings that say
  little beyond "museum at lat/lon"). The descriptions still carry the model's general knowledge about famous
  places, which Ragas counts as unsupported. A prompt rule restricting descriptions to evidenced facts (added
  before this run) raised Kyoto from 0.00 to 0.25; closing the rest of the gap needs richer per-place evidence
  (e.g. passage text per POI), which is the next improvement. Context recall 0.00: the hand-written references
  name highlights (e.g. Kinkaku-ji) that the plans' cited passages did not contain.
- **Judge**: 43 of 146 judge attempts failed (rate limits / malformed JSON) and were retried on the other model.
- **Latency here is higher than a single live run** (p50 60 s vs 33 s for Kyoto via the API) because the 10
  trips ran back to back under Groq's 8K tokens/min per model, and because OpenStreetMap search was degraded
  (Overpass at capacity, Photon unreachable from this network), so place search fell through to Nominatim
  (1 request/s): that is the `stays`/`food`/`destination` time.
- **Retrieval**: Hit@5 is 1.00 for every stage on this small labelled set; MRR rises from 0.85 (BM25 only) to
  1.00 with hybrid + rerank. Latencies are CPU times on this laptop with the embedded Qdrant (local mode is a
  brute-force Python implementation; a Qdrant server would be much faster).
