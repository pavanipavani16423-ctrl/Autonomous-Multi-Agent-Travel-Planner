"""A2A client for the Budget Analyst: fetch the Agent Card, send the costing request over HTTP
(JSON-RPC via a2a-sdk), read the data part back. Emits `a2a` SSE events: card -> sent -> received."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_data_parts, new_data_part, new_message
from a2a.types import Role, SendMessageRequest

from voyager.a2a.budget_agent import CARD_PATH, SKILL
from voyager.observability.tracing import get_tracer

Emit = Callable[[dict[str, Any]], Awaitable[None]]
_TRANSPORT: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests: talk to the ASGI app in-process (still the full A2A HTTP protocol)."""
    global _TRANSPORT
    _TRANSPORT = transport


class A2AError(Exception):
    pass


async def ask_budget(base_url: str, payload: dict[str, Any], emit: Emit, timeout: float = 30.0) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    started = time.perf_counter()
    async with httpx.AsyncClient(transport=_TRANSPORT, timeout=timeout, base_url=base_url) as http:
        resp = await http.get(f"{base_url}{CARD_PATH}")
        resp.raise_for_status()
        card = resp.json()
        skills = [s.get("id") for s in card.get("skills") or []]
        if SKILL not in skills:
            raise A2AError(f"agent card at {base_url} has no '{SKILL}' skill (has {skills})")
        await emit({"agent": "budget", "peer": "budget-analyst", "status": "card",
                    "summary": f"{card.get('name')} v{card.get('version')} - skills: {', '.join(skills)}"})
        client = await create_client(base_url, client_config=ClientConfig(httpx_client=http, streaming=False))
        message = new_message(parts=[new_data_part({"skill": SKILL, "input": payload})], role=Role.ROLE_USER)
        trace = get_tracer().trace_context()
        if trace:  # the remote agent opens its span inside this run's Langfuse trace
            message.metadata.update(trace)
        await emit({"agent": "budget", "peer": "budget-analyst", "status": "sent",
                    "summary": f"SendMessage {SKILL}: {len(payload.get('days') or [])} days, "
                               f"{len(payload.get('stays') or [])} stays, limit {payload['request']['budget']:.0f} "
                               f"{payload['request']['currency']}"})
        body = None
        async for response in client.send_message(SendMessageRequest(message=message)):
            if response.HasField("message"):
                parts = get_data_parts(response.message.parts)
                body = parts[0] if parts else None
            elif response.HasField("task") and response.task.history:
                parts = get_data_parts(response.task.history[-1].parts)
                body = parts[0] if parts else None
    if not body:
        raise A2AError("empty A2A response")
    if "error" in body:
        raise A2AError(body["error"])
    result = body["result"]
    ms = int((time.perf_counter() - started) * 1000)
    await emit({"agent": "budget", "peer": "budget-analyst", "status": "received",
                "summary": f"total {result['total']['amount']:,.0f} {result['total']['currency']} "
                           f"({result['utilisation']:.0%} of limit) in {ms} ms"})
    return {"result": result, "tool_calls": body.get("tool_calls") or [], "card": card, "ms": ms}
