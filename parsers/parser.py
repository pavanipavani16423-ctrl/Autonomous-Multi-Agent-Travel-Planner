# ============================================================
# parsers/parser.py — Pydantic Output Parsers + Repair Logic
# ============================================================
# PURPOSE:
#   Converts raw LLM string output → validated Python objects.
#   Uses LangChain's PydanticOutputParser which:
#     1. Injects the JSON schema into the prompt.
#     2. Attempts JSON parsing on the response.
#     3. Validates the parsed dict against the Pydantic model.
#   Also contains a smart repair function that fixes common LLM
#   formatting mistakes (markdown fences, trailing commas, etc.)
#
# WHY:
#   LLMs occasionally produce malformed JSON.  A robust parser
#   with auto-repair dramatically improves pipeline reliability
#   without requiring the user to retry from scratch.
# ============================================================

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Type, TypeVar

from langchain.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError
from loguru import logger

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from models.models import (
    PlanSynthesis,
    RouteOutput, WeatherOutput, HotelOutput,
    BudgetOutput, FoodOutput, TravelPlan,
)

# Generic TypeVar so repair_and_parse works with any Pydantic model
T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════
# SECTION 1 — JSON Repair Utilities
# ══════════════════════════════════════════════════════════════

def _strip_markdown_fences(text: str) -> str:
    """
    Remove ```json ... ``` or ``` ... ``` wrappers that LLMs sometimes add
    despite being instructed not to.

    Example input : '```json\n{"key": "val"}\n```'
    Example output: '{"key": "val"}'
    """
    # Match optional language tag after opening fence
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    return text.strip()


def _fix_trailing_commas(text: str) -> str:
    """
    JSON is strict: trailing commas before } or ] are invalid.
    LLMs (and humans) frequently include them.

    Replaces: ,\\n} → \\n}
              ,\\n] → \\n]
    """
    # Trailing comma before closing brace / bracket (with optional whitespace)
    text = re.sub(r",\s*([\}\]])", r"\1", text)
    return text


def _extract_first_json_object(text: str) -> str:
    """
    If the LLM prepended prose before the JSON, find and extract
    only the first { ... } block.
    """
    # Find the first opening brace
    start = text.find("{")
    if start == -1:
        return text  # No JSON found; return as-is and let parser fail loudly

    # Walk forward tracking brace depth to find matching close
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return text[start:]  # Incomplete JSON — best effort


def repair_json(raw: str) -> str:
    """
    Apply all repair heuristics in sequence.
    Returns the best-effort repaired JSON string.
    """
    raw = _strip_markdown_fences(raw)
    raw = _fix_trailing_commas(raw)
    raw = _extract_first_json_object(raw)
    return raw


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Generic Parse + Repair Function
# ══════════════════════════════════════════════════════════════

def repair_and_parse(raw_output: str, model_class: Type[T]) -> Optional[T]:
    """
    Attempts to parse raw LLM text into a Pydantic model instance.

    Strategy:
    1. Try direct JSON parse + Pydantic validation (fast path).
    2. If that fails, run repair_json() and retry (slow path).
    3. If still failing, log the error and return None.

    Parameters
    ----------
    raw_output  : The raw string returned by the LLM.
    model_class : The Pydantic BaseModel subclass to parse into.

    Returns
    -------
    An instance of model_class, or None on irrecoverable failure.
    """
    # ── Attempt 1: Direct parse ──────────────────────────────
    try:
        data = json.loads(raw_output)
        instance = model_class(**data)
        logger.debug(f"[Parser] Direct parse succeeded for {model_class.__name__}")
        return instance
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        logger.debug(f"[Parser] Direct parse failed ({e}), attempting repair…")

    # ── Attempt 2: Repaired parse ────────────────────────────
    try:
        repaired = repair_json(raw_output)
        data = json.loads(repaired)
        instance = model_class(**data)
        logger.info(
            f"[Parser] Repaired JSON parse succeeded for {model_class.__name__}"
        )
        return instance
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        logger.error(
            f"[Parser] Could not parse {model_class.__name__} after repair: {e}\n"
            f"Raw output (first 400 chars): {raw_output[:400]}"
        )
        return None


# ══════════════════════════════════════════════════════════════
# SECTION 3 — Typed Parser Instances
# ══════════════════════════════════════════════════════════════
# LangChain's PydanticOutputParser does two things:
#   • get_format_instructions() → embeds the JSON schema into the prompt
#   • parse(text) → validates text against the Pydantic model
#
# We create one instance per output type and expose them as
# module-level singletons for import across the project.

