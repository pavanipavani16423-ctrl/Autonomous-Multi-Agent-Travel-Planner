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
import operator

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

def get_compiled_graph():
    """
    Build, compile, and return the LangGraph application.

    MemorySaver provides in-memory checkpointing, enabling:
      • Pause and resume mid-execution
      • State inspection at each node
      • Automatic retry on transient failures

    Returns
    -------
    A compiled LangGraph CompiledGraph object with:
      .invoke(state)  — synchronous execution
      .stream(state)  — token streaming
      .get_state()    — current state inspection
    """
    workflow = build_travel_graph()
    # MemorySaver: stores checkpoints in RAM (use SqliteSaver for persistence)
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    logger.info("[Graph] LangGraph application compiled and ready")
    return app


# ══════════════════════════════════════════════════════════════
# SECTION 6 — High-Level Run Function
# ══════════════════════════════════════════════════════════════

def run_travel_pipeline(request: TravelRequest) -> dict:
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

    try:
        final_state = app.invoke(initial_state, config=config)
        logger.info(
            f"[Graph] Pipeline completed | "
            f"plan={final_state.get('final_plan') is not None} | "
            f"errors={len(final_state.get('errors', []))}"
        )
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