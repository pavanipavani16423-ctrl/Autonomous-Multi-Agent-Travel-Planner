"""Per-run runtime context (not checkpointed): the event emitter, timings, LLM stats.

Nodes find it by trip id. `agent_node` wraps every node: `agent` started/done/error events, a
Langfuse span, wall-clock timing, and the "agents never raise" rule (an exception becomes a
labelled gap, and the graph carries on).
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from voyager.graph.state import TripState
from voyager.llm.gateway import RUN_STATS, CallStats
from voyager.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _noop_emit(kind: str, payload: dict[str, Any]) -> None:
    return None


@dataclass
class RunContext:
    trip_id: str
    revision: int
    emit: Emit = _noop_emit
    timings: dict[str, int] = field(default_factory=dict)
    stats: CallStats = field(default_factory=CallStats)
    methods: dict[str, str] = field(default_factory=dict)  # agent -> "llm" | "fallback:..." | ...
    started: float = field(default_factory=time.perf_counter)
    trace_id: str | None = None

    async def tool_emit(self, event: dict[str, Any]) -> None:
        event = dict(event)
        kind = event.pop("type", "tool")
        await self.emit(kind, event)


_CONTEXTS: dict[str, RunContext] = {}


def register(ctx: RunContext) -> None:
    _CONTEXTS[ctx.trip_id] = ctx


def unregister(trip_id: str) -> None:
    _CONTEXTS.pop(trip_id, None)


def context_for(trip_id: str) -> RunContext:
    ctx = _CONTEXTS.get(trip_id)
    if ctx is None:  # direct graph use (tests/scripts) without a run manager
        ctx = RunContext(trip_id=trip_id, revision=0)
        _CONTEXTS[trip_id] = ctx
    return ctx


Node = Callable[[TripState, RunContext], Awaitable[dict[str, Any]]]


def agent_node(agent: str, gap: Callable[[TripState, str], dict[str, Any]] | None = None):
    """Decorate `async def node(state, ctx) -> dict`. The node may return `_message` (shown in the
    `agent` done event) and `_status` ("done" | "skipped")."""

    def wrap(fn: Node) -> Callable[[TripState], Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def run(state: TripState) -> dict[str, Any]:
            ctx = context_for(state["trip_id"])
            token = RUN_STATS.set(ctx.stats)
            await ctx.emit("agent", {"agent": agent, "status": "started", "message": _start_message(agent)})
            started = time.perf_counter()
            with get_tracer().section(agent, as_type="agent", metadata={"revision": ctx.revision}) as span:
                try:
                    update = await fn(state, ctx)
                    status = update.pop("_status", "done")
                    message = update.pop("_message", "done")
                    ms = int((time.perf_counter() - started) * 1000)
                    span.update(output={"message": message, "status": status})
                except Exception as exc:  # noqa: BLE001 - agents never raise
                    logger.exception("agent %s failed", agent)
                    ms = int((time.perf_counter() - started) * 1000)
                    status, message = "error", f"{type(exc).__name__}: {exc}"[:240]
                    span.update(level="ERROR", status_message=message)
                    update = gap(state, message) if gap else {}
                finally:
                    RUN_STATS.reset(token)
            ctx.timings[agent] = ctx.timings.get(agent, 0) + ms
            await ctx.emit("agent", {"agent": agent, "status": status, "message": message, "ms": ms})
            return update

        return run

    return wrap


START_MESSAGES = {
    "guard": "Checking the request (injection, PII, scope, dates, budget)",
    "brief": "Locating the destination and checking guidebook coverage",
    "destination": "Researching highlights and neighbourhoods in the guidebook",
    "weather": "Fetching the forecast",
    "stays": "Finding places to stay on OpenStreetMap",
    "food": "Finding food that fits your diet",
    "logistics": "Working out transport, visa, safety and money",
    "itinerary": "Composing the day-by-day plan",
    "budget": "Asking the Budget Analyst agent (A2A) to cost the plan",
    "critic": "Checking the plan against the facts and your constraints",
    "finalize": "Assembling the final plan and quality scores",
}


def _start_message(agent: str) -> str:
    return START_MESSAGES.get(agent, "working")
