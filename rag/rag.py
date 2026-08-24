# ============================================================
# rag/rag.py — Hybrid RAG Pipeline (Dense + Sparse)
# ============================================================
# PURPOSE:
#   Builds and queries a Hybrid Retrieval-Augmented Generation
#   system that enriches agent prompts with factual travel knowledge
#   from a PDF knowledge base.
#
# ARCHITECTURE:
#   ┌──────────────────────────────────────────┐
#   │  travel_data.pdf  (knowledge base)       │
#   │         ↓ PyPDFLoader                    │
#   │  Text chunks (RecursiveCharacterTextSplitter)
#   │         ↓                                │
#   │  ┌──────────────┐  ┌──────────────────┐ │
#   │  │ ChromaDB     │  │  BM25Retriever   │ │
#   │  │ (dense/vec.) │  │  (sparse/kw.)    │ │
#   │  └──────────────┘  └──────────────────┘ │
#   │         ↓  Reciprocal Rank Fusion        │
#   │  Top-K ranked, de-duplicated results     │
#   └──────────────────────────────────────────┘
#
# WHY HYBRID?
#   Dense retrieval (embeddings) captures semantic similarity
#   but misses exact keyword matches.  Sparse/BM25 is great at
#   exact keyword matching but ignores synonyms.  Combining them
#   via Reciprocal Rank Fusion (RRF) consistently outperforms
#   either method alone.
# ============================================================

from __future__ import annotations

import os
import unicodedata
from typing import List, Optional

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from loguru import logger

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import rag_config


# Metadata marker for chunks that apply to any trip (packing, insurance,
# budgeting) rather than to one destination.
GENERAL_KNOWLEDGE = "__general__"


def _destination_key(name: str) -> str:
    """
    Normalise a destination for comparison: 'Paris, France' -> 'paris'.

    Diacritics are stripped, because the corpus stores the title Wikivoyage
    resolved to ('Reykjavík', 'Zürich') while a user types the plain ASCII
    form. Without this the filter drops every chunk for exactly the cities
    whose names carry accents.
    """
    base = (name or "").split(",")[0].strip().lower()
    decomposed = unicodedata.normalize("NFKD", base)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def filter_by_destination(documents: List[Document], destination: str) -> List[Document]:
    """
    Drop chunks that are about a *different* destination.

    This is the core grounding rule. A relevance score alone cannot express
    "this passage is well written, on-topic for hotels, and about the wrong
    city" — which is exactly the failure that had a Dubai itinerary quoting
    Bali's dry season. Destination-tagged chunks must match; untagged and
    general chunks always survive, because generic travel advice is useful
    everywhere and misleads no one.
    """
    want = _destination_key(destination)
    if not want:
        return documents

    kept, dropped = [], []
    for doc in documents:
        doc_dest = doc.metadata.get("destination")
        # `alias` carries the name that was *requested* at ingest time when the
        # wiki redirected to a different spelling (Marrakesh -> Marrakech), so
        # either spelling finds the article.
        alias = doc.metadata.get("destination_alias")
        matches = (
            not doc_dest
            or doc_dest == GENERAL_KNOWLEDGE
            or _destination_key(doc_dest) == want
            or (alias and _destination_key(alias) == want)
        )
        if matches:
            kept.append(doc)
        else:
            dropped.append(doc_dest)

    if dropped:
        logger.info(
            f"[RAG] Dropped {len(dropped)} chunk(s) about other destinations "
            f"({', '.join(sorted(set(dropped)))}) for '{destination}'"
        )
    return kept


# ══════════════════════════════════════════════════════════════
# SECTION 0b — Embeddings
# ══════════════════════════════════════════════════════════════
# The embedding model is all-MiniLM-L6-v2 either way. What differs is the
# runtime used to execute it:
#
#   sentence-transformers -> pulls in PyTorch. Measured resident set for the
#                            whole app: 1,025 MB, and a ~2 GB install.
#   ONNX (chromadb's own) -> the same 22M-parameter model, no torch at all.
#
# Half a gigabyte of PyTorch to run a small embedding model is a poor trade
# on a 1 GB host, so ONNX is the default and torch is only used if the ONNX
# runtime is unavailable. Both produce 384-dim L2-normalised vectors, so the
# cosine distances the index is built on are unchanged — but an index built
# by one MUST be queried by the same one, so switching means re-indexing.

