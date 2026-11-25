"""Offline test harness: VOYAGER_OFFLINE=1 (deterministic fake LLM + hashing embedders), every external
API mocked through httpx.MockTransport, an in-memory Qdrant with a tiny slice of the real corpus, and
the A2A Budget Analyst reached over ASGI (still the full A2A HTTP protocol)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_DATA = Path(tempfile.mkdtemp(prefix="voyager-test-"))
os.environ.update({
    "VOYAGER_OFFLINE": "1", "VOYAGER_DATA_DIR": str(_DATA), "GROQ_API_KEY": "", "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "", "A2A_BUDGET_URL": "http://budget.test", "QDRANT_URL": "",
    "RATE_LIMIT_WRITE_PER_MIN": "100", "RATE_LIMIT_READ_PER_MIN": "1000", "VOYAGER_LOG_LEVEL": "WARNING",
})
sys.path.insert(0, str(Path(__file__).parent))

import httpx  # noqa: E402
import pytest  # noqa: E402

REPO_CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus.jsonl"


def _tiny_corpus() -> list[dict]:
    keep = {"kyoto": 200, "tokyo": 20, "paris": 25}
    counts: dict[str, int] = {}
    out = []
    with open(REPO_CORPUS, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            d = rec["metadata"]["destination"]
            if d in keep and counts.get(d, 0) < keep[d]:
                counts[d] = counts.get(d, 0) + 1
                out.append(rec)
    return out


TINY = _tiny_corpus()
with open(_DATA / "corpus.jsonl", "w", encoding="utf-8") as fh:
    for r in TINY:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def guidebook():
    from qdrant_client import QdrantClient

    from voyager.rag.ingest import ingest_corpus
    from voyager.rag.store import Guidebook, set_guidebook

    book = Guidebook(QdrantClient(":memory:"))
    ingest_corpus(book, records=TINY)
    set_guidebook(book)
    return book


@pytest.fixture(autouse=True)
def offline_env(guidebook):
    import mocks

    from voyager.a2a import client as a2a_client
    from voyager.config import reset_settings
    from voyager.graph import context
    from voyager.llm import gateway
    from voyager.mcp import http as mcp_http
    from voyager.mcp.hub import set_hub
    from voyager.mcp.servers import places

    reset_settings()
    mcp_http.set_transport(mocks.transport())
    mcp_http.CACHE.clear()
    places._DOWN_UNTIL.clear()
    gateway.set_chat_factory(None)
    gateway._BUCKETS.clear()
    set_hub(None)
    context._CONTEXTS.clear()
    # drop cities added by an expansion test so coverage starts from the tiny corpus
    for key in [k for k in guidebook.cities if k not in ("kyoto", "tokyo", "paris")]:
        guidebook.cities.pop(key)
    a2a_client.set_transport(httpx.ASGITransport(app=budget_app()))
    yield
    mcp_http.set_transport(None)
    a2a_client.set_transport(None)
    set_hub(None)


def budget_app():
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from fastapi import FastAPI

    from voyager.a2a.budget_agent import routes

    app = FastAPI()
    card, rpc = routes("http://budget.test")
    add_a2a_routes_to_fastapi(app, agent_card_routes=card, jsonrpc_routes=rpc)
    return app


@pytest.fixture
async def hub():
    from voyager.mcp.hub import MCPHub, set_hub

    async with MCPHub() as h:
        set_hub(h)
        yield h
        set_hub(None)


def future_request(days: int = 4, start_in: int = 7, **kw) -> dict:
    from datetime import date, timedelta

    s = date.today() + timedelta(days=start_in)
    base = {"destination": "Kyoto", "start_date": s.isoformat(),
            "end_date": (s + timedelta(days=days - 1)).isoformat(), "adults": 2, "children": 0,
            "budget": 3000, "currency": "USD", "interests": ["temples", "food"], "pace": "balanced",
            "diet": ["vegetarian"], "stay_style": "mid", "origin": "Mumbai", "client_id": "test-client"}
    base.update(kw)
    return base
