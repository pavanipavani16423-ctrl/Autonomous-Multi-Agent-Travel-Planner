"""Small helpers shared by the agent nodes: retrieval with events, evidence, matching, geo."""

from __future__ import annotations

import difflib
import re
from typing import Any

from voyager.graph.context import RunContext
from voyager.guardrails.injection import quarantine_passage
from voyager.mcp.hub import MCPHub, get_hub
from voyager.mcp.servers.places import haversine_km
from voyager.observability.tracing import get_tracer
from voyager.rag.store import Passage, get_guidebook
from voyager.schemas import TripRequest

OPEN_METEO = {"id": "open-meteo", "title": "Open-Meteo weather forecast / archive", "url": "https://open-meteo.com/",
              "snippet": "Daily forecast (16 days) and historical weather from Open-Meteo.", "source": "open-meteo"}
FRANKFURTER = {"id": "frankfurter", "title": "ECB reference exchange rates (Frankfurter)",
               "url": "https://frankfurter.dev/", "snippet": "Daily ECB reference rates.", "source": "frankfurter"}
BUDGET_ANALYST = {"id": "budget-analyst", "title": "Budget Analyst agent (A2A)", "url": "/a2a/budget/.well-known/agent-card.json",
                  "snippet": "Costed by the remote Budget Analyst agent from curated daily cost bands and the plan's own prices.",
                  "source": "budget-analyst"}


def req_of(state: dict[str, Any]) -> TripRequest:
    return TripRequest.model_validate(state["request"])


async def hub() -> MCPHub:
    return await get_hub()


async def retrieve(ctx: RunContext, agent: str, query: str, destination: str,
                   sections: list[str] | None = None, k: int = 5) -> tuple[list[Passage], dict[str, Any]]:
    """Guidebook search + `retrieval` SSE event + Langfuse retriever span. Quarantines passages that
    read like instructions (indirect prompt injection)."""
    book = get_guidebook()
    with get_tracer().section("rag.search", as_type="retriever", input={"query": query, "sections": sections},
                              metadata={"agent": agent, "destination": destination}) as span:
        res = await book.asearch(query, destination, sections, k)
        passages = [p for p in res.passages if not quarantine_passage(p.text)]
        span.update(output={"hits": len(passages), "top_score": res.top_score, "covered": res.covered,
                            "ids": [p.id for p in passages]})
    await ctx.emit("retrieval", {"agent": agent, "query": query, "hits": len(passages),
                                 "top_score": round(res.top_score, 4), "covered": res.covered})
    record = {f"{agent}:{query}": {"ids": [p.id for p in passages], "scores": [p.score for p in passages],
                                   "covered": res.covered, "ms": res.ms}}
    return passages, record


def evidence_from(passages: list[Passage]) -> dict[str, Any]:
    return {p.id: p.citation() for p in passages}


def osm_citation(place: dict[str, Any]) -> dict[str, Any]:
    return {"id": place["id"], "title": f"{place['name']} (OpenStreetMap)", "url": place.get("source_url", ""),
            "snippet": f"{place.get('kind', 'place')} at {place['lat']:.5f}, {place['lon']:.5f}"
                       + (f" in {place['area']}" if place.get("area") else ""), "source": "openstreetmap"}


def passages_block(passages: list[Passage], chars: int = 320) -> str:
    lines = []
    for p in passages:
        body = p.text.split(":", 1)[-1].strip() if ":" in p.text[:80] else p.text
        body = re.sub(r"\s+", " ", body)[:chars]
        lines.append(f"[{p.id}] ({p.section}) {body}")
    return "\n".join(lines) or "(no guidebook passages)"


def dedupe(passages: list[Passage]) -> list[Passage]:
    seen, out = set(), []
    for p in passages:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def best_match(name: str, candidates: list[dict[str, Any]], cutoff: float = 0.72) -> dict[str, Any] | None:
    """Fuzzy-match a name to a candidate place (by `name`)."""
    if not name or not candidates:
        return None
    n = norm(name)
    if not n:
        return None
    for c in candidates:
        cn = norm(c.get("name", ""))
        if cn and (cn == n or (len(cn) > 5 and (cn in n or n in cn))):
            return c
    names = [norm(c.get("name", "")) for c in candidates]
    hit = difflib.get_close_matches(n, names, n=1, cutoff=cutoff)
    return candidates[names.index(hit[0])] if hit else None


def within_km(lat: float, lon: float, center: dict[str, Any], km: float = 60.0) -> bool:
    return haversine_km(lat, lon, center["lat"], center["lon"]) <= km


def cluster_areas(places: list[dict[str, Any]], center: dict[str, Any]) -> None:
    """Label each place with an `area` (in place). Uses the OSM area tag when present, otherwise a
    compass sector + ring around the centre - good enough to keep one day in one part of town."""
    for p in places:
        if p.get("area"):
            continue
        dlat, dlon = p["lat"] - center["lat"], p["lon"] - center["lon"]
        dist = haversine_km(center["lat"], center["lon"], p["lat"], p["lon"])
        if dist < 1.2:
            p["area"] = "Centre"
            continue
        ns = "North" if dlat > 0 else "South"
        ew = "east" if dlon > 0 else "west"
        p["area"] = f"{ns}-{ew}" + (" (outer)" if dist > 6 else "")


def to_money(amount: float, currency: str) -> dict[str, Any]:
    decimals = 0 if currency in ("JPY", "KRW", "VND", "IDR", "INR", "HUF", "CLP", "COP", "UZS", "ISK") else 2
    return {"amount": round(float(amount), decimals), "currency": currency}


def usd_to(amount_usd: float, fx: dict[str, Any]) -> float:
    return amount_usd * float(fx.get("usd_to_trip") or 1.0)