_embeddings_instance = None


class OnnxMiniLMEmbeddings(Embeddings):
    """LangChain Embeddings adapter over chromadb's bundled ONNX MiniLM."""

    def __init__(self) -> None:
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        self._fn = ONNXMiniLM_L6_V2()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [[float(x) for x in vec] for vec in self._fn(list(texts))]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


def get_embeddings():
    """
    Return the embedding function, cached for the process.

    Falls back to sentence-transformers only if ONNX cannot start, so a
    machine without onnxruntime still works — just heavier.
    """
    global _embeddings_instance
    if _embeddings_instance is not None:
        return _embeddings_instance

    try:
        _embeddings_instance = OnnxMiniLMEmbeddings()
        logger.info("[RAG] Embeddings: ONNX MiniLM-L6-v2 (no torch)")
    except Exception as e:
        logger.warning(
            f"[RAG] ONNX embeddings unavailable ({e}) — falling back to "
            "sentence-transformers, which loads PyTorch"
        )
        from langchain_community.embeddings import HuggingFaceEmbeddings
        _embeddings_instance = HuggingFaceEmbeddings(
            model_name=rag_config.embedding_model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings_instance


# ══════════════════════════════════════════════════════════════
# SECTION 1 — Document Loading & Chunking
# ══════════════════════════════════════════════════════════════

def load_and_chunk_documents(pdf_path: str) -> List[Document]:
    """
    Load a PDF and split it into overlapping text chunks.

    Why RecursiveCharacterTextSplitter?
    ------------------------------------
    It tries to split on natural boundaries (paragraphs → sentences
    → words) before resorting to character-level splits.  This
    preserves semantic coherence better than naive character splits.

    Parameters
    ----------
    pdf_path : Absolute or relative path to the PDF file.

    Returns
    -------
    List of LangChain Document objects, each with .page_content
    and .metadata (source, page number).
    """
    if not os.path.exists(pdf_path):
        logger.warning(
            f"[RAG] PDF not found at {pdf_path}. "
            "Using synthetic travel knowledge instead."
        )
        return _get_synthetic_documents()

    logger.info(f"[RAG] Loading PDF: {pdf_path}")
    loader = PyPDFLoader(pdf_path)      # Reads each page as a Document
    raw_docs = loader.load()
    logger.info(f"[RAG] Loaded {len(raw_docs)} pages from PDF")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=rag_config.chunk_size,     # Max chars per chunk (512)
        chunk_overlap=rag_config.chunk_overlap,  # Overlap to preserve context (64)
        separators=["\n\n", "\n", ".", "!", "?", " ", ""],  # Split hierarchy
    )
    chunks = splitter.split_documents(raw_docs)
    logger.info(f"[RAG] Split into {len(chunks)} chunks")
    return chunks


