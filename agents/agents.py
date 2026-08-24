# ============================================================
# agents/agents.py — All 9 Specialist Agents
# ============================================================
# PURPOSE:
#   Implements every agent in the multi-agent system.  Each
#   agent is a self-contained class with a single public method
#   `run(**kwargs) → <TypedOutput>`.
#
# AGENT ROSTER:
#   1.  SupervisorAgent   — orchestrates the pipeline
#   2.  RouteAgent        — route planning & day-wise itinerary
#   3.  WeatherAgent      — weather data & clothing advice
#   4.  HotelAgent        — hotel recommendations (3 tiers)
#   5.  BudgetAgent       — full cost breakdown
#   6.  FoodAgent         — cuisine & restaurant recommendations
#   7.  RetrievalAgent    — RAG knowledge fetcher
#   8.  ToolAgent         — external API dispatcher
#   9.  FinalPlannerAgent — assembles the complete TravelPlan
#
# DESIGN PATTERN:
#   Every agent uses the LCEL (LangChain Expression Language)
#   pipe  →  prompt | llm | parser
#   This is declarative, composable, and easy to test in isolation.
#
# PROMPTING TECHNIQUES USED:
#   • ChatPromptTemplate — structured system + human messages
#   • Few-shot examples  — demonstrate expected JSON format
#   • Chain-of-Thought   — "Step 1…Step 2…" in system prompt
#   • ReAct              — Supervisor uses Thought/Action loops
# ============================================================

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_core.output_parsers import StrOutputParser
from loguru import logger

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.models import (
    get_llm, TravelRequest, TravelPlan,
    RouteOutput, WeatherOutput, HotelOutput, BudgetOutput, FoodOutput,
)
from prompts.prompts import (
    supervisor_prompt, route_prompt, weather_prompt,
    hotel_prompt, budget_prompt, food_prompt, final_planner_prompt,
)
from parsers.parser import (
    parse_route_output, parse_weather_output, parse_hotel_output,
    parse_budget_output, parse_food_output, parse_travel_plan,
    parse_plan_synthesis,
    get_route_format_instructions, get_weather_format_instructions,
    get_hotel_format_instructions, get_budget_format_instructions,
    get_food_format_instructions,
)
from guardrails.guardrails import validate_agent_confidence
from tools.tools import tool_registry, source_of, SOURCE_MOCK
from rag.rag import get_retriever, RetrievalResult, NO_CONTEXT_NOTICE
from langfuse_setup import get_tracer


# ══════════════════════════════════════════════════════════════
# BASE AGENT
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# LLM failure tracking
# ══════════════════════════════════════════════════════════════
# Agents deliberately never raise — a failed call becomes a None section so
# one bad agent cannot take down the run. The cost of that design is that
# failures were completely invisible: a rate-limited call produced an empty
# tab labelled "No itinerary available" with no reason given anywhere.
#
# These record what went wrong so the graph can attach it to the state and
# the UI can tell the user the truth.

_llm_errors: list = []


def _parse_retry_after(message: str) -> str:
    """
    Pull the wait time out of a provider rate-limit message.

    Groq says "Please try again in 25m23.664s". Telling the user to "wait a
    minute or two" when the real answer is 25 minutes is worse than saying
    nothing, so the actual figure is extracted and shown.
    """
    import re
    m = re.search(r"try again in\s+(?:(\d+)m)?([\d.]+)s", message, re.I)
    if not m:
        return ""
    minutes = int(m.group(1) or 0)
    seconds = float(m.group(2) or 0)
    total = minutes * 60 + seconds
    if total < 90:
        return f"about {int(total)} seconds"
    return f"about {round(total / 60)} minutes"


def record_llm_error(agent: str, message: str) -> None:
    """Note an LLM failure so it can be surfaced instead of silently dropped."""
    kind = "error"
    retry_after = ""
    daily = False
    lowered = message.lower()
    if "rate limit" in lowered or "429" in lowered:
        kind = "rate_limit"
        retry_after = _parse_retry_after(message)
        # Per-day and per-minute limits need completely different advice:
        # one is "wait a moment", the other is "you are done for today".
        daily = "per day" in lowered or "tpd" in lowered
    elif "empty" in lowered:
        kind = "empty_response"
    elif "auth" in lowered or "401" in lowered or "api key" in lowered:
        kind = "auth"
    _llm_errors.append({
        "agent": agent, "kind": kind, "message": message[:400],
        "retry_after": retry_after, "daily": daily,
    })
    logger.error(f"[{agent}] LLM {kind}: {message[:200]}")


