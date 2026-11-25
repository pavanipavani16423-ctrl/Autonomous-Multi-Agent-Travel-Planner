"""The five parallel specialists: destination, weather, stays, food, logistics.

Each grounds itself in the guidebook (Qdrant hybrid RAG, destination pre-filter) and/or live MCP
tools, asks the small model for a compact structured answer, and keeps only what it can back with
evidence: a place the model names must match an OSM result or cite a guidebook passage, otherwise it
is dropped (no fabricated data shown as real).
"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from voyager.graph.context import RunContext, agent_node
from voyager.graph.helpers import (
    OPEN_METEO,
    best_match,
    cluster_areas,
    dedupe,
    evidence_from,
    hub,
    norm,
    osm_citation,
    passages_block,
    req_of,
    retrieve,
    to_money,
    usd_to,
)
from voyager.graph.state import TripState
from voyager.llm.gateway import structured
from voyager.mcp.servers.weather import is_wet
from voyager.rag.store import BULLET_RE, LISTING_RE, get_guidebook
from voyager.schemas import Category

# ---------------------------------------------------------------------------------------------
# destination
# ---------------------------------------------------------------------------------------------


class Highlight(BaseModel):
    name: str
    why: str = Field(description="one sentence, grounded in the passages")
    category: Category = "sight"
    indoor: bool = False
    citations: list[str] = Field(default_factory=list, description="passage ids like wv-1a2b3c4d5e")

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> str:
        v = str(v or "sight").lower()
        allowed = {"sight", "food", "activity", "transit", "shopping", "nature", "culture", "nightlife"}
        return v if v in allowed else {"temple": "culture", "museum": "culture", "park": "nature"}.get(v, "sight")


class Neighbourhood(BaseModel):
    name: str
    vibe: str
    citations: list[str] = Field(default_factory=list)


class DestinationDraft(BaseModel):
    blurb: str = Field(description="2 sentences about the destination")
    highlights: list[Highlight] = Field(default_factory=list)
    neighbourhoods: list[Neighbourhood] = Field(default_factory=list)
    culture_tips: list[str] = Field(default_factory=list)


DEST_SYSTEM = (
    "You are the Destination researcher of a travel-planning team. Use ONLY the guidebook passages and "
    "the OpenStreetMap places given. Every highlight must be a real place from the passages or the OSM "
    "list, and cite the passage ids that support it (empty list if it only comes from OSM). Prefer places "
    "that match the traveller's interests. Be concise.")

KIND_CATEGORY = {"museum": "culture", "temple": "culture", "park": "nature", "viewpoint": "sight",
                 "attraction": "sight"}


def named_in(name: str, passages: list[Any], ids: list[str]) -> bool:
    """True when a cited guidebook passage literally names the place (guards against invented names)."""
    n = norm(name)
    return len(n) >= 4 and any(n in norm(p.text) for p in passages if p.id in ids)


_CHAIN_RE = re.compile(
    r"\b(mcdonald'?s|kfc|burger king|domino'?s|pizza hut|subway|starbucks|dunkin|jollibee|andok'?s|"
    r"wendy'?s|taco bell|papa john'?s|costa coffee|tim hortons|chowking|mang inasal|greenwich)\b", re.I)

_GENERIC = {"parking", "area", "lot", "temple", "hindu", "mosque", "church", "shrine", "mandir", "park",
             "garden", "viewpoint", "museum", "lake", "the", "of", "public", "toilet", "entrance", "gate",
             "statue", "fountain", "playground", "point", "spot", "view", "jain", "sikh", "gurudwara"}


def _good_poi(p: dict[str, Any]) -> bool:
    """Drop map features that aren't real sights: 'parking area', 'temple hindu', bare 'Temple'."""
    n = p["name"].lower()
    words = re.findall(r"[a-z]+", n)
    if not words or all(w in _GENERIC for w in words):
        return False
    return not n.startswith(("viewpoint of", "view of")) and len(p["name"]) <= 70


@agent_node("destination", gap=lambda s, m: {"destination": {"blurb": "", "highlights": [], "pois": [],
                                                               "neighbourhoods": [], "error": m}})
