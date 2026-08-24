# ============================================================
# config.py — Central Configuration Hub
# ============================================================
# PURPOSE:
#   Single source of truth for every setting in the project.
#   Loads environment variables, defines constants, and exports
#   strongly-typed config objects consumed by all other modules.
#
# WHY:
#   Avoids magic strings/numbers scattered across files.
#   One place to tune behaviour (temperature, top-k, etc.)
#   without touching business logic.
# ============================================================

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from loguru import logger

# ── 1. Load .env file ────────────────────────────────────────
# load_dotenv() scans the filesystem for a .env file and
# injects each KEY=VALUE pair into os.environ so the rest
# of the application can read them with os.getenv().
load_dotenv()
logger.info("Environment variables loaded from .env")


# ── 2. LLM Configuration ────────────────────────────────────
@dataclass
class LLMConfig:
    """
    Holds every knob related to the Groq-hosted LLM.

    groq_api_key  : authenticates requests to Groq's inference API.
    model_name    : selects the exact model checkpoint.
    temperature   : 0 = deterministic, 1 = creative. 0.3 balances
                    coherence with mild creative variation.
    max_tokens    : hard cap on the response length.
    timeout       : seconds before we raise a TimeoutError.
    max_retries   : number of automatic retries on transient errors.
    """
    groq_api_key: str = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY", "")
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    )
    temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.3"))
    )
    max_tokens: int = field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096"))
    )
    timeout: int = 90
    # The free Groq tier allows 8,000 tokens per MINUTE while a single plan
    # needs ~20,000 across seven calls, so hitting 429 is routine rather than
    # exceptional. The Groq SDK honours the Retry-After header, so the fix is
    # simply to let it wait long enough instead of giving up after three tries
    # and silently dropping a section of the plan.
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "8"))
    )


# ── 3. RAG Configuration ────────────────────────────────────
@dataclass
class RAGConfig:
    """
    Controls the Hybrid RAG (dense + sparse) retrieval pipeline.

    persist_dir      : where ChromaDB stores its vector index on disk.
    embedding_model  : HuggingFace model used to encode text chunks.
    top_k            : number of candidate chunks returned per query.
    score_threshold  : cosine-similarity floor; chunks below this are dropped.
    chunk_size       : token/character window for document splitting.
    chunk_overlap    : overlap between consecutive chunks to preserve context.
    bm25_weight      : weight given to BM25 (sparse) vs dense retrieval.
    dense_weight     : weight given to dense (embedding) retrieval.
    """
    persist_dir: str = field(
        default_factory=lambda: os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )
    top_k: int = field(
        default_factory=lambda: int(os.getenv("RAG_TOP_K", "5"))
    )
    score_threshold: float = field(
        default_factory=lambda: float(os.getenv("RAG_SCORE_THRESHOLD", "0.3"))
    )
    # 512 chars is roughly 80 words — enough for a synthetic one-liner but it
    # cuts real guide prose mid-thought (a hotel's price separated from its
    # name). 900 keeps a coherent paragraph and still sits well inside the
    # reranker's 512-token window.
    chunk_size: int = 900
    chunk_overlap: int = 120
    bm25_weight: float = 0.4   # 40 % sparse  (keyword exact-match)
    dense_weight: float = 0.6  # 60 % dense   (semantic similarity)

    # ── Reranking / grounding ────────────────────────────────
    # RRF fuses two ranked lists but never re-reads the query against the
    # document, so it happily returns the least-bad of a bad corpus. A cross
    # encoder scores (query, passage) pairs directly, which is what lets us
    # tell "no relevant knowledge" apart from "here is the top-5 of whatever
    # we had" — the difference between a grounded answer and a confident
    # irrelevant one.
    rerank_enabled: bool = field(
        default_factory=lambda: os.getenv("RERANK_ENABLED", "true").lower() == "true"
    )
    rerank_model: str = field(
        default_factory=lambda: os.getenv(
            "RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
    )
    # Cross-encoder logit floor, calibrated against this corpus: destinations
    # the knowledge base covers score >= -4.8, destinations it does not score
    # <= -10.6. -8.0 sits in that gap with margin on both sides. Retune if the
    # corpus or the rerank model changes — measure, don't guess.
    rerank_min_score: float = field(
        default_factory=lambda: float(os.getenv("RERANK_MIN_SCORE", "-8.0"))
    )
    # How many fused candidates to hand the (slower) cross encoder.
    rerank_candidates: int = field(
        default_factory=lambda: int(os.getenv("RERANK_CANDIDATES", "12"))
    )


# ── 4. API Keys ──────────────────────────────────────────────
@dataclass
class APIConfig:
    """External third-party service credentials."""
    openweather_api_key: str = field(
        default_factory=lambda: os.getenv("OPENWEATHER_API_KEY", "")
    )
    google_maps_api_key: str = field(
        default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY", "")
    )
    amadeus_api_key: str = field(
        default_factory=lambda: os.getenv("AMADEUS_API_KEY", "")
    )
    amadeus_api_secret: str = field(
        default_factory=lambda: os.getenv("AMADEUS_API_SECRET", "")
    )


# ── 5. Guardrail Limits ──────────────────────────────────────
@dataclass
class GuardrailConfig:
    """
    Hard safety limits applied before and after agent execution.

    max_budget_usd   : ceiling on total trip budget to prevent nonsensical plans.
    min_trip_days    : at least 1 night required for a valid itinerary.
    max_trip_days    : cap to avoid impractically long plans.
    banned_keywords  : list of terms that trigger an immediate refusal.
    confidence_floor : minimum agent confidence score to accept a plan.
    """
    max_budget_usd: float = field(
        default_factory=lambda: float(os.getenv("MAX_BUDGET_USD", "100000"))
    )
    min_trip_days: int = field(
        default_factory=lambda: int(os.getenv("MIN_TRIP_DAYS", "1"))
    )
    max_trip_days: int = field(
        default_factory=lambda: int(os.getenv("MAX_TRIP_DAYS", "90"))
    )
    banned_keywords: list = field(
        default_factory=lambda: [
            "illegal", "smuggling", "weapons", "drugs",
            "terrorism", "hack", "exploit"
        ]
    )
    confidence_floor: float = 0.5


# ── 6. App Configuration ─────────────────────────────────────
@dataclass
class AppConfig:
    """Streamlit / web-server settings."""
    host: str = field(
        default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0")
    )
    port: int = field(
        default_factory=lambda: int(os.getenv("APP_PORT", "8501"))
    )
    debug: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "False").lower() == "true"
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    title: str = "✈️ Autonomous Multi-Agent Travel Planner"
    version: str = "1.0.0"


# ── 7. Instantiate singletons ────────────────────────────────
# Every module imports these objects directly; they are created
# once at import time (module-level singletons).
llm_config = LLMConfig()
rag_config = RAGConfig()
api_config = APIConfig()
guardrail_config = GuardrailConfig()
app_config = AppConfig()

# ── 8. Validate critical keys ────────────────────────────────
# Warn (not crash) if secrets are missing so the app can still
# run in demo / mock mode.
if not llm_config.groq_api_key:
    logger.warning(
        "GROQ_API_KEY is not set — LLM calls will fail. "
        "Add it to your .env file."
    )

logger.info(
    f"Config loaded | model={llm_config.model_name} | "
    f"rag_top_k={rag_config.top_k} | debug={app_config.debug}"
)