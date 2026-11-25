"""Budget Analyst: a separate A2A agent (a2a-sdk) with one skill, "trip-costing".

    GET  <base>/.well-known/agent-card.json      Agent Card
    POST <base>/rpc                              JSON-RPC: SendMessage (A2A 1.0) / message/send (0.3 compat)

Message contract (JSON in a data part):
    request : {"skill": "trip-costing", "input": {request, country_code, fx, stays, days, travel_cost}}
    response: {"skill": "trip-costing", "result": Budget, "tool_calls": [...]}

It costs the plan from the money MCP server's daily cost bands + the plan's own prices (stays,
activities, travel), converts currencies, compares with the limit and suggests savings. The same
`cost_trip` function is the orchestrator's labelled local fallback when the agent is unreachable.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentProvider, AgentSkill, Role
from google.protobuf.json_format import MessageToDict

from voyager.mcp.hub import get_hub
from voyager.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

NAME = "budget-analyst"
SKILL = "trip-costing"
RPC_PATH = "/rpc"
CARD_PATH = "/.well-known/agent-card.json"
ZERO_DECIMALS = {"JPY", "KRW", "VND", "IDR", "INR", "HUF", "CLP", "COP", "UZS", "ISK"}


def _m(amount: float, currency: str) -> dict[str, Any]:
    return {"amount": round(amount, 0 if currency in ZERO_DECIMALS else 2), "currency": currency}


async def cost_trip(data: dict[str, Any], tool_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Pure costing logic (shared by the A2A skill and the local fallback). Returns a SPEC `Budget`
    without `analyst` (the caller labels who computed it)."""
    req = data["request"]
    cur = req["currency"]
    style = req.get("stay_style", "mid")
    adults, children = int(req.get("adults", 1)), int(req.get("children", 0))
    travellers = adults + children
    eaters = adults + 0.6 * children
    from datetime import date

    start, end = date.fromisoformat(req["start_date"]), date.fromisoformat(req["end_date"])
    days = (end - start).days + 1
    nights = max(days - 1, 0)
    fx = data.get("fx") or {}

    async def emit(event: dict[str, Any]) -> None:
        if tool_log is not None:
            tool_log.append(event)

    tools = (await get_hub()).toolbox("budget", emit)
    profile = await tools.call("money", "cost_profile", country_code=data.get("country_code") or "", style=style)
    usd_rate = fx.get("usd_to_trip")
    if not usd_rate:
        conv = await tools.call("money", "convert", amount=1.0, from_currency="USD", to_currency=cur)
        usd_rate = conv.get("rate") or 1.0
    usd_rate = float(usd_rate)

    stay_prices = [float(s["price_per_night"]["amount"]) for s in data.get("stays") or []
                   if s.get("price_per_night", {}).get("amount")]
    rooms = max(1, -(-adults // 2))
    if stay_prices:
        per_night = statistics.median(stay_prices)
        stay_note = f"{nights} nights at the median of {len(stay_prices)} suggested stays (estimated nightly rate)"
    else:
        per_night = float(profile.get("stay", 100)) * rooms * usd_rate
        stay_note = f"{nights} nights x {rooms} room(s) at a typical {style} rate (estimate)"
    stay = per_night * nights
    food = float(profile.get("food", 40)) * eaters * days * usd_rate
    plan_activities = sum(float(d.get("day_cost", {}).get("amount", 0)) for d in data.get("days") or [])
    if plan_activities > 0:
        activities, act_note = plan_activities, "sum of the itinerary's activity prices"
    else:
        activities = float(profile.get("activities", 20)) * travellers * days * 0.5 * usd_rate
        act_note = "typical entry fees (estimate; the itinerary lists mostly free sights)"
    transport = float(profile.get("transport", 10)) * travellers * days * usd_rate
    travel = float(data.get("travel_cost") or 0)
    subtotal = stay + food + activities + transport + travel
    misc = 0.07 * subtotal
    total = subtotal + misc
    limit = float(req["budget"])
    util = total / limit if limit else 0.0
    lines = [
        {"category": "stay", "amount": _m(stay, cur), "note": stay_note},
        {"category": "food", "amount": _m(food, cur),
         "note": f"{style} eating for {travellers} over {days} days (curated daily band, estimate)"},
        {"category": "activities", "amount": _m(activities, cur), "note": act_note},
        {"category": "transport", "amount": _m(transport, cur), "note": "local transport, daily band (estimate)"},
        {"category": "travel", "amount": _m(travel, cur),
         "note": "round trip to the destination (rough estimate)" if travel else "no origin given: not included"},
        {"category": "misc", "amount": _m(misc, cur), "note": "7% buffer: SIM, tips, small purchases"},
    ]
    tips = savings_tips(lines, limit, total, style, cur)
    return {"total": _m(total, cur), "limit": _m(limit, cur), "per_person": _m(total / max(travellers, 1), cur),
            "lines": lines, "within_budget": total <= limit, "utilisation": round(util, 3),
            "savings_tips": tips, "cost_profile": {k: profile.get(k) for k in ("tier", "stay", "food", "transport",
                                                                               "activities", "provenance")}}


def savings_tips(lines: list[dict[str, Any]], limit: float, total: float, style: str, cur: str) -> list[str]:
    by = {ln["category"]: ln["amount"]["amount"] for ln in lines}
    tips: list[str] = []
    over = total - limit

    def fmt(v: float) -> str:
        return f"{v:,.0f} {cur}"

    if over > 0:
        tips.append(f"The plan is about {fmt(over)} over budget ({total / limit:.0%} of the limit).")
        if style != "budget" and by["stay"] > 0:
            tips.append(f"Switching to a {'mid-range hotel' if style == 'luxury' else 'guest house or hostel'} "
                        f"could save roughly {fmt(by['stay'] * 0.35)}.")
        if by["food"] > 0:
            tips.append(f"Make lunch a market or street-food meal: saves about {fmt(by['food'] * 0.25)}.")
        if by["activities"] > 0:
            tips.append("Swap one paid attraction a day for a free temple, park or viewpoint, or look for a city pass.")
        if by["travel"] > 0:
            tips.append("Book transport 6-8 weeks ahead or travel midweek for cheaper fares.")
    else:
        headroom = limit - total
        tips.append(f"Comfortably within budget: about {fmt(headroom)} of headroom ({total / limit:.0%} used).")
        if headroom > 0.25 * limit and style != "luxury":
            tips.append("There is room for one splurge: a special dinner or a guided experience.")
        tips.append("Keep ~10% aside for surprises (taxis in the rain, entry fees that changed).")
    return tips[:4]


class BudgetExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        parts = get_data_parts(context.message.parts) if context.message else []
        payload = parts[0] if parts else {}
        skill = payload.get("skill")
        tool_log: list[dict[str, Any]] = []
        meta = MessageToDict(context.message.metadata) if context.message and context.message.metadata else {}
        trace_context = ({k: meta[k] for k in ("trace_id", "parent_span_id") if meta.get(k)}
                         if meta.get("trace_id") else None)
        with get_tracer().section(f"A2A {NAME}: {skill}", as_type="agent", trace_context=trace_context,
                                  metadata={"service": NAME, "protocol": "A2A"}) as span:
            if skill != SKILL:
                body: dict[str, Any] = {"skill": skill, "error": f"unknown skill {skill!r}; have ['{SKILL}']"}
            else:
                try:
                    body = {"skill": skill, "result": await cost_trip(payload.get("input") or {}, tool_log)}
                    span.update(output={"total": body["result"]["total"]})
                except Exception as exc:  # noqa: BLE001 - reported to the caller
                    logger.exception("budget skill failed")
                    body = {"skill": skill, "error": f"{type(exc).__name__}: {exc}"}
        body["tool_calls"] = tool_log
        await event_queue.enqueue_event(new_data_message(body, role=Role.ROLE_AGENT))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None


def agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Budget Analyst",
        description="Costs a trip plan (stays, food, activities, transport, travel), converts currencies, "
                    "compares it with the traveller's limit and suggests savings.",
        version="2.0.0",
        provider=AgentProvider(organization="Voyager (portfolio project)", url=base_url),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0",
                                             url=base_url.rstrip("/") + RPC_PATH)],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[AgentSkill(
            id=SKILL, name="Trip costing",
            description="Itemised trip budget in the traveller's currency with utilisation and savings tips.",
            tags=["budget", "travel", "currency"],
            examples=['{"skill": "trip-costing", "input": {"request": {...}, "country_code": "JP", '
                      '"stays": [...], "days": [...]}}'])],
    )


def routes(base_url: str, prefix: str = "") -> tuple[list[Any], list[Any]]:
    """(agent card routes, JSON-RPC routes) served under `prefix`."""
    card = agent_card(base_url)
    handler = DefaultRequestHandler(agent_executor=BudgetExecutor(), task_store=InMemoryTaskStore(),
                                    agent_card=card)
    return (create_agent_card_routes(card, card_url=f"{prefix}{CARD_PATH}"),
            create_jsonrpc_routes(handler, f"{prefix}{RPC_PATH}", enable_v0_3_compat=True))
