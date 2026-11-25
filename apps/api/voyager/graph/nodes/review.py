"""`budget` (remote A2A Budget Analyst, local fallback), `critic` (rules + LLM judge, one retry) and
`finalize` (TripPlan + quality + Langfuse scores)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from voyager.a2a.budget_agent import cost_trip
from voyager.a2a.client import ask_budget
from voyager.config import get_settings
from voyager.eval.online import compute_quality
from voyager.graph.context import RunContext, agent_node
from voyager.graph.helpers import BUDGET_ANALYST, norm, req_of, within_km
from voyager.graph.state import TripState
from voyager.llm.gateway import describe_mode, structured
from voyager.mcp.servers.weather import is_wet
from voyager.observability.tracing import get_tracer
from voyager.rag.store import get_guidebook
from voyager.schemas import Check, TripPlan

MAX_CRITIC_RETRIES = 1

# ---------------------------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------------------------


def budget_payload(state: TripState) -> dict[str, Any]:
    b = state["brief"]
    return {
        "request": state["request"], "country_code": b.get("country_code") or "", "fx": b.get("fx") or {},
        "stays": [{"name": s["name"], "price_per_night": s["price_per_night"]}
                  for s in (state.get("stays") or {}).get("items") or []],
        "days": [{"day": d["day"], "day_cost": d["day_cost"]} for d in (state.get("itinerary") or {}).get("days") or []],
        "travel_cost": (state.get("logistics") or {}).get("travel_cost") or 0,
    }


@agent_node("budget")
async def budget(state: TripState, ctx: RunContext) -> dict[str, Any]:
    s = get_settings()
    payload = budget_payload(state)

    async def a2a_emit(event: dict[str, Any]) -> None:
        await ctx.emit("a2a", event)

    try:
        reply = await ask_budget(s.budget_agent_url, payload, a2a_emit, timeout=s.a2a_timeout_s)
        result, analyst = reply["result"], "budget-analyst (A2A)"
        for call in reply["tool_calls"]:  # the remote agent's own MCP calls, surfaced for the UI
            await ctx.emit("tool", {k: v for k, v in call.items() if k != "type"})
        how = f"via A2A ({s.budget_agent_url}) in {reply['ms']} ms"
    except Exception as exc:  # noqa: BLE001 - unreachable agent -> labelled local fallback
        await ctx.emit("a2a", {"agent": "budget", "peer": "budget-analyst", "status": "error",
                               "summary": f"unreachable ({type(exc).__name__}: {str(exc)[:120]}); using local fallback"})
        result, analyst = await cost_trip(payload), "local fallback"
        how = "local fallback (A2A agent unreachable)"
    result.pop("cost_profile", None)
    result["analyst"] = analyst
    await ctx.emit("partial", {"section": "budget", "payload": result})
    return {"budget": result, "evidence": {BUDGET_ANALYST["id"]: BUDGET_ANALYST},
            "_message": f"{result['total']['amount']:,.0f} {result['total']['currency']} "
                        f"({result['utilisation']:.0%} of limit) {how}"}


# ---------------------------------------------------------------------------------------------
# critic
# ---------------------------------------------------------------------------------------------


class Judge(BaseModel):
    faithfulness: float = Field(ge=0, le=1, description="share of activities supported by the evidence")
    relevancy: float = Field(ge=0, le=1, description="fit to the traveller's interests, pace, diet and budget")
    issues: list[str] = Field(default_factory=list, description="concrete problems, max 5")
    verdict: Literal["pass", "revise"] = "pass"


JUDGE_SYSTEM = (
    "You are the Critic of a travel-planning team. Judge the itinerary against the evidence snippets and the "
    "traveller's constraints. faithfulness = fraction of activities whose place/claims are supported by the "
    "evidence (guidebook passages or map listings); relevancy = how well the plan fits interests, pace, diet "
    "and budget. List concrete issues only. verdict 'revise' only for serious problems.")


def _activities(state: TripState) -> list[dict[str, Any]]:
    return [a for d in (state.get("itinerary") or {}).get("days") or [] for a in d["activities"]]


def deterministic_checks(state: TripState) -> tuple[list[Check], list[str], bool]:
    """(checks, issues for the itinerary, whether a retry could fix the hard failures)."""
    req = req_of(state)
    b = state["brief"]
    days = (state.get("itinerary") or {}).get("days") or []
    acts = _activities(state)
    evidence = state.get("evidence") or {}
    checks: list[Check] = []
    issues: list[str] = []
    retry = False

    ok = len(days) == req.days and [d["day"] for d in days] == list(range(1, req.days + 1))
    checks.append(Check(name="Day count", passed=ok, detail=f"{len(days)} of {req.days} days"))
    if not ok:
        issues.append(f"The plan must have exactly {req.days} days numbered 1..{req.days}.")
        retry = True

    want = [(req.start + timedelta(days=i)).isoformat() for i in range(req.days)]
    ok = [d["date"] for d in days] == want
    checks.append(Check(name="Dates", passed=ok, detail=f"{req.start_date} to {req.end_date}" if ok else "dates misaligned"))

    bud = state.get("budget") or {}
    util = float(bud.get("utilisation") or 0)
    ok = util <= 1.10
    checks.append(Check(name="Budget fit", passed=ok, detail=f"{util:.0%} of the limit (allowed up to 110%)"))
    act_share = 0.0
    if bud:
        acts_line = next((ln for ln in bud.get("lines", []) if ln["category"] == "activities"), None)
        act_share = (acts_line["amount"]["amount"] / bud["total"]["amount"]) if acts_line and bud["total"]["amount"] else 0
    if not ok and act_share > 0.15:
        issues.append(f"Over budget ({util:.0%}); choose cheaper or free activities.")
        retry = True

    cited = sum(1 for a in acts if any(c in evidence for c in a["citations"]))
    cov = cited / len(acts) if acts else 0.0
    ok = cov >= 0.6
    checks.append(Check(name="Citation coverage", passed=ok, detail=f"{cited}/{len(acts)} activities cite evidence"))
    if cov < 0.5 and acts:
        issues.append("Too many activities have no supporting citation; use places from the lists and cite passage ids.")
        retry = True

    book = get_guidebook()
    dest_names = {norm(b["name"]), norm(b.get("country", ""))}
    passage_text = " ".join(norm(v.get("snippet", "")) for v in evidence.values())
    others = [c["name"] for k, c in book.cities.items() if norm(c["name"]) not in dest_names and k != b.get("key")]
    leaks = []
    for a in acts:
        text = norm(f"{a['title']} {a.get('place') or ''}")
        for city in others:
            n = norm(city)
            if len(n) >= 4 and re.search(rf"\b{re.escape(n)}\b", text) and n not in passage_text:
                leaks.append(f"{a['id']}: mentions {city}")
    checks.append(Check(name="Wrong-city leakage", passed=not leaks, detail="; ".join(leaks[:3]) or "none"))
    if leaks:
        issues.append(f"Activities mention other cities ({'; '.join(leaks[:3])}); keep the plan in {b['name']}.")
        retry = True

    far = [a["id"] for a in acts if a.get("location") and not within_km(a["location"]["lat"], a["location"]["lon"], b, 60)]
    located = sum(1 for a in acts if a.get("location"))
    checks.append(Check(name="Geo sanity", passed=not far,
                        detail=f"{located}/{len(acts)} activities mapped, all within 60 km" if not far else f"far: {far}"))

    lo, hi = {"relaxed": (2, 3), "balanced": (3, 4), "packed": (4, 5)}[req.pace]
    off = [d["day"] for d in days if not (lo - 1 <= len(d["activities"]) <= hi + 1)]
    checks.append(Check(name="Pace", passed=not off, detail=f"{lo}-{hi}/day" + (f"; off on days {off}" if off else "")))

    wet_bad = []
    for d in days:
        if d.get("weather") and is_wet(d["weather"]) and d["activities"]:
            outdoor = sum(1 for a in d["activities"] if not a["indoor"])
            if outdoor / len(d["activities"]) > 0.5:
                wet_bad.append(d["day"])
    checks.append(Check(name="Weather-aware", passed=not wet_bad,
                        detail="wet days lean indoors" if not wet_bad else f"mostly outdoor on wet days {wet_bad}"))
    if wet_bad:
        issues.append(f"Days {wet_bad} are wet but mostly outdoor; move indoor activities there.")
    return checks, issues, retry


@agent_node("critic")
async def critic(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req = req_of(state)
    checks, issues, retry = deterministic_checks(state)
    evidence = state.get("evidence") or {}
    acts = _activities(state)
    cited_ids = list(dict.fromkeys(c for a in acts for c in a["citations"] if c in evidence))[:14]
    lines = [f"{a['id']} | {a['title']} | {a.get('place') or '-'} | indoor={a['indoor']} | cites {a['citations'][:3]}"
             for a in acts]
    snippets = "\n".join(f"[{i}] {evidence[i]['snippet'][:200]}" for i in cited_ids)
    user = (f"Traveller: {req.days} days in {state['brief']['name']}, interests {req.interests}, pace {req.pace}, "
            f"diet {req.diet or 'none'}, budget utilisation {float((state.get('budget') or {}).get('utilisation') or 0):.0%}."
            f"\nFeedback to honour: {(state.get('feedback') or ['none'])[-1]}"
            f"\n\nItinerary:\n" + "\n".join(lines) + f"\n\nEvidence:\n{snippets or '(none)'}")

    cov = sum(1 for a in acts if a["citations"]) / len(acts) if acts else 0.0

    def fallback() -> Judge:
        return Judge(faithfulness=round(cov, 2), relevancy=0.6, issues=[], verdict="pass")

    judge, method = await structured("critic", Judge, JUDGE_SYSTEM, user, fallback=fallback, size="large",
                                     max_tokens=700)
    ctx.methods["critic"] = method
    judged = not method.startswith("fallback") and method != "offline"
    checks.append(Check(name="LLM judge", passed=judge.verdict == "pass",
                        detail=(f"faithfulness {judge.faithfulness:.2f}, relevancy {judge.relevancy:.2f}"
                                + (f"; {judge.issues[0]}" if judge.issues else "")) if judged
                        else "judge unavailable; heuristic used"))
    if judged and judge.verdict == "revise" and judge.faithfulness < 0.5:
        issues += judge.issues[:3]
        retry = True
    attempts = state.get("attempts") or 0
    will_retry = retry and attempts < MAX_CRITIC_RETRIES
    passed = all(c.passed for c in checks if c.name in ("Day count", "Citation coverage", "Wrong-city leakage", "Geo sanity"))
    msg = (f"{sum(c.passed for c in checks)}/{len(checks)} checks passed"
           + ("; sending the itinerary back for one revision" if will_retry else ""))
    return {"critic": {"checks": [c.model_dump() for c in checks], "issues": issues, "passed": passed,
                       "retry": will_retry, "judge": judge.model_dump(), "judged": judged},
            "attempts": attempts + (1 if will_retry else 0), "_message": msg}


def after_critic(state: TripState) -> str:
    return "itinerary" if (state.get("critic") or {}).get("retry") else "finalize"


# ---------------------------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------------------------


def _referenced(plan_parts: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for d in plan_parts["days"]:
        for a in d["activities"]:
            ids |= set(a["citations"])
    for s in plan_parts["stays"] + plan_parts["food"]:
        ids |= set(s.get("citations") or [])
    ids |= set(plan_parts["pre_trip"].get("citations") or [])
    return ids


def _pre_trip(state: TripState, currency: str) -> dict[str, Any]:
    pre = (state.get("logistics") or {}).get("pre_trip")
    if pre:
        return pre
    return {"getting_there": {"mode": "unknown", "duration": "n/a", "cost": {"amount": 0, "currency": currency},
                              "note": "Logistics unavailable."},
            "getting_around": "Unavailable.", "visa": "Check the official government website.",
            "currency_note": "", "safety": [], "packing": [], "local_tips": [], "best_areas": [], "citations": []}


@agent_node("finalize")
async def finalize(state: TripState, ctx: RunContext) -> dict[str, Any]:
    req = req_of(state)
    b = state["brief"]
    it = state.get("itinerary") or {}
    evidence = dict(state.get("evidence") or {})
    weather = state.get("weather") or {}
    if not state.get("budget"):  # the budget node itself failed: cost it locally, labelled
        fallback = await cost_trip(budget_payload(state))
        fallback.pop("cost_profile", None)
        state = {**state, "budget": {**fallback, "analyst": "local fallback"}}
    parts = {
        "days": it.get("days") or [], "stays": (state.get("stays") or {}).get("items") or [],
        "food": (state.get("food") or {}).get("items") or [], "pre_trip": _pre_trip(state, req.currency),
    }
    ids = _referenced(parts)
    if weather.get("days"):
        ids.add("open-meteo")
    if "frankfurter" in evidence:
        ids.add("frankfurter")
    ids.add("budget-analyst")
    citations = [evidence[i] for i in ids if i in evidence]
    citations.sort(key=lambda c: (c["source"] != "wikivoyage", c["id"]))
    guard_checks = [Check(**c) for c in (state.get("guard") or {}).get("checks", [])]
    critic_checks = [Check(**c) for c in (state.get("critic") or {}).get("checks", [])]
    quality = compute_quality(state, parts, guard_checks + critic_checks)
    dest = state.get("destination") or {}
    plan = TripPlan.model_validate({
        "trip_id": state["trip_id"], "revision": state.get("revision", 0), "request": state["request"],
        "title": it.get("title") or f"{req.days} days in {b['name']}",
        "summary": it.get("summary") or dest.get("blurb") or "",
        "destination": {"name": b["name"], "country": b.get("country", ""),
                        "location": {"lat": b["lat"], "lon": b["lon"]}, "image": b.get("image"),
                        "blurb": dest.get("blurb") or f"{b['name']}, {b.get('country', '')}."},
        "weather_overview": weather.get("overview") or "Weather unavailable.",
        "days": parts["days"], "stays": parts["stays"], "food": parts["food"],
        "budget": state.get("budget") or {}, "pre_trip": parts["pre_trip"], "citations": citations,
        "quality": quality.model_dump(), "timings": [], "model": describe_mode(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    })
    tracer = get_tracer()
    for sc in quality.scores:
        tracer.score(trace_id=ctx.trace_id, name=sc.name, value=sc.value, comment=sc.explain)
    tracer.score(trace_id=ctx.trace_id, name="Confidence", value=quality.confidence,
                 comment=f"guidebook {quality.guidebook}; grounding {quality.grounding_coverage:.0%}")
    await ctx.emit("partial", {"section": "quality", "payload": quality.model_dump()})
    return {"plan": plan.model_dump(mode="json"),
            "_message": f"Plan ready: confidence {quality.confidence:.0%}, {len(citations)} citations"}