def _get_synthetic_documents() -> List[Document]:
    """
    Synthetic travel knowledge base used when no PDF is available.
    Contains structured facts about popular destinations that agents
    can retrieve as context.
    """
    synthetic_texts = [
        # Paris
        "Paris is the capital of France and one of the world's most visited cities. "
        "Best travel months: April-June and September-October. The Eiffel Tower receives "
        "7 million visitors per year. Paris has excellent metro and bus connectivity. "
        "Average meal cost: $15-30. Main neighbourhoods: Marais, Montmartre, Saint-Germain.",

        "Paris hotels: Budget options available in the 10th and 11th arrondissements (~$70/night). "
        "Luxury hotels like Ritz Paris and Plaza Athénée charge $700+/night. "
        "Many Airbnbs available near the Canal Saint-Martin area.",

        "French cuisine in Paris: Try croissants, baguettes, steak-frites, croque-monsieur. "
        "Vegetarian options widely available. Famous restaurants: Guy Savoy (3 Michelin stars), "
        "Le Jules Verne (Eiffel Tower), Café de Flore (historic). "
        "Street food: crêpes from stands near tourist attractions.",

        # Tokyo
        "Tokyo is Japan's capital, home to 13 million people. Japan Rail Pass covers Shinkansen. "
        "Best travel months: March-April (cherry blossom) and October-November. "
        "Average hotel cost: $80-200/night. Suica card for transport. Very safe city.",

        "Tokyo food culture: Ramen, sushi, tempura, yakitori, okonomiyaki. "
        "Many vegetarian options at Buddhist temple restaurants (shojin ryori). "
        "Tsukiji outer market for fresh seafood breakfast. Depachika (department store "
        "food halls) offer premium bento boxes.",

        # New York
        "New York City: World's cultural capital. Best time to visit: September-November. "
        "Subway MetroCard for $33/7-day unlimited. JFK → Manhattan: AirTrain + Subway ($10) "
        "or taxi ($55-70). Times Square, Central Park, Brooklyn Bridge are free. "
        "Museum Mile on 5th Avenue.",

        "NYC accommodation: Budget hostels in Brooklyn ~$40/night. Mid-range hotels in "
        "Midtown $200-350/night. Luxury: The Plaza, Four Seasons $800+/night. "
        "Staten Island Ferry is free with great views of Statue of Liberty.",

        # General Travel Tips
        "Travel insurance is strongly recommended for international trips. "
        "Always carry a photocopy of your passport. Check visa requirements 3 months in advance. "
        "Travel adapters needed for different outlet types globally. "
        "Notify your bank of travel dates to prevent card blocks.",

        "Budget travel tips: Book flights 6-8 weeks in advance for best prices. "
        "Travel on Tuesdays and Wednesdays for cheaper airfares. "
        "Use Google Flights price tracking. Hostels and guesthouses save 60-70% vs hotels. "
        "Cook at accommodation with kitchen to save on food costs.",

        "Packing essentials: Lightweight clothing, universal adapter, portable charger, "
        "offline maps downloaded (Maps.me or Google Maps offline), translation app, "
        "first aid kit, rehydration salts, photocopies of all documents stored in email.",

        # Southeast Asia
        "Bangkok, Thailand: Tropical climate year-round. Dry season November-April. "
        "Tuk-tuks and BTS Skytrain for transport. Street food from $1-3/meal. "
        "Grand Palace, Wat Pho, Floating Markets are must-see. Visa on arrival for most nationalities.",

        "Bali, Indonesia: Best time to visit April-October (dry season). "
        "Ubud for culture and nature, Seminyak for beaches and nightlife. "
        "Average scooter rental $5/day. Excellent vegetarian and vegan food scene. "
        "Traditional Balinese dance performances nightly.",
    ]

    # Which destination each chunk is *about*, in the same order as above.
    # GENERAL_KNOWLEDGE marks advice that applies to any trip. This is what
    # lets retrieval distinguish "useful generic packing advice" from "facts
    # about a city the traveller is not going to" — only the latter is
    # actively misleading, and only the latter gets filtered out.
    doc_destinations = [
        "paris", "paris", "paris",
        "tokyo", "tokyo",
        "new york", "new york",
        GENERAL_KNOWLEDGE, GENERAL_KNOWLEDGE, GENERAL_KNOWLEDGE,
        "bangkok",
        "bali",
    ]
    assert len(doc_destinations) == len(synthetic_texts), (
        f"doc_destinations ({len(doc_destinations)}) must stay in step with "
        f"synthetic_texts ({len(synthetic_texts)})"
    )

    docs = [
        Document(
            page_content=text,
            metadata={
                "source": "synthetic_travel_knowledge",
                "chunk_id": i,
                "destination": dest,
            },
        )
        for i, (text, dest) in enumerate(zip(synthetic_texts, doc_destinations))
    ]
    covered = sorted({d for d in doc_destinations if d != GENERAL_KNOWLEDGE})
    logger.info(
        f"[RAG] Created {len(docs)} synthetic knowledge documents | "
        f"destinations covered: {', '.join(covered)}"
    )
    return docs


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Vector Store (Dense Retrieval)
# ══════════════════════════════════════════════════════════════

