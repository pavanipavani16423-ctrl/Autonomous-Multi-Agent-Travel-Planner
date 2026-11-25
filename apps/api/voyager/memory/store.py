"""Persistence: trips, SSE events (for replay), preference profiles and the plan cache.

SQLite via aiosqlite by default; DATABASE_URL may point at Postgres (asyncpg). SQLAlchemy Core,
JSON stored as text so both backends behave the same.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    delete,
    desc,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from voyager.config import get_settings

metadata = MetaData()

trips = Table(
    "trips", metadata,
    Column("id", String(40), primary_key=True),
    Column("client_id", String(80), index=True),
    Column("status", String(16), nullable=False),
    Column("revision", Integer, nullable=False, default=0),
    Column("request", Text, nullable=False),
    Column("plan", Text),
    Column("error", Text),
    Column("title", String(200)),
    Column("destination", String(120)),
    Column("image", Text),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
events = Table(
    "events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trip_id", String(40), index=True, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("type", String(16), nullable=False),
    Column("data", Text, nullable=False),
)
profiles = Table(
    "profiles", metadata,
    Column("client_id", String(80), primary_key=True),
    Column("data", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)
plan_cache = Table(
    "plan_cache", metadata,
    Column("key", String(64), primary_key=True),
    Column("trip_id", String(40), nullable=False),
    Column("plan", Text, nullable=False),
    Column("created_ts", Integer, nullable=False),
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or get_settings().resolved_database_url
        self.engine: AsyncEngine = create_async_engine(self.url, future=True)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    # ---- trips --------------------------------------------------------------------------------
    async def create_trip(self, trip_id: str, request: dict[str, Any]) -> None:
        ts = now_iso()
        async with self.engine.begin() as c:
            await c.execute(insert(trips).values(
                id=trip_id, client_id=request.get("client_id"), status="queued", revision=0,
                request=json.dumps(request), destination=request.get("destination"),
                title=f"Trip to {request.get('destination')}", created_at=ts, updated_at=ts))

    async def update_trip(self, trip_id: str, **fields: Any) -> None:
        if "plan" in fields and fields["plan"] is not None and not isinstance(fields["plan"], str):
            plan = fields["plan"]
            fields["title"] = plan.get("title")
            fields["image"] = (plan.get("destination") or {}).get("image")
            fields["destination"] = (plan.get("destination") or {}).get("name") or fields.get("destination")
            fields["plan"] = json.dumps(plan)
        if "request" in fields and not isinstance(fields["request"], str):
            fields["request"] = json.dumps(fields["request"])
        fields = {k: v for k, v in fields.items() if v is not None or k in ("error",)}
        fields["updated_at"] = now_iso()
        async with self.engine.begin() as c:
            await c.execute(update(trips).where(trips.c.id == trip_id).values(**fields))

    async def get_trip(self, trip_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as c:
            row = (await c.execute(select(trips).where(trips.c.id == trip_id))).mappings().first()
        if not row:
            return None
        return {
            "id": row["id"], "status": row["status"], "revision": row["revision"],
            "request": json.loads(row["request"]), "plan": json.loads(row["plan"]) if row["plan"] else None,
            "error": row["error"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    async def list_trips(self, client_id: str | None, limit: int = 20) -> list[dict[str, Any]]:
        q = select(trips).order_by(desc(trips.c.created_at)).limit(limit)
        if client_id:
            q = q.where(trips.c.client_id == client_id)
        async with self.engine.connect() as c:
            rows = (await c.execute(q)).mappings().all()
        out = []
        for r in rows:
            req = json.loads(r["request"])
            out.append({"id": r["id"], "title": r["title"] or f"Trip to {req.get('destination')}",
                        "destination": r["destination"] or req.get("destination", ""),
                        "start_date": req.get("start_date", ""), "end_date": req.get("end_date", ""),
                        "status": r["status"], "image": r["image"], "created_at": r["created_at"]})
        return out

    # ---- events -------------------------------------------------------------------------------
    async def add_event(self, trip_id: str, revision: int, seq: int, kind: str, data: dict[str, Any]) -> None:
        async with self.engine.begin() as c:
            await c.execute(insert(events).values(trip_id=trip_id, revision=revision, seq=seq, type=kind,
                                                  data=json.dumps(data, default=str)))

    async def get_events(self, trip_id: str, revision: int | None = None) -> list[dict[str, Any]]:
        cond = events.c.trip_id == trip_id
        if revision is not None:
            cond = and_(cond, events.c.revision == revision)
        async with self.engine.connect() as c:
            rows = (await c.execute(select(events).where(cond).order_by(events.c.seq))).mappings().all()
        return [{"type": r["type"], "data": json.loads(r["data"]), "seq": r["seq"], "revision": r["revision"]}
                for r in rows]

    async def last_seq(self, trip_id: str) -> int:
        async with self.engine.connect() as c:
            row = (await c.execute(select(events.c.seq).where(events.c.trip_id == trip_id)
                                   .order_by(desc(events.c.seq)).limit(1))).first()
        return int(row[0]) if row else 0

    # ---- preference profiles -------------------------------------------------------------------
    async def get_profile(self, client_id: str) -> dict[str, Any]:
        async with self.engine.connect() as c:
            row = (await c.execute(select(profiles.c.data).where(profiles.c.client_id == client_id))).first()
        return json.loads(row[0]) if row else {}

    async def put_profile(self, client_id: str, data: dict[str, Any]) -> None:
        async with self.engine.begin() as c:
            await c.execute(delete(profiles).where(profiles.c.client_id == client_id))
            await c.execute(insert(profiles).values(client_id=client_id, data=json.dumps(data), updated_at=now_iso()))

    # ---- plan cache ---------------------------------------------------------------------------
    async def cache_get(self, key: str, max_age_s: int) -> dict[str, Any] | None:
        import time

        async with self.engine.connect() as c:
            row = (await c.execute(select(plan_cache).where(plan_cache.c.key == key))).mappings().first()
        if not row or time.time() - row["created_ts"] > max_age_s:
            return None
        return {"trip_id": row["trip_id"], "plan": json.loads(row["plan"]), "created_ts": row["created_ts"]}

    async def cache_put(self, key: str, trip_id: str, plan: dict[str, Any]) -> None:
        import time

        async with self.engine.begin() as c:
            await c.execute(delete(plan_cache).where(plan_cache.c.key == key))
            await c.execute(insert(plan_cache).values(key=key, trip_id=trip_id, plan=json.dumps(plan),
                                                      created_ts=int(time.time())))
