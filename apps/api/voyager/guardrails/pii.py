"""PII redaction: emails, phone numbers, payment cards (Luhn-checked) and passport-like ids.

Runs on free text before it reaches the LLM, the database or Langfuse (also used as the Langfuse
`mask` function, so nothing slips through a trace).
"""

from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PHONE = re.compile(r"(?<![\w-])\+?\(?\d{1,4}\)?[\s.-]?\(?\d{2,5}\)?(?:[\s.-]?\d{2,5}){1,4}(?![\w-])")
PASSPORT = re.compile(r"\b(?:passport(?:\s*(?:no\.?|number|#))?\s*[:#]?\s*)?([A-Z]{1,2}\d{6,9})\b")
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted text, kinds found)."""
    if not text:
        return text, []
    found: list[str] = []

    def sub_email(_: re.Match) -> str:
        found.append("email")
        return "[EMAIL]"

    def sub_card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.append("card")
            return "[CARD]"
        return m.group(0)

    def sub_phone(m: re.Match) -> str:
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if DATE_LIKE.match(raw.strip()) or len(digits) < 9 or len(digits) > 15:
            return raw
        found.append("phone")
        return "[PHONE]"

    def sub_passport(m: re.Match) -> str:
        found.append("passport")
        return m.group(0).replace(m.group(1), "[ID]")

    text = EMAIL.sub(sub_email, text)
    text = CARD.sub(sub_card, text)
    text = PHONE.sub(sub_phone, text)
    text = PASSPORT.sub(sub_passport, text)
    return text, found


def redact_any(value: Any) -> Any:
    """Recursively redact strings inside dicts/lists (used as the Langfuse mask)."""
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        return {k: redact_any(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_any(v) for v in value]
    return value
