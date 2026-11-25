"""Run the Budget Analyst as its own service:  python -m voyager.a2a.budget_server [--port 9101]

The main API mounts the same routes at /a2a/budget (so one Render service is enough); set
A2A_BUDGET_URL=http://localhost:9101 to make the orchestrator call this standalone process instead.
"""

from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager

from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from fastapi import FastAPI

from voyager.a2a.budget_agent import routes
from voyager.mcp.hub import MCPHub, set_hub


def build_app(base_url: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with MCPHub() as hub:
            set_hub(hub)
            yield
            set_hub(None)

    app = FastAPI(title="Voyager Budget Analyst (A2A)", lifespan=lifespan)
    card_routes, rpc_routes = routes(base_url)
    add_a2a_routes_to_fastapi(app, agent_card_routes=card_routes, jsonrpc_routes=rpc_routes)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("A2A_PORT", 9101)))
    args = parser.parse_args()
    base = os.environ.get("A2A_PUBLIC_URL") or f"http://{args.host}:{args.port}"
    uvicorn.run(build_app(base), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