route_parser = PydanticOutputParser(pydantic_object=RouteOutput)
weather_parser = PydanticOutputParser(pydantic_object=WeatherOutput)
hotel_parser = PydanticOutputParser(pydantic_object=HotelOutput)
budget_parser = PydanticOutputParser(pydantic_object=BudgetOutput)
food_parser = PydanticOutputParser(pydantic_object=FoodOutput)
travel_plan_parser = PydanticOutputParser(pydantic_object=TravelPlan)
plan_synthesis_parser = PydanticOutputParser(pydantic_object=PlanSynthesis)


# ══════════════════════════════════════════════════════════════
# SECTION 4 — Agent-Specific Safe Parse Wrappers
# ══════════════════════════════════════════════════════════════
# Each wrapper adds:
#   • Automatic format_instructions injection into the prompt
#   • Fallback to repair_and_parse on failure
#   • Logging of confidence scores

def parse_route_output(raw: str) -> Optional[RouteOutput]:
    """Parse LLM output → RouteOutput with auto-repair."""
    try:
        result = route_parser.parse(raw)
        logger.info(f"[RouteParser] Parsed OK | confidence={result.confidence}")
        return result
    except OutputParserException:
        return repair_and_parse(raw, RouteOutput)


def parse_weather_output(raw: str) -> Optional[WeatherOutput]:
    """Parse LLM output → WeatherOutput with auto-repair."""
    try:
        result = weather_parser.parse(raw)
        logger.info(f"[WeatherParser] Parsed OK | confidence={result.confidence}")
        return result
    except OutputParserException:
        return repair_and_parse(raw, WeatherOutput)


def parse_hotel_output(raw: str) -> Optional[HotelOutput]:
    """Parse LLM output → HotelOutput with auto-repair."""
    try:
        result = hotel_parser.parse(raw)
        logger.info(f"[HotelParser] Parsed OK | confidence={result.confidence}")
        return result
    except OutputParserException:
        return repair_and_parse(raw, HotelOutput)


def parse_budget_output(raw: str) -> Optional[BudgetOutput]:
    """Parse LLM output → BudgetOutput with auto-repair."""
    try:
        result = budget_parser.parse(raw)
        logger.info(f"[BudgetParser] Parsed OK | confidence={result.confidence}")
        return result
    except OutputParserException:
        return repair_and_parse(raw, BudgetOutput)


def parse_food_output(raw: str) -> Optional[FoodOutput]:
    """Parse LLM output → FoodOutput with auto-repair."""
    try:
        result = food_parser.parse(raw)
        logger.info(f"[FoodParser] Parsed OK | confidence={result.confidence}")
        return result
    except OutputParserException:
        return repair_and_parse(raw, FoodOutput)


def parse_travel_plan(raw: str) -> Optional[TravelPlan]:
    """Parse LLM output → TravelPlan with auto-repair."""
    try:
        result = travel_plan_parser.parse(raw)
        logger.info(
            f"[PlanParser] Parsed OK | confidence={result.overall_confidence}"
        )
        return result
    except OutputParserException:
        return repair_and_parse(raw, TravelPlan)


# ══════════════════════════════════════════════════════════════
# SECTION 5 — Format Instructions Getters
# ══════════════════════════════════════════════════════════════
# Prompts need format_instructions to tell the LLM exactly which
# JSON fields are expected.

def get_route_format_instructions() -> str:
    return route_parser.get_format_instructions()

def get_weather_format_instructions() -> str:
    return weather_parser.get_format_instructions()

def get_hotel_format_instructions() -> str:
    return hotel_parser.get_format_instructions()

def get_budget_format_instructions() -> str:
    return budget_parser.get_format_instructions()

def get_food_format_instructions() -> str:
    return food_parser.get_format_instructions()


def parse_plan_synthesis(raw: str) -> Optional[PlanSynthesis]:
    """Parse LLM output -> PlanSynthesis with auto-repair."""
    try:
        result = plan_synthesis_parser.parse(raw)
        logger.info(
            f"[SynthesisParser] Parsed OK | confidence={result.overall_confidence}"
        )
        return result
    except OutputParserException:
        return repair_and_parse(raw, PlanSynthesis)


def get_plan_synthesis_format_instructions() -> str:
    return plan_synthesis_parser.get_format_instructions()


__all__ = [
    "repair_and_parse",
    "repair_json",
    "parse_route_output",
    "parse_weather_output",
    "parse_hotel_output",
    "parse_budget_output",
    "parse_food_output",
    "parse_travel_plan",
    "parse_plan_synthesis",
    "get_plan_synthesis_format_instructions",
    "get_route_format_instructions",
    "get_weather_format_instructions",
    "get_hotel_format_instructions",
    "get_budget_format_instructions",
    "get_food_format_instructions",
    "route_parser",
    "weather_parser",
    "hotel_parser",
    "budget_parser",
    "food_parser",
]