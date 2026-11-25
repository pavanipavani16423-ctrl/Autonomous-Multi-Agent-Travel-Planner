"""Shared LangGraph state. Plain JSON-able dicts so the SQLite checkpointer can persist every step
(refinement resumes from it)."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    return {**(a or {}), **(b or {})}


class TripState(TypedDict, total=False):
    trip_id: str
    revision: int
    mode: str  # "plan" | "refine"
    request: dict[str, Any]  # TripRequest (sanitised by guard)
    feedback: list[str]  # refinement messages, oldest first
    guard: dict[str, Any]
    brief: dict[str, Any]
    destination: dict[str, Any]
    weather: dict[str, Any]
    stays: dict[str, Any]
    food: dict[str, Any]
    logistics: dict[str, Any]
    itinerary: dict[str, Any]
    budget: dict[str, Any]
    critic: dict[str, Any]
    attempts: int  # itinerary revisions requested by the critic in this revision
    evidence: Annotated[dict[str, Any], merge]  # citation id -> Citation
    retrieval: Annotated[dict[str, Any], merge]  # "agent:query" -> {ids, scores, covered}
    plan: dict[str, Any]
    error: str
