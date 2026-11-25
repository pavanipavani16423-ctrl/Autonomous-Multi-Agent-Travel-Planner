"""MCP client hub: one long-lived MCP session per tool server, shared by every run.

Transports (MCP_TRANSPORT):
* ``inprocess`` (default) - each server runs in this process behind the SDK's `InMemoryTransport`:
  a full MCP JSON-RPC session (initialize -> tools/list -> tools/call) over memory streams. Same
  protocol as stdio, minus the subprocess, so a 512 MB instance doesn't pay for 3 extra Pythons.
* ``stdio`` - each server is spawned as ``python -m voyager.mcp.servers.<name>``.

Agents never see the hub: each gets a `Toolbox` limited by `AGENT_TOOLS` (least privilege). Every
call becomes a Langfuse *tool* observation and a `tool` SSE event (with provenance and latency).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from types import ModuleType
from typing import Any

from mcp import Client
from mcp.client._memory import InMemoryTransport
from mcp.client.stdio import StdioServerParameters

from voyager.config import API_DIR, get_settings
from voyager.mcp.servers import money, places, weather
from voyager.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

SERVERS: dict[str, ModuleType] = {"weather": weather, "places": places, "money": money}

# agent id -> allowed "server.tool" (or "server.*")
AGENT_TOOLS: dict[str, frozenset[str]] = {
    "brief": frozenset({"places.geocode", "money.convert"}),
    "destination": frozenset({"places.search_places"}),
    "weather": frozenset({"weather.*"}),
    "stays": frozenset({"places.search_places", "money.cost_profile"}),
    "food": frozenset({"places.search_places"}),
    "logistics": frozenset({"places.geocode", "places.distance", "money.convert", "money.cost_profile"}),
    "itinerary": frozenset({"places.geocode"}),
    "budget": frozenset({"money.*"}),
    "api": frozenset({"places.geocode"}),
}

Emitter = Callable[[dict[str, Any]], Awaitable[None]]


class ToolDenied(Exception):
    pass


def allowed(agent: str, server: str, tool: str) -> bool:
    acl = AGENT_TOOLS.get(agent, frozenset())
    return f"{server}.{tool}" in acl or f"{server}.*" in acl


def summarize(server: str, tool: str, args: dict[str, Any], data: dict[str, Any]) -> str:
    prov = data.get("provenance", "unavailable")
    if prov == "unavailable":
        return f"unavailable: {data.get('note', '')}"[:160]
    if tool in ("forecast", "historical_normals"):
        days = data.get("days") or []
        live = sum(1 for d in days if d.get("provenance") == "live")
        return f"{len(days)} days ({live} forecast, {len(days) - live} estimated)"
    if tool == "geocode":
        rows = data.get("results") or []
        if not rows:
            return "no match"
        r = rows[0]
        return f"{args.get('query')} -> {r.get('name')}, {r.get('country', '')} ({r['lat']:.3f}, {r['lon']:.3f})"
    if tool == "search_places":
        return f"{len(data.get('results') or [])} OSM places ({args.get('kind')})"
    if tool == "distance":
        return f"{data.get('km')} km, ~{data.get('minutes')} min by {data.get('mode')}"
    if tool == "convert":
        return f"{args.get('amount')} {args.get('from_currency')} = {data.get('amount')} {data.get('currency')}"
    if tool == "cost_profile":
        return f"{data.get('country_code')} {data.get('style')}: stay ${data.get('stay')}/night, food ${data.get('food')}/day"
    return prov


class MCPHub:
    def __init__(self, transport: str | None = None, timeout: float = 40.0) -> None:
        self.transport = transport or get_settings().mcp_transport
        self.timeout = timeout
        self._clients: dict[str, Client] = {}
        self._tools: dict[str, set[str]] = {}
        self._stack: AsyncExitStack | None = None
        self.healthy: dict[str, bool] = dict.fromkeys(SERVERS, False)

    async def __aenter__(self) -> MCPHub:
        self._stack = AsyncExitStack()
        for name, module in SERVERS.items():
            try:
                client = await self._stack.enter_async_context(
                    Client(self._target(module), read_timeout_seconds=self.timeout))
                listing = await client.list_tools()
                self._clients[name] = client
                self._tools[name] = {t.name for t in listing.tools}
                self.healthy[name] = True
            except Exception as exc:  # noqa: BLE001 - one broken server must not take down the rest
                logger.error("MCP server %s failed to start: %s", name, exc)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    def _target(self, module: ModuleType) -> Any:
        if self.transport == "stdio":
            return StdioServerParameters(
                command=sys.executable, args=["-m", module.__name__],
                env={**os.environ, "PYTHONPATH": str(API_DIR)}, cwd=str(API_DIR))
        return InMemoryTransport(module.build_server())

    def catalog(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in self._tools.items()}

    def toolbox(self, agent: str, emit: Emitter | None = None) -> Toolbox:
        return Toolbox(self, agent, emit)

    async def call(self, agent: str, server: str, tool: str, args: dict[str, Any],
                   emit: Emitter | None = None) -> dict[str, Any]:
        """Call a tool. Never raises for tool/transport failures: returns provenance 'unavailable'."""
        args = {k: v for k, v in args.items() if v is not None}
        started = time.perf_counter()
        tracer = get_tracer()
        with tracer.section(f"mcp.{server}.{tool}", as_type="tool", input=args,
                            metadata={"agent": agent, "transport": self.transport}) as obs:
            data: dict[str, Any]
            if server not in self._clients or tool not in self._tools.get(server, set()):
                data = {"provenance": "unavailable", "note": f"MCP {server}.{tool} not available"}
            else:
                data = {}
                for attempt in range(2):
                    try:
                        result = await asyncio.wait_for(
                            self._clients[server].call_tool(tool, args), timeout=self.timeout + 5)
                        if result.is_error:
                            msg = " ".join(getattr(c, "text", "") for c in result.content).strip()
                            data = {"provenance": "unavailable", "note": f"tool error: {msg[:200]}"}
                        else:
                            data = dict(result.structured_content or {})
                        break
                    except Exception as exc:  # noqa: BLE001 - transport failure of any kind
                        data = {"provenance": "unavailable", "note": f"{type(exc).__name__}: {exc}"[:200]}
                        if attempt == 0:
                            continue
            ms = int((time.perf_counter() - started) * 1000)
            prov = data.get("provenance", "unavailable")
            event_prov = "cached" if data.get("cached") and prov != "unavailable" else prov
            summary = summarize(server, tool, args, data)
            obs.update(output={"provenance": prov, "summary": summary},
                       metadata={"agent": agent, "ms": ms, "cached": bool(data.get("cached"))})
        if emit is not None:
            await emit({"type": "tool", "agent": agent, "server": server, "tool": tool,
                        "provenance": event_prov, "summary": summary, "ms": ms})
        return data


class Toolbox:
    """The tools one agent may use (allow-listed)."""

    def __init__(self, hub: MCPHub, agent: str, emit: Emitter | None) -> None:
        self.hub, self.agent, self.emit = hub, agent, emit

    async def call(self, server: str, tool: str, **args: Any) -> dict[str, Any]:
        if not allowed(self.agent, server, tool):
            raise ToolDenied(f"agent {self.agent!r} may not call {server}.{tool}")
        return await self.hub.call(self.agent, server, tool, args, self.emit)


_HUB: MCPHub | None = None
_HUB_LOCK = asyncio.Lock()


def set_hub(hub: MCPHub | None) -> None:
    global _HUB
    _HUB = hub


async def get_hub() -> MCPHub:
    """The process-wide hub (opened by the API lifespan; opened lazily for scripts/the A2A server)."""
    global _HUB
    if _HUB is None:
        async with _HUB_LOCK:
            if _HUB is None:
                hub = MCPHub()
                await hub.__aenter__()
                _HUB = hub
    return _HUB