def build_vector_store(documents: List[Document]) -> Chroma:
    """
    Create or load a ChromaDB vector store from documents.

    Dense retrieval uses cosine similarity between query embedding
    and document embeddings generated by the HuggingFace model.

    Why all-MiniLM-L6-v2?
    ----------------------
    384-dimension model, fast inference, good semantic understanding,
    runs entirely locally (no API cost for embeddings).
    """
    embeddings = get_embeddings()

    persist_dir = rag_config.persist_dir

    # If a persisted store exists, load it; otherwise build from scratch.
    # Compatibility is checked with plain sqlite3 BEFORE any Chroma client
    # touches the directory: chromadb caches its client per path and keeps the
    # sqlite file open, so discovering the problem by catching an exception
    # leaves the file locked and the directory only half-removable.
    if os.path.exists(persist_dir) and os.listdir(persist_dir):
        if _persisted_store_is_compatible(persist_dir):
            logger.info(f"[RAG] Loading existing ChromaDB from {persist_dir}")
            try:
                vector_store = Chroma(
                    persist_directory=persist_dir,
                    embedding_function=embeddings,
                )
                count = vector_store._collection.count()
                logger.info(f"[RAG] Existing vector store OK | {count} vectors")
                return vector_store
            except Exception as e:
                logger.warning(f"[RAG] Existing store failed to open ({e}) — rebuilding")
        else:
            logger.warning(
                f"[RAG] Persisted store at {persist_dir} was written by an "
                f"incompatible chromadb version — dense retrieval would silently "
                f"return nothing and hybrid search would degrade to BM25-only. "
                f"Rebuilding it from source documents."
            )
        _discard_persist_dir(persist_dir)

    logger.info(f"[RAG] Building new ChromaDB vector store ({len(documents)} chunks)…")
    vector_store = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        # Embeddings are L2-normalised above, so cosine is the metric the
        # score_threshold is meant to be read against. Chroma defaults to l2
        # when this is unset, which silently changes what the threshold means.
        collection_metadata={"hnsw:space": "cosine"},
    )

    # Chroma rejects any single insert above ~5.4k records (a SQLite variable
    # limit), so a real corpus has to go in batches. Doing it in slices also
    # keeps peak memory during embedding bounded.
    batch = 2000
    for start in range(0, len(documents), batch):
        slice_ = documents[start:start + batch]
        vector_store.add_documents(slice_)
        logger.info(
            f"[RAG]   indexed {min(start + batch, len(documents))}/{len(documents)}"
        )

    logger.info(
        f"[RAG] Vector store built and persisted at {persist_dir} "
        f"| {len(documents)} documents | space=cosine"
    )
    return vector_store


def _persisted_store_is_compatible(persist_dir: str) -> bool:
    """
    Can the *installed* chromadb read this directory?

    Checked by reading chroma.sqlite3 directly, read-only, with no chromadb
    involvement — so a "no" leaves nothing open and the directory stays
    deletable. chromadb < 0.6 stores `max_seq_id.seq_id` as an 8/24-byte BLOB
    and decodes it with `len()`; newer versions write a plain INTEGER, which
    makes every query raise `TypeError: object of type 'int' has no len()`.
    """
    db_path = os.path.join(persist_dir, "chroma.sqlite3")
    if not os.path.exists(db_path):
        return False

    import sqlite3
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT seq_id FROM max_seq_id LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.debug(f"[RAG] Could not inspect {db_path}: {e}")
        return False

    if row is None:
        return True  # no rows to decode; nothing can break

    compatible = isinstance(row[0], (bytes, bytearray))
    if not compatible:
        logger.debug(
            f"[RAG] max_seq_id.seq_id is {type(row[0]).__name__}, "
            "expected bytes — store predates/postdates installed chromadb"
        )
    return compatible


