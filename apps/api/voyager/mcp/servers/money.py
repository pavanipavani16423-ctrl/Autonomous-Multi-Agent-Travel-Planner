"""MCP server `money`: currency conversion (Frankfurter / ECB rates) and daily cost bands.

Run standalone:  python -m voyager.mcp.servers.money [--transport stdio|streamable-http] [--port 9203]
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from voyager.mcp import costs
from voyager.mcp.http import fetch_json
from voyager.mcp.servers._run import run_cli

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"


async def _ecb_rate(src: str, dst: str) -> tuple[float | None, bool, str | None]:
    res = await fetch_json(FRANKFURTER_URL, params={"base": src, "symbols": dst}, ttl=6 * 3600)
    if not res.ok:
        return None, False, res.error
    rate = (res.data.get("rates") or {}).get(dst)
    return (float(rate) if rate else None), res.cached, None if rate else "currency not published by ECB"


async def convert(amount: float, from_currency: str, to_currency: str) -> dict[str, Any]:
    """Convert an amount between ISO 4217 currencies (ECB reference rates via Frankfurter). Currencies
    the ECB does not publish fall back to a static estimate, labelled `estimate`."""
    src, dst = from_currency.upper().strip(), to_currency.upper().strip()
    url = f"{FRANKFURTER_URL}?base={src}&symbols={dst}"
    if src == dst:
        return {"amount": round(amount, 2), "currency": dst, "rate": 1.0, "provenance": "live",
                "source_url": url, "cached": True, "note": "same currency"}
    rate, cached, err = await _ecb_rate(src, dst)
    if rate is not None:
        return {"amount": round(amount * rate, 2), "currency": dst, "rate": rate, "provenance": "live",
                "source_url": url, "cached": cached, "note": "ECB reference rate (Frankfurter)"}
    # via USD: ECB leg where possible, static table otherwise
    async def usd_to(cur: str) -> tuple[float | None, bool]:
        if cur == "USD":
            return 1.0, True
        r, _, _ = await _ecb_rate("USD", cur)
        if r is not None:
            return r, True
        static = costs.STATIC_USD_RATES.get(cur)
        return static, False

    to_src, src_live = await usd_to(src)
    to_dst, dst_live = await usd_to(dst)
    if to_src and to_dst:
        rate = to_dst / to_src
        live = src_live and dst_live
        return {"amount": round(amount * rate, 2), "currency": dst, "rate": rate,
                "provenance": "live" if live else "estimate", "source_url": url, "cached": False,
                "note": "cross rate via USD" + ("" if live else "; includes a static estimated rate "
                                                 "(currency not published by the ECB)")}
    return {"amount": None, "currency": dst, "rate": None, "provenance": "unavailable", "source_url": url,
            "cached": False, "note": f"no rate for {src}->{dst} ({err})"}


async def cost_profile(country_code: str, style: str = "mid") -> dict[str, Any]:
    """Typical daily travel costs in USD for a country and travel style (budget | mid | luxury):
    stay per room-night; food, local transport and activities per person per day. Curated estimate."""
    cc = (country_code or "").upper()
    band = costs.profile(cc, style)
    return {
        "country_code": cc, "style": style, "currency": "USD", "local_currency": costs.currency_for(cc),
        "tier": costs.tier_for(cc), **band, "provenance": "estimate",
        "source_url": "local:voyager/mcp/costs.py",
        "note": "Hand-curated estimate by country price tier (late 2025 guidebook ranges); not a live price.",
    }


def build_server() -> MCPServer:
    server = MCPServer("voyager-money", instructions="Currency conversion and daily travel-cost bands.")
    server.tool(description="Convert money between currencies (ECB rates via Frankfurter).")(convert)
    server.tool(description="Daily travel cost bands (USD) for a country code and style; an estimate.")(
        cost_profile)
    return server


if __name__ == "__main__":
    run_cli(build_server, default_port=9203)
