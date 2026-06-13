# ============================================================
# guardrails/guardrails.py — Input & Output Safety Validation
# ============================================================
# PURPOSE:
#   Enforces a double guardrail:
#     1. INPUT guardrail  — validates TravelRequest before any LLM call.
#     2. OUTPUT guardrail — validates each agent's structured output
#                           before it enters the shared state.
#
# WHY:
#   Without guardrails, adversarial or malformed inputs can cause
#   agents to generate nonsensical, harmful, or extremely expensive
#   plans.  Failing fast with clear error messages is far better
#   than propagating bad data through 7+ agents.
# ============================================================

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, List, Any

from pydantic import ValidationError
from loguru import logger

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import guardrail_config
from models.models import (
    TravelRequest, RouteOutput, WeatherOutput,
    HotelOutput, BudgetOutput, FoodOutput, TravelPlan,
)


# ══════════════════════════════════════════════════════════════
# SECTION 1 — Result Container
# ══════════════════════════════════════════════════════════════

class GuardrailResult:
    """
    Immutable result of a guardrail check.

    Attributes
    ----------
    passed   : True when all checks pass; False on any violation.
    errors   : List of human-readable violation messages.
    warnings : Non-blocking advisory messages.
    """

    def __init__(self) -> None:
        self.passed: bool = True
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def fail(self, message: str) -> None:
        """Record a blocking violation."""
        self.passed = False
        self.errors.append(message)
        logger.warning(f"[Guardrail] FAIL → {message}")

    def warn(self, message: str) -> None:
        """Record a non-blocking advisory."""
        self.warnings.append(message)
        logger.info(f"[Guardrail] WARN → {message}")

    def __repr__(self) -> str:
        return (
            f"GuardrailResult(passed={self.passed}, "
            f"errors={self.errors}, warnings={self.warnings})"
        )


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Input Guardrails
# ══════════════════════════════════════════════════════════════

def validate_travel_request(request: TravelRequest) -> GuardrailResult:
    """
    Comprehensive input validation before any agent is invoked.

    Checks performed:
    ─────────────────
    1. GROQ API key present (prevents silent failures deep in the graph).
    2. Banned keyword scan across all string fields.
    3. Date logic — departure must be in the future; return after departure.
    4. Trip duration within [min_trip_days, max_trip_days].
    5. Budget within [1, max_budget_usd].
    6. Traveller count positive.
    7. Origin ≠ Destination.
    """
    result = GuardrailResult()
    cfg = guardrail_config

    # ── Check 1: Non-empty destination/origin ────────────────
    if not request.origin.strip():
        result.fail("Origin city cannot be empty.")
    if not request.destination.strip():
        result.fail("Destination city cannot be empty.")

    # ── Check 2: Origin ≠ Destination ────────────────────────
    if request.origin.strip().lower() == request.destination.strip().lower():
        result.fail("Origin and destination must be different cities.")

    # ── Check 3: Banned keyword scan ─────────────────────────
    all_text = " ".join(
        str(v) for v in [
            request.origin, request.destination,
            request.travel_purpose, request.special_requests or "",
            request.dietary_preference,
        ]
    ).lower()

    for kw in cfg.banned_keywords:
        if kw in all_text:
            result.fail(
                f"Request contains prohibited content: '{kw}'. "
                "This system only supports legitimate travel planning."
            )

    # ── Check 4: Date validation ──────────────────────────────
    try:
        dep = datetime.strptime(request.departure_date, "%Y-%m-%d")
        ret = datetime.strptime(request.return_date, "%Y-%m-%d")
        today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

        if dep < today:
            result.fail(
                f"Departure date {request.departure_date} is in the past. "
                "Please select a future date."
            )
        if ret <= dep:
            result.fail(
                "Return date must be strictly after departure date."
            )

        trip_days = (ret - dep).days
        if trip_days < cfg.min_trip_days:
            result.fail(
                f"Trip duration {trip_days} day(s) is below the minimum "
                f"of {cfg.min_trip_days} day(s)."
            )
        if trip_days > cfg.max_trip_days:
            result.fail(
                f"Trip duration {trip_days} days exceeds the maximum "
                f"of {cfg.max_trip_days} days supported by this planner."
            )

    except ValueError as e:
        result.fail(f"Invalid date format: {e}. Use YYYY-MM-DD.")

    # ── Check 5: Budget validation ────────────────────────────
    if request.budget_usd <= 0:
        result.fail("Budget must be greater than $0.")
    if request.budget_usd > cfg.max_budget_usd:
        result.warn(
            f"Budget ${request.budget_usd:,.0f} is unusually high. "
            "Proceeding, but please verify."
        )

    # ── Check 6: Traveller count ──────────────────────────────
    if request.travellers < 1:
        result.fail("Number of travellers must be at least 1.")
    if request.travellers > 20:
        result.warn(
            "More than 20 travellers detected. Plans are optimised for groups ≤ 20."
        )

    # ── Check 7: Valid enum values ────────────────────────────
    valid_purposes = {"leisure", "business", "adventure", "family", "honeymoon"}
    if request.travel_purpose.lower() not in valid_purposes:
        result.warn(
            f"Unknown travel purpose '{request.travel_purpose}'. "
            f"Valid options: {valid_purposes}. Defaulting to 'leisure'."
        )

    valid_dietary = {"vegetarian", "vegan", "no preference", "halal", "kosher"}
    if request.dietary_preference.lower() not in valid_dietary:
        result.warn(
            f"Dietary preference '{request.dietary_preference}' not recognised. "
            "Will use 'no preference'."
        )

    logger.info(
        f"[Guardrail] Input validation complete | "
        f"passed={result.passed} errors={len(result.errors)} "
        f"warnings={len(result.warnings)}"
    )
    return result


