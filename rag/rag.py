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
from typing import List, Optional

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from loguru import logger

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import rag_config


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

    docs = [
        Document(
            page_content=text,
            metadata={"source": "synthetic_travel_knowledge", "chunk_id": i}
        )
        for i, text in enumerate(synthetic_texts)
    ]
    logger.info(f"[RAG] Created {len(docs)} synthetic knowledge documents")
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
    embeddings = HuggingFaceEmbeddings(
        model_name=rag_config.embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},  # L2 norm → cosine sim
    )

    persist_dir = rag_config.persist_dir

    # If a persisted store exists, load it; otherwise build from scratch
    if os.path.exists(persist_dir) and os.listdir(persist_dir):
        logger.info(f"[RAG] Loading existing ChromaDB from {persist_dir}")
        vector_store = Chroma(
            persist_directory=persist_dir,
            embedding_function=embeddings,
        )
    else:
        logger.info(f"[RAG] Building new ChromaDB vector store…")
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            persist_directory=persist_dir,
        )
        logger.info(f"[RAG] Vector store built and persisted at {persist_dir}")

    return vector_store


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

        # Load and chunk documents
        self.documents = load_and_chunk_documents(pdf_path)

        # Build both retrievers
        self.vector_store = build_vector_store(self.documents)
        self.bm25 = build_bm25_retriever(self.documents)

        # Build the dense retriever from the vector store
        self.dense_retriever = self.vector_store.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={
                "k": rag_config.top_k,
                "score_threshold": rag_config.score_threshold,
            },
        )

        self._top_k = rag_config.top_k
        logger.info(
            f"[RAG] HybridRetriever ready | docs={len(self.documents)} "
            f"top_k={self._top_k}"
        )

    def retrieve(self, query: str) -> str:
        """
        Run hybrid retrieval for a query and return formatted context string.

        Flow:
        1. Dense retrieval (embedding similarity)
        2. Sparse retrieval (BM25 keyword)
        3. Reciprocal Rank Fusion merge
        4. Trim to top_k results
        5. Format as numbered context string

        Parameters
        ----------
        query : The search query (e.g., "best hotels in Bali under $100")

        Returns
        -------
        Formatted multi-line string ready to inject into a prompt.
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

        # Take top-k
        top_docs = merged[: self._top_k]

        if not top_docs:
            logger.warning("[RAG] No documents retrieved — returning empty context")
            return "No relevant travel knowledge found for this query."

        # Format for prompt injection
        context_lines = [
            f"[Context {i+1}] {doc.page_content}"
            for i, doc in enumerate(top_docs)
        ]
        context = "\n\n".join(context_lines)
        logger.info(f"[RAG] Retrieved {len(top_docs)} context chunks")
        return context

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
    "get_retriever",
    "load_and_chunk_documents",
    "build_vector_store",
    "build_bm25_retriever",
    "reciprocal_rank_fusion",
]