def drain_llm_errors() -> list:
    """Return and clear the errors recorded since the last drain."""
    out = list(_llm_errors)
    _llm_errors.clear()
    return out


class BaseAgent:
    """
    Abstract base class providing common infrastructure:
      • LLM instance (shared ChatGroq)
      • RAG retriever (HybridRetriever singleton)
      • _invoke_llm() helper that handles errors gracefully
      • _get_rag_context() helper for context enrichment
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self.llm = get_llm()  # Groq-hosted chat model (see LLM_MODEL)
        self.retriever = get_retriever()  # HybridRetriever singleton
        logger.info(f"[{self.agent_name}] Initialised")

    def _invoke_llm(self, chain: Any, inputs: dict) -> str:
        """
        Safely invoke an LCEL chain and return the raw string output.
        Catches exceptions and returns an error JSON so downstream
        parsers can handle the failure gracefully rather than crashing.

        The Langfuse callback handler is attached here, which is the only
        place it can be: without it the chain runs untraced and Langfuse sees
        a trace envelope with no prompts, completions, token counts or
        latencies inside it.
        """
        config = get_tracer().langchain_config(
            run_name=self.agent_name,
            metadata={"agent": self.agent_name},
        )
        try:
            result = chain.invoke(inputs, config=config)
            text = result if isinstance(result, str) else str(result)

            # An empty completion is a failure, not an answer. This model
            # spends "reasoning tokens" before it emits any content, so a
            # response truncated by max_tokens comes back as "" — which the
            # parser would turn into a None section with no explanation.
            if not text.strip():
                record_llm_error(
                    self.agent_name,
                    "Model returned an empty response (the token budget was "
                    "likely consumed before any output was produced).",
                )
                return json.dumps({"error": "empty response", "confidence": 0.0})

            return text
        except Exception as e:
            record_llm_error(self.agent_name, str(e))
            return json.dumps({"error": str(e), "confidence": 0.0})

    def _get_rag_context(self, query: str, destination: Optional[str] = None):
        """
        Retrieve relevant travel knowledge for a query.

        Returns a RetrievalResult, which stringifies to the context text but
        also carries `.grounded` — False when nothing in the knowledge base
        cleared the relevance floor, in which case the context is an explicit
        instruction to fall back on the model's own knowledge rather than
        borrowed facts about another destination.
        """
        try:
            return self.retriever.retrieve(query, destination=destination)
        except Exception as e:
            logger.warning(f"[{self.agent_name}] RAG retrieval failed: {e}")
            return RetrievalResult(NO_CONTEXT_NOTICE, grounded=False)


# ══════════════════════════════════════════════════════════════
# 1. RETRIEVAL AGENT
# ══════════════════════════════════════════════════════════════

class RetrievalAgent(BaseAgent):
    """
    Fetches relevant knowledge from the hybrid RAG system.
    Always called FIRST in the pipeline so every specialist
    agent receives destination-specific context.

    Queries performed:
      • General destination knowledge
      • Accommodation knowledge
      • Food & dining knowledge
    """

    def __init__(self) -> None:
        super().__init__("RetrievalAgent")

    def run(self, request: TravelRequest) -> Dict[str, str]:
        """
        Retrieve context for the destination across three dimensions.

        Returns
        -------
        dict with keys:
            general_context    — overview facts about destination
            hotel_context      — accommodation-specific knowledge
            food_context       — dining & cuisine knowledge
        """
        dest = request.destination

        # Three targeted queries cover the information needs of all 5 agents.
        # Phrased as natural questions rather than keyword soup: the reranker
        # is a cross encoder trained on question/passage pairs, and scores
        # keyword strings far lower, which would gate out genuine matches.
        general = self._get_rag_context(
            f"What should a traveller know about visiting {dest}?", destination=dest
        )
        hotel = self._get_rag_context(
            f"Where should I stay in {dest} and what do hotels cost?", destination=dest
        )
        food = self._get_rag_context(
            f"What food and restaurants is {dest} known for?", destination=dest
        )

        grounded = {
            "general": general.grounded,
            "hotel": hotel.grounded,
            "food": food.grounded,
        }
        n_grounded = sum(grounded.values())

        if n_grounded == 0:
            logger.warning(
                f"[RetrievalAgent] NO grounding for '{dest}' — the knowledge base "
                f"has nothing relevant. Agents will fall back to model knowledge, "
                f"which is recorded on the plan."
            )
        else:
            logger.info(
                f"[RetrievalAgent] Retrieved context | grounded {n_grounded}/3 | "
                f"general={len(general.context)}ch hotel={len(hotel.context)}ch "
                f"food={len(food.context)}ch"
            )

        return {
            "general_context": general.context,
            "hotel_context": hotel.context,
            "food_context": food.context,
            # Grounding telemetry — consumed by guardrails, the plan and the UI.
            "grounded": grounded,
            "grounded_count": n_grounded,
            "top_scores": {
                "general": general.top_score,
                "hotel": hotel.top_score,
                "food": food.top_score,
            },
        }


# ══════════════════════════════════════════════════════════════
# 2. TOOL AGENT
# ══════════════════════════════════════════════════════════════

class ToolAgent(BaseAgent):
    """
    Dispatcher that calls external API tools and formats results
    for other agents.  Uses the MCPToolRegistry to discover and
    invoke tools by name.

    Acts as the bridge between the agentic graph and real-world data.
    """

    def __init__(self) -> None:
        super().__init__("ToolAgent")

    def get_weather_data(self, destination: str) -> str:
        """Fetch live weather for the destination city."""
        city = destination.split(",")[0].strip()
        result = tool_registry.invoke("weather_tool", city=city)
        logger.info(f"[ToolAgent] Weather data fetched for {city}")
        return result

    def get_maps_data(self, origin: str, destination: str) -> str:
        """Get distance and travel time between origin and destination."""
        result = tool_registry.invoke(
            "maps_tool", origin=origin, destination=destination
        )
        logger.info(f"[ToolAgent] Maps data: {origin} → {destination}")
        return result

    def get_hotel_data(self, destination: str, check_in: str, check_out: str, adults: int) -> str:
        """Search for hotels at the destination."""
        # Use destination as both city_code placeholder and actual name
        city_code = destination[:3].upper()  # Rough IATA approximation
        result = tool_registry.invoke(
            "hotel_search_tool",
            city_code=city_code,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
        )
        logger.info(f"[ToolAgent] Hotel data fetched for {destination}")
        return result

    def get_restaurant_data(self, destination: str, dietary: str) -> str:
        """Get restaurant recommendations for the destination."""
        result = tool_registry.invoke(
            "restaurant_tool",
            city=destination,
            dietary=dietary,
        )
        logger.info(f"[ToolAgent] Restaurant data fetched for {destination}")
        return result

    def get_flight_data(self, origin: str, destination: str, departure_date: str) -> str:
        """Search for flights from origin to destination."""
        # Extract rough IATA codes (fallback)
        origin_code = origin[:3].upper()
        dest_code = destination[:3].upper()
        result = tool_registry.invoke(
            "flight_search_tool",
            origin_iata=origin_code,
            destination_iata=dest_code,
            departure_date=departure_date,
            adults=1,
        )
        logger.info(f"[ToolAgent] Flight data: {origin_code}→{dest_code}")
        return result

    def run(self, request: TravelRequest) -> Dict[str, str]:
        """
        Execute all relevant tool calls and return bundled results.

        The bundle also carries a `data_sources` map ({tool: live|curated|mock})
        read off each payload's provenance stamp, so downstream guardrails and
        the UI can tell a real forecast from a fixture.
        """
        bundle = {
            "weather_data": self.get_weather_data(request.destination),
            "maps_data": self.get_maps_data(request.origin, request.destination),
            "hotel_data": self.get_hotel_data(
                request.destination,
                request.departure_date,
                request.return_date,
                request.travellers,
            ),
            "restaurant_data": self.get_restaurant_data(
                request.destination, request.dietary_preference
            ),
            "flight_data": self.get_flight_data(
                request.origin, request.destination, request.departure_date
            ),
        }

        sources = {
            key.replace("_data", ""): source_of(raw)
            for key, raw in bundle.items()
        }
        bundle["data_sources"] = sources

        mocked = [name for name, src in sources.items() if src == SOURCE_MOCK]
        if mocked:
            logger.warning(
                f"[ToolAgent] {len(mocked)}/{len(sources)} tools returned FIXTURE data "
                f"(no API key or call failed): {', '.join(mocked)}"
            )
        return bundle


# ══════════════════════════════════════════════════════════════
# 3. WEATHER AGENT
# ══════════════════════════════════════════════════════════════

class WeatherAgent(BaseAgent):
    """
    Produces a structured WeatherOutput by combining:
      • Live weather data from WeatherTool (via ToolAgent)
      • Destination climate knowledge from RAG
      • LLM reasoning to complete the analysis
    """

    def __init__(self) -> None:
        super().__init__("WeatherAgent")
        # LCEL chain: prompt → llm → string output
        self._chain = weather_prompt | self.llm | StrOutputParser()

    def run(
        self,
        request: TravelRequest,
        weather_tool_data: str,
        rag_context: str,
    ) -> Optional[WeatherOutput]:
        """
        Generate weather analysis.

        Parameters
        ----------
        request          : Original travel request
        weather_tool_data: Raw JSON from WeatherTool
        rag_context      : RAG knowledge about destination climate

        Returns
        -------
        WeatherOutput or None on failure
        """
        logger.info(f"[WeatherAgent] Analysing weather for {request.destination}")

        # Append format instructions to help the LLM produce valid JSON
        enriched_context = (
            f"{rag_context}\n\n"
            f"Format Instructions: {get_weather_format_instructions()}"
        )

        raw = self._invoke_llm(self._chain, {
            "destination": request.destination,
            "departure_date": request.departure_date,
            "return_date": request.return_date,
            "weather_tool_data": weather_tool_data,
            "rag_context": enriched_context,
        })

        result = parse_weather_output(raw)

        # Validate confidence
        check = validate_agent_confidence("WeatherAgent", result)
        if not check.passed:
            logger.warning(f"[WeatherAgent] Confidence check failed: {check.errors}")

        return result


# ══════════════════════════════════════════════════════════════
# 4. ROUTE AGENT
# ══════════════════════════════════════════════════════════════

class RouteAgent(BaseAgent):
    """
    Plans the optimal route and creates a day-by-day itinerary.
    Receives weather context so it can avoid monsoon routes or
    recommend indoor activities on rainy days.
    """

    def __init__(self) -> None:
        super().__init__("RouteAgent")
        self._chain = route_prompt | self.llm | StrOutputParser()

    def run(
        self,
        request: TravelRequest,
        rag_context: str,
        weather_summary: str = "",
    ) -> Optional[RouteOutput]:
        """
        Generate the route plan.

        Parameters
        ----------
        request        : Original travel request
        rag_context    : General destination knowledge from RAG
        weather_summary: Short weather summary to influence routing

        Returns
        -------
        RouteOutput or None on failure
        """
        logger.info(
            f"[RouteAgent] Planning route "
            f"{request.origin} → {request.destination}"
        )

        enriched_context = (
            f"{rag_context}\n"
            f"Weather context: {weather_summary}\n"
            f"Format Instructions: {get_route_format_instructions()}"
        )

        preferences = (
            f"Purpose: {request.travel_purpose} | "
            f"Dietary: {request.dietary_preference} | "
            f"Accommodation: {request.accommodation_preference} | "
            f"Special: {request.special_requests or 'None'}"
        )

        raw = self._invoke_llm(self._chain, {
            "origin": request.origin,
            "destination": request.destination,
            "departure_date": request.departure_date,
            "return_date": request.return_date,
            "travellers": request.travellers,
            "budget_usd": request.budget_usd,
            "preferences": preferences,
            "rag_context": enriched_context,
        })

        result = parse_route_output(raw)
        check = validate_agent_confidence("RouteAgent", result)
        if not check.passed:
            logger.warning(f"[RouteAgent] Confidence check failed: {check.errors}")

        return result


# ══════════════════════════════════════════════════════════════
# 5. HOTEL AGENT
# ══════════════════════════════════════════════════════════════

class HotelAgent(BaseAgent):
    """
    Recommends hotels across three tiers: budget, premium, family.
    Combines real hotel search results from HotelSearchTool with
    RAG knowledge about the best neighbourhoods to stay.
    """

    def __init__(self) -> None:
        super().__init__("HotelAgent")
        self._chain = hotel_prompt | self.llm | StrOutputParser()

    def run(
        self,
        request: TravelRequest,
        hotel_tool_data: str,
        rag_context: str,
    ) -> Optional[HotelOutput]:
        """Generate hotel recommendations."""
        logger.info(f"[HotelAgent] Finding hotels in {request.destination}")

        enriched_context = (
            f"{rag_context}\n"
            f"Format Instructions: {get_hotel_format_instructions()}"
        )

        raw = self._invoke_llm(self._chain, {
            "destination": request.destination,
            "departure_date": request.departure_date,
            "return_date": request.return_date,
            "travellers": request.travellers,
            "budget_usd": request.budget_usd,
            "accommodation_preference": request.accommodation_preference,
            "hotel_tool_data": hotel_tool_data,
            "rag_context": enriched_context,
        })

        result = parse_hotel_output(raw)
        check = validate_agent_confidence("HotelAgent", result)
        if not check.passed:
            logger.warning(f"[HotelAgent] Confidence check failed: {check.errors}")

        return result


# ══════════════════════════════════════════════════════════════
# 6. BUDGET AGENT
# ══════════════════════════════════════════════════════════════

class BudgetAgent(BaseAgent):
    """
    Creates a detailed financial breakdown for the trip.
    Uses route and hotel data for accurate cost estimation,
    then adds food and activity estimates from RAG context.
    """

    def __init__(self) -> None:
        super().__init__("BudgetAgent")
        self._chain = budget_prompt | self.llm | StrOutputParser()

    def run(
        self,
        request: TravelRequest,
        route_data: str,
        hotel_data: str,
        rag_context: str,
    ) -> Optional[BudgetOutput]:
        """Generate budget breakdown."""
        from datetime import date
        dep = datetime.strptime(request.departure_date, "%Y-%m-%d")
        ret = datetime.strptime(request.return_date, "%Y-%m-%d")
        trip_days = (ret - dep).days

        logger.info(
            f"[BudgetAgent] Calculating budget for {trip_days} days "
            f"in {request.destination}"
        )

        enriched_context = (
            f"{rag_context}\n"
            f"Format Instructions: {get_budget_format_instructions()}"
        )

        raw = self._invoke_llm(self._chain, {
            "origin": request.origin,
            "destination": request.destination,
            "trip_days": trip_days,
            "travellers": request.travellers,
            "budget_usd": request.budget_usd,
            "accommodation_preference": request.accommodation_preference,
            "hotel_data": hotel_data,
            "route_data": route_data,
            "rag_context": enriched_context,
        })

        result = parse_budget_output(raw)
        check = validate_agent_confidence("BudgetAgent", result)
        if not check.passed:
            logger.warning(f"[BudgetAgent] Confidence check failed: {check.errors}")

        return result


# ══════════════════════════════════════════════════════════════
# 7. FOOD AGENT
# ══════════════════════════════════════════════════════════════

class FoodAgent(BaseAgent):
    """
    Recommends local cuisine, vegetarian/non-vegetarian dishes,
    street food, and specific restaurants.
    Respects dietary preferences from the travel request.
    """

    def __init__(self) -> None:
        super().__init__("FoodAgent")
        self._chain = food_prompt | self.llm | StrOutputParser()

    def run(
        self,
        request: TravelRequest,
        food_tool_data: str,
        rag_context: str,
    ) -> Optional[FoodOutput]:
        """Generate food recommendations."""
        logger.info(
            f"[FoodAgent] Generating food plan for {request.destination} "
            f"({request.dietary_preference})"
        )

        enriched_context = (
            f"{rag_context}\n"
            f"Format Instructions: {get_food_format_instructions()}"
        )

        raw = self._invoke_llm(self._chain, {
            "destination": request.destination,
            "travellers": request.travellers,
            "dietary_preference": request.dietary_preference,
            "accommodation_preference": request.accommodation_preference,
            "food_tool_data": food_tool_data,
            "rag_context": enriched_context,
        })

        result = parse_food_output(raw)
        check = validate_agent_confidence("FoodAgent", result)
        if not check.passed:
            logger.warning(f"[FoodAgent] Confidence check failed: {check.errors}")

        return result


# ══════════════════════════════════════════════════════════════
# 8. FINAL PLANNER AGENT
# ══════════════════════════════════════════════════════════════

# ── Compact digests for the synthesis prompt ─────────────────
# Each returns a few dense lines instead of a full JSON dump. Together they
# take the final planner's prompt from ~8,000 tokens (over the per-request
# limit) to roughly 900, which is what makes the call possible at all.

def _digest_route(route) -> str:
    if not route:
        return "Not available"
    days = "\n".join(
        f"  Day {d.day} ({d.date}): {', '.join(d.activities[:3])} "
        f"| {d.transportation} | {d.accommodation} | ${d.estimated_cost_usd:.0f}"
        for d in route.day_wise_itinerary
    )
    return (
        f"{route.origin} to {route.destination}, {route.total_days} days, "
        f"{route.distance_km:.0f} km. {route.best_route_summary}\n"
        f"Transport: {', '.join(route.transportation_options[:4])}\n{days}"
    )


def _digest_weather(weather) -> str:
    if not weather:
        return "Not available"
    warnings = "; ".join(weather.travel_warnings[:3]) or "none"
    return (
        f"{weather.condition}, {weather.current_temp_celsius:g}C, "
        f"humidity {weather.humidity_percent}%, wind {weather.wind_speed_kmh:.0f} km/h. "
        f"Warnings: {warnings}. "
        f"Pack: {', '.join(weather.clothing_suggestions[:4])}. "
        f"Best months: {', '.join(weather.best_travel_months[:4])}"
    )


def _digest_hotels(hotels) -> str:
    if not hotels:
        return "Not available"
    def tier(label, group):
        if not group:
            return ""
        picks = "; ".join(
            f"{h.name} ${h.price_per_night_usd:.0f}/night ({h.rating:g}*)"
            for h in group[:3]
        )
        return f"\n  {label}: {picks}"
    return (
        f"{hotels.total_nights} nights, {hotels.check_in} to {hotels.check_out}. "
        f"Recommended area: {hotels.recommended_area}."
        + tier("Budget", hotels.budget_hotels)
        + tier("Premium", hotels.premium_hotels)
        + tier("Family", hotels.family_hotels)
    )


def _digest_budget(budget) -> str:
    if not budget:
        return "Not available"
    b = budget.per_person_breakdown
    return (
        f"Tier {budget.budget_tier}, {budget.trip_days} days, "
        f"{budget.travellers} traveller(s). "
        f"Per person: flights ${b.flights_usd:.0f}, stay ${b.accommodation_usd:.0f}, "
        f"food ${b.food_usd:.0f}, transport ${b.local_transport_usd:.0f}, "
        f"activities ${b.activities_usd:.0f}, other ${b.miscellaneous_usd:.0f}, "
        f"total ${b.total_usd:.0f}. "
        f"TRIP TOTAL ${budget.total_trip_cost_usd:.0f}. {budget.currency_info}"
    )


def _digest_food(food) -> str:
    if not food:
        return "Not available"
    places = "; ".join(
        f"{r.name} ({r.cuisine_type}, {r.price_range})"
        for r in food.restaurant_suggestions[:4]
    )
    return (
        f"Average meal ${food.average_meal_cost_usd:.0f}/person. "
        f"Specialities: {', '.join(food.local_specialties[:5])}. "
        f"Vegetarian: {', '.join(food.vegetarian_dishes[:4])}. "
        f"Restaurants: {places}"
    )


class FinalPlannerAgent(BaseAgent):
    """
    Synthesis agent that combines outputs from all 5 specialist
    agents into a single coherent TravelPlan.

    Responsibilities:
      • Write the executive summary
      • Compute overall confidence (weighted mean)
      • Attach all sub-plans to the TravelPlan object
      • Inject metadata (plan_id, created_at, warnings)
    """

    def __init__(self) -> None:
        super().__init__("FinalPlannerAgent")
        # Groq counts reserved output tokens toward the per-request budget, so
        # the default 4,096 was consuming half the 8,000 TPM ceiling for a
        # reply that is three short fields. Reserving what the response
        # actually needs keeps the request comfortably inside the limit.
        self.llm = get_llm(max_tokens=1200)
        self._chain = final_planner_prompt | self.llm | StrOutputParser()

    def run(
        self,
        request: TravelRequest,
        route: Optional[RouteOutput],
        weather: Optional[WeatherOutput],
        hotels: Optional[HotelOutput],
        budget: Optional[BudgetOutput],
        food: Optional[FoodOutput],
        warnings: list,
        data_sources: Optional[dict] = None,
        rag_grounding: Optional[dict] = None,
    ) -> Optional[TravelPlan]:
        """
        Compile the final TravelPlan.

        The plan is always assembled in Python from the request and the five
        sub-outputs; the LLM only supplies the executive summary, the overall
        confidence and any cross-section inconsistencies it spotted. That split
        means a bad LLM response degrades to a plainer summary instead of
        discarding the whole synthesis.

        Parameters
        ----------
        request      : Original user request
        route        : RouteAgent output
        weather      : WeatherAgent output
        hotels       : HotelAgent output
        budget       : BudgetAgent output
        food         : FoodAgent output
        warnings     : Accumulated guardrail warnings
        data_sources : {tool: live|curated|mock} provenance from ToolAgent

        Returns
        -------
        TravelPlan (never None — assembly cannot fail)
        """
        plan_id = str(uuid.uuid4())[:8].upper()
        created_at = datetime.utcnow().isoformat() + "Z"
        data_sources = data_sources or {}
        rag_grounding = rag_grounding or {}

        logger.info(f"[FinalPlannerAgent] Compiling plan {plan_id}")

        # Digest the sub-outputs rather than dumping them.
        #
        # This used to inject all five sub-plans as indented JSON, which came
        # to ~8,000 tokens — over Groq's 8,000 tokens-per-minute ceiling for a
        # single request. The API rejected it with HTTP 413 *every time*, so
        # retries could never help and the synthesis silently fell back to a
        # canned summary on every run.
        #
        # The model only has to write a summary, score confidence, and spot
        # inconsistencies. It needs the facts, not the schema: names, numbers
        # and dates, with no field names, brackets or pretty-printing.
        raw = self._invoke_llm(self._chain, {
            "travel_request": (
                f"{request.origin} to {request.destination}, "
                f"{request.departure_date} to {request.return_date}, "
                f"{request.travellers} traveller(s), budget ${request.budget_usd:,.0f}, "
                f"{request.travel_purpose}, {request.dietary_preference}, "
                f"{request.accommodation_preference} accommodation"
                + (f". Note: {request.special_requests}" if request.special_requests else "")
            ),
            "route_data": _digest_route(route),
            "weather_data": _digest_weather(weather),
            "hotel_data": _digest_hotels(hotels),
            "budget_data": _digest_budget(budget),
            "food_data": _digest_food(food),
            "plan_id": plan_id,
            "created_at": created_at,
        })

        synthesis = parse_plan_synthesis(raw)

        # Confidence computed from the sub-agents is the trustworthy floor;
        # the LLM's self-assessment is only used when it actually parsed.
        confidences = [
            getattr(r, "confidence", 0.7)
            for r in [route, weather, hotels, budget, food]
            if r is not None
        ]
        computed_conf = round(sum(confidences) / max(len(confidences), 1), 2)

        all_warnings = list(warnings)

        if synthesis:
            summary = synthesis.executive_summary
            overall_conf = synthesis.overall_confidence
            all_warnings.extend(
                f"[Synthesis] {w}" for w in synthesis.consistency_warnings
            )
            logger.info(
                f"[FinalPlannerAgent] Plan {plan_id} synthesised | "
                f"confidence={overall_conf:.2f} | "
                f"consistency_warnings={len(synthesis.consistency_warnings)}"
            )
        else:
            logger.warning(
                "[FinalPlannerAgent] Synthesis parse failed — "
                "falling back to a generated summary"
            )
            summary = (
                f"A {request.travel_purpose} trip from {request.origin} to "
                f"{request.destination} for {request.travellers} traveller(s). "
                f"The plan covers routes, accommodation, dining, and budget "
                f"within your ${request.budget_usd:,.0f} total budget."
            )
            overall_conf = computed_conf

        # A plan resting on fixtures must not advertise high confidence.
        mocked = [k for k, v in data_sources.items() if v == "mock"]
        if mocked and data_sources:
            penalty = len(mocked) / len(data_sources)
            overall_conf = round(overall_conf * (1.0 - 0.5 * penalty), 2)
            logger.warning(
                f"[FinalPlannerAgent] Confidence reduced to {overall_conf:.2f} — "
                f"{len(mocked)}/{len(data_sources)} sources are simulated"
            )

        return TravelPlan(
            plan_id=plan_id,
            created_at=created_at,
            origin=request.origin,
            destination=request.destination,
            departure_date=request.departure_date,
            return_date=request.return_date,
            travellers=request.travellers,
            travel_purpose=request.travel_purpose,
            route=route,
            weather=weather,
            hotels=hotels,
            budget=budget,
            food=food,
            executive_summary=summary,
            overall_confidence=overall_conf,
            warnings=all_warnings,
            # Honest: True only if the KB actually had destination knowledge.
            rag_context_used=any(rag_grounding.values()),
            rag_grounding=rag_grounding,
            data_sources=data_sources,
        )


# ══════════════════════════════════════════════════════════════
# 9. SUPERVISOR AGENT
# ══════════════════════════════════════════════════════════════

class SupervisorAgent(BaseAgent):
    """
    Top-level orchestrator.  Decides which agents to invoke,
    in what order, and validates results before passing to the
    FinalPlannerAgent.

    Uses ReAct-style reasoning (Thought → Action → Observation)
    via the supervisor_prompt, but the actual invocation of
    specialist agents happens in Python (not tool-call JSON)
    for reliability and speed.

    The LangGraph workflow (graph.py) calls supervisor.plan()
    which returns a routing decision; the graph then executes it.
    """

    def __init__(self) -> None:
        super().__init__("SupervisorAgent")
        # Supervisor uses a string output parser (its output is narrative)
        self._chain = supervisor_prompt | self.llm | StrOutputParser()

        # Initialise all specialist agents
        self.retrieval_agent = RetrievalAgent()
        self.tool_agent = ToolAgent()
        self.weather_agent = WeatherAgent()
        self.route_agent = RouteAgent()
        self.hotel_agent = HotelAgent()
        self.budget_agent = BudgetAgent()
        self.food_agent = FoodAgent()
        self.final_planner = FinalPlannerAgent()

    def plan(self, request: TravelRequest, current_results: dict) -> str:
        """
        Ask the LLM which agent to invoke next given current state.
        Returns a string like "RouteAgent", "WeatherAgent", or "FINISH".
        """
        raw = self._invoke_llm(self._chain, {
            "travel_request": request.model_dump_json(indent=2),
            "agent_results": json.dumps(
                {k: str(v)[:200] for k, v in current_results.items()},
                indent=2,
            ),
        })
        logger.info(f"[SupervisorAgent] Planning decision (first 200ch): {raw[:200]}")
        return raw

    def run_full_pipeline(
        self, request: TravelRequest
    ) -> TravelPlan:
        """
        Execute the complete pipeline sequentially.
        Called by the LangGraph workflow nodes.

        Pipeline order (based on dependency analysis):
        1. RetrievalAgent  → destination context (no dependencies)
        2. ToolAgent       → live API data (no dependencies)
        3. WeatherAgent    → needs tool data + RAG context
        4. RouteAgent      → needs weather + RAG context
        5. HotelAgent      → needs hotel tool data + RAG context
        6. BudgetAgent     → needs route + hotel outputs + RAG
        7. FoodAgent       → needs food tool data + RAG context
        8. FinalPlannerAgent → needs all of the above
        """
        logger.info(
            f"[SupervisorAgent] Starting full pipeline for "
            f"{request.origin} → {request.destination}"
        )

        warnings: list = []

        # ── Step 1: Retrieve RAG context ─────────────────────
        rag_contexts = self.retrieval_agent.run(request)

        # ── Step 2: Fetch tool data ───────────────────────────
        tool_data = self.tool_agent.run(request)

        # ── Step 3: Weather ───────────────────────────────────
        weather = self.weather_agent.run(
            request=request,
            weather_tool_data=tool_data["weather_data"],
            rag_context=rag_contexts["general_context"],
        )
        weather_summary = (
            f"{weather.condition}, {weather.current_temp_celsius}°C"
            if weather else "Unknown weather"
        )

        # ── Step 4: Route ─────────────────────────────────────
        route = self.route_agent.run(
            request=request,
            rag_context=rag_contexts["general_context"],
            weather_summary=weather_summary,
        )

        # ── Step 5: Hotels ────────────────────────────────────
        hotels = self.hotel_agent.run(
            request=request,
            hotel_tool_data=tool_data["hotel_data"],
            rag_context=rag_contexts["hotel_context"],
        )

        # ── Step 6: Budget ────────────────────────────────────
        budget = self.budget_agent.run(
            request=request,
            route_data=route.model_dump_json() if route else "{}",
            hotel_data=hotels.model_dump_json() if hotels else "{}",
            rag_context=rag_contexts["general_context"],
        )

        # ── Step 7: Food ──────────────────────────────────────
        food = self.food_agent.run(
            request=request,
            food_tool_data=tool_data["restaurant_data"],
            rag_context=rag_contexts["food_context"],
        )

        # ── Step 8: Final compilation ─────────────────────────
        if weather and weather.travel_warnings:
            warnings.extend(weather.travel_warnings)

        plan = self.final_planner.run(
            request=request,
            route=route,
            weather=weather,
            hotels=hotels,
            budget=budget,
            food=food,
            warnings=warnings,
        )

        logger.info(
            f"[SupervisorAgent] Pipeline complete | "
            f"plan_id={plan.plan_id if plan else 'N/A'}"
        )
        return plan


# ── Module-level agent instances ─────────────────────────────
# Lazy-initialised so import doesn't trigger LLM connection
_supervisor: Optional[SupervisorAgent] = None


def get_supervisor() -> SupervisorAgent:
    """Return the module-level SupervisorAgent singleton."""
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorAgent()
    return _supervisor


__all__ = [
    "SupervisorAgent",
    "RouteAgent",
    "WeatherAgent",
    "HotelAgent",
    "BudgetAgent",
    "FoodAgent",
    "RetrievalAgent",
    "ToolAgent",
    "FinalPlannerAgent",
    "get_supervisor",
]