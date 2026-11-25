"""HTTP API (prefix /api) per docs/SPEC.md."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from voyager.mcp.hub import get_hub
from voyager.rag.store import get_guidebook
from voyager.schemas import (
    ChatBody,
    DestinationCoverage,
    ParseBody,
    PlaceSuggestion,
    RefineAccepted,
    RefineBody,
    Trip,
    TripCreated,
    TripRequest,
    TripSummary,
)
from voyager.services.parse import parse_text

router = APIRouter(prefix="/api")


def _runs(request: Request) -> Any:
    return request.app.state.runs


@router.post("/trips/parse", response_model=TripRequest)
async def parse(body: ParseBody, request: Request) -> TripRequest:
    profile = await request.app.state.store.get_profile(body.client_id) if body.client_id else {}
    try:
        req = await parse_text(body.text, profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.client_id:
        req.client_id = body.client_id
    return req


@router.post("/trips", status_code=202, response_model=TripCreated)
async def create_trip(req: TripRequest, request: Request) -> TripCreated:
    from voyager.guardrails.sanity import date_problems

    problems = date_problems(req)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    trip_id = await _runs(request).start(req)
    return TripCreated(trip_id=trip_id)


@router.get("/trips/{trip_id}/stream")
async def stream(trip_id: str, request: Request) -> EventSourceResponse:
    runs = _runs(request)
    trip = await runs.store.get_trip(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="trip not found")
    after = 0
    last_id = request.headers.get("last-event-id")
    if last_id and last_id.isdigit():
        after = int(last_id)

    async def events():  # noqa: ANN202
        async for ev in runs.bus.subscribe(trip_id, int(trip["revision"]), after):
            if ev["type"] == "ping":
                continue
            yield {"event": ev["type"], "data": json.dumps(ev["data"], ensure_ascii=False), "id": str(ev["seq"])}

    return EventSourceResponse(events(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/trips/{trip_id}", response_model=Trip, response_model_exclude_none=False)
async def get_trip(trip_id: str, request: Request) -> Any:
    trip = await _runs(request).store.get_trip(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="trip not found")
    return trip


@router.post("/trips/{trip_id}/refine", response_model=RefineAccepted)
async def refine(trip_id: str, body: RefineBody, request: Request) -> RefineAccepted:
    from voyager.guardrails import injection, pii

    if injection.detect(body.message).flagged:
        raise HTTPException(status_code=422, detail="That message looks like instructions to the assistant, "
                                                    "not feedback on the trip.")
    message, _ = pii.redact(body.message)
    try:
        revision = await _runs(request).refine(trip_id, message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trip not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RefineAccepted(trip_id=trip_id, revision=revision)


@router.post("/chat")
async def chat(body: ChatBody, request: Request) -> EventSourceResponse:
    """The Voyager assistant: grounded answers about the open trip, the guidebook and Voyager itself,
    streamed as `token` events, then `sources`, an optional `action` (refine | plan) and `done`."""
    from voyager.services.chat import chat_events

    async def events():  # noqa: ANN202
        async for kind, data in chat_events(body, request.app.state.store):
            yield {"event": kind, "data": json.dumps(data, ensure_ascii=False)}

    return EventSourceResponse(events(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/trips", response_model=list[TripSummary])
async def list_trips(request: Request, client_id: str | None = Query(None, max_length=80)) -> Any:
    return await _runs(request).store.list_trips(client_id, limit=20)


@router.get("/destinations", response_model=list[DestinationCoverage])
async def destinations() -> list[DestinationCoverage]:
    book = get_guidebook()
    rows = [DestinationCoverage(name=c["name"], country=c.get("country", ""), passages=c["passages"])
            for c in book.cities.values()]
    return sorted(rows, key=lambda r: r.name)


@router.get("/places/suggest", response_model=list[PlaceSuggestion])
async def suggest(q: str = Query(..., min_length=2, max_length=80)) -> list[PlaceSuggestion]:
    book = get_guidebook()
    res = await (await get_hub()).call("api", "places", "geocode", {"query": q, "kind": "city", "limit": 6})
    out: list[PlaceSuggestion] = []
    for r in res.get("results") or []:
        out.append(PlaceSuggestion(name=r["name"], country=r.get("country", ""), lat=r["lat"], lon=r["lon"],
                                   covered=book.is_covered(r["name"])))
    return out[:6]
