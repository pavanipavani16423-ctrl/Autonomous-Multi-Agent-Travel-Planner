"""The guidebook: a Qdrant collection with named dense + sparse vectors and a destination pre-filter.

Search pipeline (one Query API call + a rerank):

    payload pre-filter  destination == city (keyword index)  [+ section in (...)]
    prefetch            dense  bge-small cosine  -> 30 candidates
                        sparse BM25 (IDF)        -> 30 candidates
    fusion              Reciprocal Rank Fusion
    rerank              MiniLM cross-encoder over the fused top 20 -> top k
    grounding gate      city not covered, or nothing relevant survives -> covered = False

Embedded Qdrant on disk by default (`data/qdrant`), `QDRANT_URL` switches to a server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from voyager.config import get_settings
from voyager.rag import embeddings as emb
from voyager.rag.text import GENERAL_KNOWLEDGE, citation_id, destination_key, point_id

logger = logging.getLogger(__name__)

RERANK_GATE = -6.0  # cross-encoder logit below which a passage is treated as irrelevant
PREFETCH = 30
RERANK_POOL = 16
# a numbered Wikivoyage "See" listing: "Jaipur — See: 8 Hawa Mahal (Palace of Breeze). 9AM-5PM ..."
# or a bulleted one: "Agonda — also known as Turtle Beach, in the south."
BULLET_RE = re.compile(r"(?:^|\n)\s*([A-Z][^\n—]{2,40}?)\s+—\s")
LISTING_RE = re.compile(r"See:\s*\d+\s+([^(,.;☏\n]{3,60})")

CITY_COUNTRY: dict[str, str] = {
    "abu dhabi": "United Arab Emirates", "agra": "India", "amritsar": "India", "amsterdam": "Netherlands",
    "athens": "Greece", "auckland": "New Zealand", "bali": "Indonesia", "bangalore": "India",
    "bangkok": "Thailand", "barcelona": "Spain", "beijing": "China", "berlin": "Germany",
    "buenos aires": "Argentina", "cairo": "Egypt", "cape town": "South Africa", "chennai": "India",
    "chicago": "United States", "copenhagen": "Denmark", "darjeeling": "India", "delhi": "India",
    "doha": "Qatar", "dubai": "United Arab Emirates", "edinburgh": "United Kingdom", "florence": "Italy",
    "goa": "India", "hanoi": "Vietnam", "hong kong": "China", "hyderabad": "India", "istanbul": "Turkey",
    "jaipur": "India", "kochi": "India", "kolkata": "India", "kuala lumpur": "Malaysia", "kyoto": "Japan",
    "lima": "Peru", "lisbon": "Portugal", "london": "United Kingdom", "los angeles": "United States",
    "marrakech": "Morocco", "melbourne": "Australia", "mexico city": "Mexico", "mumbai": "India",
    "new york city": "United States", "oslo": "Norway", "paris": "France", "pondicherry": "India",
    "prague": "Czech Republic", "reykjavik": "Iceland", "rio de janeiro": "Brazil", "rishikesh": "India",
    "rome": "Italy", "san francisco": "United States", "seoul": "South Korea", "shanghai": "China",
    "singapore": "Singapore", "stockholm": "Sweden", "sydney": "Australia", "tashkent": "Uzbekistan",
    "tokyo": "Japan", "toronto": "Canada", "udaipur": "India", "varanasi": "India", "venice": "Italy",
    "vienna": "Austria", "zurich": "Switzerland",
}


@dataclass
class Passage:
    id: str  # citation id (wv-xxxxxxxxxx)
    text: str
    destination: str
    destination_name: str
    section: str
    area: str
    url: str
    score: float = 0.0  # rerank relevance in [0, 1] (sigmoid of the cross-encoder logit)

    def citation(self) -> dict[str, Any]:
        body = self.text.split(":", 1)[-1].strip() if ":" in self.text[:80] else self.text
        return {"id": self.id, "title": f"{self.destination_name} — {self.section} (Wikivoyage)",
                "url": self.url, "snippet": body[:280], "source": "wikivoyage"}


@dataclass
class SearchResult:
    query: str
    passages: list[Passage] = field(default_factory=list)
    covered: bool = False
    top_score: float = 0.0
    ms: int = 0


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(min(x, 30), -30)))


class Guidebook:
    def __init__(self, client: QdrantClient | None = None) -> None:
        s = get_settings()
        self.collection = s.collection
        if client is not None:
            self.client = client
        elif s.qdrant_url:
            self.client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=30)
        else:
            s.qdrant_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(s.qdrant_path))
        self.lock = threading.RLock()
        self.cities: dict[str, dict[str, Any]] = {}  # key -> {name, country, passages, aliases}
        self.ready = False  # set once the corpus is indexed
        self._landmark_cache: dict[str, list[Passage]] = {}

    # ---- schema -------------------------------------------------------------------------------
    def ensure_collection(self) -> None:
        with self.lock:
            if self.client.collection_exists(self.collection):
                return
            self.client.create_collection(
                self.collection,
                vectors_config={"dense": qm.VectorParams(size=emb.DENSE_DIM, distance=qm.Distance.COSINE)},
                sparse_vectors_config={"sparse": qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
            )
            for fld in ("destination", "destination_alias", "section"):
                try:
                    self.client.create_payload_index(self.collection, fld, qm.PayloadSchemaType.KEYWORD)
                except Exception:  # noqa: BLE001 - local mode ignores payload indexes (warning only)
                    pass

    def existing_ids(self) -> set[str]:
        ids: set[str] = set()
        with self.lock:
            if not self.client.collection_exists(self.collection):
                return ids
            offset = None
            while True:
                points, offset = self.client.scroll(self.collection, limit=4096, offset=offset,
                                                    with_payload=False, with_vectors=False)
                ids |= {str(p.id) for p in points}
                if offset is None:
                    return ids

    def texts_for(self, cids: list[str]) -> dict[str, str]:
        """Full passage text for citation ids (evaluation uses whole passages as Ragas contexts)."""
        if not cids:
            return {}
        with self.lock:
            points, _ = self.client.scroll(
                self.collection, limit=len(cids) * 2, with_vectors=False, with_payload=["cid", "text"],
                scroll_filter=qm.Filter(must=[qm.FieldCondition(key="cid", match=qm.MatchAny(any=cids))]))
        return {p.payload["cid"]: p.payload["text"] for p in points}

    def count(self) -> int:
        with self.lock:
            if not self.client.collection_exists(self.collection):
                return 0
            return self.client.count(self.collection, exact=True).count

    # ---- writes -------------------------------------------------------------------------------
    def upsert_records(self, records: list[dict[str, Any]], batch: int = 128) -> int:
        """Embed + upsert corpus records (idempotent: point ids derive from the text)."""
        self.ensure_collection()
        n = 0
        for i in range(0, len(records), batch):
            part = records[i:i + batch]
            texts = [r["page_content"] for r in part]
            dense = emb.embed_passages(texts)
            sparse = emb.sparse_passages(texts)
            points = []
            for r, d, (idx, val) in zip(part, dense, sparse, strict=True):
                md = r.get("metadata") or {}
                payload = {
                    "text": r["page_content"], "cid": citation_id(r["page_content"]),
                    "destination": md.get("destination", ""), "destination_name": md.get("destination_name", ""),
                    "destination_alias": md.get("destination_alias", ""), "area": md.get("area", "general"),
                    "section": md.get("section", ""), "url": md.get("url", ""), "country": md.get("country", ""),
                }
                points.append(qm.PointStruct(id=point_id(r["page_content"]), payload=payload,
                                             vector={"dense": d, "sparse": qm.SparseVector(indices=idx, values=val)}))
            with self.lock:
                self.client.upsert(self.collection, points=points, wait=True)
            n += len(points)
        return n

    # ---- coverage -----------------------------------------------------------------------------
    def refresh_cities(self) -> dict[str, dict[str, Any]]:
        """Scan payloads once to know which cities are covered (and by how many passages)."""
        cities: dict[str, dict[str, Any]] = {}
        with self.lock:
            if not self.client.collection_exists(self.collection):
                self.cities = {}
                return self.cities
            offset = None
            while True:
                points, offset = self.client.scroll(
                    self.collection, limit=2048, offset=offset, with_vectors=False,
                    with_payload=["destination", "destination_name", "destination_alias", "country"])
                for p in points:
                    pl = p.payload or {}
                    key = pl.get("destination", "")
                    if not key or key == GENERAL_KNOWLEDGE:
                        continue
                    c = cities.setdefault(key, {"name": pl.get("destination_name") or key.title(),
                                                "country": pl.get("country") or CITY_COUNTRY.get(key, ""),
                                                "passages": 0, "aliases": set()})
                    c["passages"] += 1
                    if pl.get("destination_alias"):
                        c["aliases"].add(pl["destination_alias"])
                if offset is None:
                    break
        self.cities = cities
        return cities

    def resolve(self, name: str) -> str | None:
        """City key for a typed name (matches key, alias or display name)."""
        key = destination_key(name)
        if key in self.cities:
            return key
        for k, c in self.cities.items():
            if key in c["aliases"] or destination_key(c["name"]) == key:
                return k
        return None

    def passages_for(self, key: str | None) -> int:
        return self.cities.get(key or "", {}).get("passages", 0)

    def is_covered(self, name: str) -> bool:
        key = self.resolve(name)
        return key is not None and self.passages_for(key) >= get_settings().min_city_passages

    # ---- search -------------------------------------------------------------------------------
    def _filter(self, key: str, sections: list[str] | None) -> qm.Filter:
        must: list[Any] = [qm.Filter(should=[
            qm.FieldCondition(key="destination", match=qm.MatchValue(value=key)),
            qm.FieldCondition(key="destination_alias", match=qm.MatchValue(value=key)),
        ])]
        if sections:
            must.append(qm.FieldCondition(key="section", match=qm.MatchAny(any=sections)))
        return qm.Filter(must=must)

    def search(self, query: str, destination: str, sections: list[str] | None = None, k: int = 6) -> SearchResult:
        started = time.perf_counter()
        key = self.resolve(destination) or destination_key(destination)
        result = SearchResult(query=query)
        if self.passages_for(key) == 0:
            result.ms = int((time.perf_counter() - started) * 1000)
            return result  # grounding gate: city not in the guidebook
        flt = self._filter(key, sections)
        dense = emb.embed_query(query)
        idx, val = emb.sparse_query(query)
        with self.lock:
            res = self.client.query_points(
                self.collection,
                prefetch=[qm.Prefetch(query=dense, using="dense", limit=PREFETCH, filter=flt),
                          qm.Prefetch(query=qm.SparseVector(indices=idx, values=val), using="sparse",
                                      limit=PREFETCH, filter=flt)],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=RERANK_POOL, with_payload=True,
            )
        pool = res.points
        if not pool:
            result.ms = int((time.perf_counter() - started) * 1000)
            return result
        logits = emb.rerank(query, [p.payload["text"] for p in pool])
        ranked = sorted(zip(pool, logits, strict=True), key=lambda x: -x[1])
        for p, logit in ranked:
            if logit < RERANK_GATE or len(result.passages) >= k:
                continue
            pl = p.payload
            result.passages.append(Passage(
                id=pl.get("cid") or citation_id(pl["text"]), text=pl["text"], destination=pl["destination"],
                destination_name=pl.get("destination_name", ""), section=pl.get("section", ""),
                area=pl.get("area", ""), url=pl.get("url", ""), score=round(_sigmoid(logit), 4)))
        result.covered = bool(result.passages) and self.passages_for(key) >= get_settings().min_city_passages
        result.top_score = result.passages[0].score if result.passages else 0.0
        result.ms = int((time.perf_counter() - started) * 1000)
        return result

    async def asearch(self, query: str, destination: str, sections: list[str] | None = None,
                      k: int = 6) -> SearchResult:
        return await asyncio.to_thread(self.search, query, destination, sections, k)

    # ---- landmark salience ------------------------------------------------------------------
    def landmarks(self, destination: str, k: int = 6) -> list[Passage]:
        """The city's most-referenced 'See' listings.

        Relevance search has no notion of fame: for "top sights" it happily ranks a small garden above
        the city's famous fort. Wikivoyage keeps each sight as a numbered listing ("See: 8 Hawa Mahal
        (...)"), and famous sights are mentioned again elsewhere in the guide (how to get there, where
        to eat nearby, festivals). Counting those cross-references is a cheap, explainable fame signal.
        """
        key = self.resolve(destination) or destination_key(destination)
        if self.passages_for(key) == 0:
            return []
        if key in self._landmark_cache:
            return self._landmark_cache[key][:k]
        points, offset = [], None
        with self.lock:
            while True:
                batch, offset = self.client.scroll(self.collection, scroll_filter=self._filter(key, None),
                                                   limit=256, offset=offset, with_payload=True,
                                                   with_vectors=False)
                points.extend(batch)
                if offset is None or len(points) > 3000:
                    break
        texts = [(p.payload.get("text") or "") for p in points]
        lowered = [t.lower() for t in texts]
        scored: list[tuple[int, Passage]] = []
        for p, text in zip(points, texts, strict=True):
            pl = p.payload
            if pl.get("section") != "See":
                continue
            m = LISTING_RE.search(text)
            names = [m.group(1)] if m else BULLET_RE.findall(text.split(":", 1)[-1])
            best = ("", 0)
            for raw in names:
                name = raw.strip(" .,-").lower()
                if len(name) < 4:
                    continue
                refs = sum(1 for t in lowered if name in t) - 1
                if refs > best[1]:
                    best = (name, refs)
            name, refs = best
            if refs < 1:
                continue
            scored.append((refs, name, Passage(
                id=pl.get("cid") or citation_id(text), text=text, destination=pl["destination"],
                destination_name=pl.get("destination_name", ""), section="See", area=pl.get("area", ""),
                url=pl.get("url", ""), score=1.0)))
        seen: set[str] = set()
        ranked: list[Passage] = []
        for _refs, nm, psg in sorted(scored, key=lambda x: -x[0]):
            if nm not in seen and psg.id not in {r.id for r in ranked}:
                seen.add(nm)
                ranked.append(psg)
        self._landmark_cache[key] = ranked[:12]
        return ranked[:k]

    async def alandmarks(self, destination: str, k: int = 6) -> list[Passage]:
        return await asyncio.to_thread(self.landmarks, destination, k)


def read_corpus(path: Any) -> list[dict[str, Any]]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


_BOOK: Guidebook | None = None


def get_guidebook() -> Guidebook:
    global _BOOK
    if _BOOK is None:
        _BOOK = Guidebook()
    return _BOOK


def set_guidebook(book: Guidebook | None) -> None:
    global _BOOK
    _BOOK = book
