"""Input guardrails: prompt injection, PII redaction, scope, date and budget sanity."""

from __future__ import annotations

from dataclasses import dataclass, field

from voyager.guardrails import injection, pii, sanity, scope
from voyager.schemas import Check, TripRequest


@dataclass
class GuardResult:
    request: TripRequest
    blocked: bool = False
    reason: str = ""
    checks: list[Check] = field(default_factory=list)
    pii_found: list[str] = field(default_factory=list)
    injection_hits: list[str] = field(default_factory=list)


def check_request(req: TripRequest, max_days: int = 14) -> GuardResult:
    """Sanitise a request. Injection in notes -> notes dropped (the run continues, flagged).
    Injection in the destination, an off-topic destination, or bad dates -> blocked."""
    data = req.model_dump()
    checks: list[Check] = []
    pii_found: list[str] = []
    for key in ("notes", "origin", "destination"):
        if data.get(key):
            data[key], kinds = pii.redact(data[key])
            pii_found += kinds
    checks.append(Check(name="PII redaction", passed=True,
                        detail=f"redacted: {', '.join(sorted(set(pii_found)))}" if pii_found
                        else "no personal data found"))

    blocked, reason, hits = False, "", []
    dest_inj = injection.detect(data["destination"])
    if dest_inj.flagged:
        blocked, reason = True, "The destination field contains instructions rather than a place."
        hits += dest_inj.hits
    notes_inj = injection.detect(data.get("notes"))
    if notes_inj.flagged:
        hits += notes_inj.hits
        data["notes"] = None
    if hits:
        detail = ("notes removed; " if notes_inj.flagged else "") + "patterns: " + ", ".join(hits)
    else:
        detail = "no injection patterns"
    checks.append(Check(name="Prompt injection", passed=not (dest_inj.flagged or notes_inj.flagged),
                        detail=detail))

    ok, why = scope.in_scope(f"trip to {data['destination']}")
    if data.get("notes") and not scope.in_scope(data["notes"] + " trip")[0]:
        data["notes"] = None
        why = "off-topic notes removed"
    if not ok:
        blocked, reason = True, reason or why
    checks.append(Check(name="Scope", passed=ok, detail=why))

    clean = TripRequest.model_validate(data)
    problems = sanity.date_problems(clean, max_days=max_days) + sanity.budget_problems(clean)
    if problems:
        blocked, reason = True, reason or " ".join(problems)
    checks.append(Check(name="Dates & budget", passed=not problems, detail=" ".join(problems) or "valid"))
    return GuardResult(clean, blocked, reason, checks, pii_found, hits)
