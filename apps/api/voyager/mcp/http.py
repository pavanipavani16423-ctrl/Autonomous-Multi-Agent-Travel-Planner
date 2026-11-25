"""Outbound HTTP for the MCP tool servers: timeouts, one retry, a SQLite TTL cache.

Free public APIs (Open-Meteo, Overpass, Photon, Frankfurter, Wikivoyage) are polite-use services,
so every response is cached by URL+params for a TTL that matches how fast the data changes
(forecast 1 h, geocoding 30 days). A failure never raises out of a tool: callers get `None` and
report `provenance: "unavailable"`.

Tests swap the transport for an `httpx.MockTransport` (see `set_transport`), so the whole stack
runs offline with recorded payloads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from voyager.config import get_settings

logger = logging.getLogger(__name__)

_TRANSPORT: httpx.AsyncBaseTransport | None = None
_CLIENT: httpx.AsyncClient | None = None
_CLIENT_LOOP: asyncio.AbstractEventLoop | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route every tool request through `transport` (tests: recorded payloads)."""
    global _TRANSPORT, _CLIENT
    _TRANSPORT = transport
    _CLIENT = None


def _client() -> httpx.AsyncClient:
    global _CLIENT, _CLIENT_LOOP
    loop = asyncio.get_running_loop()
    if _CLIENT is None or _CLIENT_LOOP is not loop or _CLIENT.is_closed:
        s = get_settings()
        _CLIENT = httpx.AsyncClient(
            transport=_TRANSPORT, timeout=httpx.Timeout(s.http_timeout_s, connect=6.0),
            headers={"User-Agent": s.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )
        _CLIENT_LOOP = loop
    return _CLIENT


class _Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._path = None

    def _db(self) -> sqlite3.Connection:
        path = get_settings().tool_cache_path
        if self._conn is None or self._path != path:
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS http_cache (key TEXT PRIMARY KEY, value TEXT, expires REAL)"
            )
            self._path = path
        return self._conn

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._db().execute(
                "SELECT value, expires FROM http_cache WHERE key = ?", (key,)
            ).fetchone()
        if not row or row[1] < time.time():
            return None
        return json.loads(row[0])

    def put(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            db = self._db()
            db.execute("INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?)",
                       (key, json.dumps(value), time.time() + ttl))
            db.commit()

    def clear(self) -> None:
        with self._lock:
            db = self._db()
            db.execute("DELETE FROM http_cache")
            db.commit()


CACHE = _Cache()


@dataclass
class Fetched:
    data: Any | None
    cached: bool = False
    error: str | None = None
    url: str = ""

    @property
    def ok(self) -> bool:
        return self.data is not None


def _key(method: str, url: str, params: dict | None, body: dict | None) -> str:
    raw = json.dumps([method, url, params or {}, body or {}], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def fetch_json(url: str, *, params: dict[str, Any] | None = None, ttl: float = 3600,
                     method: str = "GET", form: dict[str, str] | None = None,
                     retries: int = 1, timeout: float | None = None) -> Fetched:
    """GET/POST JSON with cache, timeout and `retries` retries on transient errors."""
    key = _key(method, url, params, form)
    hit = await asyncio.to_thread(CACHE.get, key) if ttl > 0 else None
    if hit is not None:
        return Fetched(hit, cached=True, url=url)
    last = "unknown error"
    for attempt in range(retries + 1):
        try:
            client = _client()
            kwargs: dict[str, Any] = {"params": params}
            if timeout is not None:
                kwargs["timeout"] = timeout
            if method == "POST":
                resp = await client.post(url, data=form, **kwargs)
            else:
                resp = await client.get(url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {resp.status_code}"
                if attempt < retries:
                    await asyncio.sleep(min(float(resp.headers.get("Retry-After", 1.0) or 1.0), 3.0))
                    continue
                break
            if resp.status_code >= 400:
                last = f"HTTP {resp.status_code}"
                break
            data = resp.json()
            if ttl > 0:
                await asyncio.to_thread(CACHE.put, key, data, ttl)
            return Fetched(data, url=str(resp.url))
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last = f"{type(exc).__name__}: {exc}"[:200]
            if attempt < retries:
                await asyncio.sleep(0.6)
                continue
    logger.warning("fetch failed %s: %s", url, last)
    return Fetched(None, error=last, url=url)
