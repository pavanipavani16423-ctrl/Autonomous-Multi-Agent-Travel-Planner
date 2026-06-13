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
    Holds every knob related to the Groq-hosted Llama model.

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
        default_factory=lambda: os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    )
    temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.3"))
    )
    max_tokens: int = field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096"))
    )
    timeout: int = 60
    max_retries: int = 3


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
    chunk_size: int = 512
    chunk_overlap: int = 64
    bm25_weight: float = 0.4   # 40 % sparse  (keyword exact-match)
    dense_weight: float = 0.6  # 60 % dense   (semantic similarity)


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