async def destination(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req, b = req_of(state), state["brief"]
    city = b["name"]
    interests = ", ".join(req.interests) or "general sightseeing"
    radius = 15000 if b.get("region") else 7000 if (b.get("population") or 0) > 1_000_000 else 4000
    tools = (await hub()).toolbox("destination", ctx.tool_emit)
    (sights, r1), (famous, r3), (context, r2), osm, landmarks = await asyncio.gather(
        retrieve(ctx, "destination", f"{city} top sights attractions {interests}", city, ["See", "Do"], k=8),
        retrieve(ctx, "destination", f"{city} most famous landmarks must-see monuments palace fort old town",
                 city, ["See", "Understand"], k=4),
        retrieve(ctx, "destination", f"{city} neighbourhoods districts culture etiquette", city,
                 ["Understand", "Districts", "Respect", "Cope", "Talk"], k=4),
        tools.call("places", "search_places", lat=b["lat"], lon=b["lon"],
                   kind="attraction,museum,temple,park,viewpoint", radius_m=radius, limit=30),
        get_guidebook().alandmarks(city, 6),
    )
    pois = [p for p in osm.get("results") or [] if _good_poi(p)]
    cluster_areas(pois, b)
    # the city's most cross-referenced sights go first, so the model sees the famous ones
    passages = dedupe(landmarks + famous + sights + context)
    r1 = {**r1, **r3}
    known = {p.id for p in passages}

    def fallback() -> DestinationDraft:
        hl = []
        for psg in landmarks:  # famous guidebook sights first, then map places
            m = LISTING_RE.search(psg.text) or BULLET_RE.search(psg.text.split(":", 1)[-1])
            if m:
                hl.append(Highlight(name=m.group(1).strip(" .,-"), why="One of the most-referenced sights "
                                    "in the guidebook.", category="sight", indoor=False, citations=[psg.id]))
        hl += [Highlight(name=p["name"], why=f"{p['kind'].title()} in {p.get('area') or city} (OpenStreetMap).",
                         category=KIND_CATEGORY.get(p["kind"], "sight"), indoor=p["kind"] == "museum")
               for p in pois[: max(0, 8 - len(hl))]]
        lead = next((x.text.split(":", 1)[-1].strip() for x in context if x.section == "Understand"), "")
        blurb = (lead[:260] + "...") if lead else f"{city}, {b.get('country', '')}."
        return DestinationDraft(blurb=blurb, highlights=hl)

    user = (f"Destination: {city}, {b.get('country', '')}. Interests: {interests}. Pace: {req.pace}.\n\n"
            f"Guidebook passages:\n{passages_block(passages)}\n\n"
            f"OpenStreetMap places (name | kind | area):\n"
            + "\n".join(f"- {p['name']} | {p['kind']} | {p.get('area', '')}" for p in pois[:25])
            + "\n\nThe first passages are the city's most-referenced landmarks: include each as a highlight "
              "unless it clearly clashes with the interests. Return 6-10 highlights, up to 4 neighbourhoods "
              "and up to 4 culture tips.")
    draft, method = await structured("destination", DestinationDraft, DEST_SYSTEM, user,
                                     fallback=fallback, size="small", max_tokens=1600)
    ctx.methods["destination"] = method
    for h in draft.highlights:
        h.citations = [c for c in h.citations if c in known]
    for n in draft.neighbourhoods:
        n.citations = [c for c in n.citations if c in known]
    # keep highlights that are grounded: a known OSM place, or named in a passage it cites
    draft.highlights = [h for h in draft.highlights
                        if best_match(h.name, pois) or named_in(h.name, passages, h.citations)]
    out = {"blurb": draft.blurb, "highlights": [h.model_dump() for h in draft.highlights],
           "neighbourhoods": [n.model_dump() for n in draft.neighbourhoods],
           "culture_tips": draft.culture_tips[:4], "pois": pois, "passage_ids": [p.id for p in passages],
           "osm_provenance": osm.get("provenance")}
    await ctx.emit("partial", {"section": "destination", "payload": {
        "blurb": draft.blurb, "highlights": out["highlights"], "neighbourhoods": out["neighbourhoods"]}})
    return {"destination": out, "evidence": evidence_from(passages), "retrieval": {**r1, **r2},
            "_message": f"{len(draft.highlights)} highlights from {len(passages)} passages + {len(pois)} OSM places"}


# ---------------------------------------------------------------------------------------------
# weather
# ---------------------------------------------------------------------------------------------


def weather_overview(days: list[dict[str, Any]]) -> str:
    if not days:
        return "Weather data is unavailable for these dates; pack for changeable conditions."
    lo = min(d["t_min"] for d in days)
    hi = max(d["t_max"] for d in days)
    wet = [d for d in days if is_wet(d)]
    est = all(d["provenance"] == "estimate" for d in days)
    head = (f"Typically {lo:.0f}-{hi:.0f}°C on these dates (last year's weather, an estimate)" if est
            else f"{lo:.0f}-{hi:.0f}°C")
    if wet:
        when = ", ".join(date.fromisoformat(d["date"]).strftime("%a %d %b") for d in wet[:4])
        return f"{head}; wet on {when}, so those days lean indoors."
    return f"{head}; mostly dry."


@agent_node("weather", gap=lambda s, m: {"weather": {"days": [], "overview": weather_overview([]), "error": m}})
async def weather(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req, b = req_of(state), state["brief"]
    tools = (await hub()).toolbox("weather", ctx.tool_emit)
    data = await tools.call("weather", "forecast", lat=b["lat"], lon=b["lon"], start=req.start_date,
                            end=req.end_date)
    days = data.get("days") or []
    overview = weather_overview(days)
    out = {"days": days, "overview": overview, "provenance": data.get("provenance", "unavailable"),
           "note": data.get("note", "")}
    await ctx.emit("partial", {"section": "weather", "payload": {"days": days, "overview": overview}})
    evidence = {OPEN_METEO["id"]: OPEN_METEO} if days else {}
    return {"weather": out, "evidence": evidence,
            "_message": overview if days else "Weather unavailable (labelled in the plan)"}


# ---------------------------------------------------------------------------------------------
# stays
# ---------------------------------------------------------------------------------------------

StayKind = Literal["hotel", "hostel", "guest_house", "apartment", "resort"]
STYLE_KINDS = {"budget": "hostel,guest_house,hotel", "mid": "hotel,guest_house,apartment", "luxury": "hotel,resort"}
KIND_PRICE = {"hostel": 0.45, "guest_house": 0.75, "apartment": 0.9, "hotel": 1.0, "resort": 1.5}


class StayPick(BaseModel):
    name: str
    kind: StayKind = "hotel"
    area: str = ""
    why: str
    citations: list[str] = Field(default_factory=list)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        v = str(v or "hotel").lower().replace(" ", "_").replace("-", "_")
        return v if v in KIND_PRICE else {"guesthouse": "guest_house", "ryokan": "guest_house",
                                          "homestay": "guest_house", "bnb": "guest_house"}.get(v, "hotel")


class StaysDraft(BaseModel):
    stays: list[StayPick] = Field(default_factory=list)


STAYS_SYSTEM = (
    "You are the Stays specialist. Pick 3-5 places to stay that fit the travel style and budget, ONLY "
    "from the OpenStreetMap list or places named in the guidebook passages (cite those ids). Spread them "
    "across good areas. `why` is one sentence.")


def rooms_for(req: Any) -> int:
    return max(1, math.ceil(req.adults / 2))


@agent_node("stays", gap=lambda s, m: {"stays": {"items": [], "error": m}})
async def stays(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req, b = req_of(state), state["brief"]
    city = b["name"]
    tools = (await hub()).toolbox("stays", ctx.tool_emit)
    (passages, rec), osm, profile = await asyncio.gather(
        retrieve(ctx, "stays", f"where to stay in {city} {req.stay_style} accommodation areas", city, ["Sleep"], k=5),
        tools.call("places", "search_places", lat=b["lat"], lon=b["lon"], kind=STYLE_KINDS[req.stay_style],
                   radius_m=12000 if b.get("region") else 3500, limit=15),
        tools.call("money", "cost_profile", country_code=b.get("country_code") or "", style=req.stay_style),
    )
    cands = osm.get("results") or []
    cluster_areas(cands, b)
    known = {p.id for p in passages}
    band_usd = float(profile.get("stay") or 100)
    fx = b.get("fx") or {}

    def fallback() -> StaysDraft:
        picks = []
        for c in cands[:4]:
            kind = c["kind"] if c["kind"] in KIND_PRICE else "hotel"
            picks.append(StayPick(name=c["name"], kind=kind, area=c.get("area") or "",
                                  why=f"A {kind.replace('_', ' ')} in {c.get('area') or city} from OpenStreetMap."))
        return StaysDraft(stays=picks)

    user = (f"City: {city}. Style: {req.stay_style}. Travellers: {req.adults} adults, {req.children} children. "
            f"Total trip budget: {req.budget:.0f} {req.currency} for {req.nights} nights.\n\n"
            f"Guidebook (Sleep):\n{passages_block(passages, 280)}\n\nOpenStreetMap places (name | kind | area):\n"
            + "\n".join(f"- {c['name']} | {c['kind']} | {c.get('area', '')}" for c in cands))
    draft, method = await structured("stays", StaysDraft, STAYS_SYSTEM, user, fallback=fallback,
                                     size="small", max_tokens=900)
    ctx.methods["stays"] = method
    items, evidence = [], evidence_from(passages)
    for pick in draft.stays[:5]:
        cites = [c for c in pick.citations if c in known]
        match = best_match(pick.name, cands)
        if not match and not named_in(pick.name, passages, cites):
            continue  # neither on the map nor named in the guidebook: drop it (no invented hotels)
        kind = (match["kind"] if match and match["kind"] in KIND_PRICE else pick.kind)
        stars = None
        if match and match.get("tags", {}).get("stars"):
            try:
                stars = float(match["tags"]["stars"])
            except ValueError:
                stars = None
        factor = KIND_PRICE.get(kind, 1.0) * (1 + 0.15 * ((stars or 3) - 3))
        price = usd_to(band_usd * factor * rooms_for(req), fx)
        if match:
            evidence[match["id"]] = osm_citation(match)
            cites.append(match["id"])
        items.append({
            "name": match["name"] if match else pick.name, "kind": kind,
            "area": pick.area or (match.get("area") if match else "") or city,
            "location": {"lat": match["lat"], "lon": match["lon"]} if match else None,
            "price_per_night": to_money(price, req.currency), "rating": stars, "why": pick.why,
            "provenance": "live" if match else "guidebook",
            "url": (match.get("tags", {}).get("website") or match.get("source_url")) if match else None,
            "citations": cites,
        })
    out = {"items": items, "band_usd": band_usd, "rooms": rooms_for(req), "price_note":
           "Nightly prices are estimates from a curated cost table (by country, style and property type)."}
    await ctx.emit("partial", {"section": "stays", "payload": {"items": items}})
    return {"stays": out, "evidence": evidence, "retrieval": rec,
            "_message": f"{len(items)} stays ({sum(1 for i in items if i['provenance'] == 'live')} on OpenStreetMap)"}


# ---------------------------------------------------------------------------------------------
# food
# ---------------------------------------------------------------------------------------------


class FoodDraftPick(BaseModel):
    name: str
    cuisine: str = "local"
    area: str = ""
    price_level: int = Field(2, ge=1, le=4)
    must_try: str
    diet_ok: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)

    @field_validator("price_level", mode="before")
    @classmethod
    def _level(cls, v: Any) -> int:
        if isinstance(v, str):
            v = v.count("$") or v.count("€") or (int(v) if v.isdigit() else 2)
        return max(1, min(4, int(v or 2)))


class FoodDraft(BaseModel):
    picks: list[FoodDraftPick] = Field(default_factory=list)


FOOD_SYSTEM = (
    "You are the Food specialist. Pick 5-8 places to eat ONLY from the OpenStreetMap list or places named "
    "in the guidebook passages (cite those ids). Respect the diet strictly: list in diet_ok only diets the "
    "place can really serve (use OSM diet tags and the passages). must_try = a dish to order.")


def _diet_ok(tags: dict[str, str]) -> list[str]:
    return [d for d in ("vegetarian", "vegan", "halal", "kosher") if tags.get(f"diet:{d}") in ("yes", "only")]


@agent_node("food", gap=lambda s, m: {"food": {"items": [], "error": m}})
async def food(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req, b = req_of(state), state["brief"]
    city = b["name"]
    diet = ", ".join(req.diet) or "no restrictions"
    tools = (await hub()).toolbox("food", ctx.tool_emit)
    (passages, rec), osm = await asyncio.gather(
        retrieve(ctx, "food", f"{city} local food dishes where to eat {' '.join(req.diet)}", city,
                 ["Eat", "Drink"], k=6),
        tools.call("places", "search_places", lat=b["lat"], lon=b["lon"], kind="restaurant,cafe,street_food",
                   radius_m=12000 if b.get("region") else 3000, limit=25),
    )
    # a travel plan recommends local places, not global fast-food chains
    cands = [c for c in osm.get("results") or [] if not _CHAIN_RE.search(c["name"])]
    cluster_areas(cands, b)
    known = {p.id for p in passages}

    def fallback() -> FoodDraft:
        ordered = sorted(cands, key=lambda c: -len(set(_diet_ok(c.get("tags", {}))) & set(req.diet)))
        return FoodDraft(picks=[FoodDraftPick(
            name=c["name"], cuisine=(c.get("tags", {}).get("cuisine") or c["kind"]).replace(";", ", "),
            area=c.get("area") or "", price_level=1 if c["kind"] == "street_food" else 2,
            must_try="Ask for the house speciality", diet_ok=_diet_ok(c.get("tags", {})))
            for c in ordered[:6]])

    user = (f"City: {city}. Diet: {diet}. Style: {req.stay_style}. Interests: {', '.join(req.interests)}.\n\n"
            f"Guidebook (Eat/Drink):\n{passages_block(passages, 300)}\n\nOpenStreetMap places "
            "(name | kind | cuisine | diet tags | area):\n"
            + "\n".join(f"- {c['name']} | {c['kind']} | {c.get('tags', {}).get('cuisine', '')} | "
                        f"{','.join(_diet_ok(c.get('tags', {})))} | {c.get('area', '')}" for c in cands))
    draft, method = await structured("food", FoodDraft, FOOD_SYSTEM, user, fallback=fallback,
                                     size="small", max_tokens=1300)
    ctx.methods["food"] = method
    items, evidence = [], evidence_from(passages)
    seen: set[str] = set()
    for pick in draft.picks[:8]:
        cites = [c for c in pick.citations if c in known]
        match = best_match(pick.name, cands)
        if not match and not named_in(pick.name, passages, cites):
            continue
        key = norm(match["name"] if match else pick.name)
        if key in seen:  # two picks resolving to the same place
            continue
        seen.add(key)
        diet_ok = sorted(set(pick.diet_ok) | set(_diet_ok(match.get("tags", {})) if match else set()))
        if match:
            evidence[match["id"]] = osm_citation(match)
            cites.append(match["id"])
        items.append({
            "name": match["name"] if match else pick.name, "cuisine": pick.cuisine,
            "area": pick.area or (match.get("area") if match else None) or None,
            "location": {"lat": match["lat"], "lon": match["lon"]} if match else None,
            "price_level": max(1, min(4, pick.price_level)), "must_try": pick.must_try,
            "diet_ok": [d.lower() for d in diet_ok], "provenance": "live" if match else "guidebook",
            "citations": cites,
        })
    await ctx.emit("partial", {"section": "food", "payload": {"items": items}})
    return {"food": {"items": items}, "evidence": evidence, "retrieval": rec,
            "_message": f"{len(items)} food picks for diet: {diet}"}


# ---------------------------------------------------------------------------------------------
# logistics
# ---------------------------------------------------------------------------------------------


class LogisticsDraft(BaseModel):
    getting_there_note: str = ""
    getting_around: str
    visa: str
    currency_note: str
    safety: list[str] = Field(default_factory=list)
    packing: list[str] = Field(default_factory=list)
    local_tips: list[str] = Field(default_factory=list)
    best_areas: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


LOGI_SYSTEM = (
    "You are the Logistics specialist. Write practical pre-trip guidance grounded in the guidebook "
    "passages (cite ids in `citations`). For visa, give general guidance only and tell the traveller to "
    "confirm with the official government source; never invent fees or rules. 3-5 items per list.")


def travel_estimate(km: float | None, domestic: bool = False) -> tuple[str, float, float]:
    """(mode, round-trip USD per person, one-way hours) - a rough rule of thumb.

    Domestic flights are priced on a cheaper curve: a short-haul domestic fare (e.g. Bengaluru-Jaipur,
    ~1,560 km) is a fraction of an international fare over the same distance."""
    if km is None:
        return "unknown", 0.0, 0.0
    if km < 40:
        return "local transport", 6.0, km / 25
    if km < 350:
        return "train or bus", 2 * (6 + 0.07 * km), km * 1.3 / 70
    if km < 700:
        return "train or drive", 2 * (10 + 0.08 * km), km * 1.3 / 85
    if domestic:
        return "flight", min(2 * (35 + 0.03 * km), 600.0), km / 750 + 2.5
    return "flight", min(2 * (45 + 0.075 * km), 1900.0), km / 750 + 2.5


@agent_node("logistics", gap=lambda s, m: {"logistics": {"pre_trip": None, "error": m}})
async def logistics(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req, b = req_of(state), state["brief"]
    city = b["name"]
    tools = (await hub()).toolbox("logistics", ctx.tool_emit)
    origin_geo: dict[str, Any] = {}
    searches = [
        retrieve(ctx, "logistics", f"how to get to {city} airport train", city, ["Get in"], k=3),
        retrieve(ctx, "logistics", f"getting around {city} public transport passes", city, ["Get around"], k=3),
        retrieve(ctx, "logistics", f"{city} safety scams health tips", city, ["Stay safe", "Stay healthy", "Cope"], k=3),
    ]
    if req.origin:
        results = await asyncio.gather(*searches, tools.call("places", "geocode", query=req.origin, limit=1))
        origin_geo = (results[-1].get("results") or [{}])[0]
        results = results[:-1]
    else:
        results = await asyncio.gather(*searches)
    passages = dedupe([p for ps, _ in results for p in ps])
    rec: dict[str, Any] = {}
    for _, r in results:
        rec.update(r)
    km = None
    if origin_geo.get("lat") is not None:
        d = await tools.call("places", "distance", a_lat=origin_geo["lat"], a_lon=origin_geo["lon"],
                             b_lat=b["lat"], b_lon=b["lon"], mode="flight")
        km = d.get("km")
    o_cc = (origin_geo.get("country_code") or "").upper()
    domestic = bool(o_cc) and o_cc == (b.get("country_code") or "").upper()
    mode, rt_usd, hours = travel_estimate(km, domestic)
    fx = b.get("fx") or {}
    travel_cost = usd_to(rt_usd * req.travellers, fx)
    known = {p.id for p in passages}
    month = req.start.strftime("%B")
    local_cur = fx.get("local_currency", "")
    rate = fx.get("local_to_trip")
    rate_txt = (f"1 {local_cur} ≈ {rate:.4g} {req.currency} (ECB rate via Frankfurter)"
                if rate and local_cur and local_cur != req.currency else f"Prices are in {local_cur or req.currency}.")

    def fallback() -> LogisticsDraft:
        around = next((p.text.split(":", 1)[-1].strip()[:240] for p in passages if p.section == "Get around"),
                      f"Use public transport and walk in central {city}.")
        safety = [p.text.split(":", 1)[-1].strip()[:160] for p in passages if p.section in ("Stay safe", "Cope")][:3]
        return LogisticsDraft(
            getting_around=around, visa=f"Check visa requirements for {b.get('country', 'your destination')} "
            "with the official government website before booking.", currency_note=rate_txt,
            safety=safety or ["Keep valuables secure in crowded places."],
            packing=["Comfortable walking shoes", "Universal power adapter", f"Layers suitable for {month}"],
            local_tips=[], best_areas=[])

    user = (f"Destination: {city}, {b.get('country', '')}. Travel month: {month}. Origin: {req.origin or 'not given'}"
            f"{f' (~{km:.0f} km away; likely {mode})' if km else ''}. Travellers: {req.travellers}. "
            f"Currency: {rate_txt}.\n\nGuidebook passages:\n{passages_block(passages, 300)}")
    draft, method = await structured("logistics", LogisticsDraft, LOGI_SYSTEM, user, fallback=fallback,
                                     size="small", max_tokens=1300)
    ctx.methods["logistics"] = method
    cites = [c for c in draft.citations if c in known] or [p.id for p in passages[:2]]
    duration = f"~{hours:.1f} h each way" if hours else "n/a"
    pre_trip = {
        "getting_there": {"mode": mode if km else "not estimated", "duration": duration,
                          "cost": to_money(travel_cost, req.currency),
                          "note": ((draft.getting_there_note + " ") if draft.getting_there_note else "")
                          + (f"Round trip for {req.travellers}, rough estimate from ~{km:.0f} km distance."
                             if km else "Add an origin to estimate travel to the destination.")},
        "getting_around": draft.getting_around, "visa": draft.visa,
        "currency_note": draft.currency_note if rate_txt.split(" (")[0] in draft.currency_note
        else f"{draft.currency_note} {rate_txt}".strip(),
        "safety": draft.safety[:5], "packing": draft.packing[:6], "local_tips": draft.local_tips[:5],
        "best_areas": draft.best_areas[:5], "citations": cites,
    }
    await ctx.emit("partial", {"section": "logistics", "payload": pre_trip})
    return {"logistics": {"pre_trip": pre_trip, "travel_km": km, "travel_cost": travel_cost},
            "evidence": evidence_from(passages), "retrieval": rec,
            "_message": f"Pre-trip guide ready ({mode if km else 'no origin given'})"}
