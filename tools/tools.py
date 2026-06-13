# ============================================================
# tools/tools.py — MCP Tool Registry + All Tool Implementations
# ============================================================
# PURPOSE:
#   Implements ALL external-API tools used by agents AND wraps
#   them in a simple MCP (Model Context Protocol) style registry
#   so LangChain ToolAgent can discover and invoke them by name.
#
# Tools included:
#   1. WeatherTool      — OpenWeatherMap current + forecast
#   2. MapsTool         — Google Maps distance, duration, route
#   3. HotelSearchTool  — Amadeus hotel search API
#   4. RestaurantTool   — Simulated restaurant data (production: Google Places)
#   5. FlightSearchTool — Amadeus flight offers search
#
# WHY MCP Registry?
#   A centralised registry decouples tool discovery from agent
#   implementation.  New tools can be added without touching agent
#   code — just register them here and agents will find them.
# ============================================================

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Type

import requests
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import api_config


# ══════════════════════════════════════════════════════════════
# SECTION 1 — Base Classes & Mock Fallback
# ══════════════════════════════════════════════════════════════

def _mock_response(tool_name: str, params: dict) -> dict:
    """
    Returns realistic mock data when real API keys are unavailable.
    Used in development / demo mode so the pipeline can run end-to-end
    without live credentials.
    """
    logger.warning(f"[{tool_name}] API key not configured — returning mock data.")
    mocks = {
        "weather": {
            "temperature": 24,
            "feels_like": 22,
            "humidity": 65,
            "description": "Partly cloudy",
            "wind_speed": 14,
            "forecast": [
                {"date": "Day+1", "temp_high": 26, "temp_low": 18, "description": "Sunny"},
                {"date": "Day+2", "temp_high": 22, "temp_low": 17, "description": "Cloudy"},
                {"date": "Day+3", "temp_high": 20, "temp_low": 15, "description": "Rain"},
                {"date": "Day+4", "temp_high": 25, "temp_low": 19, "description": "Sunny"},
                {"date": "Day+5", "temp_high": 27, "temp_low": 20, "description": "Sunny"},
            ],
        },
        "maps": {
            "distance_km": 1400,
            "duration_hours": 2.5,
            "route_summary": "Direct route via major highways",
            "waypoints": [],
        },
        "hotel": {
            "hotels": [
                {"name": "Grand Central Hotel", "stars": 4, "price_per_night": 120, "rating": 4.3},
                {"name": "Budget Inn Express", "stars": 2, "price_per_night": 45, "rating": 3.8},
                {"name": "Family Suites Resort", "stars": 3, "price_per_night": 85, "rating": 4.1},
            ]
        },
        "restaurant": {
            "restaurants": [
                {"name": "Local Kitchen", "cuisine": "Local", "rating": 4.5, "price_range": "$$"},
                {"name": "Veggie Delight", "cuisine": "Vegetarian", "rating": 4.2, "price_range": "$"},
                {"name": "Seafood Palace", "cuisine": "Seafood", "rating": 4.7, "price_range": "$$$"},
            ]
        },
        "flight": {
            "flights": [
                {"airline": "AirExpress", "departure": "08:00", "arrival": "10:30", "price_usd": 280, "stops": 0},
                {"airline": "BudgetJet", "departure": "14:00", "arrival": "18:45", "price_usd": 165, "stops": 1},
            ]
        },
    }
    return mocks.get(tool_name, {"status": "mock", "data": {}})


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Weather Tool
# ══════════════════════════════════════════════════════════════

class WeatherToolInput(BaseModel):
    """Input schema for WeatherTool."""
    city: str = Field(description="City name, e.g. 'Paris'")
    country_code: str = Field(default="", description="ISO 3166 country code, e.g. 'FR'")


