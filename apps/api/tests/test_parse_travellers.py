"""Traveller count from free text: "for 2" means two adults, but "for 4 days" and "for 40,000" don't."""

from __future__ import annotations

from datetime import date

import pytest

from voyager.services.parse import regex_parse

TODAY = date(2026, 11, 25)


@pytest.mark.parametrize(("text", "adults"), [
    ("4 days in Udaipur from 18 December for 2, ₹50,000", 2),
    ("3 days in Goa for two people", 2),
    ("a weekend in Rome for 3", 3),
    ("Goa for 2.", 2),
    ("honeymoon in Bali with my wife", 2),
    ("trip to Goa for 4 days", None),
    ("Paris for 40,000 rupees", None),
    ("Kyoto for 2.5k dollars", None),
])
def test_traveller_count(text: str, adults: int | None) -> None:
    assert regex_parse(text, TODAY).adults == adults
