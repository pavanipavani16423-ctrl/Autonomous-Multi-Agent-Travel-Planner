"""Destination hero image: Wikipedia REST `page/summary` thumbnail (free, no key)."""

from __future__ import annotations

import re
from urllib.parse import quote

from voyager.mcp.http import fetch_json

SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"


async def wikipedia_image(*titles: str, width: int = 1280) -> str | None:
    for title in dict.fromkeys(t for t in titles if t):
        res = await fetch_json(SUMMARY_URL + quote(title.replace(" ", "_")), ttl=30 * 86400, timeout=8)
        if not res.ok or res.data.get("type") == "disambiguation":
            continue
        thumb = (res.data.get("thumbnail") or {}).get("source")
        original = (res.data.get("originalimage") or {}).get("source")
        if thumb:
            # thumbnails are served at any width: /320px-Foo.jpg -> /1280px-Foo.jpg
            return re.sub(r"/\d+px-", f"/{width}px-", thumb)
        if original:
            return original
    return None
