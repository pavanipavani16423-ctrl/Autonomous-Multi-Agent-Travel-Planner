"""Per-trip SSE event log with replay for late subscribers.

Every event gets an increasing `seq` and an ISO `ts`, is kept in memory for live fan-out and written
to the database (so a stream can be replayed after a restart). A subscriber receives the events of
the trip's current revision from the start, then live ones, and the stream ends with `done`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from voyager.memory.store import Store


@dataclass
class Channel:
    seq: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)  # {revision, seq, type, data}
    queues: set[asyncio.Queue] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    loaded: bool = False  # seq initialised from the database


class EventBus:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.channels: dict[str, Channel] = {}

    def _channel(self, trip_id: str) -> Channel:
        # created synchronously: a publisher and a subscriber racing here must share ONE channel
        ch = self.channels.get(trip_id)
        if ch is None:
            ch = self.channels[trip_id] = Channel()
        return ch

    async def publish(self, trip_id: str, revision: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        ch = self._channel(trip_id)
        async with ch.lock:
            if not ch.loaded:
                ch.seq = max(ch.seq, await self.store.last_seq(trip_id))
                ch.loaded = True
            ch.seq += 1
            data = {**payload, "ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "seq": ch.seq}
            ev = {"revision": revision, "seq": ch.seq, "type": kind, "data": data}
            ch.events.append(ev)
            await self.store.add_event(trip_id, revision, ch.seq, kind, data)
        for q in list(ch.queues):
            q.put_nowait(ev)
        return data

    async def subscribe(self, trip_id: str, revision: int, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Yield {type, data} for `revision`: replay, then live, until `done`."""
        ch = self._channel(trip_id)
        q: asyncio.Queue = asyncio.Queue()
        ch.queues.add(q)
        try:
            past = [e for e in ch.events if e["revision"] == revision]
            if not past:
                past = [e for e in await self.store.get_events(trip_id, revision)]
            last = after_seq
            for ev in past:
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield ev
                if ev["type"] == "done":
                    return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield {"type": "ping", "data": {}, "seq": last, "revision": revision}
                    continue
                if ev["revision"] != revision or ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield ev
                if ev["type"] == "done":
                    return
        finally:
            ch.queues.discard(q)

    def forget(self, trip_id: str) -> None:
        """Drop the in-memory log of a finished trip (the database keeps it)."""
        ch = self.channels.get(trip_id)
        if ch and not ch.queues:
            self.channels.pop(trip_id, None)