class WeatherTool(BaseTool):
    """
    Fetches current weather + 5-day forecast from OpenWeatherMap.

    Uses the /weather endpoint for current conditions and
    /forecast for the 5-day 3-hourly forecast, then condenses
    that into daily summaries.
    """
    name: str = "weather_tool"
    description: str = (
        "Get current weather conditions and 5-day forecast for any city. "
        "Input: city name and optional country code."
    )
    args_schema: Type[BaseModel] = WeatherToolInput

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _call_api(self, city: str, country_code: str) -> dict:
        if not api_config.openweather_api_key:
            return _mock_response("weather", {"city": city})

        base_url = "https://api.openweathermap.org/data/2.5"
        q = f"{city},{country_code}" if country_code else city
        params = {
            "q": q,
            "appid": api_config.openweather_api_key,
            "units": "metric",
        }

        # Current weather
        cur_resp = requests.get(f"{base_url}/weather", params=params, timeout=10)
        cur_resp.raise_for_status()
        cur = cur_resp.json()

        # 5-day forecast
        fc_resp = requests.get(f"{base_url}/forecast", params=params, timeout=10)
        fc_resp.raise_for_status()
        fc_raw = fc_resp.json()

        # Condense 3-hourly forecast into daily
        daily: Dict[str, dict] = {}
        for item in fc_raw.get("list", []):
            date = item["dt_txt"][:10]
            if date not in daily:
                daily[date] = {"temps": [], "descriptions": []}
            daily[date]["temps"].append(item["main"]["temp"])
            daily[date]["descriptions"].append(item["weather"][0]["main"])

        forecast = [
            {
                "date": d,
                "temp_high": round(max(v["temps"]), 1),
                "temp_low": round(min(v["temps"]), 1),
                "description": max(set(v["descriptions"]), key=v["descriptions"].count),
            }
            for d, v in list(daily.items())[:7]  # Up to 7 days
        ]

        return {
            "temperature": cur["main"]["temp"],
            "feels_like": cur["main"]["feels_like"],
            "humidity": cur["main"]["humidity"],
            "description": cur["weather"][0]["description"],
            "wind_speed": cur["wind"]["speed"] * 3.6,  # m/s → km/h
            "forecast": forecast,
        }

    def _run(self, city: str, country_code: str = "") -> str:
        """Execute the tool and return JSON string."""
        logger.info(f"[WeatherTool] Fetching weather for {city}")
        try:
            data = self._call_api(city, country_code)
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[WeatherTool] Error: {e}")
            return json.dumps(_mock_response("weather", {"city": city}))

    async def _arun(self, city: str, country_code: str = "") -> str:
        """Async version — delegates to sync for simplicity."""
        return self._run(city, country_code)


# ══════════════════════════════════════════════════════════════
# SECTION 3 — Maps Tool
# ══════════════════════════════════════════════════════════════

class MapsToolInput(BaseModel):
    origin: str = Field(description="Origin city or address")
    destination: str = Field(description="Destination city or address")
    mode: str = Field(default="driving", description="driving | transit | walking | bicycling")


class MapsTool(BaseTool):
    """
    Calculates distance and travel time between two locations
    using the Google Maps Distance Matrix API.
    """
    name: str = "maps_tool"
    description: str = (
        "Calculate travel distance and duration between origin and destination. "
        "Supports driving, transit, walking, and bicycling modes."
    )
    args_schema: Type[BaseModel] = MapsToolInput

    def _run(self, origin: str, destination: str, mode: str = "driving") -> str:
        logger.info(f"[MapsTool] {origin} → {destination} via {mode}")

        if not api_config.google_maps_api_key:
            return json.dumps(_mock_response("maps", {}))

        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origin,
            "destinations": destination,
            "mode": mode,
            "key": api_config.google_maps_api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            element = data["rows"][0]["elements"][0]
            return json.dumps({
                "distance_km": element["distance"]["value"] / 1000,
                "duration_hours": element["duration"]["value"] / 3600,
                "distance_text": element["distance"]["text"],
                "duration_text": element["duration"]["text"],
                "status": element["status"],
            })
        except Exception as e:
            logger.error(f"[MapsTool] Error: {e}")
            return json.dumps(_mock_response("maps", {}))

    async def _arun(self, origin: str, destination: str, mode: str = "driving") -> str:
        return self._run(origin, destination, mode)


# ══════════════════════════════════════════════════════════════
# SECTION 4 — Hotel Search Tool
# ══════════════════════════════════════════════════════════════

class HotelToolInput(BaseModel):
    city_code: str = Field(description="IATA city code, e.g. 'LON' for London")
    check_in: str = Field(description="YYYY-MM-DD")
    check_out: str = Field(description="YYYY-MM-DD")
    adults: int = Field(default=2)