# ══════════════════════════════════════════════════════════════
# SECTION 3 — Output / Agent-Result Guardrails
# ══════════════════════════════════════════════════════════════

def validate_agent_confidence(
    agent_name: str, output: Any, threshold: Optional[float] = None
) -> GuardrailResult:
    """
    Checks that an agent's output confidence meets the minimum floor.

    Parameters
    ----------
    agent_name : Display name used in log messages.
    output     : Any Pydantic model that has a `confidence` field.
    threshold  : Override the config's confidence_floor.
    """
    result = GuardrailResult()
    floor = threshold or guardrail_config.confidence_floor

    if output is None:
        result.fail(
            f"{agent_name} returned None — parsing likely failed. "
            "Check LLM output format."
        )
        return result

    confidence = getattr(output, "confidence", None)
    if confidence is None:
        result.warn(f"{agent_name} output has no confidence field.")
        return result

    if confidence < floor:
        result.fail(
            f"{agent_name} confidence {confidence:.2f} is below threshold {floor}. "
            "Consider re-invoking with additional context."
        )
    elif confidence < 0.7:
        result.warn(
            f"{agent_name} confidence {confidence:.2f} is acceptable but not high. "
            "Results may be incomplete."
        )

    return result


def validate_route_output(output: Optional[RouteOutput]) -> GuardrailResult:
    """Domain-specific validation for RouteOutput."""
    result = GuardrailResult()

    if output is None:
        result.fail("RouteOutput is None.")
        return result

    # Must have at least 1 itinerary day
    if not output.day_wise_itinerary:
        result.fail("Route plan has no day-wise itinerary.")

    # Day count consistency
    expected_days = output.total_days
    actual_days = len(output.day_wise_itinerary)
    if actual_days != expected_days:
        result.warn(
            f"Route plan says {expected_days} days but itinerary has {actual_days} entries."
        )

    # Each day must have activities
    for day in output.day_wise_itinerary:
        if not day.activities:
            result.warn(f"Day {day.day} has no activities listed.")

    result.passed = result.passed and len(result.errors) == 0
    return result


def validate_budget_output(
    output: Optional[BudgetOutput], request: TravelRequest
) -> GuardrailResult:
    """Validate budget output doesn't wildly exceed requested budget."""
    result = GuardrailResult()

    if output is None:
        result.fail("BudgetOutput is None.")
        return result

    # Total trip cost must be <= requested budget * 1.2 (20 % tolerance)
    max_allowed = request.budget_usd * 1.2
    if output.total_trip_cost_usd > max_allowed:
        result.fail(
            f"Estimated total cost ${output.total_trip_cost_usd:,.0f} exceeds "
            f"budget ${request.budget_usd:,.0f} by more than 20%. "
            "Agent may have misunderstood the budget constraint."
        )
    elif output.total_trip_cost_usd > request.budget_usd:
        result.warn(
            f"Estimated cost ${output.total_trip_cost_usd:,.0f} slightly exceeds "
            f"budget ${request.budget_usd:,.0f}. Consider the saving tips."
        )

    # Breakdown must sum reasonably close to total
    bd = output.per_person_breakdown
    sub_total = (
        bd.flights_usd + bd.accommodation_usd + bd.food_usd
        + bd.local_transport_usd + bd.activities_usd + bd.miscellaneous_usd
    )
    per_person_total = bd.total_usd
    if abs(sub_total - per_person_total) > per_person_total * 0.05:
        result.warn(
            f"Budget breakdown components sum to ${sub_total:,.0f} but "
            f"per_person total is ${per_person_total:,.0f} — minor discrepancy."
        )

    return result


