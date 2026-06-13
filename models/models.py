# ============================================================
# models/models.py — LLM Factory + Pydantic Schema Definitions
# ============================================================
# PURPOSE:
#   • Initialises and exposes the Groq-hosted Llama 3.3 70B model
#     as a reusable LangChain ChatModel instance.
#   • Defines ALL Pydantic v2 schemas used as structured outputs
#     across the entire agent system.
#
# WHY:
#   Centralising model creation prevents multiple conflicting
#   instances and makes swapping the backend (e.g., OpenAI →
#   Groq) a one-line change.  Pydantic schemas enforce type
#   safety and give downstream parsers a contract to validate
#   against.
# ============================================================

from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from langchain_groq import ChatGroq
from loguru import logger

# Import central config object
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import llm_config


# ══════════════════════════════════════════════════════════════
# SECTION 1 — LLM Factory
# ══════════════════════════════════════════════════════════════

def get_llm(
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    streaming: bool = False,
) -> ChatGroq:
    """
    Factory that returns a ChatGroq instance pointing at Llama 3.3 70B.

    Parameters
    ----------
    temperature : Override the default temperature from config.
    max_tokens  : Override the default max_tokens from config.
    streaming   : Enable token-by-token streaming (used in Streamlit).

    Why ChatGroq?
    -------------
    Groq's hardware (LPUs) delivers significantly lower latency than
    GPU-based providers for inference, which matters in an agentic loop
    where multiple sequential LLM calls happen per user request.
    """
    temp = temperature if temperature is not None else llm_config.temperature
    tokens = max_tokens if max_tokens is not None else llm_config.max_tokens

    llm = ChatGroq(
        api_key=llm_config.groq_api_key,   # Auth token from config
        model=llm_config.model_name,        # "llama-3.3-70b-versatile"
        temperature=temp,                   # Sampling temperature
        max_tokens=tokens,                  # Response length cap
        timeout=llm_config.timeout,         # Request timeout in seconds
        max_retries=llm_config.max_retries, # Auto-retry on transient errors
        streaming=streaming,                # Streaming flag
    )

    logger.info(
        f"LLM initialised | model={llm_config.model_name} "
        f"temp={temp} tokens={tokens} streaming={streaming}"
    )
    return llm


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Pydantic Output Schemas
# ══════════════════════════════════════════════════════════════
# Each class maps 1-to-1 with the structured JSON output expected
# from a specific agent.  Using Pydantic v2:
#   • Field descriptions become part of the JSON schema hint
#     sent to the LLM via PydanticOutputParser.
#   • @field_validator decorators add business-rule validation
#     that runs automatically on parse.

# ── 2a. Route / Itinerary Schema ────────────────────────────

class DayItinerary(BaseModel):
    """One day in the travel plan."""
    day: int = Field(description="Day number starting from 1")
    date: str = Field(description="Date in YYYY-MM-DD format")
    activities: List[str] = Field(description="List of activities for the day")
    transportation: str = Field(description="Primary transport mode for the day")
    accommodation: str = Field(description="Where the traveller sleeps tonight")
    estimated_cost_usd: float = Field(description="Estimated daily spend in USD")


class RouteOutput(BaseModel):
    """Structured output from RouteAgent."""
    origin: str = Field(description="Departure city / airport")
    destination: str = Field(description="Arrival city / airport")
    total_days: int = Field(description="Total trip duration in days")
    best_route_summary: str = Field(description="Narrative summary of the best route")
    transportation_options: List[str] = Field(
        description="Available transport modes e.g. ['Flight', 'Train', 'Bus']"
    )
    day_wise_itinerary: List[DayItinerary] = Field(
        description="Ordered list of daily plans"
    )
    distance_km: float = Field(description="Approximate total distance in km")
    confidence: float = Field(ge=0.0, le=1.0, description="Agent confidence 0-1")

    @field_validator("total_days")
    @classmethod
    def days_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Trip must be at least 1 day")
        return v


# ── 2b. Weather Schema ──────────────────────────────────────

class WeatherOutput(BaseModel):
    """Structured output from WeatherAgent."""
    destination: str
    current_temp_celsius: float
    condition: str = Field(description="e.g. Sunny, Rainy, Cloudy")
    humidity_percent: int
    wind_speed_kmh: float
    forecast_7days: List[Dict[str, Any]] = Field(
        description="List of daily forecasts [{date, high, low, condition}]"
    )
    travel_warnings: List[str] = Field(
        default_factory=list,
        description="Any weather-related warnings for travellers"
    )
    clothing_suggestions: List[str] = Field(
        description="What to pack based on weather"
    )
    best_travel_months: List[str] = Field(
        description="Ideal months to visit the destination"
    )
    confidence: float = Field(ge=0.0, le=1.0)


# ── 2c. Hotel Schema ────────────────────────────────────────

