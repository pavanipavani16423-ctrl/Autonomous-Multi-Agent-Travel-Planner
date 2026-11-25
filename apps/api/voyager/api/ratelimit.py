"""Per-IP rate limiting (pure ASGI middleware, in memory): a sliding 60 s window, separate budgets for
writes (POST) and reads. Exceeding it returns 429 with Retry-After and `{"detail": ...}`."""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from typing import Any

EXEMPT = ("/health", "/a2a/")


class RateLimiter:
    def __init__(self, app: Any, write_per_min: int, read_per_min: int) -> None:
        self.app = app
        self.limits = {"write": write_per_min, "read": read_per_min}
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, ip: str, kind: str, now: float | None = None) -> float:
        """0 if allowed (and recorded), else seconds until the next slot."""
        now = now or time.monotonic()
        q = self.hits[(ip, kind)]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= self.limits[kind]:
            return max(1.0, 60 - (now - q[0]))
        q.append(now)
        return 0.0

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"].startswith(EXEMPT) or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        fwd = headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (scope.get("client") or ("unknown", 0))[0]
        kind = "write" if scope["method"] in ("POST", "PUT", "PATCH", "DELETE") else "read"
        wait = self.check(ip, kind)
        if wait:
            body = json.dumps({"detail": f"Rate limit exceeded ({self.limits[kind]} {kind} requests/min). "
                                         f"Retry in {wait:.0f}s."}).encode()
            await send({"type": "http.response.start", "status": 429, "headers": [
                (b"content-type", b"application/json"), (b"retry-after", str(int(wait + 0.999)).encode()),
                (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
