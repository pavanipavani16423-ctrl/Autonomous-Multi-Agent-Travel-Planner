"""Prompt-injection detection for user free text (notes, refine messages, parse text) and for
retrieved passages (indirect injection). Patterns + heuristics, scored; no model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PATTERNS: tuple[tuple[str, float, re.Pattern[str]], ...] = tuple(
    (name, weight, re.compile(rx, re.I)) for name, weight, rx in (
        ("override", 0.9, r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your|the)\b.{0,30}\b(instructions?|prompts?|rules?|guidelines?|directions?)"),
        ("system_prompt", 0.8, r"\b(reveal|show|print|repeat|leak|output|display)\b.{0,40}\b(system|hidden|initial|developer)\s*(prompt|message|instructions?)"),
        ("role_play", 0.6, r"\b(you are now|act as|pretend (to be|you are)|from now on you)\b"),
        ("jailbreak", 0.9, r"\b(DAN|do anything now|jailbreak|developer mode|god mode)\b"),
        ("role_tags", 0.7, r"(<\|?(system|im_start|im_end|assistant)\|?>|\[/?INST\]|^\s*(system|assistant)\s*:)"),
        ("exfiltrate", 0.7, r"\b(api[_ -]?key|secret|password|token|credentials?)\b.{0,30}\b(show|send|give|reveal|print|tell)\b|\b(show|send|give|reveal|print|tell)\b.{0,30}\b(api[_ -]?key|secret key|password|credentials?)\b"),
        ("tool_abuse", 0.6, r"\b(call|invoke|execute|run)\b.{0,20}\b(tool|function|shell|command|curl|wget)\b"),
        ("code_exec", 0.6, r"(`{3}|\bimport os\b|\bsubprocess\b|\beval\(|\bexec\(|rm -rf)"),
        ("new_instructions", 0.5, r"\b(new|updated|real|actual)\s+instructions?\b"),
    )
)
THRESHOLD = 0.6


@dataclass
class InjectionResult:
    score: float
    hits: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.score >= THRESHOLD


def detect(text: str | None) -> InjectionResult:
    if not text:
        return InjectionResult(0.0)
    hits: list[str] = []
    score = 0.0
    for name, weight, rx in PATTERNS:
        if rx.search(text):
            hits.append(name)
            score = max(score, weight) + (0.1 if score else 0.0)
    # heuristics: many imperative "you must" sentences, or a wall of special tokens
    if len(re.findall(r"\byou (must|should|will)\b", text, re.I)) >= 3:
        hits.append("imperatives")
        score = max(score, 0.5) + 0.1
    if len(re.findall(r"[<>{}\[\]|]", text)) > max(20, len(text) // 8):
        hits.append("special_chars")
        score += 0.2
    return InjectionResult(min(score, 1.0), hits)


def quarantine_passage(text: str) -> bool:
    """True when a retrieved passage reads like instructions to the model (indirect injection)."""
    r = detect(text)
    return r.flagged and any(h in r.hits for h in ("override", "system_prompt", "jailbreak", "role_tags"))
