from __future__ import annotations

import httpx
import pytest
from conftest import budget_app, future_request

from voyager.a2a.client import A2AError, ask_budget

pytestmark = pytest.mark.anyio


def payload() -> dict:
    return {"request": future_request(days=4, budget=3000), "country_code": "JP",
            "fx": {"usd_to_trip": 1.0}, "stays": [{"name": "Hotel", "price_per_night": {"amount": 140, "currency": "USD"}}],
            "days": [{"day": i, "day_cost": {"amount": 20, "currency": "USD"}} for i in range(1, 5)],
            "travel_cost": 900}


async def test_agent_card() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=budget_app()), base_url="http://budget.test") as c:
        card = (await c.get("/.well-known/agent-card.json")).json()
    assert card["name"] == "Budget Analyst"
    assert [s["id"] for s in card["skills"]] == ["trip-costing"]
    assert card["supportedInterfaces"][0]["url"] == "http://budget.test/rpc"


async def test_round_trip_over_a2a(hub) -> None:
    events = []

    async def emit(ev):
        events.append(ev)

    reply = await ask_budget("http://budget.test", payload(), emit)
    budget = reply["result"]
    assert [e["status"] for e in events] == ["card", "sent", "received"]
    assert {ln["category"] for ln in budget["lines"]} == {"stay", "food", "activities", "transport", "travel", "misc"}
    stay = next(ln for ln in budget["lines"] if ln["category"] == "stay")
    assert stay["amount"]["amount"] == 140 * 3  # 3 nights at the median stay price
    total = sum(ln["amount"]["amount"] for ln in budget["lines"])
    assert budget["total"]["amount"] == pytest.approx(total, abs=1)
    assert budget["utilisation"] == pytest.approx(budget["total"]["amount"] / 3000, abs=0.001)
    assert budget["savings_tips"]
    assert any(c["tool"] == "cost_profile" for c in reply["tool_calls"])  # the agent used the money MCP server


async def test_jsonrpc_v03_message_send_compat(hub) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
        "role": "user", "messageId": "m1", "kind": "message",
        "parts": [{"kind": "data", "data": {"skill": "trip-costing", "input": payload()}}]}}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=budget_app()), base_url="http://budget.test") as c:
        r = await c.post("/rpc", json=body)
    assert r.status_code == 200
    assert "result" in r.json(), r.text[:300]


async def test_unknown_skill_is_an_error(hub) -> None:
    from a2a.client import ClientConfig, create_client
    from a2a.helpers.proto_helpers import get_data_parts, new_data_part, new_message
    from a2a.types import Role, SendMessageRequest

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=budget_app()), base_url="http://budget.test") as http:
        client = await create_client("http://budget.test", client_config=ClientConfig(httpx_client=http, streaming=False))
        msg = new_message(parts=[new_data_part({"skill": "nope", "input": {}})], role=Role.ROLE_USER)
        bodies = [get_data_parts(r.message.parts)[0] async for r in client.send_message(SendMessageRequest(message=msg))
                  if r.HasField("message")]
    assert "unknown skill" in bodies[0]["error"]


async def test_unreachable_agent_raises() -> None:
    from voyager.a2a import client as a2a_client

    a2a_client.set_transport(httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises((A2AError, httpx.HTTPError)):
        async def emit(ev):
            return None
        await ask_budget("http://budget.test", payload(), emit)
