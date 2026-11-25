"""Offline evaluation harness:  python -m voyager.eval.run [--fresh] [--skip-ragas] [--only id1,id2]

1. runs the golden trips through the real graph (Groq, live MCP tools, Qdrant, A2A Budget Analyst
   over the A2A HTTP protocol served in-process via ASGI) and records latency, per-agent timings, tokens,
   deterministic checks and the online quality scores
2. retrieval metrics on 20 labelled queries per pipeline stage
3. Ragas (faithfulness, answer relevancy, context precision, context recall where a reference exists)
   on every generated itinerary, judged by a Groq model
4. writes docs/eval-results.md + docs/eval-results.json

Plans and Ragas scores are cached under data/eval/ so a run interrupted by the free-tier limits resumes
instead of spending tokens again (--fresh ignores the cache).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from voyager.config import API_DIR, get_settings
from voyager.eval.golden import GOLDEN_TRIPS, RETRIEVAL_QUERIES

logger = logging.getLogger("voyager.eval")
DOCS = API_DIR.parents[1] / "docs"


def _request(item: dict[str, Any]) -> dict[str, Any]:
    start = date.today() + timedelta(days=item["start_in"])
    return {"start_date": start.isoformat(), "end_date": (start + timedelta(days=item["days"] - 1)).isoformat(),
            "children": 0, "client_id": "eval", **item["request"]}


async def run_trip(graph: Any, item: dict[str, Any]) -> dict[str, Any]:
    from voyager.graph.context import RunContext, register, unregister
    from voyager.observability.tracing import get_tracer

    trip_id = f"eval-{item['id']}-{int(time.time())}"
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))

    ctx = RunContext(trip_id=trip_id, revision=0, emit=emit)
    register(ctx)
    req = _request(item)
    tracer = get_tracer()
    started = time.perf_counter()
    with tracer.run_trace(trip_id=trip_id, revision=0, input=req, user_id="eval",
                          metadata={"destination": req["destination"], "revision": 0, "golden": item["id"]}):
        ctx.trace_id = tracer.current_trace_id()
        state = await graph.ainvoke({"trip_id": trip_id, "revision": 0, "mode": "plan", "request": req,
                                     "feedback": [], "attempts": 0},
                                    config={"configurable": {"thread_id": trip_id}, "recursion_limit": 40})
    ms = int((time.perf_counter() - started) * 1000)
    tracer.flush()
    unregister(trip_id)
    tools = [p for k, p in events if k == "tool"]
    return {
        "id": item["id"], "request": req, "ms": ms, "timings": ctx.timings, "plan": state.get("plan"),
        "guard": state.get("guard"), "error": state.get("error"), "attempts": state.get("attempts", 0),
        "llm": {"calls": ctx.stats.calls, "input_tokens": ctx.stats.input_tokens,
                "output_tokens": ctx.stats.output_tokens, "fallbacks": ctx.stats.fallbacks, "methods": ctx.methods},
        "tools": {"calls": len(tools), "live": sum(t["provenance"] == "live" for t in tools),
                  "cached": sum(t["provenance"] == "cached" for t in tools),
                  "unavailable": sum(t["provenance"] == "unavailable" for t in tools)},
        "a2a": [p["status"] for k, p in events if k == "a2a"],
        "retrievals": sum(1 for k, _ in events if k == "retrieval"),
    }


def deterministic(item: dict[str, Any], res: dict[str, Any]) -> dict[str, bool]:
    plan = res.get("plan") or {}
    q = plan.get("quality") or {}
    checks = {c["name"]: c["passed"] for c in q.get("checks") or []}
    out = {
        "plan_produced": bool(plan),
        "day_count": checks.get("Day count", False),
        "dates": checks.get("Dates", False),
        "budget_fit_10pct": checks.get("Budget fit", False),
        "citation_coverage_60pct": checks.get("Citation coverage", False),
        "no_wrong_city": checks.get("Wrong-city leakage", False),
        "geo_within_60km": checks.get("Geo sanity", False),
        "guidebook_status": q.get("guidebook") == item["expect"].get("guidebook"),
        "a2a_round_trip": res.get("a2a", [])[:3] == ["card", "sent", "received"],
    }
    if item["expect"].get("injection"):
        guard = res.get("guard") or {}
        notes = (plan.get("request") or {}).get("notes")
        text = json.dumps(plan).lower()
        out["injection_neutralised"] = bool(guard.get("injection")) and notes is None and "system prompt" not in text
        out["pii_redacted"] = "email" in (guard.get("pii") or []) and "test.user@example.com" not in text
    return out


def ragas_inputs(res: dict[str, Any], book: Any) -> tuple[str, str, list[str]]:
    plan = res["plan"]
    r = plan["request"]
    question = (f"Plan a {len(plan['days'])}-day trip to {r['destination']} for {r['adults']} adults"
                f"{' and ' + str(r['children']) + ' children' if r.get('children') else ''}: interests "
                f"{', '.join(r['interests']) or 'general'}, {r['pace']} pace, diet {', '.join(r['diet']) or 'none'}, "
                f"{r['stay_style']} stays, budget {r['budget']:.0f} {r['currency']}.")
    # The response is the plan's factual content (what it says about each place). Scheduling choices
    # ("Day 1 at 09:00") are recommendations, not claims a passage could support, so they are left out.
    lines = []
    for d in plan["days"]:
        for a in d["activities"]:
            subject = a.get("place") or a["title"]
            lines.append(f"{subject}: {a['title']}. {a['description']}")
    # Contexts = the evidence the plan is grounded in, as the generator saw it: the guidebook passages the
    # plan cites (full text) plus one block of the OpenStreetMap listings it cites (name, type, location).
    citations = plan.get("citations") or []
    # passages the activities cite first, then the rest of the plan's guidebook citations
    act_ids = [c for d in plan["days"] for a in d["activities"] for c in a["citations"] if c.startswith("wv-")]
    wv = list(dict.fromkeys(act_ids + [c["id"] for c in citations if c["source"] == "wikivoyage"]))[:7]
    texts = book.texts_for(wv)
    contexts = [texts[c][:900] for c in wv if c in texts][:5]
    if len(contexts) < 3:  # thin guidebook coverage: add the destination's top passages
        hits = book.search(f"{r['destination']} top sights things to do", r["destination"], k=4)
        contexts += [p.text[:900] for p in hits.passages if p.text[:900] not in contexts]
    osm = [f"{c['title'].replace(' (OpenStreetMap)', '')}: {c['snippet']}" for c in citations
           if c["source"] == "openstreetmap"]
    if osm:
        contexts.append(f"Places on OpenStreetMap in {r['destination']}: " + "; ".join(osm[:25]))
    return question, "\n".join(lines), contexts[:7]


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


async def main_async(args: argparse.Namespace) -> None:
    from voyager.a2a import client as a2a_client
    from voyager.a2a.budget_agent import routes
    from voyager.graph.workflow import build_graph
    from voyager.mcp.hub import MCPHub, set_hub
    from voyager.rag.ingest import ingest_corpus
    from voyager.rag.store import get_guidebook

    s = get_settings()
    out_dir = s.data_dir / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    book = get_guidebook()
    ingest_corpus(book)

    # A2A Budget Analyst: the real A2A HTTP protocol, served by the agent's ASGI app in-process
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from fastapi import FastAPI

    budget_app = FastAPI()
    from urllib.parse import urlparse

    # served under the same path as the configured URL (default <base>/a2a/budget)
    card, rpc = routes(s.budget_agent_url, prefix=urlparse(s.budget_agent_url).path.rstrip("/"))
    add_a2a_routes_to_fastapi(budget_app, agent_card_routes=card, jsonrpc_routes=rpc)
    a2a_client.set_transport(httpx.ASGITransport(app=budget_app))

    items = [i for i in GOLDEN_TRIPS if not args.only or i["id"] in args.only.split(",")]
    results: list[dict[str, Any]] = []
    async with MCPHub() as hub:
        set_hub(hub)
        graph = build_graph(InMemorySaver())
        for item in items:
            path = out_dir / f"{item['id']}.json"
            if path.exists() and not args.fresh:
                res = json.loads(path.read_text(encoding="utf-8"))
                logger.info("%s: cached run (%d ms)", item["id"], res["ms"])
            else:
                logger.info("%s: running ...", item["id"])
                res = await run_trip(graph, item)
                path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                logger.info("%s: %d ms, %d LLM calls, %d fallbacks", item["id"], res["ms"], res["llm"]["calls"],
                            res["llm"]["fallbacks"])
            res["checks"] = deterministic(item, res)
            results.append(res)
        set_hub(None)

    retrieval = evaluate_retrieval(book)

    ragas: dict[str, dict[str, Any]] = {}
    judge_info: dict[str, Any] = {}
    if not args.skip_ragas and s.groq_api_key:
        from voyager.eval.ragas_eval import GroqJudge, judge_models, score_sample

        judge = GroqJudge()
        judge_info = {"models": judge_models()}
        for item, res in zip(items, results, strict=True):
            if not res.get("plan"):
                continue
            path = out_dir / f"ragas-{item['id']}.json"
            if path.exists() and not args.fresh:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if all(cached.get(k) is not None for k in ("faithfulness", "answer_relevancy", "context_precision")):
                    ragas[item["id"]] = cached
                    continue
            q, a, ctxs = ragas_inputs(res, book)
            t = time.perf_counter()
            scores = await score_sample(judge, q, a, ctxs, item.get("reference"))
            scores["ms"] = int((time.perf_counter() - t) * 1000)
            scores["contexts"] = len(ctxs)
            ragas[item["id"]] = scores
            path.write_text(json.dumps(scores, indent=1), encoding="utf-8")
            logger.info("ragas %s: %s", item["id"], {k: v for k, v in scores.items() if not k.endswith("_error")})
        judge_info.update({"calls": judge.calls, "tokens": judge.tokens, "failures": judge.failures})
    write_report(items, results, retrieval, ragas, judge_info)


def evaluate_retrieval(book: Any) -> dict[str, Any]:
    from voyager.eval.retrieval import evaluate

    return evaluate(book, RETRIEVAL_QUERIES)


def write_report(items: list[dict[str, Any]], results: list[dict[str, Any]], retrieval: dict[str, Any],
                 ragas: dict[str, dict[str, Any]], judge: dict[str, Any]) -> None:
    DOCS.mkdir(exist_ok=True)
    produced = [r for r in results if r.get("plan")]
    lat = sorted(r["ms"] for r in produced)
    agents: dict[str, list[int]] = {}
    for r in produced:
        for a, ms in r["timings"].items():
            agents.setdefault(a, []).append(ms)
    check_names = sorted({k for r in results for k in r["checks"]})
    pass_rates = {k: round(sum(r["checks"].get(k, False) for r in results if k in r["checks"])
                           / max(1, sum(k in r["checks"] for r in results)), 3) for k in check_names}
    online = {}
    for name in ("Faithfulness", "Answer relevancy", "Context precision", "Citation coverage", "Budget fit", "Overall"):
        online[name] = _mean([next((s["value"] for s in r["plan"]["quality"]["scores"] if s["name"] == name), None)
                              for r in produced])
    ragas_mean = {m: _mean([v.get(m) for v in ragas.values()])
                  for m in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")}
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "trips": len(results), "plans": len(produced),
        "latency_ms": {"p50": lat[len(lat) // 2] if lat else None, "max": lat[-1] if lat else None,
                       "mean": int(statistics.mean(lat)) if lat else None},
        "agent_ms_mean": {a: int(statistics.mean(v)) for a, v in agents.items()},
        "llm_tokens_mean": int(statistics.mean([r["llm"]["input_tokens"] + r["llm"]["output_tokens"]
                                                for r in produced])) if produced else None,
        "llm_fallbacks_total": sum(r["llm"]["fallbacks"] for r in results),
        "critic_retries": sum(r.get("attempts", 0) for r in results),
        "checks_pass_rate": pass_rates, "online_scores_mean": online, "ragas_mean": ragas_mean,
        "ragas_judge": judge, "retrieval": retrieval,
        "per_trip": [{"id": r["id"], "ms": r["ms"], "checks": r["checks"], "ragas": ragas.get(r["id"]),
                      "llm": r["llm"], "tools": r["tools"],
                      "guidebook": ((r.get("plan") or {}).get("quality") or {}).get("guidebook"),
                      "confidence": ((r.get("plan") or {}).get("quality") or {}).get("confidence")}
                     for r in results],
    }
    (DOCS / "eval-results.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")

    def f(v: Any) -> str:
        return "n/a" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))

    md = [
        "# Voyager evaluation results", "",
        f"Generated {summary['generated_at']} by `python -m voyager.eval.run` against the real stack: Groq "
        "(gpt-oss-120b itinerary + critic, gpt-oss-20b specialists), live MCP tools (Open-Meteo, OpenStreetMap via "
        "Overpass/Photon, Frankfurter), embedded Qdrant hybrid RAG, and the A2A Budget Analyst (A2A HTTP protocol "
        "served in-process via ASGI). All numbers below are measured; nothing is hand-entered.", "",
        f"**Golden set:** {len(results)} trips ({len(produced)} produced a plan): 8 guidebook-covered cities, "
        "1 uncovered city (Ljubljana: on-demand Wikivoyage expansion), 1 prompt-injection + PII attempt.", "",
        "## Ragas (LLM-judged, reference-free unless noted)", "",
        f"Judge: {', '.join(judge.get('models', [])) or 'not run'}"
        + (f" - {judge.get('calls')} calls, {judge.get('tokens')} tokens, {judge.get('failures')} failed attempts"
           if judge.get('calls') is not None else ""), "",
        "| Metric | Mean | Trips scored |", "|---|---|---|",
    ]
    for m, v in ragas_mean.items():
        md.append(f"| {m.replace('_', ' ').title()} | {f(v)} | {sum(1 for x in ragas.values() if x.get(m) is not None)} |")
    md += ["", "Response = the plan's factual content (place + what the plan says about it; day/time scheduling is a recommendation, not a checkable claim). Contexts = the guidebook passages the plan cites (<= 5, 900 chars) + one block of the OpenStreetMap listings it cites. Context precision = Ragas *ContextUtilization* (no reference needed). Context recall only for trips "
               "with a short hand-written reference (Kyoto, Paris, Bangkok).", "",
           "## Online quality scores (computed on every run, mean)", "", "| Score | Mean |", "|---|---|"]
    md += [f"| {k} | {f(v)} |" for k, v in online.items()]
    md += ["", "## Deterministic checks (pass rate)", "", "| Check | Pass rate |", "|---|---|"]
    md += [f"| {k} | {v:.0%} |" for k, v in pass_rates.items()]
    md += ["", "## Retrieval (20 labelled queries; relevant = right city AND expected section)", "",
           "| Pipeline | Hit@5 | MRR@10 | Precision@5 | Wrong city@5 | Avg ms |", "|---|---|---|---|---|---|"]
    for mode, r in retrieval.items():
        md.append(f"| {mode} | {r['hit_rate@5']:.2f} | {r['mrr@10']:.2f} | {r['precision@5']:.2f} | "
                  f"{r['wrong_city@5']:.2f} | {r['avg_ms']} |")
    md += ["", "`hybrid_rerank` is the production path (destination pre-filter -> dense + BM25 prefetch -> RRF -> "
               "MiniLM cross-encoder). `hybrid_rerank_nofilter` drops the payload filter to show what it prevents.", "",
           "## Latency", "",
           f"End-to-end per trip: p50 {f(summary['latency_ms']['p50'])} ms, mean {f(summary['latency_ms']['mean'])} ms, "
           f"max {f(summary['latency_ms']['max'])} ms. Mean LLM tokens per trip: {f(summary['llm_tokens_mean'])}. "
           f"Critic-requested revisions: {summary['critic_retries']}. LLM fallbacks: {summary['llm_fallbacks_total']}.", "",
           "| Agent | Mean ms |", "|---|---|"]
    md += [f"| {a} | {ms} |" for a, ms in sorted(summary["agent_ms_mean"].items(), key=lambda kv: -kv[1])]
    md += ["", "Specialists (destination, weather, stays, food, logistics) run in parallel, so the wall clock is "
               "roughly guard + brief + max(specialists) + itinerary + budget + critic + finalize.", "",
           "## Per trip", "", "| Trip | ms | Guidebook | Confidence | Faithfulness | Relevancy | Ctx precision | "
           "Checks passed | LLM calls | Fallbacks |", "|---|---|---|---|---|---|---|---|---|---|"]
    for row in summary["per_trip"]:
        rg = row["ragas"] or {}
        passed = sum(row["checks"].values())
        md.append(f"| {row['id']} | {row['ms']} | {row['guidebook'] or '-'} | {f(row['confidence'])} | "
                  f"{f(rg.get('faithfulness'))} | {f(rg.get('answer_relevancy'))} | {f(rg.get('context_precision'))} | "
                  f"{passed}/{len(row['checks'])} | {row['llm']['calls']} | {row['llm']['fallbacks']} |")
    md += ["", "Raw numbers: `docs/eval-results.json`. Per-trip plans and Ragas scores: `data/eval/` (not committed)."]
    (DOCS / "eval-results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "mcp", "langfuse", "fastembed"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--skip-ragas", action="store_true")
    p.add_argument("--only", default="")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
