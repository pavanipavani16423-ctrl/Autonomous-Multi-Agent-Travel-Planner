"""Retrieval evaluation: hit-rate@5, MRR@10 and precision@5 on the labelled query set, per pipeline
stage (dense, sparse BM25, hybrid RRF, hybrid + rerank = production), plus the wrong-city rate
without the destination pre-filter (what the payload filter buys)."""

from __future__ import annotations

import time
from typing import Any

from qdrant_client import models as qm

from voyager.rag import embeddings as emb
from voyager.rag.store import RERANK_POOL, Guidebook
from voyager.rag.text import destination_key

MODES = ("dense", "sparse", "hybrid", "hybrid_rerank", "hybrid_rerank_nofilter")


def _ranked(book: Guidebook, mode: str, query: str, dest: str, n: int = 10) -> list[dict[str, Any]]:
    key = book.resolve(dest) or destination_key(dest)
    flt = None if mode.endswith("nofilter") else book._filter(key, None)
    dense = emb.embed_query(query)
    idx, val = emb.sparse_query(query)
    sparse = qm.SparseVector(indices=idx, values=val)
    with book.lock:
        if mode == "dense":
            pts = book.client.query_points(book.collection, query=dense, using="dense", limit=n,
                                           query_filter=flt, with_payload=True).points
        elif mode == "sparse":
            pts = book.client.query_points(book.collection, query=sparse, using="sparse", limit=n,
                                           query_filter=flt, with_payload=True).points
        else:
            pts = book.client.query_points(
                book.collection, prefetch=[qm.Prefetch(query=dense, using="dense", limit=30, filter=flt),
                                           qm.Prefetch(query=sparse, using="sparse", limit=30, filter=flt)],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=max(n, RERANK_POOL), with_payload=True).points
    rows = [p.payload for p in pts]
    if "rerank" in mode and rows:
        scores = emb.rerank(query, [r["text"] for r in rows])
        rows = [r for r, _ in sorted(zip(rows, scores, strict=True), key=lambda x: -x[1])]
    return rows[:n]


def evaluate(book: Guidebook, queries: list[tuple[str, str, list[str]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for mode in MODES:
        hits, rr, p5, wrong, ms = 0, 0.0, 0.0, 0.0, 0.0
        for dest, query, sections in queries:
            key = book.resolve(dest) or destination_key(dest)
            t = time.perf_counter()
            rows = _ranked(book, mode, f"{dest} {query}", dest)
            ms += (time.perf_counter() - t) * 1000
            rel = [r.get("destination") == key and r.get("section") in sections for r in rows]
            hits += any(rel[:5])
            first = next((i for i, x in enumerate(rel) if x), None)
            rr += 1 / (first + 1) if first is not None else 0
            p5 += sum(rel[:5]) / 5
            wrong += sum(r.get("destination") != key for r in rows[:5]) / 5
        n = len(queries)
        out[mode] = {"hit_rate@5": round(hits / n, 3), "mrr@10": round(rr / n, 3), "precision@5": round(p5 / n, 3),
                     "wrong_city@5": round(wrong / n, 3), "avg_ms": round(ms / n, 1)}
    return out
