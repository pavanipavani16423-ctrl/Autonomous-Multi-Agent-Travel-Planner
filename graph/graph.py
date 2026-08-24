# ============================================================
# graph/graph.py — LangGraph State Machine + Workflow
# ============================================================
# PURPOSE:
#   Defines the stateful multi-agent workflow using LangGraph.
#   LangGraph models the agent pipeline as a directed graph where:
#     • Nodes = agents or validation steps
#     • Edges = transitions between nodes (conditional or fixed)
#     • State = shared TypedDict passed between all nodes
#
# WHY LANGGRAPH?
#   Traditional sequential calls (fn1 → fn2 → fn3) lack:
#     • Checkpointing (resume on failure)
#     • Conditional routing (retry failed agents)
#     • Parallelism support
#     • Built-in state management
#   LangGraph provides all of this with minimal boilerplate.
#
# GRAPH TOPOLOGY:
#
#   START
#     │
#   [validate_input]          ← GuardrailAgent (input check)
#     │ (pass)  │ (fail)
#     │         └──────────────→ END (error state)
#   [retrieval_node]          ← RetrievalAgent
#     │
#   [tool_node]               ← ToolAgent
#     │
#   [weather_node]            ← WeatherAgent
#     │
#   [route_node]              ← RouteAgent
#     │
#   [hotel_node]              ┐
#   [budget_node]             ├── run in sequence (can be parallel)
#   [food_node]               ┘
#     │
#   [validate_outputs]        ← Output guardrails
#     │
#   [final_planner_node]      ← FinalPlannerAgent
#     │
#   END
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional, Annotated
import functools
import operator
import time

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from loguru import logger

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.models import (
    TravelRequest, TravelPlan,
    RouteOutput, WeatherOutput, HotelOutput, BudgetOutput, FoodOutput,
)
from guardrails.guardrails import (
    validate_travel_request, run_all_output_guardrails, validate_final_plan,
)
from agents.agents import (
    RetrievalAgent, ToolAgent, WeatherAgent,
    RouteAgent, HotelAgent, BudgetAgent, FoodAgent, FinalPlannerAgent,
    SupervisorAgent,
)
from langfuse_setup import get_tracer
from agents.agents import drain_llm_errors
from memory.store import save_run, get_cached_plan
from memory.metrics import plan_metrics
from prompts.prompts import PROMPT_VERSION


# ══════════════════════════════════════════════════════════════
# Node instrumentation
# ══════════════════════════════════════════════════════════════

