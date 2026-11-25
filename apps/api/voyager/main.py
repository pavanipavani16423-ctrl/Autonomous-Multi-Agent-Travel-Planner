"""FastAPI app: `uvicorn voyager.main:app --port 8000`.

Lifespan: database -> MCP hub (3 servers) -> guidebook (index the corpus in a background thread if
the collection is empty) -> LangGraph + AsyncSqliteSaver -> run manager. The A2A Budget Analyst is
mounted at /a2a/budget (one service on Render); A2A_BUDGET_URL can point at a standalone one.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from voyager.api.ratelimit import RateLimiter
from voyager.api.routes import router
from voyager.config import get_settings
from voyager.mcp.hub import MCPHub, set_hub
from voyager.memory.store import Store
from voyager.observability.tracing import get_tracer
from voyager.rag.store import get_guidebook

logger = logging.getLogger("voyager")


def _logging() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console
    except (AttributeError, OSError):
        pass
    logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "mcp", "fastembed", "langfuse"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _index_guidebook(app: FastAPI) -> None:
    from voyager.rag.ingest import ingest_corpus

    book = get_guidebook()
    try:
        if get_settings().ingest_on_boot:
            stats = await asyncio.to_thread(ingest_corpus, book)
            app.state.ingest_stats = stats
        else:
            await asyncio.to_thread(book.refresh_cities)
            book.ready = True
    except Exception:  # noqa: BLE001 - the API stays up; brief will report coverage "none"
        logger.exception("guidebook indexing failed")
        book.ready = True  # don't make runs wait for an index that will not come


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from voyager.graph.workflow import build_graph
    from voyager.services.runs import RunManager

    _logging()
    s = get_settings()
    store = Store()
    await store.init()
    app.state.store = store
    async with MCPHub() as hub, AsyncSqliteSaver.from_conn_string(str(s.checkpoint_path)) as saver:
        set_hub(hub)
        app.state.hub = hub
        book = get_guidebook()
        book.refresh_cities()
        index_task = asyncio.create_task(_index_guidebook(app))
        graph = build_graph(checkpointer=saver)
        app.state.runs = RunManager(store, graph)
        logger.info("voyager ready: llm=%s langfuse=%s mcp=%s cities=%d a2a=%s", s.llm_enabled,
                    get_tracer().enabled, hub.healthy, len(book.cities), s.budget_agent_url)
        try:
            yield
        finally:
            index_task.cancel()
            for t in app.state.runs.tasks.values():
                t.cancel()
            get_tracer().flush()
            set_hub(None)
    await store.close()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Voyager API", version="2.0.0", lifespan=lifespan,
                  description="Multi-agent travel planner: LangGraph + MCP + A2A + Qdrant hybrid RAG.")
    app.add_middleware(RateLimiter, write_per_min=s.rate_limit_write_per_min, read_per_min=s.rate_limit_read_per_min)
    origins = [o.strip() for o in s.web_origin.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"], expose_headers=["Retry-After"])

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors()[:3]:
            loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body", "query"))
            parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return JSONResponse({"detail": "; ".join(parts) or "invalid request"}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> dict[str, Any]:
        book = get_guidebook()
        try:
            qdrant_ok = bool(await asyncio.to_thread(book.count))
        except Exception:  # noqa: BLE001
            qdrant_ok = False
        a2a_ok = False
        try:
            from voyager.a2a import client as a2a_client

            async with httpx.AsyncClient(transport=a2a_client._TRANSPORT, timeout=3) as http:
                r = await http.get(f"{s.budget_agent_url}/.well-known/agent-card.json")
                a2a_ok = r.status_code == 200 and "trip-costing" in r.text
        except Exception:  # noqa: BLE001
            a2a_ok = False
        hub = getattr(request.app.state, "hub", None)
        return {"llm": s.llm_enabled, "qdrant": qdrant_ok, "langfuse": get_tracer().enabled,
                "mcp": dict(hub.healthy) if hub else {"weather": False, "places": False, "money": False},
                "a2a": a2a_ok, "guidebook_cities": len(book.cities)}

    app.include_router(router)
    if s.mount_a2a:
        from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi

        from voyager.a2a.budget_agent import routes

        card_routes, rpc_routes = routes(f"{s.base_url}/a2a/budget", prefix="/a2a/budget")
        add_a2a_routes_to_fastapi(app, agent_card_routes=card_routes, jsonrpc_routes=rpc_routes)
    return app


app = create_app()
