"""MCP server `places`: geocoding, OpenStreetMap place search and distances. No API keys.

* `geocode`       - cities via Open-Meteo geocoding; points of interest via Photon (komoot)
* `search_places` - hotels / food / sights around a point from OpenStreetMap, through a provider chain
                    with circuit breakers and one overall deadline: Overpass (mirrors raced) ->
                    Photon (tag-filtered search) -> Nominatim (1 request/s, per its usage policy).
                    All three serve OpenStreetMap data; the note says which one answered.
* `distance`      - haversine distance plus a rough travel time by mode

Run standalone:  python -m voyager.mcp.servers.places [--transport stdio|streamable-http] [--port 9202]
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from mcp.server.mcpserver import MCPServer

from voyager.mcp.http import Fetched, fetch_json
from voyager.mcp.servers._run import run_cli

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

KIND_FILTERS: dict[str, tuple[str, ...]] = {
    "hotel": ('["tourism"="hotel"]',),
    "hostel": ('["tourism"="hostel"]',),
    "guest_house": ('["tourism"="guest_house"]',),
    "apartment": ('["tourism"="apartment"]',),
    "resort": ('["leisure"="resort"]',),
    "restaurant": ('["amenity"="restaurant"]',),
    "cafe": ('["amenity"="cafe"]',),
    "street_food": ('["amenity"="fast_food"]', '["amenity"="food_court"]'),
    "attraction": ('["tourism"="attraction"]',),
    "museum": ('["tourism"="museum"]',),
    "viewpoint": ('["tourism"="viewpoint"]',),
    "temple": ('["amenity"="place_of_worship"]["wikidata"]', '["amenity"="place_of_worship"]["historic"]'),
    "park": ('["leisure"="park"]["wikidata"]', '["leisure"="garden"]["wikidata"]'),
}
# Photon fallback: (query word, osm_tag filter) per kind
PHOTON_KIND: dict[str, tuple[str, str]] = {
    "hotel": ("hotel", "tourism:hotel"), "hostel": ("hostel", "tourism:hostel"),
    "guest_house": ("guest house", "tourism:guest_house"), "apartment": ("apartment", "tourism:apartment"),
    "resort": ("resort", "leisure:resort"), "restaurant": ("restaurant", "amenity:restaurant"),
    "cafe": ("cafe", "amenity:cafe"), "street_food": ("food", "amenity:fast_food"),
    "attraction": ("museum", "tourism:museum"), "museum": ("museum", "tourism:museum"),
    "viewpoint": ("viewpoint", "tourism:viewpoint"), "temple": ("temple", "amenity:place_of_worship"),
    "park": ("park", "leisure:park"),
}
TAG_KIND = (
    ("tourism", "hotel", "hotel"), ("tourism", "hostel", "hostel"), ("tourism", "guest_house", "guest_house"),
    ("tourism", "apartment", "apartment"), ("leisure", "resort", "resort"),
    ("amenity", "restaurant", "restaurant"), ("amenity", "cafe", "cafe"), ("amenity", "fast_food", "street_food"),
    ("amenity", "food_court", "street_food"), ("tourism", "museum", "museum"),
    ("tourism", "viewpoint", "viewpoint"), ("amenity", "place_of_worship", "temple"),
    ("leisure", "park", "park"), ("leisure", "garden", "park"), ("tourism", "attraction", "attraction"),
)
KEEP_TAGS = ("cuisine", "diet:vegetarian", "diet:vegan", "diet:halal", "diet:kosher", "stars", "website",
             "opening_hours", "wikipedia", "wikidata", "addr:suburb", "addr:district", "addr:quarter",
             "addr:neighbourhood", "addr:city", "religion", "fee", "historic", "price_range")
SPEED_KMH = {"walk": 4.5, "transit": 20.0, "drive": 32.0, "train": 90.0, "flight": 750.0}
OVERPASS_DEADLINE_S = 6.0
SEARCH_DEADLINE_S = 30.0  # whole provider chain; the MCP call itself times out at 40 s
NOMINATIM_WORD = {"hotel": "hotel", "hostel": "hostel", "guest_house": "guest house", "apartment": "apartment",
                  "resort": "resort", "restaurant": "restaurant", "cafe": "cafe", "street_food": "fast food",
                  "attraction": "tourist attraction", "museum": "museum", "viewpoint": "viewpoint",
                  "temple": "temple", "park": "park"}
_DOWN_UNTIL: dict[str, float] = {}  # provider -> monotonic time until which it is skipped (circuit breaker)
_NOMINATIM_GATE: dict[int, list] = {}


def _down(provider: str) -> bool:
    return time.monotonic() < _DOWN_UNTIL.get(provider, 0.0)


def _trip(provider: str, seconds: float = 600) -> None:
    _DOWN_UNTIL[provider] = time.monotonic() + seconds


async def _nominatim(params: dict[str, Any]) -> Fetched:
    """Nominatim allows at most 1 request/second: requests are serialised and spaced (per event loop)."""
    loop = id(asyncio.get_running_loop())
    gate = _NOMINATIM_GATE.setdefault(loop, [asyncio.Lock(), 0.0])
    async with gate[0]:
        wait = gate[1] + 1.05 - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        res = await fetch_json(NOMINATIM_URL, params={"format": "jsonv2", "accept-language": "en", **params}, ttl=30 * 86400,
                               retries=0, timeout=8)
        gate[1] = time.monotonic()
    return res


def _nominatim_kind(row: dict[str, Any]) -> str:
    return _kind_of({row.get("category", ""): row.get("type", "")})
_PHOTON_SLOTS: dict[int, asyncio.Semaphore] = {}


def _photon_slots() -> asyncio.Semaphore:
    """Photon is a shared free service: at most 2 requests in flight (one semaphore per event loop)."""
    loop = id(asyncio.get_running_loop())
    if loop not in _PHOTON_SLOTS:
        _PHOTON_SLOTS[loop] = asyncio.Semaphore(2)
    return _PHOTON_SLOTS[loop]


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


# ---- geocoding ------------------------------------------------------------------------------
async def _geocode_city(query: str, limit: int) -> dict[str, Any]:
    name, _, country = (p.strip() for p in query.partition(","))
    res = await fetch_json(GEOCODE_URL, params={"name": name, "count": 10, "language": "en", "format": "json"},
                           ttl=30 * 86400)
    url = f"{GEOCODE_URL}?name={name}"
    if not res.ok:
        return {"results": [], "provenance": "unavailable", "source_url": url, "cached": False,
                "note": f"geocoding unavailable ({res.error})"}
    rows = list(res.data.get("results") or [])
    if country:
        c = country.lower()
        filtered = [r for r in rows if c in (r.get("country") or "").lower()
                    or c == (r.get("country_code") or "").lower() or c in (r.get("admin1") or "").lower()]
        rows = filtered or rows
    exact = [r for r in rows if (r.get("name") or "").lower() == name.lower()]
    rows = (exact or rows)
    if any(r.get("population") for r in rows):
        rows.sort(key=lambda r: -(r.get("population") or 0))
    out = [{
        "name": r.get("name", ""), "country": r.get("country", ""),
        "country_code": (r.get("country_code") or "").upper(), "admin1": r.get("admin1", ""),
        "lat": r.get("latitude"), "lon": r.get("longitude"), "population": r.get("population"),
        "timezone": r.get("timezone"), "kind": "city",
    } for r in rows[:limit] if r.get("latitude") is not None]
    weak = not out or (not out[0].get("population") and (out[0]["name"] or "").lower() != name.lower())
    if weak:  # GeoNames misses some alternate names (e.g. "Bangalore" -> Bengaluru): ask Nominatim
        alt = await _nominatim({"q": query, "featureType": "settlement", "addressdetails": 1, "limit": 3})
        hits = [h for h in (alt.data or []) if float(h.get("importance") or 0) >= 0.4] if alt.ok else []
        if hits:
            h = hits[0]
            addr = h.get("address") or {}
            out = [{"name": h.get("name") or name, "country": addr.get("country", ""),
                    "country_code": (addr.get("country_code") or "").upper(), "admin1": addr.get("state", ""),
                    "lat": float(h["lat"]), "lon": float(h["lon"]), "population": None, "timezone": None,
                    "kind": "city"}] + out
            return {"results": out[:limit], "provenance": "live", "source_url": f"{NOMINATIM_URL}?q={query}",
                    "cached": alt.cached, "note": "Nominatim (OpenStreetMap); GeoNames had no good match"}
    return {"results": out, "provenance": "live" if out else "unavailable", "source_url": url,
            "cached": res.cached, "note": "Open-Meteo geocoding (GeoNames)"}


async def _geocode_poi(query: str, limit: int, near_lat: float | None, near_lon: float | None) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query, "limit": limit, "lang": "en"}
    if near_lat is not None and near_lon is not None:
        params.update({"lat": round(near_lat, 4), "lon": round(near_lon, 4)})
    url = f"{PHOTON_URL}?q={query}"
    res = None if _down("photon") else await fetch_json(PHOTON_URL, params=params, ttl=30 * 86400, timeout=8)
    if res is None or not res.ok:
        if res is not None and "Timeout" in (res.error or ""):
            _trip("photon")
        nparams: dict[str, Any] = {"q": query, "limit": limit}
        if near_lat is not None and near_lon is not None:
            nparams.update({"viewbox": f"{near_lon - 0.4},{near_lat + 0.4},{near_lon + 0.4},{near_lat - 0.4}",
                            "bounded": 1})
        alt = await _nominatim(nparams)
        rows = alt.data if alt.ok and isinstance(alt.data, list) else []
        out = [{"name": h.get("name") or query, "country": "", "country_code": "", "city": "",
                "lat": float(h["lat"]), "lon": float(h["lon"]), "kind": h.get("type") or "poi",
                "source_url": f"https://www.openstreetmap.org/{h.get('osm_type', 'node')}/{h.get('osm_id', '')}"}
               for h in rows]
        return {"results": out, "provenance": "live" if out else "unavailable",
                "source_url": f"{NOMINATIM_URL}?q={query}", "cached": alt.cached if alt.ok else False,
                "note": "Nominatim (OpenStreetMap; Photon unavailable)" if out else
                f"Photon and Nominatim unavailable ({alt.error or 'no match'})"}
    out = []
    for f in res.data.get("features") or []:
        props, coords = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        otype = {"N": "node", "W": "way", "R": "relation"}.get(str(props.get("osm_type", "N")), "node")
        out.append({
            "name": props.get("name") or query, "country": props.get("country", ""),
            "country_code": (props.get("countrycode") or "").upper(), "city": props.get("city", ""),
            "lat": coords[1], "lon": coords[0], "kind": props.get("osm_value") or "poi",
            "source_url": f"https://www.openstreetmap.org/{otype}/{props.get('osm_id', '')}",
        })
    return {"results": out, "provenance": "live" if out else "unavailable", "source_url": url,
            "cached": res.cached, "note": "Photon geocoder (OpenStreetMap)"}


async def geocode(query: str, kind: str = "city", near_lat: float | None = None,
                  near_lon: float | None = None, limit: int = 5) -> dict[str, Any]:
    """Resolve a place name. kind='city' uses Open-Meteo geocoding, kind='poi' uses Photon (OSM),
    optionally biased toward (near_lat, near_lon)."""
    limit = max(1, min(int(limit), 10))
    if kind == "poi":
        return await _geocode_poi(query, limit, near_lat, near_lon)
    return await _geocode_city(query, limit)


# ---- place search ---------------------------------------------------------------------------
def _kind_of(tags: dict[str, str]) -> str:
    for key, value, kind in TAG_KIND:
        if tags.get(key) == value:
            return kind
    return "place"


def _notability(tags: dict[str, str]) -> float:
    score = 0.0
    if tags.get("wikidata") or tags.get("wikipedia"):
        score += 3
    if tags.get("website") or tags.get("contact:website"):
        score += 1
    if tags.get("stars"):
        try:
            score += min(float(tags["stars"]), 5) / 2
        except ValueError:
            pass
    if tags.get("cuisine"):
        score += 0.5
    if tags.get("opening_hours"):
        score += 0.3
    return score


async def _overpass(query: str) -> Fetched | None:
    """Race the Overpass mirrors; first good answer wins, all within the deadline."""
    if _down("overpass"):
        return None
    tasks = [asyncio.create_task(fetch_json(u, method="POST", form={"data": query}, ttl=7 * 86400,
                                            retries=0, timeout=OVERPASS_DEADLINE_S)) for u in OVERPASS_URLS]
    result = None
    try:
        for fut in asyncio.as_completed(tasks, timeout=OVERPASS_DEADLINE_S + 1):
            res = await fut
            if res.ok:
                result = res
                break
    except TimeoutError:
        result = None
    finally:
        for t in tasks:
            t.cancel()
    if result is None:
        _trip("overpass")
    return result


def _overpass_rows(data: dict[str, Any], lat: float, lon: float, radius_m: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows = []
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        name = tags.get("name:en") or tags.get("name")
        plat = el.get("lat") or (el.get("center") or {}).get("lat")
        plon = el.get("lon") or (el.get("center") or {}).get("lon")
        if not name or plat is None or plon is None or name.lower() in seen:
            continue
        seen.add(name.lower())
        dist = haversine_km(lat, lon, plat, plon) * 1000
        rows.append({
            "id": f"osm-{el.get('type', 'node')}-{el.get('id')}", "name": name, "kind": _kind_of(tags),
            "lat": round(plat, 6), "lon": round(plon, 6), "distance_m": round(dist),
            "area": tags.get("addr:suburb") or tags.get("addr:quarter") or tags.get("addr:neighbourhood")
                    or tags.get("addr:district") or "",
            "tags": {k: tags[k] for k in KEEP_TAGS if k in tags},
            "source_url": f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id')}",
            "_rank": _notability(tags) - dist / max(radius_m, 1) * 2,
        })
    return rows


async def _photon_rows(kinds: list[str], lat: float, lon: float, radius_m: int,
                       limit: int) -> tuple[list[dict[str, Any]], bool, str]:
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * max(math.cos(math.radians(lat)), 0.2))
    bbox = f"{lon - dlon:.5f},{lat - dlat:.5f},{lon + dlon:.5f},{lat + dlat:.5f}"
    pairs = list(dict.fromkeys(PHOTON_KIND[k] for k in kinds))

    async def one(q: str, tag: str) -> Fetched:
        async with _photon_slots():
            return await fetch_json(PHOTON_URL, params={"q": q, "osm_tag": tag, "bbox": bbox,
                                                        "limit": min(limit + 5, 20), "lang": "en"},
                                    ttl=7 * 86400, retries=0, timeout=6)

    if _down("photon"):
        return [], False, "Photon skipped (circuit open)"
    results = await asyncio.gather(*(one(q, t) for q, t in pairs))
    if any("Timeout" in (r.error or "") or "HTTP 5" in (r.error or "") for r in results):
        _trip("photon")  # overloaded or unreachable: skip it for 10 minutes
    rows: list[dict[str, Any]] = []
    cached, errors = True, []
    seen: set[str] = set()
    for (q, tag), res in zip(pairs, results, strict=True):
        if not res.ok:
            errors.append(res.error or "error")
            continue
        cached = cached and res.cached
        kind = next(k for k in kinds if PHOTON_KIND[k] == (q, tag))
        for i, f in enumerate(res.data.get("features") or []):
            props, coords = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
            name = props.get("name")
            if not name or len(coords) < 2 or name.lower() in seen:
                continue
            seen.add(name.lower())
            plat, plon = coords[1], coords[0]
            dist = haversine_km(lat, lon, plat, plon) * 1000
            otype = {"N": "node", "W": "way", "R": "relation"}.get(str(props.get("osm_type", "N")), "node")
            rows.append({
                "id": f"osm-{otype}-{props.get('osm_id')}", "name": name, "kind": kind,
                "lat": round(plat, 6), "lon": round(plon, 6), "distance_m": round(dist),
                "area": props.get("district") or props.get("locality") or "", "tags": {},
                "source_url": f"https://www.openstreetmap.org/{otype}/{props.get('osm_id')}",
                "_rank": -i * 0.2 - dist / max(radius_m, 1),
            })
    return rows, cached and bool(rows), "; ".join(errors)


async def _nominatim_rows(kinds: list[str], lat: float, lon: float, radius_m: int,
                          limit: int) -> tuple[list[dict[str, Any]], bool, str]:
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * max(math.cos(math.radians(lat)), 0.2))
    box = f"{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f},{lat - dlat:.5f}"
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cached, errors = True, []
    for word in list(dict.fromkeys(NOMINATIM_WORD[k] for k in kinds))[:3]:  # 1 req/s: keep it short
        res = await _nominatim({"q": word, "viewbox": box, "bounded": 1, "extratags": 1, "addressdetails": 1,
                                "limit": min(limit, 15)})
        if not res.ok or not isinstance(res.data, list):
            errors.append(res.error or "error")
            continue
        cached = cached and res.cached
        for i, h in enumerate(res.data):
            name = h.get("name")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            plat, plon = float(h["lat"]), float(h["lon"])
            tags = h.get("extratags") or {}
            addr = h.get("address") or {}
            dist = haversine_km(lat, lon, plat, plon) * 1000
            rows.append({
                "id": f"osm-{h.get('osm_type', 'node')}-{h.get('osm_id')}", "name": name, "kind": _nominatim_kind(h),
                "lat": round(plat, 6), "lon": round(plon, 6), "distance_m": round(dist),
                "area": addr.get("suburb") or addr.get("neighbourhood") or addr.get("quarter") or "",
                "tags": {k: tags[k] for k in KEEP_TAGS if k in tags},
                "source_url": f"https://www.openstreetmap.org/{h.get('osm_type', 'node')}/{h.get('osm_id')}",
                "_rank": _notability(tags) - i * 0.2 - dist / max(radius_m, 1),
            })
    return rows, cached and bool(rows), "; ".join(errors)


async def search_places(lat: float, lon: float, kind: str, radius_m: int = 3000, limit: int = 15) -> dict[str, Any]:
    """OpenStreetMap places around a point. `kind` is one kind or a comma-separated list of:
    hotel, hostel, guest_house, apartment, resort, restaurant, cafe, street_food, attraction, museum,
    viewpoint, temple, park."""
    try:
        return await asyncio.wait_for(_search_places(lat, lon, kind, radius_m, limit), timeout=SEARCH_DEADLINE_S)
    except TimeoutError:
        return {"results": [], "provenance": "unavailable", "cached": False,
                "source_url": f"https://www.openstreetmap.org/#map=15/{lat:.4f}/{lon:.4f}",
                "note": f"OpenStreetMap providers did not answer within {SEARCH_DEADLINE_S:.0f} s"}


async def _search_places(lat: float, lon: float, kind: str, radius_m: int = 3000, limit: int = 15) -> dict[str, Any]:
    """OpenStreetMap places around a point. `kind` is one kind or a comma-separated list of:
    hotel, hostel, guest_house, apartment, resort, restaurant, cafe, street_food, attraction, museum,
    viewpoint, temple, park."""
    kinds = [k.strip() for k in kind.split(",") if k.strip() in KIND_FILTERS]
    if not kinds:
        return {"results": [], "provenance": "unavailable", "source_url": "", "cached": False,
                "note": f"unknown kind {kind!r}; use {sorted(KIND_FILTERS)}"}
    radius_m = max(300, min(int(radius_m), 15000))
    limit = max(1, min(int(limit), 40))
    clauses = "".join(
        f'nw{flt}["name"](around:{radius_m},{lat:.5f},{lon:.5f});'
        for k in kinds for flt in KIND_FILTERS[k]
    )
    query = f"[out:json][timeout:10];({clauses});out center tags qt 300;"
    src = f"https://www.openstreetmap.org/#map=15/{lat:.4f}/{lon:.4f}"
    res = await _overpass(query)
    if res is not None:
        rows, cached, via, err = _overpass_rows(res.data, lat, lon, radius_m), res.cached, "Overpass", ""
    else:
        rows, cached, err = await _photon_rows(kinds, lat, lon, radius_m, limit)
        via = "Photon (Overpass unavailable)"
        if not rows:
            rows, cached, err2 = await _nominatim_rows(kinds, lat, lon, radius_m, limit)
            via, err = "Nominatim (Overpass and Photon unavailable)", f"{err}; {err2}"
    if not rows:
        return {"results": [], "provenance": "unavailable", "source_url": src, "cached": False,
                "note": f"no OSM places found ({err or 'empty result'})"}
    rows.sort(key=lambda r: -r["_rank"])
    # spread across kinds so "hotel,hostel" doesn't return only hotels
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    picked: list[dict[str, Any]] = []
    while len(picked) < limit and any(by_kind.values()):
        for k in list(by_kind):
            if by_kind[k] and len(picked) < limit:
                picked.append(by_kind[k].pop(0))
    for r in picked:
        r.pop("_rank", None)
    return {"results": picked, "provenance": "live", "source_url": src, "cached": cached,
            "note": f"OpenStreetMap via {via}: {len(rows)} matches within {radius_m} m"}


async def distance(a_lat: float, a_lon: float, b_lat: float, b_lon: float, mode: str = "walk") -> dict[str, Any]:
    """Great-circle distance and a rough travel time. mode: walk | transit | drive | train | flight."""
    km = haversine_km(a_lat, a_lon, b_lat, b_lon)
    speed = SPEED_KMH.get(mode, SPEED_KMH["transit"])
    road_factor = 1.0 if mode == "flight" else 1.3
    hours = km * road_factor / speed + (2.5 if mode == "flight" else 0.0)
    return {"km": round(km, 2), "mode": mode, "minutes": round(hours * 60), "provenance": "estimate",
            "source_url": "https://en.wikipedia.org/wiki/Haversine_formula",
            "note": "straight-line distance x1.3 for ground travel; rough average speeds"}


def build_server() -> MCPServer:
    server = MCPServer("voyager-places", instructions="Geocoding and OpenStreetMap places (free, no key).")
    server.tool(description="Geocode a city (kind='city') or a point of interest (kind='poi').")(geocode)
    server.tool(description="Find named OpenStreetMap places of given kinds around a point.")(search_places)
    server.tool(description="Distance and rough travel time between two points.")(distance)
    return server


if __name__ == "__main__":
    run_cli(build_server, default_port=9202)