class HotelOption(BaseModel):
    """A single hotel recommendation."""
    name: str
    category: str = Field(description="budget | premium | family")
    price_per_night_usd: float
    rating: float = Field(ge=0.0, le=5.0)
    amenities: List[str]
    location_description: str
    booking_tip: str


class HotelOutput(BaseModel):
    """Structured output from HotelAgent."""
    destination: str
    check_in: str
    check_out: str
    total_nights: int
    budget_hotels: List[HotelOption]
    premium_hotels: List[HotelOption]
    family_hotels: List[HotelOption]
    recommended_area: str = Field(
        description="Best neighbourhood to stay in"
    )
    confidence: float = Field(ge=0.0, le=1.0)


# ── 2d. Budget Schema ───────────────────────────────────────

class BudgetBreakdown(BaseModel):
    """Detailed cost breakdown."""
    flights_usd: float
    accommodation_usd: float
    food_usd: float
    local_transport_usd: float
    activities_usd: float
    miscellaneous_usd: float
    total_usd: float

    @field_validator("total_usd")
    @classmethod
    def total_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Total budget must be greater than 0")
        return v


class BudgetOutput(BaseModel):
    """Structured output from BudgetAgent."""
    destination: str
    trip_days: int
    travellers: int
    budget_tier: str = Field(description="budget | mid-range | luxury")
    per_person_breakdown: BudgetBreakdown
    total_trip_cost_usd: float
    saving_tips: List[str]
    currency_info: str = Field(
        description="Local currency and approximate exchange rate to USD"
    )
    confidence: float = Field(ge=0.0, le=1.0)


# ── 2e. Food Schema ─────────────────────────────────────────

class Restaurant(BaseModel):
    """One restaurant suggestion."""
    name: str
    cuisine_type: str
    price_range: str = Field(description="$ | $$ | $$$")
    must_try_dish: str
    dietary_options: List[str] = Field(
        description="e.g. vegetarian, vegan, gluten-free"
    )
    location_hint: str
    rating: float = Field(ge=0.0, le=5.0)


class FoodOutput(BaseModel):
    """Structured output from FoodAgent."""
    destination: str
    local_specialties: List[str]
    vegetarian_dishes: List[str]
    non_vegetarian_dishes: List[str]
    street_food_recommendations: List[str]
    restaurant_suggestions: List[Restaurant]
    food_safety_tips: List[str]
    average_meal_cost_usd: float
    confidence: float = Field(ge=0.0, le=1.0)


# ── 2f. Master Travel Plan Schema ───────────────────────────

class TravelPlan(BaseModel):
    """
    The final aggregated travel plan produced by FinalPlannerAgent.
    Contains sub-plans from every specialist agent.
    """
    plan_id: str = Field(description="Unique plan identifier (UUID)")
    created_at: str = Field(description="ISO-8601 timestamp")
    origin: str
    destination: str
    departure_date: str
    return_date: str
    travellers: int
    travel_purpose: str = Field(description="leisure | business | adventure | family")

    route: Optional[RouteOutput] = None
    weather: Optional[WeatherOutput] = None
    hotels: Optional[HotelOutput] = None
    budget: Optional[BudgetOutput] = None
    food: Optional[FoodOutput] = None

    executive_summary: str = Field(
        description="2-3 sentence overview of the complete travel plan"
    )
    overall_confidence: float = Field(ge=0.0, le=1.0)
    warnings: List[str] = Field(default_factory=list)
    rag_context_used: bool = Field(
        default=False,
        description="Whether RAG retrieval enriched this plan"
    )


# ── 2g. Agent State Schema (used by LangGraph) ──────────────

class TravelRequest(BaseModel):
    """Input schema — what the user provides to start the system."""
    origin: str = Field(description="Departure city")
    destination: str = Field(description="Destination city / country")
    departure_date: str = Field(description="YYYY-MM-DD")
    return_date: str = Field(description="YYYY-MM-DD")
    travellers: int = Field(ge=1, le=20, default=2)
    budget_usd: float = Field(gt=0, description="Total trip budget in USD")
    travel_purpose: str = Field(default="leisure")
    dietary_preference: str = Field(
        default="no preference",
        description="vegetarian | vegan | no preference"
    )
    accommodation_preference: str = Field(
        default="mid-range",
        description="budget | mid-range | luxury"
    )
    special_requests: Optional[str] = Field(
        default=None,
        description="Any extra requirements from the traveller"
    )


# Export everything needed by other modules
__all__ = [
    "get_llm",
    "TravelRequest",
    "TravelPlan",
    "RouteOutput",
    "WeatherOutput",
    "HotelOutput",
    "BudgetOutput",
    "FoodOutput",
    "DayItinerary",
    "HotelOption",
    "Restaurant",
    "BudgetBreakdown",
]