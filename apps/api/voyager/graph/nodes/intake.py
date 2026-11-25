"""`guard` (input guardrails) and `brief` (geocode, coverage, on-demand guidebook expansion, fx)."""

from __future__ import annotations

import asyncio
from typing import Any

from voyager.graph.context import RunContext, agent_node
from voyager.graph.helpers import FRANKFURTER, hub, req_of
from voyager.graph.state import TripState
from voyager.guardrails import check_request
from voyager.mcp.costs import currency_for
from voyager.rag.ingest import expand_city
from voyager.rag.store import get_guidebook
from voyager.rag.text import destination_key
from voyager.services.images import wikipedia_image


@agent_node("guard")
async def guard(state: TripState, ctx: RunContext) -> dict[str, Any]:
    result = check_request(req_of(state))
    out = {
        "request": result.request.model_dump(mode="json"),
        "guard": {"blocked": result.blocked, "reason": result.reason,
                  "checks": [c.model_dump() for c in result.checks],
                  "pii": result.pii_found, "injection": result.injection_hits},
    }
    if result.blocked:
        out["error"] = result.reason
        out["_status"] = "error"
        out["_message"] = f"Blocked: {result.reason}"
    else:
        flags = []
        if result.pii_found:
            flags.append(f"redacted {len(result.pii_found)} personal detail(s)")
        if result.injection_hits:
            flags.append("removed an injection attempt from the notes")
        out["_message"] = "Request is safe to plan" + (f" ({'; '.join(flags)})" if flags else "")
    return out


async def _fx(ctx: RunContext, trip_currency: str, local_currency: str) -> dict[str, Any]:
    tools = (await hub()).toolbox("brief", ctx.tool_emit)
    usd, local = await asyncio.gather(
        tools.call("money", "convert", amount=1.0, from_currency="USD", to_currency=trip_currency),
        tools.call("money", "convert", amount=1.0, from_currency=local_currency, to_currency=trip_currency),
    )
    return {
        "trip_currency": trip_currency, "local_currency": local_currency,
        "usd_to_trip": usd.get("rate") or None, "local_to_trip": local.get("rate") or None,
        "provenance": "live" if usd.get("provenance") == "live" and local.get("provenance") == "live"
        else ("estimate" if usd.get("rate") else "unavailable"),
        "note": usd.get("note", ""),
    }


@agent_node("brief")
async def brief(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req = req_of(state)
    tools = (await hub()).toolbox("brief", ctx.tool_emit)
    book = get_guidebook()
    for _ in range(240):  # first boot: let the corpus finish indexing (never "expand" a covered city)
        if book.ready:
            break
        await asyncio.sleep(0.5)
    geo = await tools.call("places", "geocode", query=req.destination, kind="city", limit=3)
    rows = geo.get("results") or []
    if not rows:  # a landmark / region rather than a city: try the OSM geocoder
        geo = await tools.call("places", "geocode", query=req.destination, kind="poi", limit=3)
        rows = geo.get("results") or []
    if not rows:
        return {"error": f"Could not locate '{req.destination}'.", "brief": {"located": False},
                "_status": "error", "_message": f"Could not locate '{req.destination}' (geocoding unavailable)"}
    top = rows[0]
    name = top.get("name") or req.destination
    country, cc = top.get("country", ""), top.get("country_code", "")
    key = book.resolve(name) or book.resolve(req.destination)
    passages = book.passages_for(key)
    status, note = "covered", f"{passages} guidebook passages"
    image_task = asyncio.create_task(wikipedia_image(name, f"{name}, {country}", req.destination))
    fx_task = asyncio.create_task(_fx(ctx, req.currency, currency_for(cc)))
    if key is None or passages < 15:
        await ctx.emit("agent", {"agent": "brief", "status": "started",
                                 "message": f"{name} is not in the guidebook yet: fetching its Wikivoyage article"})
        exp = await expand_city(name, country)
        if exp["status"] == "expanded":
            key = destination_key(exp.get("title") or name)
            passages, status = exp["passages"], "expanded"
        else:
            status = "none"
            passages = book.passages_for(key)
            if passages:  # a few passages exist (e.g. alias); still usable but thin
                status = "expanded"
        note = exp["note"]
    image, fx = await asyncio.gather(image_task, fx_task)
    brief_out = {
        "located": True, "name": name, "country": country, "country_code": cc,
        "lat": top["lat"], "lon": top["lon"], "timezone": top.get("timezone"), "population": top.get("population"),
        "key": key or destination_key(name), "guidebook": status, "passages": passages, "note": note,
        "image": image, "fx": fx, "geocode_source": geo.get("source_url"),
    }
    evidence = {FRANKFURTER["id"]: FRANKFURTER} if fx.get("provenance") != "unavailable" else {}
    label = {"covered": "in the guidebook", "expanded": "guidebook expanded on demand",
             "none": "no guidebook coverage (lower confidence)"}[status]
    return {"brief": brief_out, "evidence": evidence,
            "_message": f"{name}, {country} ({top['lat']:.3f}, {top['lon']:.3f}) - {label}: {note}"}
