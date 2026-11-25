from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from voyager.graph.nodes.itinerary import ItineraryDraft
from voyager.llm import gateway


class Pick(BaseModel):
    name: str
    score: float = 0.5


def test_parse_json_repairs_fences_and_trailing_commas() -> None:
    out = gateway.parse_json('```json\n{"name": "Kyoto", "score": 0.9,}\n```', Pick)
    assert out == Pick(name="Kyoto", score=0.9)


def test_parse_json_wraps_a_bare_days_array() -> None:
    days = [{"day": 1, "title": "t", "theme": "t", "activities": [
        {"slot": "morning", "time": "9:00", "title": "Temple", "description": "d", "category": "temple",
         "cost": "¥500", "citations": "wv-1"}]}]
    draft = gateway.parse_json(json.dumps(days), ItineraryDraft)
    act = draft.days[0].activities[0]
    assert act.time == "09:00" and act.category == "culture" and act.cost == 500 and act.citations == ["wv-1"]


def test_parse_json_unwraps_a_wrapper_key() -> None:
    assert gateway.parse_json('{"result": {"name": "Lisbon"}}', Pick).name == "Lisbon"


def test_null_for_defaulted_field_uses_default() -> None:
    from voyager.services.parse import ParseDraft

    d = gateway.parse_json('{"destination": "Lisbon", "diet": null, "interests": null, "days": 5}', ParseDraft)
    assert d.diet == [] and d.interests == [] and d.days == 5


def test_slot_is_inferred_from_time() -> None:
    draft = gateway.parse_json(json.dumps({"days": [{"day": 1, "title": "t", "theme": "t", "activities": [
        {"slot": "night", "time": "19:30", "title": "Dinner", "description": "d"}]}]}), ItineraryDraft)
    assert draft.days[0].activities[0].slot == "evening"


@pytest.mark.anyio
async def test_structured_repairs_once_then_succeeds() -> None:
    replies = iter(['{"score": 1}', '{"name": "Fixed", "score": 1}'])

    class Chat:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content=next(replies))

    gateway.set_chat_factory(lambda model, max_tokens: Chat())
    out, method = await gateway.structured("t", Pick, "sys", "user", fallback=lambda: Pick(name="fallback"))
    assert out.name == "Fixed" and method == "llm-repaired"


@pytest.mark.anyio
async def test_structured_never_raises() -> None:
    class Chat:
        async def ainvoke(self, messages, config=None):
            raise RuntimeError("provider down")

    gateway.set_chat_factory(lambda model, max_tokens: Chat())
    out, method = await gateway.structured("t", Pick, "sys", "user", fallback=lambda: Pick(name="rules"))
    assert out.name == "rules" and method.startswith("fallback:")


@pytest.mark.anyio
async def test_token_bucket_waits_when_full() -> None:
    b = gateway.TokenBucket(1000)
    assert await b.acquire(900) == 0.0
    assert b.wait_estimate(500) > 50  # must wait for the first reservation to age out
    b.settle(900, 100)
    assert b.wait_estimate(500) == 0.0


def test_regex_fallback_understands_weekdays() -> None:
    from datetime import date

    from voyager.services.parse import regex_parse

    d = regex_parse("5 days in Lisbon starting next Friday, 2000 euros, vegetarian", date(2026, 11, 23))  # a Monday
    assert d.destination == "Lisbon" and d.start_date == "2026-11-27" and d.days == 5
    assert d.budget == 2000 and d.currency == "EUR" and d.diet == ["vegetarian"]