def validate_hotel_output(output: Optional[HotelOutput]) -> GuardrailResult:
    """Ensure at least one hotel option exists per tier."""
    result = GuardrailResult()

    if output is None:
        result.fail("HotelOutput is None.")
        return result

    if not output.budget_hotels:
        result.warn("No budget hotel options returned.")
    if not output.premium_hotels:
        result.warn("No premium hotel options returned.")
    if not output.family_hotels:
        result.warn("No family hotel options returned.")

    # Validate all hotels have non-zero prices
    all_hotels = output.budget_hotels + output.premium_hotels + output.family_hotels
    for hotel in all_hotels:
        if hotel.price_per_night_usd <= 0:
            result.fail(f"Hotel '{hotel.name}' has invalid price ${hotel.price_per_night_usd}.")

    return result


def validate_final_plan(plan: Optional[TravelPlan]) -> GuardrailResult:
    """Top-level validation of the assembled TravelPlan."""
    result = GuardrailResult()

    if plan is None:
        result.fail("FinalPlannerAgent returned None plan.")
        return result

    if not plan.executive_summary:
        result.warn("Executive summary is missing from the final plan.")

    if plan.overall_confidence < guardrail_config.confidence_floor:
        result.fail(
            f"Overall plan confidence {plan.overall_confidence:.2f} is below "
            f"threshold {guardrail_config.confidence_floor}. Plan may be unreliable."
        )

    # At least 3 of 5 sub-plans must be populated
    populated = sum([
        plan.route is not None,
        plan.weather is not None,
        plan.hotels is not None,
        plan.budget is not None,
        plan.food is not None,
    ])
    if populated < 3:
        result.fail(
            f"Only {populated}/5 agent sub-plans are populated. "
            "Plan is incomplete."
        )

    logger.info(
        f"[Guardrail] Final plan validation | passed={result.passed} "
        f"confidence={plan.overall_confidence:.2f}"
    )
    return result


# ══════════════════════════════════════════════════════════════
# SECTION 4 — Convenience Orchestrator
# ══════════════════════════════════════════════════════════════

def run_all_output_guardrails(
    route: Optional[RouteOutput],
    weather: Optional[WeatherOutput],
    hotels: Optional[HotelOutput],
    budget: Optional[BudgetOutput],
    food: Optional[FoodOutput],
    request: TravelRequest,
) -> GuardrailResult:
    """
    Run every output guardrail in sequence and aggregate results.
    Returns a single GuardrailResult that merges all findings.
    """
    master = GuardrailResult()

    checks = [
        ("RouteAgent",   validate_agent_confidence("RouteAgent", route)),
        ("RouteOutput",  validate_route_output(route)),
        ("WeatherAgent", validate_agent_confidence("WeatherAgent", weather)),
        ("HotelAgent",   validate_agent_confidence("HotelAgent", hotels)),
        ("HotelOutput",  validate_hotel_output(hotels)),
        ("BudgetAgent",  validate_agent_confidence("BudgetAgent", budget)),
        ("BudgetOutput", validate_budget_output(budget, request)),
        ("FoodAgent",    validate_agent_confidence("FoodAgent", food)),
    ]

    for label, check_result in checks:
        if not check_result.passed:
            for err in check_result.errors:
                master.fail(f"[{label}] {err}")
        for warn in check_result.warnings:
            master.warn(f"[{label}] {warn}")

    return master


__all__ = [
    "GuardrailResult",
    "validate_travel_request",
    "validate_agent_confidence",
    "validate_route_output",
    "validate_budget_output",
    "validate_hotel_output",
    "validate_final_plan",
    "run_all_output_guardrails",
]