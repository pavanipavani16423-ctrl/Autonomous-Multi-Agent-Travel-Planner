"""Run manager: starts plan / refine runs in the background, streams their events, persists results.

* one Langfuse trace per run (session = trip id, metadata: destination, revision)
* identical request seen recently -> the cached plan is replayed instantly (labelled `cached`)
* preference profile updated from every request and refinement
* at most `MAX_CONCURRENT_RUNS` graphs at once (free-tier LLM limits and a 512 MB instance)
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from voyager.config import get_settings
from voyager.graph.context import RunContext, register, unregister
from voyager.memory.preferences import cache_key, learn_from_feedback, learn_from_request
from voyager.memory.store import Store
from voyager.observability.tracing import get_tracer
from voyager.schemas import AGENT_IDS, TripRequest
from voyager.services.events import EventBus

logger = logging.getLogger(__name__)
MAX_CONCURRENT_RUNS = 2


class RunManager:
    def __init__(self, store: Store, graph: Any) -> None:
        self.store = store
        self.graph = graph
        self.bus = EventBus(store)
        self.tasks: dict[str, asyncio.Task] = {}
        self.sem = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
        self.run_stats: dict[str, dict[str, Any]] = {}  # trip id -> LLM usage / timings of the last run

    # ---- public API ---------------------------------------------------------------------------
    async def start(self, req: TripRequest) -> str:
        trip_id = uuid.uuid4().hex[:12]
        data = req.model_dump(mode="json")
        await self.store.create_trip(trip_id, data)
        if req.client_id:
            prof = await self.store.get_profile(req.client_id)
            await self.store.put_profile(req.client_id, learn_from_request(prof, req))
        cached = await self.store.cache_get(cache_key(req), get_settings().plan_cache_ttl_s)
        coro = self._serve_cached(trip_id, data, cached) if cached else self._run(
            trip_id, 0, {"trip_id": trip_id, "revision": 0, "mode": "plan", "request": data, "feedback": [],
                         "attempts": 0}, data, cache=cache_key(req))
        self.tasks[trip_id] = asyncio.create_task(coro)
        return trip_id

    async def refine(self, trip_id: str, message: str) -> int:
        trip = await self.store.get_trip(trip_id)
        if trip is None:
            raise KeyError(trip_id)
        if trip["status"] in ("queued", "running"):
            raise RuntimeError("trip is still running")
        if not trip.get("plan"):
            raise RuntimeError("trip has no plan to refine")
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": trip_id}})
        if not snapshot or not snapshot.values.get("brief"):
            raise RuntimeError("no checkpoint to resume from (cached or blocked trip); plan it again")
        revision = int(trip["revision"]) + 1
        feedback = list(snapshot.values.get("feedback") or []) + [message]
        req = trip["request"]
        if req.get("client_id"):
            prof = await self.store.get_profile(req["client_id"])
            await self.store.put_profile(req["client_id"], learn_from_feedback(prof, message))
        await self.store.update_trip(trip_id, status="queued", revision=revision, error=None)
        self.tasks[trip_id] = asyncio.create_task(self._run(
            trip_id, revision, {"mode": "refine", "revision": revision, "feedback": feedback, "attempts": 0,
                                "error": ""},
            req))
        return revision

    # ---- internals ----------------------------------------------------------------------------
    async def _emit_factory(self, trip_id: str, revision: int):  # noqa: ANN202
        async def emit(kind: str, payload: dict[str, Any]) -> None:
            await self.bus.publish(trip_id, revision, kind, payload)
        return emit

    async def _run(self, trip_id: str, revision: int, graph_input: dict[str, Any], request: dict[str, Any],
                   cache: str | None = None) -> None:
        emit = await self._emit_factory(trip_id, revision)
        ctx = RunContext(trip_id=trip_id, revision=revision, emit=emit)
        register(ctx)
        started = time.perf_counter()
        tracer = get_tracer()
        try:
            async with self.sem:
                await self.store.update_trip(trip_id, status="running")
                with tracer.run_trace(trip_id=trip_id, revision=revision, input=request,
                                      user_id=request.get("client_id"),
                                      metadata={"destination": request.get("destination"), "revision": revision,
                                                "mode": graph_input.get("mode", "plan")}) as root:
                    ctx.trace_id = tracer.current_trace_id()
                    state = await self.graph.ainvoke(
                        graph_input, config={"configurable": {"thread_id": trip_id}, "recursion_limit": 40})
                    plan = state.get("plan")
                    if plan and plan.get("revision") != revision:
                        plan = None  # a stale plan from an earlier revision (this run failed)
                    root.update(output={"title": (plan or {}).get("title"), "error": state.get("error")})
            ms = int((time.perf_counter() - started) * 1000)
            if plan and not state.get("error"):
                plan["timings"] = [{"agent": a, "ms": ctx.timings[a]} for a in AGENT_IDS if a in ctx.timings]
                await self.store.update_trip(trip_id, status="done", plan=plan, revision=revision, error=None)
                await emit("plan", plan)
                if cache and revision == 0:
                    await self.store.cache_put(cache, trip_id, plan)
            else:
                msg = state.get("error") or "the run finished without a plan"
                blocked = bool((state.get("guard") or {}).get("blocked"))
                await self.store.update_trip(trip_id, status="error", error=msg)
                await emit("error", {"message": msg, "recoverable": not blocked})
            await emit("done", {"trip_id": trip_id, "revision": revision, "ms": ms})
            logger.info("trip %s rev %d finished in %d ms (llm calls %d, tokens %d/%d)", trip_id, revision, ms,
                        ctx.stats.calls, ctx.stats.input_tokens, ctx.stats.output_tokens)
        except Exception as exc:  # noqa: BLE001 - a crash must still end the stream
            logger.exception("trip %s failed", trip_id)
            await self.store.update_trip(trip_id, status="error", error=f"{type(exc).__name__}: {exc}"[:300])
            await emit("error", {"message": f"Internal error: {type(exc).__name__}", "recoverable": True})
            await emit("done", {"trip_id": trip_id, "revision": revision,
                                "ms": int((time.perf_counter() - started) * 1000)})
        finally:
            tracer.flush()
            unregister(trip_id)
            self.run_stats[trip_id] = {"llm_calls": ctx.stats.calls, "input_tokens": ctx.stats.input_tokens,
                                       "output_tokens": ctx.stats.output_tokens, "fallbacks": ctx.stats.fallbacks,
                                       "by_agent": ctx.stats.by_agent, "methods": ctx.methods,
                                       "timings": dict(ctx.timings)}

    async def _serve_cached(self, trip_id: str, request: dict[str, Any], cached: dict[str, Any]) -> None:
        emit = await self._emit_factory(trip_id, 0)
        started = time.perf_counter()
        age_min = int((time.time() - cached["created_ts"]) / 60)
        for agent in AGENT_IDS:
            await emit("agent", {"agent": agent, "status": "skipped",
                                 "message": f"served from the plan cache (identical request {age_min} min ago)"})
        plan = copy.deepcopy(cached["plan"])
        plan.update({"trip_id": trip_id, "revision": 0, "request": request,
                     "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "timings": []})
        for d in plan.get("days") or []:
            if d.get("weather"):
                d["weather"]["provenance"] = "cached"
        for s in (plan.get("stays") or []) + (plan.get("food") or []):
            if s.get("provenance") == "live":
                s["provenance"] = "cached"
        plan["quality"]["checks"].insert(0, {
            "name": "Plan cache", "passed": True,
            "detail": f"Identical request planned {age_min} min ago (trip {cached['trip_id']}); live data marked 'cached'."})
        await self.store.update_trip(trip_id, status="done", plan=plan, revision=0)
        await emit("plan", plan)
        await emit("done", {"trip_id": trip_id, "revision": 0, "ms": int((time.perf_counter() - started) * 1000)})
