"""MCP server `weather`: Open-Meteo forecast (<= 16 days out) or same-dates-last-year normals.

Run standalone:  python -m voyager.mcp.servers.weather [--transport stdio|streamable-http] [--port 9201]

Every day carries its own provenance: `live` for the forecast, `estimate` for days filled from
last year's archive (the forecast horizon is 16 days, so a trip in 3 weeks is an estimate).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from voyager.mcp.http import fetch_json
from voyager.mcp.servers._run import run_cli

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HORIZON_DAYS = 15  # today + 15 = 16 forecast days

WMO: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
    81: "Rain showers", 82: "Violent rain showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def describe(code: int) -> str:
    return WMO.get(int(code), "Mixed conditions")


def is_wet(day: dict[str, Any]) -> bool:
    """Rainy enough that the itinerary should move activities indoors."""
    code = int(day.get("code", 0))
    return (day.get("precip_mm") or 0) >= 4 or (day.get("precip_prob") or 0) >= 65 or code >= 61


def _days(payload: dict[str, Any], provenance: str, shift_years: int = 0) -> list[dict[str, Any]]:
    daily = payload.get("daily") or {}
    out = []
    times = daily.get("time") or []
    for i, t in enumerate(times):
        def at(name: str, default: Any = None, i: int = i) -> Any:
            values = daily.get(name) or []
            v = values[i] if i < len(values) else None
            return default if v is None else v

        d = date.fromisoformat(t)
        if shift_years:
            try:
                d = d.replace(year=d.year + shift_years)
            except ValueError:  # 29 Feb
                d = d + timedelta(days=365 * shift_years)
        code = int(at("weather_code", 0))
        out.append({
            "date": d.isoformat(),
            "t_min": round(float(at("temperature_2m_min", 0.0)), 1),
            "t_max": round(float(at("temperature_2m_max", 0.0)), 1),
            "precip_mm": round(float(at("precipitation_sum", 0.0)), 1),
            "precip_prob": at("precipitation_probability_max"),
            "code": code,
            "summary": describe(code) + (" (typical for these dates)" if provenance == "estimate" else ""),
            "provenance": provenance,
        })
    return out


async def historical_normals(lat: float, lon: float, start: str, end: str) -> dict[str, Any]:
    """Weather on the same dates last year (Open-Meteo archive) as an estimate for future dates."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    try:
        ps, pe = s.replace(year=s.year - 1), e.replace(year=e.year - 1)
    except ValueError:
        ps, pe = s - timedelta(days=365), e - timedelta(days=365)
    # the archive lags a few days behind today
    latest = date.today() - timedelta(days=6)
    while pe > latest:
        ps, pe = ps - timedelta(days=365), pe - timedelta(days=365)
    shift = s.year - ps.year
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4), "start_date": ps.isoformat(),
        "end_date": pe.isoformat(), "timezone": "auto",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
    }
    res = await fetch_json(ARCHIVE_URL, params=params, ttl=30 * 86400)
    url = f"{ARCHIVE_URL}?latitude={params['latitude']}&longitude={params['longitude']}"
    if not res.ok:
        return {"days": [], "provenance": "unavailable", "source_url": url, "cached": False,
                "note": f"Open-Meteo archive unavailable ({res.error})."}
    return {"days": _days(res.data, "estimate", shift_years=shift), "provenance": "estimate",
            "source_url": url, "cached": res.cached,
            "note": f"Estimated from the same dates in {ps.year} (Open-Meteo archive); not a forecast."}


async def forecast(lat: float, lon: float, start: str, end: str) -> dict[str, Any]:
    """Daily forecast for [start, end]. Days beyond the 16-day horizon come from last year's archive
    and are labelled `estimate`."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    today = date.today()
    horizon = today + timedelta(days=FORECAST_HORIZON_DAYS)
    days: list[dict[str, Any]] = []
    notes: list[str] = []
    cached = True
    url = f"{FORECAST_URL}?latitude={round(lat, 4)}&longitude={round(lon, 4)}"
    live_start, live_end = max(s, today), min(e, horizon)
    if live_start <= live_end:
        params = {
            "latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "auto",
            "start_date": live_start.isoformat(), "end_date": live_end.isoformat(),
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "precipitation_probability_max",
        }
        res = await fetch_json(FORECAST_URL, params=params, ttl=3600)
        if res.ok:
            days += _days(res.data, "live")
            cached = cached and res.cached
            notes.append("Open-Meteo forecast")
        else:
            notes.append(f"forecast unavailable ({res.error})")
    have = {d["date"] for d in days}
    missing = [s + timedelta(days=i) for i in range((e - s).days + 1)
               if (s + timedelta(days=i)).isoformat() not in have]
    if missing:
        normals = await historical_normals(lat, lon, missing[0].isoformat(), missing[-1].isoformat())
        days += [d for d in normals["days"] if d["date"] not in have]
        cached = cached and normals.get("cached", False)
        notes.append(normals["note"])
        if not days:
            url = normals["source_url"]
    days.sort(key=lambda d: d["date"])
    provs = {d["provenance"] for d in days}
    provenance = "unavailable" if not days else ("live" if provs == {"live"} else
                                                 "estimate" if provs == {"estimate"} else "live")
    return {"days": days, "provenance": provenance, "source_url": url, "cached": cached and bool(days),
            "note": "; ".join(notes)}


def build_server() -> MCPServer:
    server = MCPServer("voyager-weather", instructions="Daily weather for trip dates (Open-Meteo, free).")
    server.tool(description="Daily forecast (max 16 days ahead); later days are filled with last year's "
                "weather for the same dates and labelled 'estimate'.")(forecast)
    server.tool(description="Same-dates-last-year daily weather (Open-Meteo archive), labelled 'estimate'.")(
        historical_normals)
    return server


if __name__ == "__main__":
    run_cli(build_server, default_port=9201)
