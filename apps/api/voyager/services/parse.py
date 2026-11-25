"""Free text -> TripRequest draft. LLM (small model) with today's date for relative dates, a regex
fallback, then the preference profile fills whatever the text didn't say."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from voyager.guardrails import injection, pii, scope
from voyager.llm.gateway import structured
from voyager.memory.preferences import prefill
from voyager.schemas import TripRequest


class ParseDraft(BaseModel):
    destination: str = Field(description="city or place, e.g. 'Kyoto'")
    origin: str | None = None
    start_date: str | None = Field(None, description="YYYY-MM-DD")
    end_date: str | None = Field(None, description="YYYY-MM-DD, inclusive")
    days: int | None = None
    adults: int | None = None
    children: int | None = None
    budget: float | None = None
    currency: str | None = Field(None, description="ISO 4217")
    interests: list[str] = Field(default_factory=list)
    pace: str | None = Field(None, description="relaxed | balanced | packed")
    diet: list[str] = Field(default_factory=list)
    stay_style: str | None = Field(None, description="budget | mid | luxury")
    notes: str | None = None


SYSTEM = (
    "Extract a trip request from the traveller's message. Resolve relative dates ('next Friday', "
    "'in two weeks', 'mid-December') against TODAY. Only fill fields the message states or clearly implies; "
    "leave the rest null. 'for 2' / 'for two' / 'a couple' means adults=2. interests from: food, temples, nature, nightlife, art, shopping, history, adventure. "
    "diet from: vegetarian, vegan, halal, jain, kosher, gluten-free.")

CURRENCY_SIGNS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "rs": "INR", "inr": "INR",
                  "usd": "USD", "eur": "EUR", "gbp": "GBP", "jpy": "JPY", "aud": "AUD", "cad": "CAD", "sgd": "SGD"}
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "a": 1}


def regex_parse(text: str, today: date) -> ParseDraft:
    t = text.lower()
    dest = None
    m = re.search(r"\b(?:to|in|visit|visiting|explore)\s+([A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,2})", text)
    if m:
        dest = m.group(1).strip(" .,")
    days = None
    m = re.search(r"\b(\d{1,2}|" + "|".join(WORD_NUM) + r")[\s-]*(day|night)s?\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1)]
        days = n + (1 if m.group(2) == "night" else 0)
    elif "weekend" in t:
        days = 3
    elif re.search(r"\b(a|one) week\b", t):
        days = 7
    budget, currency = None, None
    m = re.search(r"(\$|€|£|¥|₹|rs\.?|inr|usd|eur|gbp|jpy)\s*([\d,]+(?:\.\d+)?)\s*(k|lakh)?", t) or \
        re.search(r"([\d,]+(?:\.\d+)?)\s*(k|lakh)?\s*(\$|€|£|¥|₹|rs|inr|usd|eur|gbp|jpy|dollars|euros|rupees)", t)
    if m:
        groups = m.groups()
        if groups[0] and not groups[0][0].isdigit():
            sign, num, mult = groups[0], groups[1], groups[2]
        else:
            num, mult, sign = groups
        budget = float(num.replace(",", "")) * (1000 if mult == "k" else 100000 if mult == "lakh" else 1)
        sign = sign.rstrip(".")
        currency = CURRENCY_SIGNS.get(sign) or {"dollars": "USD", "euros": "EUR", "rupees": "INR"}.get(sign)
    adults = None
    m = re.search(r"\b(\d+|two|three|four|five|six)\s+(adults|people|of us|friends|persons)\b", t)
    if m:
        adults = int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1)]
    elif re.search(r"\b(couple|my (wife|husband|partner)|two of us)\b", t):
        adults = 2
    else:  # "for 2", "for two" (but not "for 4 days" or "for 40,000")
        m = re.search(r"\bfor\s+(\d{1,2}|two|three|four|five|six)\b(?!\d|[.,]\d)(?!\s*(?:day|night|week|k\b|lakh))", t)
        if m:
            adults = int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1)]
    start = None
    if "next week" in t:
        start = today + timedelta(days=7 - today.weekday())
    elif "next month" in t:
        start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    m = re.search(r"\b(next|this|on)\s+(" + "|".join(days_of_week) + r")\b", t)
    if m:
        ahead = (days_of_week.index(m.group(2)) - today.weekday()) % 7 or 7
        start = today + timedelta(days=ahead + (7 if m.group(1) == "next" and ahead < 3 else 0))
    m = re.search(r"in (\d+|two|three|four) weeks", t)
    if m:
        start = today + timedelta(weeks=int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1)])
    interests = [i for i in ("food", "temples", "nature", "nightlife", "art", "shopping", "history", "adventure")
                 if re.search(rf"\b{i.rstrip('s')}s?\b", t) or (i == "art" and "museum" in t)]
    diet = [d for d in ("vegetarian", "vegan", "halal", "jain", "kosher", "gluten-free") if d in t]
    pace = "relaxed" if re.search(r"\b(relax|slow|chill)", t) else "packed" if re.search(r"\b(packed|busy|see everything)", t) else None
    style = "budget" if re.search(r"\b(cheap|budget|backpack|hostel)", t) else "luxury" if re.search(r"\b(luxury|5-star|fancy)", t) else None
    return ParseDraft(destination=dest or "", start_date=start.isoformat() if start else None, days=days,
                      adults=adults, budget=budget, currency=currency, interests=interests, pace=pace, diet=diet,
                      stay_style=style)


async def parse_text(text: str, profile: dict[str, Any] | None = None, today: date | None = None) -> TripRequest:
    """Raises ValueError with a human message when the text can't become a trip request."""
    today = today or date.today()
    if injection.detect(text).flagged:
        raise ValueError("That message looks like instructions to the assistant rather than a trip description.")
    ok, why = scope.in_scope(text)
    if not ok:
        raise ValueError(why)
    clean, _ = pii.redact(text)
    user = f"TODAY: {today.isoformat()} ({today:%A})\nMessage: {clean}"
    draft, _method = await structured("parse", ParseDraft, SYSTEM, user, fallback=lambda: regex_parse(clean, today),
                                      size="small", max_tokens=600)
    if not draft.destination:
        draft.destination = regex_parse(clean, today).destination
    if not draft.destination:
        raise ValueError("Couldn't find a destination in that message. Try e.g. '4 days in Kyoto in March'.")
    defaults = prefill(profile or {})
    start = _date(draft.start_date) or today + timedelta(days=14)
    if start < today:
        start = today + timedelta(days=1)
    days = draft.days
    end = _date(draft.end_date)
    if end is None or end < start:
        end = start + timedelta(days=max(1, min(days or 4, 14)) - 1)
    if (end - start).days > 13:
        end = start + timedelta(days=13)
    currency = (draft.currency or defaults.get("currency") or "USD").upper()[:3]
    adults = max(1, draft.adults or regex_parse(clean, today).adults or 1)
    n_days = (end - start).days + 1
    budget = draft.budget or _default_budget(currency, n_days, adults)
    pace = draft.pace if draft.pace in ("relaxed", "balanced", "packed") else defaults.get("pace", "balanced")
    style = draft.stay_style if draft.stay_style in ("budget", "mid", "luxury") else defaults.get("stay_style", "mid")
    return TripRequest(
        origin=draft.origin or defaults.get("origin"), destination=draft.destination[:120],
        start_date=start.isoformat(), end_date=end.isoformat(), adults=adults,
        children=max(0, draft.children or 0), budget=budget, currency=currency,
        interests=draft.interests or defaults.get("interests", []), pace=pace,
        diet=draft.diet or defaults.get("diet", []), stay_style=style,
        notes=(draft.notes or None) and draft.notes[:1000])


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _default_budget(currency: str, days: int, adults: int) -> float:
    per_day_usd = 150.0
    rough = {"USD": 1, "EUR": 0.92, "GBP": 0.78, "INR": 85, "JPY": 155, "AUD": 1.5, "CAD": 1.37, "SGD": 1.33}
    return round(per_day_usd * days * adults * rough.get(currency, 1), -1)