def traced_node(node_name: str):
    """
    Wrap a graph node so each one becomes a named Langfuse span.

    The LLM calls inside are already traced by the callback handler in
    BaseAgent; this adds the surrounding structure — which node ran, how long
    it took, and what it produced — so a trace reads as the pipeline rather
    than as nine loose generations. Node functions stay plain dict->dict.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            tracer = get_tracer()
            request = state.get("request")
            with tracer.span(
                f"node:{node_name}",
                input={"destination": getattr(request, "destination", None)},
                metadata={"node": node_name},
            ) as span:
                result = fn(state)
                produced = result.get(node_name) if isinstance(result, dict) else None
                span.set_output(
                    produced=type(produced).__name__ if produced is not None else None,
                    ok=produced is not None,
                    warnings=len(result.get("warnings", [])) if isinstance(result, dict) else 0,
                )
                return result
        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════
# SECTION 1 — Graph State Definition
# ══════════════════════════════════════════════════════════════

class TravelGraphState(dict):
    """
    Shared mutable state passed between every graph node.

    LangGraph passes state as a dictionary between nodes.
    Each node reads what it needs and writes its outputs back.
    Using a plain dict subclass keeps it simple and JSON-serialisable.

    Key fields:
    -----------
    request          : Original TravelRequest from the user
    rag_contexts     : Dict of RAG-retrieved context strings
    tool_data        : Dict of external API responses
    weather          : WeatherAgent output
    route            : RouteAgent output
    hotels           : HotelAgent output
    budget           : BudgetAgent output
    food             : FoodAgent output
    final_plan       : Assembled TravelPlan
    errors           : List of blocking errors (causes graph to terminate)
    warnings         : Accumulates non-blocking warnings
    current_node     : Tracks which node is executing (for logging)
    is_valid_input   : Set to False if input guardrails fail
    """

    def __init__(self, request: TravelRequest) -> None:
        super().__init__()
        self["request"] = request
        self["rag_contexts"] = {}
        self["tool_data"] = {}
        self["weather"] = None
        self["route"] = None
        self["hotels"] = None
        self["budget"] = None
        self["food"] = None
        self["final_plan"] = None
        self["errors"] = []
        self["warnings"] = []
        self["current_node"] = "start"
        self["is_valid_input"] = True


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Node Functions
# ══════════════════════════════════════════════════════════════
# Each node is a plain Python function that accepts and returns
# a state dict.  LangGraph handles routing between them.

@traced_node("validate_input")
def validate_input_node(state: dict) -> dict:
    """
    Node 1: Input Guardrails

    Validates the TravelRequest against all business rules.
    If validation fails, marks state with errors so the routing
    function can direct the graph to END.
    """
    state["current_node"] = "validate_input"
    request: TravelRequest = state["request"]

    logger.info(f"[Graph:validate_input] Validating request for {request.destination}")

    result = validate_travel_request(request)

    if not result.passed:
        state["errors"].extend(result.errors)
        state["is_valid_input"] = False
        logger.error(f"[Graph:validate_input] Validation FAILED: {result.errors}")
    else:
        state["warnings"].extend(result.warnings)
        logger.info("[Graph:validate_input] Validation PASSED")

    return state


@traced_node("retrieval")
def retrieval_node(state: dict) -> dict:
    """
    Node 2: RAG Retrieval

    Fetches destination knowledge from the hybrid RAG system.
    Populates state["rag_contexts"] for use by all downstream agents.
    """
    state["current_node"] = "retrieval"
    request = state["request"]

    logger.info(f"[Graph:retrieval] Fetching RAG context for {request.destination}")
    agent = RetrievalAgent()
    state["rag_contexts"] = agent.run(request)

    return state


@traced_node("tools")
def tool_node(state: dict) -> dict:
    """
    Node 3: External Tool Calls

    Executes all API tools in parallel-ish (sequential in current
    implementation for simplicity) and stores results in state["tool_data"].
    """
    state["current_node"] = "tools"
    request = state["request"]

    logger.info("[Graph:tools] Fetching external API data")
    agent = ToolAgent()
    state["tool_data"] = agent.run(request)

    return state


@traced_node("weather")
def weather_node(state: dict) -> dict:
    """
    Node 4: Weather Analysis

    Produces WeatherOutput.  Must run before RouteAgent because
    weather conditions influence route selection.
    """
    state["current_node"] = "weather"
    request = state["request"]
    rag_ctx = state["rag_contexts"].get("general_context", "")
    tool_data = state["tool_data"]

    logger.info(f"[Graph:weather] Analysing weather for {request.destination}")
    agent = WeatherAgent()
    state["weather"] = agent.run(
        request=request,
        weather_tool_data=tool_data.get("weather_data", "{}"),
        rag_context=rag_ctx,
    )

    return state


@traced_node("route")
def route_node(state: dict) -> dict:
    """
    Node 5: Route Planning

    Creates the day-wise itinerary.  Receives weather summary
    from the previous node to make weather-aware routing decisions.
    """
    state["current_node"] = "route"
    request = state["request"]
    rag_ctx = state["rag_contexts"].get("general_context", "")
    weather: Optional[WeatherOutput] = state.get("weather")

    weather_summary = ""
    if weather:
        weather_summary = (
            f"{weather.condition}, {weather.current_temp_celsius}°C. "
            f"Warnings: {'; '.join(weather.travel_warnings) or 'None'}"
        )

    logger.info("[Graph:route] Planning route and itinerary")
    agent = RouteAgent()
    state["route"] = agent.run(
        request=request,
        rag_context=rag_ctx,
        weather_summary=weather_summary,
    )

    return state


@traced_node("hotels")
def hotel_node(state: dict) -> dict:
    """
    Node 6: Hotel Recommendations

    Finds hotels across three price tiers using live search data
    enriched by RAG knowledge of the destination.
    """
    state["current_node"] = "hotels"
    request = state["request"]
    rag_ctx = state["rag_contexts"].get("hotel_context", "")
    tool_data = state["tool_data"]

    logger.info(f"[Graph:hotels] Finding hotels in {request.destination}")
    agent = HotelAgent()
    state["hotels"] = agent.run(
        request=request,
        hotel_tool_data=tool_data.get("hotel_data", "{}"),
        rag_context=rag_ctx,
    )

    return state


@traced_node("budget")
def budget_node(state: dict) -> dict:
    """
    Node 7: Budget Planning

    Computes the full cost breakdown.  Depends on route and hotel
    outputs for accurate accommodation and transport cost estimation.
    """
    state["current_node"] = "budget"
    request = state["request"]
    rag_ctx = state["rag_contexts"].get("general_context", "")
    route: Optional[RouteOutput] = state.get("route")
    hotels: Optional[HotelOutput] = state.get("hotels")

    logger.info("[Graph:budget] Calculating travel budget")
    agent = BudgetAgent()
    state["budget"] = agent.run(
        request=request,
        route_data=route.model_dump_json() if route else "{}",
        hotel_data=hotels.model_dump_json() if hotels else "{}",
        rag_context=rag_ctx,
    )

    return state


@traced_node("food")
def food_node(state: dict) -> dict:
    """
    Node 8: Food Recommendations

    Suggests local cuisine, vegetarian/non-vegetarian options,
    and specific restaurant recommendations.
    """
    state["current_node"] = "food"
    request = state["request"]
    rag_ctx = state["rag_contexts"].get("food_context", "")
    tool_data = state["tool_data"]

    logger.info(f"[Graph:food] Generating food recommendations for {request.destination}")
    agent = FoodAgent()
    state["food"] = agent.run(
        request=request,
        food_tool_data=tool_data.get("restaurant_data", "{}"),
        rag_context=rag_ctx,
    )

    return state


@traced_node("validate_outputs")
def validate_outputs_node(state: dict) -> dict:
    """
    Node 9: Output Guardrails

    Validates all agent outputs before final compilation.
    Adds warnings to state for inclusion in the final plan.
    Does NOT fail the pipeline on warnings (only on errors).
    """
    state["current_node"] = "validate_outputs"
    request = state["request"]

    logger.info("[Graph:validate_outputs] Running output guardrails")

    guardrail_result = run_all_output_guardrails(
        route=state.get("route"),
        weather=state.get("weather"),
        hotels=state.get("hotels"),
        budget=state.get("budget"),
        food=state.get("food"),
        request=request,
        data_sources=state.get("tool_data", {}).get("data_sources", {}),
        rag_grounding=state.get("rag_contexts", {}).get("grounded", {}),
    )

    state["warnings"].extend(guardrail_result.warnings)

    # Only add errors for truly blocking issues
    if not guardrail_result.passed:
        for err in guardrail_result.errors:
            state["warnings"].append(f"[Validation] {err}")

    logger.info(
        f"[Graph:validate_outputs] Done | "
        f"warnings={len(state['warnings'])}"
    )
    return state


@traced_node("final_planner")
def final_planner_node(state: dict) -> dict:
    """
    Node 10: Final Plan Assembly

    Combines all agent outputs into a single coherent TravelPlan.
    This is the terminal node before END.
    """
    state["current_node"] = "final_planner"
    request = state["request"]

    logger.info("[Graph:final_planner] Assembling final travel plan")
    agent = FinalPlannerAgent()
    state["final_plan"] = agent.run(
        request=request,
        route=state.get("route"),
        weather=state.get("weather"),
        hotels=state.get("hotels"),
        budget=state.get("budget"),
        food=state.get("food"),
        warnings=state.get("warnings", []),
        data_sources=state.get("tool_data", {}).get("data_sources", {}),
        rag_grounding=state.get("rag_contexts", {}).get("grounded", {}),
    )

    return state


def error_node(state: dict) -> dict:
    """
    Terminal error node.
    Reached when input validation fails.
    Formats the error state for display.
    """
    state["current_node"] = "error"
    logger.error(f"[Graph:error] Pipeline terminated with errors: {state['errors']}")
    return state


# ══════════════════════════════════════════════════════════════
# SECTION 3 — Routing Functions (Conditional Edges)
# ══════════════════════════════════════════════════════════════

def route_after_validation(state: dict) -> str:
    """
    Conditional router after input validation.
    Returns the name of the next node to execute.
    """
    if not state.get("is_valid_input", True):
        return "error"
    return "retrieval"


# ══════════════════════════════════════════════════════════════
# SECTION 4 — Graph Builder
# ══════════════════════════════════════════════════════════════

def build_travel_graph() -> StateGraph:
    """
    Construct the LangGraph StateGraph with all nodes and edges.

    Why StateGraph?
    ---------------
    StateGraph automatically merges node outputs back into the
    shared state dict.  Each node function returns a partial
    state update; LangGraph handles the merge.

    Returns
    -------
    A compiled LangGraph application ready for invocation.
    """

    # ── Instantiate the graph with a dict state ───────────────
    # We use dict (not TypedDict) for maximum flexibility
    workflow = StateGraph(dict)

    # ── Register nodes ────────────────────────────────────────
    # Each call maps a string label to a Python function
    workflow.add_node("validate_input",   validate_input_node)
    workflow.add_node("retrieval",        retrieval_node)
    workflow.add_node("tools",            tool_node)
    workflow.add_node("weather",          weather_node)
    workflow.add_node("route",            route_node)
    workflow.add_node("hotels",           hotel_node)
    workflow.add_node("budget",           budget_node)
    workflow.add_node("food",             food_node)
    workflow.add_node("validate_outputs", validate_outputs_node)
    workflow.add_node("final_planner",    final_planner_node)
    workflow.add_node("error",            error_node)

    # ── Set entry point ───────────────────────────────────────
    workflow.set_entry_point("validate_input")

    # ── Define edges ──────────────────────────────────────────
    # Conditional edge after validation (pass → retrieval, fail → error)
    workflow.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {
            "retrieval": "retrieval",
            "error": "error",
        },
    )

    # Fixed sequential edges
    workflow.add_edge("retrieval",        "tools")
    workflow.add_edge("tools",            "weather")
    workflow.add_edge("weather",          "route")
    workflow.add_edge("route",            "hotels")
    workflow.add_edge("hotels",           "budget")
    workflow.add_edge("budget",           "food")
    workflow.add_edge("food",             "validate_outputs")
    workflow.add_edge("validate_outputs", "final_planner")

    # Terminal edges
    workflow.add_edge("final_planner",    END)
    workflow.add_edge("error",            END)

    logger.info("[Graph] Workflow graph built successfully")
    return workflow


# ══════════════════════════════════════════════════════════════
# SECTION 5 — Compiled App Factory
# ══════════════════════════════════════════════════════════════

_COMPILED = None


def _make_checkpointer():
    """
    Durable working memory.

    MemorySaver kept checkpoints in RAM *and* was constructed fresh inside
    every call, so the pause/resume and state-inspection that LangGraph
    advertises were unreachable: each run's checkpoints were discarded the
    moment it returned. SQLite makes the working state outlive the process,
    which is what lets a crashed or interrupted run be inspected afterwards.

    check_same_thread=False because Streamlit serves each session on its own
    thread; the default would reject the connection on the second request.
    Falls back to RAM rather than failing the run if the file is unusable.
    """
    try:
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        from memory.store import DB_DIR

        os.makedirs(DB_DIR, exist_ok=True)
        path = os.path.join(DB_DIR, "checkpoints.db")
        conn = sqlite3.connect(path, check_same_thread=False)
        logger.info(f"[Graph] Checkpointing to {path}")
        return SqliteSaver(conn)
    except Exception as e:
        logger.warning(
            f"[Graph] SQLite checkpointer unavailable ({e}) — "
            "falling back to in-memory checkpoints for this process"
        )
        return MemorySaver()


def get_compiled_graph():
    """
    Build, compile, and return the LangGraph application.

    Compiled once and cached. Rebuilding the graph on every request was pure
    overhead — the topology never changes between runs, and a fresh
    checkpointer each time defeated checkpointing entirely.

    Returns
    -------
    A compiled LangGraph CompiledGraph object with:
      .invoke(state)  — synchronous execution
      .stream(state)  — token streaming
      .get_state()    — current state inspection
    """
    global _COMPILED
    if _COMPILED is None:
        workflow = build_travel_graph()
        _COMPILED = workflow.compile(checkpointer=_make_checkpointer())
        logger.info("[Graph] LangGraph application compiled and ready")
    return _COMPILED


# ══════════════════════════════════════════════════════════════
# SECTION 6 — High-Level Run Function
# ══════════════════════════════════════════════════════════════

def run_travel_pipeline(
    request: TravelRequest,
    use_cache: bool = True,
    trace_id: str = "",
) -> dict:
    """
    Public interface for the entire multi-agent pipeline.

    Takes a validated TravelRequest and runs it through the
    complete LangGraph workflow, returning the final state dict.

    Parameters
    ----------
    request : TravelRequest pydantic model from the user

    Returns
    -------
    Final state dict containing:
      state["final_plan"]  : TravelPlan (or None on error)
      state["errors"]      : List of error messages
      state["warnings"]    : List of warning messages
    """
    # ── Cache lookup ──────────────────────────────────────────
    # An identical request costs ~4 minutes and ~19k tokens to recompute for
    # a byte-identical answer. The returned state is marked `from_cache` so
    # callers (and the UI) can say so rather than implying fresh work.
    if use_cache:
        cached = get_cached_plan(request)
        if cached is not None:
            return {
                "request": request,
                "final_plan": cached,
                "route": cached.route,
                "weather": cached.weather,
                "hotels": cached.hotels,
                "budget": cached.budget,
                "food": cached.food,
                "rag_contexts": {"grounded": cached.rag_grounding or {}},
                "tool_data": {"data_sources": cached.data_sources or {}},
                "errors": [],
                "warnings": list(cached.warnings or []),
                "current_node": "cache",
                "is_valid_input": True,
                "from_cache": True,
            }

    drain_llm_errors()   # discard anything left over from a previous run

    # Guarantee exactly one trace per pipeline run.
    #
    # The agents attach their LLM calls to whatever trace is open. When there
    # isn't one — the CLI, the eval harness, any direct caller — each chain
    # opened its OWN root trace, so a single plan showed up in Langfuse as
    # seven unrelated traces named "RouteAgent", "FoodAgent" and so on, with
    # no request context and no scores. Opening one here when the caller has
    # not already done so keeps every entry point consistent.
    tracer = get_tracer()
    if not tracer.is_tracing():
        with tracer.trace(
            name=f"travel_plan_{request.destination}",
            input_data={
                "origin": request.origin, "destination": request.destination,
                "departure": request.departure_date, "return": request.return_date,
                "travellers": request.travellers, "budget_usd": request.budget_usd,
            },
            metadata={"entrypoint": "pipeline"},
            tags=["travel-planner"],
        ):
            return _execute_pipeline(request, trace_id=trace_id)

    return _execute_pipeline(request, trace_id=trace_id)


def _execute_pipeline(request: TravelRequest, trace_id: str = "") -> dict:
    """Run the compiled graph. Assumes a trace is already open."""
    app = get_compiled_graph()

    # Initial state
    initial_state = {
        "request": request,
        "rag_contexts": {},
        "tool_data": {},
        "weather": None,
        "route": None,
        "hotels": None,
        "budget": None,
        "food": None,
        "final_plan": None,
        "errors": [],
        "warnings": [],
        "current_node": "start",
        "is_valid_input": True,
    }

    # Config provides a thread_id for checkpointing
    config = {"configurable": {"thread_id": f"trip_{request.destination}_{request.departure_date}"}}

    logger.info(
        f"[Graph] Executing pipeline | "
        f"{request.origin} → {request.destination} | "
        f"{request.departure_date} – {request.return_date}"
    )

    started = time.time()
    try:
        final_state = app.invoke(initial_state, config=config)
        elapsed = time.time() - started
        final_state["from_cache"] = False

        # Agents swallow their exceptions so one failure cannot abort the run.
        # Collect what they swallowed, otherwise a rate-limited call shows up
        # as an empty section with no explanation anywhere in the UI.
        final_state["llm_errors"] = drain_llm_errors()
        if final_state["llm_errors"]:
            kinds = {e["kind"] for e in final_state["llm_errors"]}
            logger.warning(
                f"[Graph] {len(final_state['llm_errors'])} LLM call(s) failed "
                f"({', '.join(sorted(kinds))}) — sections will be incomplete"
            )

        logger.info(
            f"[Graph] Pipeline completed in {elapsed:.0f}s | "
            f"plan={final_state.get('final_plan') is not None} | "
            f"errors={len(final_state.get('errors', []))}"
        )

        # Record the run: history for the user, and the metrics substrate the
        # quality harness compares prompt versions against.
        try:
            metrics = plan_metrics(final_state, latency_s=elapsed)
            final_state["metrics"] = metrics
            final_state["run_id"] = save_run(
                request=request,
                plan=final_state.get("final_plan"),
                metrics=metrics,
                prompt_version=PROMPT_VERSION,
                trace_id=trace_id,
                latency_s=elapsed,
            )
        except Exception as e:
            logger.warning(f"[Graph] Could not record run: {e}")

        return final_state
    except Exception as e:
        logger.error(f"[Graph] Pipeline execution failed: {e}")
        return {
            **initial_state,
            "errors": [f"Pipeline execution error: {str(e)}"],
            "final_plan": None,
        }


__all__ = [
    "TravelGraphState",
    "build_travel_graph",
    "get_compiled_graph",
    "run_travel_pipeline",
]