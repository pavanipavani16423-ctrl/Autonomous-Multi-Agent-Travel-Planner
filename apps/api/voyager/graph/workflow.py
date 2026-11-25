"""The LangGraph workflow.

    START ─┬─(plan)──> guard ──> brief ──┬─> destination ─┐
           │                             ├─> weather     ─┤
           │                             ├─> stays       ─┼─> itinerary ─> budget(A2A) ─> critic ─┬─> finalize ─> END
           │                             ├─> food        ─┤        ^                              │
           │                             └─> logistics   ─┘        └────────(fail, ≤1 retry)──────┘
           └─(refine)──────────────────────────────────────> itinerary   (resumes from the checkpoint)

State is checkpointed per trip (thread_id = trip_id) with AsyncSqliteSaver, so a refinement re-runs
only itinerary -> budget -> critic -> finalize on top of the stored specialist results.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from voyager.graph.nodes.intake import brief, guard
from voyager.graph.nodes.itinerary import itinerary
from voyager.graph.nodes.research import destination, food, logistics, stays, weather
from voyager.graph.nodes.review import after_critic, budget, critic, finalize
from voyager.graph.state import TripState

SPECIALISTS = ["destination", "weather", "stays", "food", "logistics"]


def _entry(state: TripState) -> str:
    return "itinerary" if state.get("mode") == "refine" else "guard"


def _after_guard(state: TripState) -> str:
    return END if (state.get("guard") or {}).get("blocked") else "brief"


def _after_brief(state: TripState) -> list[str] | str:
    return SPECIALISTS if (state.get("brief") or {}).get("located") else END


def build_graph(checkpointer: Any = None) -> Any:
    g = StateGraph(TripState)
    g.add_node("guard", guard)
    g.add_node("brief", brief)
    g.add_node("destination", destination)
    g.add_node("weather", weather)
    g.add_node("stays", stays)
    g.add_node("food", food)
    g.add_node("logistics", logistics)
    g.add_node("itinerary", itinerary)
    g.add_node("budget", budget)
    g.add_node("critic", critic)
    g.add_node("finalize", finalize)

    g.add_conditional_edges(START, _entry, ["guard", "itinerary"])
    g.add_conditional_edges("guard", _after_guard, ["brief", END])
    g.add_conditional_edges("brief", _after_brief, [*SPECIALISTS, END])
    g.add_edge(SPECIALISTS, "itinerary")  # fan-in: waits for all five
    g.add_edge("itinerary", "budget")
    g.add_edge("budget", "critic")
    g.add_conditional_edges("critic", after_critic, ["itinerary", "finalize"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
