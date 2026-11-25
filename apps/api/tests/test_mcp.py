from __future__ import annotations

from datetime import date, timedelta

import mocks
import pytest

from voyager.mcp import http as mcp_http
from voyager.mcp.hub import MCPHub, ToolDenied, allowed
from voyager.mcp.servers import places

pytestmark = pytest.mark.anyio


async def test_servers_list_tools_over_mcp(hub: MCPHub) -> None:
    cat = hub.catalog()
    assert cat == {"weather": ["forecast", "historical_normals"], "places": ["distance", "geocode", "search_places"],
                   "money": ["convert", "cost_profile"]}
    assert all(hub.healthy.values())


async def test_forecast_live_then_estimate(hub: MCPHub) -> None:
    s = date.today() + timedelta(days=13)
    e = s + timedelta(days=5)  # crosses the 16-day horizon
    events = []

    async def emit(ev):
        events.append(ev)

    data = await hub.toolbox("weather", emit).call("weather", "forecast", lat=35.0, lon=135.7,
                                                   start=s.isoformat(), end=e.isoformat())
    provs = [d["provenance"] for d in data["days"]]
    assert len(data["days"]) == 6
    assert "live" in provs and "estimate" in provs
    assert provs.index("estimate") > provs.index("live")
    assert data["source_url"].startswith("https://")
    assert events and events[0]["server"] == "weather" and events[0]["tool"] == "forecast"
    assert set(events[0]) == {"type", "agent", "server", "tool", "provenance", "summary", "ms"}


async def test_geocode_city_and_poi(hub: MCPHub) -> None:
    tb = hub.toolbox("logistics")
    city = await tb.call("places", "geocode", query="Kyoto")
    assert city["provenance"] == "live" and city["results"][0]["country_code"] == "JP"
    poi = await tb.call("places", "geocode", query="Fushimi Inari", kind="poi", near_lat=35.0, near_lon=135.7)
    assert poi["results"][0]["source_url"].startswith("https://www.openstreetmap.org/")


async def test_search_places_overpass_parsing(hub: MCPHub) -> None:
    data = await hub.toolbox("stays").call("places", "search_places", lat=35.02, lon=135.75,
                                           kind="hotel,hostel,guest_house", radius_m=3000, limit=10)
    kinds = {r["kind"] for r in data["results"]}
    assert {"hotel", "hostel", "guest_house"} <= kinds
    first = data["results"][0]
    assert first["id"].startswith("osm-node-") and first["source_url"].startswith("https://www.openstreetmap.org/")
    assert "Overpass" in data["note"]


async def test_search_places_falls_back_to_photon_when_overpass_down(hub: MCPHub) -> None:
    def handler(request):
        if "overpass" in request.url.host:
            return mocks.httpx.Response(504, text="gateway timeout")
        return mocks.handler(request)

    mcp_http.set_transport(mocks.transport(handler))
    data = await hub.toolbox("food").call("places", "search_places", lat=35.02, lon=135.75,
                                          kind="restaurant", radius_m=2000, limit=5)
    assert data["provenance"] == "live" and data["results"]
    assert "Photon" in data["note"]
    assert places._down("overpass")  # circuit breaker opened


async def test_search_places_falls_back_to_nominatim_when_overpass_and_photon_down(hub: MCPHub) -> None:
    def handler(request):
        if "overpass" in request.url.host or request.url.host == "photon.komoot.io":
            return mocks.httpx.Response(503, text="down")
        return mocks.handler(request)

    mcp_http.set_transport(mocks.transport(handler))
    data = await hub.toolbox("stays").call("places", "search_places", lat=35.02, lon=135.75, kind="hotel",
                                           radius_m=2000, limit=5)
    assert data["provenance"] == "live" and "Nominatim" in data["note"]
    assert data["results"][0]["kind"] == "hotel" and data["results"][0]["source_url"].startswith("https://www.openstreetmap.org/")


async def test_city_geocode_falls_back_to_nominatim_for_alternate_names(hub: MCPHub) -> None:
    out = await hub.toolbox("logistics").call("places", "geocode", query="Bangalore")
    assert out["results"][0]["country_code"] == "IN" and "Nominatim" in out["note"]


async def test_money_convert_and_cost_profile(hub: MCPHub) -> None:
    tb = hub.toolbox("logistics")
    out = await tb.call("money", "convert", amount=100, from_currency="USD", to_currency="JPY")
    assert out["amount"] == 15000 and out["provenance"] == "live"
    est = await tb.call("money", "convert", amount=10, from_currency="USD", to_currency="AED")
    assert est["provenance"] == "estimate" and est["amount"] == pytest.approx(36.7, rel=0.01)
    prof = await tb.call("money", "cost_profile", country_code="JP", style="budget")
    assert prof["provenance"] == "estimate" and prof["stay"] < 100 and "estimate" in prof["note"]


async def test_tool_failure_becomes_unavailable(hub: MCPHub) -> None:
    mcp_http.set_transport(mocks.transport(mocks.failing_handler))
    events = []

    async def emit(ev):
        events.append(ev)

    data = await hub.toolbox("weather", emit).call("weather", "forecast", lat=1.0, lon=1.0,
                                                   start=date.today().isoformat(), end=date.today().isoformat())
    assert data["provenance"] == "unavailable" and data["days"] == []
    assert events[-1]["provenance"] == "unavailable"


async def test_cache_hit_is_reported_as_cached(hub: MCPHub) -> None:
    events = []

    async def emit(ev):
        events.append(ev)

    tb = hub.toolbox("logistics", emit)
    await tb.call("places", "geocode", query="Kyoto")
    await tb.call("places", "geocode", query="Kyoto")
    assert [e["provenance"] for e in events] == ["live", "cached"]


async def test_allow_list_enforced(hub: MCPHub) -> None:
    assert allowed("weather", "weather", "forecast")
    assert not allowed("food", "money", "convert")
    with pytest.raises(ToolDenied):
        await hub.toolbox("food").call("money", "convert", amount=1, from_currency="USD", to_currency="EUR")


async def test_distance_tool(hub: MCPHub) -> None:
    out = await hub.toolbox("logistics").call("places", "distance", a_lat=19.07, a_lon=72.88, b_lat=35.02,
                                              b_lon=135.75, mode="flight")
    assert 6000 < out["km"] < 7000 and out["provenance"] == "estimate"
