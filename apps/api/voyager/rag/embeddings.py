"""fastembed models (ONNX, no torch): dense bge-small, sparse BM25, MiniLM cross-encoder reranker.

Loaded lazily, once per process, and guarded by a lock (ONNX sessions are not re-entrant across
threads). With VOYAGER_OFFLINE=1 deterministic hashing stand-ins are used so tests need no download.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import Counter
from typing import Any

from voyager.config import get_settings
from voyager.rag.text import tokenize

DENSE_DIM = 384
_LOCK = threading.RLock()
_MODELS: dict[str, Any] = {}

RERANK_CHARS = 700  # the reranker scores the first ~150 tokens of each passage
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _h(token: str, mod: int) -> int:
    return int.from_bytes(hashlib.md5(token.encode()).digest()[:4], "little") % mod


class _FakeDense:
    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * DENSE_DIM
            for tok in tokenize(t):
                v[_h(tok, DENSE_DIM)] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class _FakeSparse:
    def embed(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        out = []
        for t in texts:
            counts = Counter(_h(tok, 2**31 - 1) for tok in tokenize(t))
            out.append((list(counts.keys()), [float(c) for c in counts.values()]))
        return out


def _model(name: str) -> Any:
    with _LOCK:
        if name in _MODELS:
            return _MODELS[name]
        s = get_settings()
        cache = str(s.models_dir)
        if name == "dense":
            from fastembed import TextEmbedding

            m = TextEmbedding(s.dense_model, cache_dir=cache, threads=s.embed_threads, enable_cpu_mem_arena=False)
        elif name == "sparse":
            from fastembed import SparseTextEmbedding

            m = SparseTextEmbedding(s.sparse_model, cache_dir=cache)
        elif name == "rerank":
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            m = TextCrossEncoder(s.rerank_model, cache_dir=cache, threads=s.embed_threads,
                                 enable_cpu_mem_arena=False)
        else:
            raise KeyError(name)
        _MODELS[name] = m
        return m


def embed_passages(texts: list[str]) -> list[list[float]]:
    if get_settings().offline:
        return _FakeDense().embed(texts)
    with _LOCK:
        return [v.tolist() for v in _model("dense").passage_embed(texts, batch_size=16)]


def embed_query(text: str) -> list[float]:
    if get_settings().offline:
        return _FakeDense().embed([text])[0]
    with _LOCK:
        return next(iter(_model("dense").query_embed(text))).tolist()


def sparse_passages(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    if get_settings().offline:
        return _FakeSparse().embed(texts)
    with _LOCK:
        return [(e.indices.tolist(), e.values.tolist()) for e in _model("sparse").embed(texts, batch_size=256)]


def sparse_query(text: str) -> tuple[list[int], list[float]]:
    if get_settings().offline:
        return _FakeSparse().embed([text])[0]
    with _LOCK:
        e = next(iter(_model("sparse").query_embed(text)))
        return e.indices.tolist(), e.values.tolist()


def rerank(query: str, docs: list[str]) -> list[float]:
    """Cross-encoder relevance logits (higher = more relevant)."""
    if not docs:
        return []
    s = get_settings()
    if s.offline or not s.rerank_enabled:
        q = set(tokenize(query))
        return [len(q & set(tokenize(d))) / (len(q) or 1) * 8 - 4 for d in docs]
    with _LOCK:
        # passages are <= ~900 chars; truncating keeps the ONNX activations (and RAM) small
        docs = [d[:RERANK_CHARS] for d in docs]
        return [float(x) for x in _model("rerank").rerank(query, docs, batch_size=8)]


def warm() -> None:
    """Load all models (Docker build / startup) so the first request isn't slow."""
    if get_settings().offline:
        return
    embed_query("warm up")
    sparse_query("warm up")
    rerank("warm up", ["warm up passage"])