def _discard_persist_dir(persist_dir: str) -> None:
    """
    Remove an unusable Chroma directory so it can be rebuilt.

    The contents are fully regenerable from the source documents, so deleting
    is safe. If the OS holds the files open (common on Windows), rename the
    directory aside rather than failing the whole run.
    """
    import shutil
    try:
        shutil.rmtree(persist_dir)
        logger.info(f"[RAG] Removed stale vector store at {persist_dir}")
    except Exception as e:
        fallback = f"{persist_dir}.broken"
        try:
            if os.path.exists(fallback):
                shutil.rmtree(fallback, ignore_errors=True)
            os.rename(persist_dir, fallback)
            logger.warning(f"[RAG] Could not delete ({e}) — moved aside to {fallback}")
        except Exception as e2:
            logger.error(
                f"[RAG] Could not clear {persist_dir} ({e2}). "
                "Delete it by hand and re-run."
            )


# ══════════════════════════════════════════════════════════════
# SECTION 3 — BM25 Retriever (Sparse Retrieval)
# ══════════════════════════════════════════════════════════════

def build_bm25_retriever(documents: List[Document]) -> BM25Retriever:
    """
    Build a BM25 (Best Matching 25) sparse keyword retriever.

    BM25 is the gold standard for keyword-based retrieval.  It
    ranks documents by term frequency (TF) weighted by inverse
    document frequency (IDF), with length normalisation.

    Why keep it alongside dense?
    -----------------------------
    Dense models can miss exact destination names, hotel names,
    or technical travel terms.  BM25 excels at these exact matches.
    """
    retriever = BM25Retriever.from_documents(
        documents,
        k=rag_config.top_k,
    )
    logger.info("[RAG] BM25 retriever built")
    return retriever


# ══════════════════════════════════════════════════════════════
# SECTION 4 — Reciprocal Rank Fusion (Hybrid Merge)
# ══════════════════════════════════════════════════════════════

