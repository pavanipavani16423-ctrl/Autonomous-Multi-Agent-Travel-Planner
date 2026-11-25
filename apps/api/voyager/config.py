"""Env-driven settings.

Everything degrades gracefully: no Groq key -> the deterministic planner answers (and says so),
no Langfuse keys -> tracing is a no-op, no QDRANT_URL -> embedded Qdrant on disk.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[1]


def _find_data_dir() -> Path:
    """The repo's `data/` (holds corpus.jsonl). Walk up so the same code works in the monorepo
    (apps/api/../../data) and in the Docker image (/app/data)."""
    env = os.environ.get("VOYAGER_DATA_DIR")
    if env:
        return Path(env).resolve()
    for parent in [API_DIR, *API_DIR.parents]:
        if (parent / "data" / "corpus.jsonl").exists():
            return parent / "data"
    return API_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(API_DIR / ".env"),), env_file_encoding="utf-8", extra="ignore",
        populate_by_name=True,
    )

    # --- runtime ---------------------------------------------------------------------------
    offline: bool = Field(False, validation_alias=AliasChoices("VOYAGER_OFFLINE"))
    port: int = Field(8000, validation_alias=AliasChoices("PORT"))
    public_base_url: str = Field("", validation_alias=AliasChoices("PUBLIC_BASE_URL"))
    web_origin: str = Field("http://localhost:3000", validation_alias=AliasChoices("WEB_ORIGIN"))
    log_level: str = Field("INFO", validation_alias=AliasChoices("VOYAGER_LOG_LEVEL"))

    # --- LLM (Groq) ------------------------------------------------------------------------
    groq_api_key: str = Field("", validation_alias=AliasChoices("GROQ_API_KEY"))
    model_large: str = Field("openai/gpt-oss-120b", validation_alias=AliasChoices("VOYAGER_MODEL_LARGE"))
    model_small: str = Field("openai/gpt-oss-20b", validation_alias=AliasChoices("VOYAGER_MODEL_SMALL"))
    model_backup: str = Field("qwen/qwen3.8-27b", validation_alias=AliasChoices("VOYAGER_MODEL_BACKUP"))
    llm_timeout_s: float = Field(60.0, validation_alias=AliasChoices("VOYAGER_LLM_TIMEOUT"))
    llm_max_retries: int = Field(3, validation_alias=AliasChoices("VOYAGER_LLM_MAX_RETRIES"))
    llm_reasoning_effort: str = Field("low", validation_alias=AliasChoices("VOYAGER_REASONING_EFFORT"))

    # --- Langfuse --------------------------------------------------------------------------
    langfuse_public_key: str = Field("", validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY"))
    langfuse_secret_key: str = Field("", validation_alias=AliasChoices("LANGFUSE_SECRET_KEY"))
    langfuse_host: str = Field(
        "https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST", "LANGFUSE_HOST_URL"),
    )
    langfuse_environment: str = Field("development", validation_alias=AliasChoices("LANGFUSE_ENVIRONMENT"))

    # --- Qdrant / RAG ----------------------------------------------------------------------
    qdrant_url: str = Field("", validation_alias=AliasChoices("QDRANT_URL"))
    qdrant_api_key: str = Field("", validation_alias=AliasChoices("QDRANT_API_KEY"))
    collection: str = Field("guidebook", validation_alias=AliasChoices("QDRANT_COLLECTION"))
    dense_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_enabled: bool = Field(True, validation_alias=AliasChoices("VOYAGER_RERANK"))
    embed_threads: int | None = Field(None, validation_alias=AliasChoices("VOYAGER_EMBED_THREADS"))  # None = all cores
    min_city_passages: int = 15  # fewer than this and a city counts as "not covered"
    ingest_on_boot: bool = Field(True, validation_alias=AliasChoices("VOYAGER_INGEST_ON_BOOT"))

    # --- persistence -----------------------------------------------------------------------
    database_url: str = Field("", validation_alias=AliasChoices("DATABASE_URL"))
    plan_cache_ttl_s: int = Field(6 * 3600, validation_alias=AliasChoices("VOYAGER_PLAN_CACHE_TTL"))

    # --- tools (MCP) -----------------------------------------------------------------------
    mcp_transport: str = Field("inprocess", validation_alias=AliasChoices("MCP_TRANSPORT"))
    http_timeout_s: float = Field(15.0, validation_alias=AliasChoices("VOYAGER_HTTP_TIMEOUT"))
    # Wikimedia APIs reject agents without a URL; set this to your repo URL when you deploy
    user_agent: str = Field("Voyager-TravelPlanner/2.0 (+https://github.com/topics/ai-travel-planner; portfolio project)",
                            validation_alias=AliasChoices("VOYAGER_USER_AGENT"))

    # --- A2A -------------------------------------------------------------------------------
    a2a_budget_url: str = Field("", validation_alias=AliasChoices("A2A_BUDGET_URL"))
    a2a_timeout_s: float = Field(30.0, validation_alias=AliasChoices("A2A_TIMEOUT"))
    mount_a2a: bool = Field(True, validation_alias=AliasChoices("VOYAGER_MOUNT_A2A"))

    # --- limits ----------------------------------------------------------------------------
    rate_limit_write_per_min: int = Field(8, validation_alias=AliasChoices("RATE_LIMIT_WRITE_PER_MIN"))
    rate_limit_read_per_min: int = Field(240, validation_alias=AliasChoices("RATE_LIMIT_READ_PER_MIN"))
    max_trip_days: int = 14

    # ---------------------------------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        path = _find_data_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus.jsonl"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / ("qdrant-test" if self.offline else "qdrant")

    @property
    def models_dir(self) -> Path:
        return Path(os.environ.get("FASTEMBED_CACHE_PATH") or (self.data_dir / "models"))

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"):
                url = "postgresql+asyncpg://" + url[len("postgres://"):]
            elif url.startswith("postgresql://"):
                url = "postgresql+asyncpg://" + url[len("postgresql://"):]
            return url
        name = "voyager-test.db" if self.offline else "voyager.db"
        return f"sqlite+aiosqlite:///{(self.data_dir / name).as_posix()}"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / ("checkpoints-test.db" if self.offline else "checkpoints.db")

    @property
    def tool_cache_path(self) -> Path:
        return self.data_dir / ("tool-cache-test.db" if self.offline else "tool-cache.db")

    @property
    def base_url(self) -> str:
        return (self.public_base_url or f"http://127.0.0.1:{self.port}").rstrip("/")

    @property
    def budget_agent_url(self) -> str:
        return (self.a2a_budget_url or f"{self.base_url}/a2a/budget").rstrip("/")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key) and not self.offline

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key) and not self.offline


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