class HotelSearchTool(BaseTool):
    """
    Searches for hotels via the Amadeus Hotel Search API.
    Falls back to mock data when keys are not configured.
    """
    name: str = "hotel_search_tool"
    description: str = (
        "Search for available hotels at a destination. "
        "Input: IATA city code, check-in/check-out dates, number of adults."
    )
    args_schema: Type[BaseModel] = HotelToolInput

    def _get_amadeus_token(self) -> Optional[str]:
        """Obtain OAuth2 bearer token from Amadeus."""
        if not api_config.amadeus_api_key or api_config.amadeus_api_key in ("demo", "your_amadeus_api_key_here", ""):
            return None
        url = "https://test.api.amadeus.com/v1/security/oauth2/token"
        resp = requests.post(url, data={
            "grant_type": "client_credentials",
            "client_id": api_config.amadeus_api_key,
            "client_secret": api_config.amadeus_api_secret,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json().get("access_token")

    def _run(
        self, city_code: str, check_in: str, check_out: str, adults: int = 2
    ) -> str:
        logger.info(f"[HotelTool] Searching hotels in {city_code}")

        token = self._get_amadeus_token()
        if not token:
            return json.dumps(_mock_response("hotel", {}))

        try:
            # Step 1: Get hotel IDs in the city
            hotels_url = "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city"
            headers = {"Authorization": f"Bearer {token}"}
            ids_resp = requests.get(
                hotels_url,
                headers=headers,
                params={"cityCode": city_code},
                timeout=10,
            )
            ids_resp.raise_for_status()
            hotel_ids = [
                h["hotelId"] for h in ids_resp.json().get("data", [])[:10]
            ]

            # Step 2: Get offers for those hotels
            offers_url = "https://test.api.amadeus.com/v3/shopping/hotel-offers"
            offers_resp = requests.get(
                offers_url,
                headers=headers,
                params={
                    "hotelIds": ",".join(hotel_ids),
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "adults": adults,
                },
                timeout=15,
            )
            offers_resp.raise_for_status()
            raw_hotels = offers_resp.json().get("data", [])

            hotels = [
                {
                    "name": h["hotel"]["name"],
                    "stars": h["hotel"].get("rating", 3),
                    "price_per_night": float(
                        h["offers"][0]["price"]["total"]
                    ) if h.get("offers") else 100.0,
                    "rating": 4.0,
                }
                for h in raw_hotels[:10]
            ]
            return json.dumps({"hotels": hotels})
        except Exception as e:
            logger.error(f"[HotelTool] Error: {e}")
            return json.dumps(_mock_response("hotel", {}))

    async def _arun(
        self, city_code: str, check_in: str, check_out: str, adults: int = 2
    ) -> str:
        return self._run(city_code, check_in, check_out, adults)


# ══════════════════════════════════════════════════════════════
# SECTION 5 — Restaurant Tool
# ══════════════════════════════════════════════════════════════

class RestaurantToolInput(BaseModel):
    city: str = Field(description="City to search restaurants in")
    cuisine: str = Field(default="all", description="Cuisine type filter")
    dietary: str = Field(default="no preference", description="Dietary filter")


class RestaurantTool(BaseTool):
    """
    Returns restaurant recommendations for a city.
    Production version would call Google Places API.
    Current implementation uses curated mock data enriched by city.
    """
    name: str = "restaurant_tool"
    description: str = (
        "Find restaurant recommendations for a destination city. "
        "Filter by cuisine type and dietary preference."
    )
    args_schema: Type[BaseModel] = RestaurantToolInput

    # Curated city-specific data
    CITY_DATA: dict = {
        "paris": [
            {"name": "Le Comptoir du Relais", "cuisine": "French Bistro", "rating": 4.6, "price_range": "$$$"},
            {"name": "Breizh Café", "cuisine": "Crêpes", "rating": 4.4, "price_range": "$$"},
            {"name": "Café de Flore", "cuisine": "French Café", "rating": 4.3, "price_range": "$$$"},
        ],
        "tokyo": [
            {"name": "Ichiran Ramen", "cuisine": "Ramen", "rating": 4.5, "price_range": "$$"},
            {"name": "Sukiyabashi Jiro", "cuisine": "Sushi", "rating": 4.9, "price_range": "$$$$"},
            {"name": "Gonpachi Nishi-Azabu", "cuisine": "Izakaya", "rating": 4.3, "price_range": "$$$"},
        ],
        "new york": [
            {"name": "Katz's Delicatessen", "cuisine": "Deli", "rating": 4.5, "price_range": "$$"},
            {"name": "Le Bernardin", "cuisine": "French Seafood", "rating": 4.8, "price_range": "$$$$"},
            {"name": "Shake Shack", "cuisine": "Burgers", "rating": 4.2, "price_range": "$"},
        ],
    }

    def _run(self, city: str, cuisine: str = "all", dietary: str = "no preference") -> str:
        logger.info(f"[RestaurantTool] Searching restaurants in {city}")
        city_key = city.lower()

        # Look for city data or fall back to generic mock
        restaurants = self.CITY_DATA.get(city_key, _mock_response("restaurant", {})["restaurants"])

        # Apply dietary filter
        if "vegetarian" in dietary.lower():
            filtered = [r for r in restaurants if "vegetar" not in r.get("cuisine", "").lower()]
            if not filtered:
                filtered = restaurants  # Don't filter to empty
        else:
            filtered = restaurants

        return json.dumps({"city": city, "restaurants": filtered})

    async def _arun(self, city: str, cuisine: str = "all", dietary: str = "no preference") -> str:
        return self._run(city, cuisine, dietary)


# ══════════════════════════════════════════════════════════════
# SECTION 6 — Flight Search Tool
# ══════════════════════════════════════════════════════════════

class FlightToolInput(BaseModel):
    origin_iata: str = Field(description="Origin airport IATA code, e.g. 'JFK'")
    destination_iata: str = Field(description="Destination airport IATA code, e.g. 'CDG'")
    departure_date: str = Field(description="YYYY-MM-DD")
    return_date: Optional[str] = Field(default=None, description="YYYY-MM-DD for round trip")
    adults: int = Field(default=1)


class FlightSearchTool(BaseTool):
    """
    Searches for flight offers using the Amadeus Flight Offers API.
    Returns top 5 cheapest options with airline, times, and price.
    """
    name: str = "flight_search_tool"
    description: str = (
        "Search for available flights between two airports. "
        "Input: origin and destination IATA codes, date(s), and number of adults."
    )
    args_schema: Type[BaseModel] = FlightToolInput

    def _get_amadeus_token(self) -> Optional[str]:
        if not api_config.amadeus_api_key or api_config.amadeus_api_key in ("demo", "your_amadeus_api_key_here", ""):
            return None
        url = "https://test.api.amadeus.com/v1/security/oauth2/token"
        resp = requests.post(url, data={
            "grant_type": "client_credentials",
            "client_id": api_config.amadeus_api_key,
            "client_secret": api_config.amadeus_api_secret,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json().get("access_token")

    def _run(
        self,
        origin_iata: str,
        destination_iata: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
    ) -> str:
        logger.info(f"[FlightTool] {origin_iata} → {destination_iata} on {departure_date}")

        token = self._get_amadeus_token()
        if not token:
            return json.dumps(_mock_response("flight", {}))

        try:
            url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
            params: dict = {
                "originLocationCode": origin_iata,
                "destinationLocationCode": destination_iata,
                "departureDate": departure_date,
                "adults": adults,
                "max": 5,
                "currencyCode": "USD",
            }
            if return_date:
                params["returnDate"] = return_date

            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            raw = resp.json().get("data", [])

            flights = [
                {
                    "airline": f["validatingAirlineCodes"][0] if f.get("validatingAirlineCodes") else "Unknown",
                    "price_usd": float(f["price"]["total"]),
                    "stops": len(f["itineraries"][0]["segments"]) - 1,
                    "duration": f["itineraries"][0]["duration"],
                    "departure": f["itineraries"][0]["segments"][0]["departure"]["at"],
                    "arrival": f["itineraries"][0]["segments"][-1]["arrival"]["at"],
                }
                for f in raw[:5]
            ]
            return json.dumps({"flights": flights})
        except Exception as e:
            logger.error(f"[FlightTool] Error: {e}")
            return json.dumps(_mock_response("flight", {}))

    async def _arun(
        self,
        origin_iata: str,
        destination_iata: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
    ) -> str:
        return self._run(origin_iata, destination_iata, departure_date, return_date, adults)


# ══════════════════════════════════════════════════════════════
# SECTION 7 — MCP Tool Registry
# ══════════════════════════════════════════════════════════════

class MCPToolRegistry:
    """
    MCP-style tool registry.

    Why:
    ----
    Model Context Protocol defines a standard way for models to
    discover, describe, and invoke tools.  This lightweight
    implementation provides:
      • register(tool)  — add a tool by name
      • get(name)       — retrieve a tool by name
      • list_tools()    — enumerate all registered tools with descriptions
      • invoke(name, kwargs) — run a tool by name

    Agents can query list_tools() to build their action space
    dynamically without importing each tool class individually.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance under its .name attribute."""
        self._tools[tool.name] = tool
        logger.debug(f"[MCPRegistry] Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve tool by name; returns None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, str]]:
        """
        Returns a list of dicts with name + description.
        Used by ToolAgent to populate its action schema.
        """
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    def invoke(self, tool_name: str, **kwargs: Any) -> str:
        """
        Run a registered tool by name.
        Raises KeyError if tool not found.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            raise KeyError(f"Tool '{tool_name}' not found in registry. "
                           f"Available: {list(self._tools.keys())}")
        logger.info(f"[MCPRegistry] Invoking: {tool_name} | args={kwargs}")
        return tool._run(**kwargs)

    def get_langchain_tools(self) -> List[BaseTool]:
        """Return all tools as a plain list for LangChain agent constructors."""
        return list(self._tools.values())


# ── Instantiate and populate the global registry ────────────
tool_registry = MCPToolRegistry()
tool_registry.register(WeatherTool())
tool_registry.register(MapsTool())
tool_registry.register(HotelSearchTool())
tool_registry.register(RestaurantTool())
tool_registry.register(FlightSearchTool())

logger.info(
    f"[MCPRegistry] Initialised with {len(tool_registry.list_tools())} tools: "
    f"{[t['name'] for t in tool_registry.list_tools()]}"
)

__all__ = [
    "MCPToolRegistry",
    "tool_registry",
    "WeatherTool",
    "MapsTool",
    "HotelSearchTool",
    "RestaurantTool",
    "FlightSearchTool",
]