def reciprocal_rank_fusion(
    dense_results: List[Document],
    sparse_results: List[Document],
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
    k: int = 60,  # RRF smoothing constant
) -> List[Document]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.

    Formula:
        RRF_score(doc) = dense_weight * 1/(rank_dense + k)
                       + sparse_weight * 1/(rank_sparse + k)

    Documents not present in a list get rank = len(list) + 1
    (i.e., penalised for absence).

    The k constant (default 60) dampens the influence of
    very high ranks, making the fusion more robust.

    Returns documents sorted by descending RRF score.
    """
    scores: dict = {}

    # Score dense results
    for rank, doc in enumerate(dense_results, start=1):
        key = doc.page_content[:100]  # Use content prefix as dedup key
        scores[key] = scores.get(key, {"doc": doc, "score": 0})
        scores[key]["score"] += dense_weight * (1.0 / (rank + k))

    # Score sparse results
    for rank, doc in enumerate(sparse_results, start=1):
        key = doc.page_content[:100]
        scores[key] = scores.get(key, {"doc": doc, "score": 0})
        scores[key]["score"] += sparse_weight * (1.0 / (rank + k))

    # Sort by score descending and extract documents
    sorted_docs = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return [item["doc"] for item in sorted_docs]


# ══════════════════════════════════════════════════════════════
# SECTION 4b — Cross-Encoder Reranking
# ══════════════════════════════════════════════════════════════
# RRF only knows rank positions — it never compares the query against the
# passage text. On a small corpus that means the top-5 is always returned,
# however unrelated, so a Dubai query gets confidently answered with Bali
# facts. A cross encoder reads (query, passage) jointly and produces a
# calibrated relevance logit, which gives us a usable "nothing here is
# relevant" signal.

_reranker = None
_reranker_failed = False


def get_reranker():
    """
    Lazily load the cross-encoder. Returns None if reranking is disabled or
    the model cannot be loaded (offline, missing torch, etc.) — retrieval then
    degrades to plain RRF rather than breaking the pipeline.
    """
    global _reranker, _reranker_failed
    if not rag_config.rerank_enabled or _reranker_failed:
        return None
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            logger.info(f"[RAG] Loading reranker: {rag_config.rerank_model}")
            _reranker = CrossEncoder(rag_config.rerank_model, max_length=512)
            logger.info("[RAG] Reranker ready")
        except Exception as e:
            _reranker_failed = True
            logger.warning(
                f"[RAG] Reranker unavailable ({e}) — falling back to RRF order. "
                "Relevance gating will be disabled."
            )
            return None
    return _reranker


def rerank(query: str, documents: List[Document]) -> List[tuple]:
    """
    Score each document against the query with the cross encoder.

    Returns
    -------
    List of (Document, score) sorted by descending score. When the reranker
    is unavailable the original order is preserved with score None, so callers
    must treat a None score as "unknown relevance", not "irrelevant".
    """
    if not documents:
        return []

    model = get_reranker()
    if model is None:
        return [(d, None) for d in documents]

    try:
        pairs = [(query, d.page_content) for d in documents]
        scores = model.predict(pairs)
        ranked = sorted(
            zip(documents, (float(s) for s in scores)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked
    except Exception as e:
        logger.warning(f"[RAG] Rerank failed ({e}) — keeping fusion order")
        return [(d, None) for d in documents]


class RetrievalResult:
    """
    Outcome of one retrieval, carrying the honesty signal alongside the text.

    grounded : True only when at least one passage cleared the relevance floor.
               When False, `context` explicitly tells the agent the knowledge
               base has nothing on this destination, instead of handing it
               unrelated passages that read as authoritative.
    """

    def __init__(
        self,
        context: str,
        grounded: bool,
        scores: Optional[List[float]] = None,
        n_considered: int = 0,
    ) -> None:
        self.context = context
        self.grounded = grounded
        self.scores = scores or []
        self.n_considered = n_considered

    @property
    def top_score(self) -> Optional[float]:
        return max(self.scores) if self.scores else None

    def __str__(self) -> str:  # so existing str(...) call sites keep working
        return self.context

    def __repr__(self) -> str:
        return (
            f"RetrievalResult(grounded={self.grounded}, "
            f"kept={len(self.scores)}/{self.n_considered}, "
            f"top_score={self.top_score})"
        )


# Text handed to an agent when the knowledge base has nothing relevant. Being
# explicit matters: the model reliably falls back on its own knowledge, whereas
# unrelated context actively pulls the answer toward the wrong destination.
NO_CONTEXT_NOTICE = (
    "No destination-specific knowledge was found in the travel knowledge base "
    "for this query. Do NOT use facts about other destinations. Rely on your "
    "own general knowledge of this destination, and keep claims general where "
    "you are uncertain."
)


# ══════════════════════════════════════════════════════════════
# SECTION 5 — HybridRetriever (Main Entry Point)
# ══════════════════════════════════════════════════════════════

class HybridRetriever:
    """
    Unified interface for hybrid dense + sparse retrieval.

    Usage:
    ------
        retriever = HybridRetriever(pdf_path="data/travel_data.pdf")
        context = retriever.retrieve("best time to visit Kyoto")
    """

    def __init__(self, pdf_path: Optional[str] = None) -> None:
        """
        Initialise the retriever with documents from PDF or synthetic data.

        Parameters
        ----------
        pdf_path : Path to a PDF knowledge base.  Defaults to
                   ./data/travel_data.pdf relative to project root.
        """
        if pdf_path is None:
            project_root = os.path.dirname(os.path.dirname(__file__))
            pdf_path = os.path.join(project_root, "data", "travel_data.pdf")

        # Source priority: an ingested Wikivoyage corpus, then a PDF, then the
        # small hand-written fallback.
        #
        # Loading the *persisted* corpus matters for correctness, not just
        # convenience: BM25 is built in-process from `self.documents` while
        # Chroma reads its own on-disk index. If those two come from different
        # sources they drift apart, and the hybrid silently fuses two rankings
        # over different corpora. Reading both from corpus.jsonl keeps them
        # in step.
        self.documents = self._load_documents(pdf_path)

        # Build both retrievers
        self.vector_store = build_vector_store(self.documents)
        self.bm25 = build_bm25_retriever(self.documents)

        # Build the dense retriever from the vector store.
        #
        # Deliberately plain `similarity` with a wide k, NOT
        # `similarity_score_threshold`. Relevance is now decided downstream by
        # the cross encoder, which reads the query and passage together and is
        # far better at it than a cosine cutoff. Pre-filtering here only threw
        # away candidates before they could be scored properly — with the old
        # 0.3 threshold, whole queries returned zero dense hits and the hybrid
        # quietly became BM25-only.
        self.dense_retriever = self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": rag_config.rerank_candidates},
        )

        self._top_k = rag_config.top_k
        logger.info(
            f"[RAG] HybridRetriever ready | docs={len(self.documents)} "
            f"top_k={self._top_k}"
        )

    @staticmethod
    def _load_documents(pdf_path: str) -> List[Document]:
        """Prefer the ingested corpus; fall back to PDF, then synthetic."""
        try:
            from rag.ingest import load_corpus, corpus_path
            corpus = load_corpus()
            if corpus:
                covered = len({
                    d.metadata.get("destination") for d in corpus
                    if d.metadata.get("destination") != GENERAL_KNOWLEDGE
                })
                logger.info(
                    f"[RAG] Loaded ingested corpus | {len(corpus)} chunks, "
                    f"{covered} destinations ({corpus_path()})"
                )
                return corpus
        except Exception as e:
            logger.warning(f"[RAG] Could not load ingested corpus ({e})")

        logger.info(
            "[RAG] No ingested corpus found — falling back. "
            "Build one with: python -m rag.ingest"
        )
        return load_and_chunk_documents(pdf_path)

    def retrieve(self, query: str, destination: Optional[str] = None) -> RetrievalResult:
        """
        Run hybrid retrieval for a query and return context plus a grounding flag.

        Flow:
        1. Dense retrieval (embedding similarity)
        2. Sparse retrieval (BM25 keyword)
        3. Reciprocal Rank Fusion merge
        4. Cross-encoder rerank of the fused candidates
        5. Drop anything below the relevance floor
        6. Format the survivors, or return an explicit "nothing relevant" notice

        Step 5 is the important one. Without it the retriever always returns
        its top_k, so an out-of-corpus destination silently receives another
        city's facts. Returning nothing is strictly better than returning
        something wrong.

        Parameters
        ----------
        query       : The search query (e.g., "best hotels in Bali under $100")
        destination : When given, chunks tagged with a *different* destination
                      are removed before scoring, and `grounded` reports
                      whether any destination-specific knowledge survived.

        Returns
        -------
        RetrievalResult — stringifies to the context, but also carries
        `.grounded` and the per-passage relevance scores.
        """
        logger.info(f"[RAG] Retrieving: '{query}'")

        try:
            # Dense retrieval
            dense_docs = self.dense_retriever.invoke(query)
        except Exception as e:
            logger.warning(f"[RAG] Dense retrieval failed ({e}), using empty list")
            dense_docs = []

        try:
            # Sparse retrieval
            sparse_docs = self.bm25.invoke(query)
        except Exception as e:
            logger.warning(f"[RAG] Sparse retrieval failed ({e}), using empty list")
            sparse_docs = []

        # Merge with RRF
        merged = reciprocal_rank_fusion(
            dense_docs,
            sparse_docs,
            dense_weight=rag_config.dense_weight,
            sparse_weight=rag_config.bm25_weight,
        )

        if not merged:
            logger.warning("[RAG] No documents retrieved — returning empty context")
            return RetrievalResult(NO_CONTEXT_NOTICE, grounded=False)

        # Drop other destinations' facts BEFORE scoring. A passage about the
        # wrong city can be perfectly relevant to the question and still be
        # the single worst thing to put in front of the model.
        if destination:
            merged = filter_by_destination(merged, destination)
            if not merged:
                logger.warning(
                    f"[RAG] NOT GROUNDED — knowledge base has nothing about "
                    f"'{destination}'"
                )
                return RetrievalResult(NO_CONTEXT_NOTICE, grounded=False)

        # Rerank the fused candidates, then gate on absolute relevance
        candidates = merged[: rag_config.rerank_candidates]
        ranked = rerank(query, candidates)

        floor = rag_config.rerank_min_score
        scored = [(d, s) for d, s in ranked if s is not None]

        if scored:
            kept = [(d, s) for d, s in scored if s >= floor][: self._top_k]
            if not kept:
                best = scored[0][1]
                logger.warning(
                    f"[RAG] NOT GROUNDED — no passage cleared the relevance floor "
                    f"({floor}); best score {best:.2f} over "
                    f"{len(scored)} candidates. Returning the no-context notice "
                    f"instead of unrelated passages."
                )
                return RetrievalResult(
                    NO_CONTEXT_NOTICE,
                    grounded=False,
                    scores=[best],
                    n_considered=len(scored),
                )
        else:
            # Reranker unavailable — fall back to fusion order, relevance unknown.
            kept = [(d, None) for d in candidates[: self._top_k]]

        # "Grounded" means we found knowledge about THIS destination. Generic
        # travel advice is worth passing along, but it is not grounding, and
        # counting it as such is how a plan ends up looking better sourced
        # than it actually is.
        def _is_specific(doc) -> bool:
            return doc.metadata.get("destination") not in (None, GENERAL_KNOWLEDGE)

        specific = [(d, s) for d, s in kept if _is_specific(d)]
        grounded = bool(specific)

        # Label each passage so the model knows what it is reading. Unlabelled
        # context invites it to treat generic budgeting advice as a fact about
        # the destination.
        context_lines = [
            f"[Context {i+1} — "
            f"{'about ' + doc.metadata['destination'] if _is_specific(doc) else 'general travel advice'}] "
            f"{doc.page_content}"
            for i, (doc, _) in enumerate(kept)
        ]
        if not grounded:
            context_lines.insert(0, f"[Note] {NO_CONTEXT_NOTICE}")

        context = "\n\n".join(context_lines)
        scores = [s for _, s in kept if s is not None]

        logger.info(
            f"[RAG] {'GROUNDED' if grounded else 'GENERIC-ONLY'} — kept "
            f"{len(kept)}/{len(ranked)} passages "
            f"({len(specific)} destination-specific)"
            + (f" | scores {[round(s, 2) for s in scores]}" if scores else " | rerank off")
        )
        return RetrievalResult(
            context,
            grounded=grounded,
            scores=scores,
            n_considered=len(ranked),
        )

    def add_documents(self, texts: List[str]) -> None:
        """
        Dynamically add new text chunks to the vector store.
        Useful for injecting real-time tool results into the knowledge base.
        """
        new_docs = [
            Document(page_content=t, metadata={"source": "dynamic"})
            for t in texts
        ]
        self.vector_store.add_documents(new_docs)
        # Rebuild BM25 with extended document list
        self.documents.extend(new_docs)
        self.bm25 = build_bm25_retriever(self.documents)
        logger.info(f"[RAG] Added {len(new_docs)} documents dynamically")


# ── Module-level singleton (lazy-initialised on first access) ─
_retriever_instance: Optional[HybridRetriever] = None


def get_retriever() -> HybridRetriever:
    """
    Return the module-level singleton HybridRetriever.
    Initialises it on first call (lazy loading) to avoid startup delay.
    """
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = HybridRetriever()
    return _retriever_instance


__all__ = [
    "HybridRetriever",
    "get_embeddings",
    "OnnxMiniLMEmbeddings",
    "GENERAL_KNOWLEDGE",
    "filter_by_destination",
    "RetrievalResult",
    "NO_CONTEXT_NOTICE",
    "rerank",
    "get_reranker",
    "get_retriever",
    "load_and_chunk_documents",
    "build_vector_store",
    "build_bm25_retriever",
    "reciprocal_rank_fusion",
]