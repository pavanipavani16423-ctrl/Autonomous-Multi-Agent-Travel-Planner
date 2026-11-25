"""Scope check: Voyager only plans trips. Off-topic requests (code, essays, finance...) are refused."""

from __future__ import annotations

import re

TRAVEL = re.compile(
    r"\b(trip|travel|visit|holiday|vacation|tour|itinerary|days?|nights?|week(end)?|fly|flight|hotel|stay|"
    r"explore|sightseeing|backpack|honeymoon|getaway|city|beach|museum|temple|food|budget|go to|going to|"
    r"weekend|journey|plan)\b", re.I)
OFF_TOPIC = re.compile(
    r"\b(write (me )?(a |an )?(essay|poem|story|code|program|script|song)|python|javascript|sql query|"
    r"stock (tips?|price)|crypto|bitcoin|homework|diagnos(e|is)|prescription|lawsuit|hack(ing)?|malware|"
    r"weapon|bomb|solve (this|the) (equation|math))\b", re.I)


def in_scope(text: str) -> tuple[bool, str]:
    if not text or not text.strip():
        return False, "empty request"
    if OFF_TOPIC.search(text) and not TRAVEL.search(text):
        return False, "Voyager only plans trips; this request is outside that scope."
    if OFF_TOPIC.search(text) and len(TRAVEL.findall(text)) < 2:
        return False, "Voyager only plans trips; this request is outside that scope."
    return True, "travel request"
