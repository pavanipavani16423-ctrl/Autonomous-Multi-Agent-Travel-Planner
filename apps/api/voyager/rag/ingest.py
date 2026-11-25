"""Index the guidebook, and expand it on demand with Wikivoyage articles for uncovered cities.

    python -m voyager.rag.ingest            # index data/corpus.jsonl (+ data/expanded.jsonl); idempotent
    python -m voyager.rag.ingest --rebuild  # drop the collection first
    python -m voyager.rag.ingest --expand "Ljubljana"   # fetch + index one more city now

On-demand expansion (used by the `brief` agent): fetch the city's Wikivoyage article (MediaWiki
`prop=extracts`, plain text, redirects resolved), split it by section, chunk, embed, upsert. The
records are also appended to `data/expanded.jsonl` so a rebuild keeps them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from typing import Any

from voyager.config import get_settings
from voyager.mcp.http import fetch_json
from voyager.rag.store import Guidebook, get_guidebook, read_corpus
from voyager.rag.text import article_records, destination_key, point_id

logger = logging.getLogger(__name__)

WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"
MIN_ARTICLE_CHARS = 500


def _all_records() -> list[dict[str, Any]]:
    s = get_settings()
    records = read_corpus(s.corpus_path) if s.corpus_path.exists() else []
    expanded = s.data_dir / "expanded.jsonl"
    if expanded.exists() and not s.offline:
        records += read_corpus(expanded)
    return records


def ingest_corpus(book: Guidebook | None = None, rebuild: bool = False,
                  records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Index the corpus if the collection is missing or incomplete. Returns timing stats."""
    book = book or get_guidebook()
    records = records if records is not None else _all_records()
    started = time.perf_counter()
    if rebuild:
        with book.lock:
            if book.client.collection_exists(book.collection):
                book.client.delete_collection(book.collection)
    have = book.count()
    upserted = 0
    if have < len(records):
        todo = records
        if have:  # resume an interrupted ingest: only embed what is missing
            existing = book.existing_ids()
            todo = [r for r in records if point_id(r["page_content"]) not in existing]
        logger.info("indexing %d guidebook passages (collection has %d)", len(todo), have)
        upserted = book.upsert_records(todo)
    book.refresh_cities()
    book.ready = True
    stats = {"records": len(records), "already_indexed": have, "upserted": upserted,
             "points": book.count(), "cities": len(book.cities),
             "seconds": round(time.perf_counter() - started, 1)}
    logger.info("guidebook ready: %s", stats)
    return stats


async def fetch_wikivoyage(title: str) -> tuple[str, str, str] | None:
    """(resolved title, plain text, url) or None when Wikivoyage has no usable article."""
    res = await fetch_json(WIKIVOYAGE_API, params={
        "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title,
        "format": "json", "maxlag": 5}, ttl=7 * 86400, timeout=20)
    if not res.ok:
        return None
    for page in (res.data.get("query") or {}).get("pages", {}).values():
        if "missing" in page:
            continue
        text = page.get("extract") or ""
        resolved = page.get("title", title)
        if len(text) < MIN_ARTICLE_CHARS or "may refer to" in text[:400]:
            continue
        return resolved, text, f"https://en.wikivoyage.org/wiki/{resolved.replace(' ', '_')}"
    return None


async def expand_city(name: str, country: str = "", book: Guidebook | None = None) -> dict[str, Any]:
    """Fetch + index a city's Wikivoyage article. status: 'expanded' | 'none'."""
    book = book or get_guidebook()
    started = time.perf_counter()
    article = None
    for title in dict.fromkeys([name, f"{name} ({country})" if country else name]):
        article = await fetch_wikivoyage(title)
        if article:
            break
    if not article:
        return {"status": "none", "passages": 0, "ms": int((time.perf_counter() - started) * 1000),
                "note": f"Wikivoyage has no usable article for {name}."}
    resolved, text, url = article
    alias = name if destination_key(name) != destination_key(resolved) else ""
    records = article_records(resolved, text, url, alias=alias, country=country)
    if not records:
        return {"status": "none", "passages": 0, "ms": int((time.perf_counter() - started) * 1000),
                "note": f"Wikivoyage article for {resolved} had no usable sections."}
    n = await asyncio.to_thread(book.upsert_records, records)
    key = destination_key(resolved)
    entry = book.cities.setdefault(key, {"name": resolved, "country": country, "passages": 0, "aliases": set()})
    entry["passages"] = max(entry["passages"], 0) + n
    if alias:
        entry["aliases"].add(destination_key(alias))
    s = get_settings()
    if not s.offline:
        with open(s.data_dir / "expanded.jsonl", "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"status": "expanded", "passages": n, "title": resolved, "url": url,
            "ms": int((time.perf_counter() - started) * 1000),
            "note": f"Indexed {n} passages from the Wikivoyage article '{resolved}'."}


def copy_to(url: str, api_key: str | None = None, batch: int = 256) -> dict[str, Any]:
    """Copy the embedded index (vectors + payloads) to a Qdrant server without re-embedding."""
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm

    src = get_guidebook()
    dst = Guidebook(QdrantClient(url=url, api_key=api_key, timeout=60))
    dst.ensure_collection()
    started, n, offset = time.perf_counter(), 0, None
    while True:
        with src.lock:
            points, offset = src.client.scroll(src.collection, limit=batch, offset=offset,
                                               with_payload=True, with_vectors=True)
        if points:
            dst.client.upsert(dst.collection, wait=True, points=[
                qm.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points])
            n += len(points)
        if offset is None:
            break
    return {"copied": n, "target_points": dst.count(), "seconds": round(time.perf_counter() - started, 1)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console
    except (AttributeError, OSError):
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Index the Voyager guidebook in Qdrant.")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--expand", help="fetch and index one more city from Wikivoyage")
    parser.add_argument("--warm", action="store_true", help="also download/load the fastembed models")
    parser.add_argument("--copy-to", metavar="QDRANT_URL",
                        help="copy the embedded index to a Qdrant server (no re-embedding)")
    args = parser.parse_args()
    if args.warm:
        from voyager.rag.embeddings import warm

        t = time.perf_counter()
        warm()
        print(f"models ready in {time.perf_counter() - t:.1f}s")
    if args.copy_to:
        print(json.dumps(copy_to(args.copy_to, get_settings().qdrant_api_key or None)))
        return
    stats = ingest_corpus(rebuild=args.rebuild)
    print(json.dumps(stats))
    if args.expand:
        print(json.dumps(asyncio.run(expand_city(args.expand))))
    get_guidebook().client.close()


if __name__ == "__main__":
    main()
