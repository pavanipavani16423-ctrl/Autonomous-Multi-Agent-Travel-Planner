"""`itinerary`: composes the day-by-day plan from the specialists' findings (large model).

* weather-aware  - wet days lean indoors (the forecast per day is in the prompt)
* pace-aware     - relaxed 2-3, balanced 3-4, packed 4-5 activities a day
* geo-clustered  - places are grouped into areas; each day stays in one or two neighbouring areas
* grounded       - activities name places from the candidate lists; locations come from OSM matches
                   (or a Photon lookup), citations are filtered to real evidence ids, and a passage that
                   literally mentions the place is attached as a citation
Long trips are generated in chunks of 5 days (Groq free tier: 8K tokens/minute).
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from voyager.graph.context import RunContext, agent_node
from voyager.graph.helpers import best_match, hub, norm, osm_citation, req_of, to_money, usd_to, within_km
from voyager.graph.state import TripState
from voyager.llm.gateway import structured
from voyager.mcp.costs import profile as cost_profile
from voyager.mcp.servers.places import haversine_km
from voyager.mcp.servers.weather import is_wet
from voyager.schemas import Category, TripRequest

CATEGORIES = {"sight", "food", "activity", "transit", "shopping", "nature", "culture", "nightlife"}
CATEGORY_ALIASES = {"temple": "culture", "museum": "culture", "history": "culture", "art": "culture",
                    "park": "nature", "garden": "nature", "hike": "nature", "meal": "food", "lunch": "food",
                    "dinner": "food", "breakfast": "food", "cafe": "food", "market": "shopping",
                    "bar": "nightlife", "travel": "transit", "transport": "transit", "relax": "activity"}
PACE = {"relaxed": (2, 3), "balanced": (3, 4), "packed": (4, 5)}
CHUNK_DAYS = 5
LOCATE_MAX, LOCATE_BUDGET_S = 6, 8.0  # Photon/Nominatim lookups for unmatched places
SLOT_TIMES = {"morning": ["09:00", "10:30"], "afternoon": ["13:00", "15:00", "16:30"], "evening": ["18:30", "20:00"]}


class ActDraft(BaseModel):
    slot: Literal["morning", "afternoon", "evening"]
    time: str = Field(description="HH:MM, 24h")
    duration_min: int = Field(90, ge=15, le=600)
    title: str
    description: str = Field(description="1-2 sentences")
    place: str | None = Field(None, description="exact place name from the candidate lists")
    category: Category = "sight"
    cost: float = Field(0, ge=0, description="total for the whole group, trip currency")
    indoor: bool = False
    citations: list[str] = Field(default_factory=list)
    tip: str | None = None

    # Coerce near-misses instead of paying for a repair turn (8K tokens/minute is precious).
    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        v = dict(v)
        t = str(v.get("time") or "")
        m = re.search(r"(\d{1,2})[:.](\d{2})", t)
        hour = int(m.group(1)) if m else None
        v["time"] = f"{hour:02d}:{m.group(2)}" if m else "10:00"
        if v.get("slot") not in ("morning", "afternoon", "evening"):
            h = hour if hour is not None else 10
            v["slot"] = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
        cat = str(v.get("category") or "sight").lower()
        v["category"] = cat if cat in CATEGORIES else CATEGORY_ALIASES.get(cat, "activity")
        cost = v.get("cost")
        if isinstance(cost, dict):
            cost = cost.get("amount", 0)
        if isinstance(cost, str):
            digits = re.sub(r"[^\d.]", "", cost)
            cost = float(digits) if digits else 0.0
        v["cost"] = max(0.0, float(cost or 0))
        try:
            v["duration_min"] = max(15, min(600, int(float(v.get("duration_min") or 90))))
        except (TypeError, ValueError):
            v["duration_min"] = 90
        if isinstance(v.get("citations"), str):
            v["citations"] = [v["citations"]]
        if not v.get("title"):
            v["title"] = v.get("name") or v.get("activity") or v.get("place") or "Free time"
        if not v.get("description"):
            v["description"] = v.get("details") or v.get("desc") or v.get("notes") or v["title"]
        if isinstance(v.get("place"), dict):
            v["place"] = v["place"].get("name")
        if not isinstance(v.get("indoor"), bool):
            v["indoor"] = str(v.get("indoor")).lower() in ("true", "yes", "1")
        return v


class DayDraft(BaseModel):
    day: int
    title: str = ""
    theme: str = ""
    area: str = ""
    activities: list[ActDraft]

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        if isinstance(v, dict):
            v = dict(v)
            if "day" not in v:
                v["day"] = v.get("day_number") or v.get("dayNumber") or 0
            if isinstance(v["day"], str):
                digits = re.sub(r"\D", "", v["day"])
                v["day"] = int(digits) if digits else 0
            v["title"] = v.get("title") or v.get("theme") or v.get("area") or ""
            v["theme"] = v.get("theme") or v["title"]
            if "activities" not in v:
                v["activities"] = v.get("items") or v.get("schedule") or []
        return v


class ItineraryDraft(BaseModel):
    title: str = ""
    summary: str = ""
    days: list[DayDraft]


SYSTEM = (
    "You are the Itinerary composer of a travel-planning team. Build a realistic day-by-day plan using ONLY "
    "the candidate places, highlights, food picks and guidebook passages provided.\nRules:\n"
    "1. Output exactly the requested day numbers.\n"
    "2. Activities per day follow the pace; slots morning/afternoon/evening with ascending HH:MM times.\n"
    "3. Geo-cluster: each day stays in one or two neighbouring areas (set `area`).\n"
    "4. Wet days: most activities indoor (museums, temples, markets, food halls). Set `indoor` truthfully.\n"
    "5. `place` must be an exact name from the lists. Cite the passage ids (wv-...) that support each "
    "activity; leave citations empty if only the map lists it.\n"
    "5b. `description` may only state facts found in the passages, highlights or map listing (type, area, "
    "cuisine, diet). Otherwise describe what the traveller will do there, not claims about the place.\n"
    "6. Include one meal per day from the food picks, respecting the diet.\n"
    "7. `cost` = total for the whole group in the trip currency (0 if free). Keep within the activity budget.\n"
    "8. Stay in the destination city; no other cities unless a passage supports a day trip.\n"
    "9. Lighter first and last day. Never repeat a place.\n"
    "10. Build the trip around the Highlights first: they are the destination's must-sees (its famous forts, "
    "palaces, temples, old quarters, markets). Fit every highlight that matches the interests unless the pace "
    "makes it impossible; use the other candidate places only to fill gaps near them, never instead of them.\n"
    "11. Day `title`: short and specific, naming the day's main sights (e.g. 'Amber Fort and the old walled "
    "city'), never just a neighbourhood name. `theme`: 2-5 words (e.g. 'Forts and royal history').")


def _weather_line(day_no: int, d: date, wx: dict[str, Any] | None) -> str:
    if not wx:
        return f"Day {day_no} ({d:%a %d %b}): weather unknown"
    tag = " -> WET, plan indoors" if is_wet(wx) else ""
    est = " (estimate)" if wx.get("provenance") == "estimate" else ""
    return f"Day {day_no} ({d:%a %d %b}): {wx['summary']}, {wx['t_min']:.0f}-{wx['t_max']:.0f}°C{est}{tag}"


def _candidates(state: TripState) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for p in (state.get("destination") or {}).get("pois") or []:
        pool.append({**p, "pool": "poi"})
    for f in (state.get("food") or {}).get("items") or []:
        if f.get("location"):
            pool.append({"name": f["name"], "lat": f["location"]["lat"], "lon": f["location"]["lon"],
                         "area": f.get("area") or "", "kind": "restaurant", "pool": "food",
                         "id": next((c for c in f.get("citations", []) if c.startswith("osm-")), None)})
    return pool


def _mentions(name: str, evidence: dict[str, Any], passage_ids: list[str]) -> list[str]:
    """Guidebook passages that literally mention a place name (cheap, honest grounding)."""
    n = norm(name)
    if len(n) < 5:
        return []
    out = []
    for pid in passage_ids:
        cit = evidence.get(pid)
        if cit and n in norm(cit.get("snippet", "")):
            out.append(pid)
    return out[:2]


def _prompt(state: TripState, req: TripRequest, day_nums: list[int], done_places: list[str],
            issues: list[str]) -> str:
    b, dest = state["brief"], state.get("destination") or {}
    wx_by_date = {d["date"]: d for d in (state.get("weather") or {}).get("days") or []}
    lo, hi = PACE[req.pace]
    prof = cost_profile(b.get("country_code") or "", req.stay_style)
    act_budget = usd_to(prof["activities"] * req.travellers, b.get("fx") or {})
    areas: dict[str, list[str]] = {}
    for p in (dest.get("pois") or [])[:30]:
        areas.setdefault(p.get("area") or "Centre", []).append(f"{p['name']} ({p['kind']})")
    evidence = state.get("evidence") or {}
    passage_ids = [i for i in dest.get("passage_ids", []) if i in evidence][:10]
    passages = "\n".join(f"[{i}] {evidence[i]['snippet'][:230]}" for i in passage_ids) or "(none)"
    highlights = "\n".join(f"- {h['name']} [{', '.join(h.get('citations') or [])}] {h.get('why', '')[:100]}"
                           for h in dest.get("highlights") or [])
    food = "\n".join(f"- {f['name']} ({f.get('area') or ''}; {f.get('cuisine', '')}; diet ok: {', '.join(f.get('diet_ok') or []) or '-'})"
                     for f in (state.get("food") or {}).get("items") or [])
    stays = ", ".join(f"{s['name']} ({s.get('area', '')})" for s in (state.get("stays") or {}).get("items") or [])
    lines = [
        f"Destination: {b['name']}, {b.get('country', '')}. Dates: {req.start_date} to {req.end_date} ({req.days} days).",
        f"Travellers: {req.adults} adults, {req.children} children. Pace: {req.pace} ({lo}-{hi} activities/day).",
        f"Interests: {', '.join(req.interests) or 'general'}. Diet: {', '.join(req.diet) or 'none'}. Style: {req.stay_style}.",
        f"Activity budget: about {act_budget:.0f} {req.currency} per day for the whole group. Trip currency: {req.currency}.",
        f"Generate days: {', '.join(map(str, day_nums))}.",
        "", "Weather:", *[_weather_line(n, req.start + timedelta(days=n - 1),
                                         wx_by_date.get((req.start + timedelta(days=n - 1)).isoformat()))
                          for n in day_nums],
        "", "Candidate places by area:", *[f"{a}: {'; '.join(v[:8])}" for a, v in areas.items()],
        "", "Highlights [citations]:", highlights or "(none)",
        "", "Food picks:", food or "(none)",
        "", f"Staying near: {stays or 'city centre'}",
        "", "Guidebook passages:", passages,
    ]
    if done_places:
        lines += ["", f"Already used on earlier days (don't repeat): {', '.join(done_places[:30])}"]
    feedback = state.get("feedback") or []
    if feedback:
        lines += ["", "TRAVELLER FEEDBACK (highest priority, apply it):", *[f"- {f}" for f in feedback[-3:]]]
    if issues:
        lines += ["", "CRITIC FOUND THESE PROBLEMS IN THE PREVIOUS DRAFT (fix them):", *[f"- {i}" for i in issues]]
    return "\n".join(lines)


def _fallback(state: TripState, req: TripRequest, day_nums: list[int], used: set[str]) -> ItineraryDraft:
    """Deterministic composer: one area per day, indoor picks on wet days, a meal each day."""
    dest = state.get("destination") or {}
    pois = [p for p in dest.get("pois") or [] if norm(p["name"]) not in used]
    foods = list((state.get("food") or {}).get("items") or [])
    wx_by_date = {d["date"]: d for d in (state.get("weather") or {}).get("days") or []}
    by_area: dict[str, list[dict[str, Any]]] = {}
    for p in pois:
        by_area.setdefault(p.get("area") or "Centre", []).append(p)
    areas = sorted(by_area, key=lambda a: -len(by_area[a])) or ["Centre"]
    lo, hi = PACE[req.pace]
    days = []
    for i, n in enumerate(day_nums):
        d = req.start + timedelta(days=n - 1)
        wet = is_wet(wx_by_date.get(d.isoformat()) or {})
        area = areas[i % len(areas)]
        group = sorted(by_area.get(area, []), key=lambda p: (wet and p["kind"] not in ("museum", "temple")))
        count = lo if n in (1, req.days) else hi
        acts: list[ActDraft] = []
        slots = ["morning", "afternoon", "afternoon", "morning", "evening"]
        for j, p in enumerate(group[: max(1, count - 1)]):
            used.add(norm(p["name"]))
            slot = slots[j] if j < len(slots) else "afternoon"
            acts.append(ActDraft(slot=slot, time=SLOT_TIMES[slot][min(j // 2, len(SLOT_TIMES[slot]) - 1)],
                                 duration_min=120, title=f"Visit {p['name']}", place=p["name"],
                                 description=f"Explore {p['name']}, a {p['kind'].replace('_', ' ')} in {area}.",
                                 category="culture" if p["kind"] in ("museum", "temple") else
                                 "nature" if p["kind"] == "park" else "sight",
                                 indoor=p["kind"] == "museum", cost=0))
        if foods:
            f = foods[i % len(foods)]
            acts.append(ActDraft(slot="evening", time="19:00", duration_min=90, title=f"Dinner at {f['name']}",
                                 place=f["name"], description=f"Try {f['must_try']}.", category="food",
                                 indoor=True, cost=0))
        acts.sort(key=lambda a: a.time)
        days.append(DayDraft(day=n, title=f"{area}" + (" (indoor day)" if wet else ""), theme=area, area=area,
                             activities=acts))
    return ItineraryDraft(title=f"{req.days} days in {state['brief']['name']}",
                          summary=f"A {req.pace} {req.days}-day plan for {state['brief']['name']}.", days=days)


async def _locate(state: TripState, ctx: RunContext, names: list[str]) -> dict[str, dict[str, Any]]:
    """Photon lookups for places not matched to an OSM candidate (bounded, in parallel)."""
    b = state["brief"]
    tools = (await hub()).toolbox("itinerary", ctx.tool_emit)

    async def one(name: str) -> tuple[str, dict[str, Any] | None]:
        res = await tools.call("places", "geocode", query=f"{name}", kind="poi", near_lat=b["lat"],
                               near_lon=b["lon"], limit=3)
        for r in res.get("results") or []:
            if within_km(r["lat"], r["lon"], b, 40):
                return name, r
        return name, None

    # best effort within a fixed budget: whatever resolves in time gets coordinates
    tasks = [asyncio.create_task(one(n)) for n in names[:LOCATE_MAX]]
    done, pending = await asyncio.wait(tasks, timeout=LOCATE_BUDGET_S)
    for t in pending:
        t.cancel()
    found = [t.result() for t in done if not t.cancelled() and t.exception() is None]
    return {n: r for n, r in found if r}


async def compose(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req = req_of(state)
    b = state["brief"]
    issues = ((state.get("critic") or {}).get("issues") or []) if (state.get("attempts") or 0) > 0 else []
    all_days = list(range(1, req.days + 1))
    chunks = [all_days[i:i + CHUNK_DAYS] for i in range(0, len(all_days), CHUNK_DAYS)]
    drafts: list[DayDraft] = []
    title = summary = ""
    used: set[str] = set()
    methods = []
    for chunk in chunks:
        done_places = [a.place for d in drafts for a in d.activities if a.place]
        user = _prompt(state, req, chunk, done_places, issues)
        draft, method = await structured(
            "itinerary", ItineraryDraft, SYSTEM, user, size="large",
            fallback=lambda c=chunk, u=used: _fallback(state, req, c, u), max_tokens=min(7000, 700 + 520 * len(chunk)))
        methods.append(method)
        title, summary = title or draft.title, summary or draft.summary
        got = {d.day: d for d in draft.days if d.day in chunk}
        for n in chunk:  # a day the model skipped is filled deterministically
            drafts.append(got.get(n) or _fallback(state, req, [n], used).days[0])
        used |= {norm(a.place or "") for d in drafts for a in d.activities}
    ctx.methods["itinerary"] = methods[0] if len(set(methods)) == 1 else ",".join(methods)
    return await _finish(state, ctx, req, b, title, summary, drafts)


async def _finish(state: TripState, ctx: RunContext, req: TripRequest, b: dict[str, Any], title: str,
                  summary: str, drafts: list[DayDraft]) -> dict[str, Any]:
    evidence: dict[str, Any] = dict(state.get("evidence") or {})
    pool = _candidates(state)
    passage_ids = [k for k in evidence if k.startswith("wv-")]
    wx_by_date = {d["date"]: d for d in (state.get("weather") or {}).get("days") or []}
    unmatched = []
    for d in drafts:
        for a in d.activities:
            if a.place and not best_match(a.place, pool) and a.category != "transit":
                unmatched.append(a.place)
    located = await _locate(state, ctx, list(dict.fromkeys(unmatched))) if unmatched else {}
    new_evidence: dict[str, Any] = {}
    days_out = []
    for d in sorted(drafts, key=lambda x: x.day):
        day_date = req.start + timedelta(days=d.day - 1)
        acts_out = []
        for i, a in enumerate(sorted(d.activities, key=lambda x: x.time)):
            cites = [c for c in a.citations if c in evidence]
            loc = None
            if a.place:
                m = best_match(a.place, pool)
                if m:
                    loc = {"lat": m["lat"], "lon": m["lon"]}
                    if m.get("id"):
                        cid = m["id"]
                        if cid not in evidence and m.get("pool") == "poi":
                            new_evidence[cid] = osm_citation(m)
                        cites.append(cid)
                elif a.place in located:
                    r = located[a.place]
                    loc = {"lat": r["lat"], "lon": r["lon"]}
                    cid = "osm-" + "-".join(r["source_url"].rstrip("/").split("/")[-2:])
                    new_evidence[cid] = {"id": cid, "title": f"{r['name']} (OpenStreetMap)", "url": r["source_url"],
                                         "snippet": f"{r.get('kind', 'place')} at {r['lat']:.5f}, {r['lon']:.5f}",
                                         "source": "openstreetmap"}
                    cites.append(cid)
                cites += [p for p in _mentions(a.place, evidence, passage_ids) if p not in cites]
            if loc and not within_km(loc["lat"], loc["lon"], b, 60):
                loc = None
            time_txt = a.time if re.fullmatch(r"\d{1,2}:\d{2}", a.time or "") else SLOT_TIMES[a.slot][0]
            acts_out.append({
                "id": f"d{d.day}-{i + 1}", "slot": a.slot, "time": time_txt.zfill(5), "duration_min": a.duration_min,
                "title": a.title, "description": a.description, "place": a.place, "location": loc,
                "category": a.category, "cost": to_money(a.cost, req.currency), "indoor": a.indoor,
                "citations": list(dict.fromkeys(cites)), "tip": a.tip,
            })
        pts = [x["location"] for x in acts_out if x["location"]]
        walk = sum(haversine_km(p["lat"], p["lon"], q["lat"], q["lon"]) for p, q in zip(pts, pts[1:], strict=False))
        days_out.append({
            "day": d.day, "date": day_date.isoformat(), "title": d.title, "theme": d.theme,
            "weather": wx_by_date.get(day_date.isoformat()), "activities": acts_out,
            "day_cost": to_money(sum(x["cost"]["amount"] for x in acts_out), req.currency),
            "walking_km": round(walk * 1.3, 1) if len(pts) > 1 else None, "area": d.area,
        })
    out = {"title": title or f"{req.days} days in {b['name']}", "summary": summary, "days": days_out}
    await ctx.emit("partial", {"section": "itinerary", "payload": {"title": out["title"], "days": days_out}})
    n_acts = sum(len(d["activities"]) for d in days_out)
    cited = sum(1 for d in days_out for x in d["activities"] if x["citations"])
    return {"itinerary": out, "evidence": new_evidence,
            "_message": f"{len(days_out)} days, {n_acts} activities ({cited} cited)"}


@agent_node("itinerary", gap=lambda s, m: {"itinerary": {"title": "", "summary": "", "days": [], "error": m}})
async def itinerary(state: TripState, ctx: RunContext) -> dict[str, Any]:
    return await compose(state, ctx)
