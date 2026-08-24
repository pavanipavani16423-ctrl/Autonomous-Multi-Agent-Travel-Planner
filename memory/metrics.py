# ============================================================
# memory/metrics.py — Objective quality metrics for one run
# ============================================================
# PURPOSE:
#   Turn a finished pipeline state into a small dict of numbers that can be
#   stored, compared across prompt versions, and asserted against thresholds.
#
# WHY THESE METRICS:
#   Every number here is computed from the run itself — no LLM judge, no
#   RAGAS, no ground truth. That matters because the metrics have to be
#   trustworthy enough to gate a release, and a judge that shares a model
#   family with the thing it grades is not that.
#
#   The agents' own `confidence` fields are deliberately NOT used as a quality
#   signal. They sat at 0.93 while the plan was built entirely on fixture
#   weather; self-reported confidence measures nothing.
# ============================================================

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# The five specialist outputs that must be present for a plan to be complete.
AGENT_SECTIONS = ("route", "weather", "hotels", "budget", "food")


def plan_metrics(state: dict, latency_s: Optional[float] = None) -> Dict[str, Any]:
    """
    Compute quality metrics for a finished run.

    Parameters
    ----------
    state     : the dict returned by run_travel_pipeline()
    latency_s : wall-clock seconds for the run, if measured

    Returns
    -------
    Flat dict of JSON-serialisable metrics.
    """
    plan = state.get("final_plan")
    request = state.get("request")

    # ── Completeness: did every agent produce a parseable output? ──
    present = [s for s in AGENT_SECTIONS if state.get(s) is not None]
    section_completeness = len(present) / len(AGENT_SECTIONS)

    # ── Provenance: how much rests on real data rather than fixtures? ──
    sources = getattr(plan, "data_sources", None) or {}
    live = sum(1 for v in sources.values() if v in ("live", "curated"))
    live_data_ratio = (live / len(sources)) if sources else 0.0

    # ── Grounding: how much came from the knowledge base? ──
    grounding = getattr(plan, "rag_grounding", None) or {}
    grounded = sum(1 for v in grounding.values() if v)
    grounding_ratio = (grounded / len(grounding)) if grounding else 0.0

    # ── Synthesis: did the final planner's own JSON parse? ──
    # A generated fallback summary is the tell-tale of a parse failure, which
    # is exactly the silent regression this metric exists to catch.
    summary = getattr(plan, "executive_summary", "") or ""
    fallback_marker = "The plan covers routes, accommodation, dining, and budget"
    synthesis_ok = bool(summary) and fallback_marker not in summary

    # ── Budget sanity: does the costing respect what was asked for? ──
    budget_ok = True
    budget_overrun = 0.0
    budget = state.get("budget")
    if budget is not None and request is not None:
        try:
            total = float(budget.total_trip_cost_usd)
            asked = float(request.budget_usd)
            if asked > 0:
                budget_overrun = max(0.0, (total - asked) / asked)
                budget_ok = total <= asked
        except (TypeError, ValueError, AttributeError):
            pass

    # ── Itinerary sanity: does the day count match the dates? ──
    itinerary_ok = True
    route = state.get("route")
    if route is not None and request is not None:
        try:
            from datetime import datetime
            dep = datetime.strptime(request.departure_date, "%Y-%m-%d").date()
            ret = datetime.strptime(request.return_date, "%Y-%m-%d").date()
            nights = (ret - dep).days
            n_days = len(route.day_wise_itinerary)
            itinerary_ok = n_days in (nights, nights + 1)
        except (ValueError, TypeError, AttributeError):
            pass

    warnings = state.get("warnings", []) or []
    errors = state.get("errors", []) or []

    return {
        "has_plan": plan is not None,
        "section_completeness": round(section_completeness, 3),
        "sections_missing": [s for s in AGENT_SECTIONS if state.get(s) is None],
        "live_data_ratio": round(live_data_ratio, 3),
        "grounding_ratio": round(grounding_ratio, 3),
        "synthesis_ok": synthesis_ok,
        "budget_ok": budget_ok,
        "budget_overrun": round(budget_overrun, 3),
        "itinerary_ok": itinerary_ok,
        "guardrail_warnings": len(warnings),
        "errors": len(errors),
        "latency_s": round(latency_s, 1) if latency_s is not None else None,
    }


# ── Release thresholds ───────────────────────────────────────
# What "good enough to ship" means. Deliberately conservative: these are
# floors that a working pipeline clears comfortably, so a failure means
# something actually broke rather than that the bar is fussy.
#
# live_data_ratio is NOT gated — it depends on which API keys are configured,
# not on the code, so gating it would fail every run on a demo box.
THRESHOLDS: Dict[str, float] = {
    "has_plan": 1.0,               # every request must produce a plan
    "section_completeness": 1.0,   # all five specialists must parse
    "synthesis_ok": 1.0,           # the LLM summary must not fall back
    "itinerary_ok": 1.0,           # day count must match the dates
    "errors": 0.0,                 # max allowed
    "latency_s": 420.0,            # max allowed
}

# Metrics where a HIGHER number is worse.
_UPPER_BOUND = {"errors", "latency_s", "budget_overrun"}


def check_thresholds(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare metrics to THRESHOLDS.

    Returns {"passed": bool, "failures": [str], "checked": int}.
    Missing or None metrics are skipped rather than failed — an unmeasured
    value is not evidence of a regression.
    """
    failures = []
    checked = 0

    for name, limit in THRESHOLDS.items():
        value = metrics.get(name)
        if value is None:
            continue
        checked += 1
        numeric = float(value) if not isinstance(value, bool) else float(bool(value))

        if name in _UPPER_BOUND:
            if numeric > limit:
                failures.append(f"{name}={numeric:g} exceeds max {limit:g}")
        else:
            if numeric < limit:
                failures.append(f"{name}={numeric:g} below min {limit:g}")

    return {"passed": not failures, "failures": failures, "checked": checked}


__all__ = ["plan_metrics", "check_thresholds", "THRESHOLDS", "AGENT_SECTIONS"]
