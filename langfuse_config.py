# ============================================================
# langfuse_setup.py  —  Langfuse v3 Tracing Integration
# Docs: langfuse.com/integrations/frameworks/langchain
# ============================================================
#
# WHAT THIS FILE DOES:
#   1. Loads .env file
#   2. Initialises Langfuse singleton (v3 pattern)
#   3. Verifies credentials with auth_check()
#   4. Creates CallbackHandler for LangChain/LangGraph
#   5. Provides flush_langfuse() to send all events
#   6. Auto-flushes on app exit via atexit
#
# HOW TO USE IN app.py:
#   from langfuse_setup import (
#       LANGFUSE_ENABLED, langfuse_client,
#       get_langfuse_handler, flush_langfuse
#   )
# ============================================================

import os
import atexit
from typing import Optional, Any
from loguru import logger
from dotenv import load_dotenv

# ── STEP 1: Load .env FIRST before any os.getenv() ───────────
load_dotenv()

# ── Availability flags ────────────────────────────────────────
LANGFUSE_AVAILABLE = False
LANGFUSE_ENABLED   = False

# ── Module-level handles ──────────────────────────────────────
langfuse_client  = None   # get_client() result — use for flush/trace
langfuse_handler = None   # CallbackHandler()  — pass to chains/agents

# ── Try imports ───────────────────────────────────────────────
try:
    from langfuse_config import Langfuse, get_client       # v3 SDK
    from langfuse.langchain import CallbackHandler  # v3 correct import
    LANGFUSE_AVAILABLE = True
except ImportError:
    logger.warning(
        "[Langfuse] Package not installed. "
        "Run: pip install langfuse"
    )


def _init_langfuse() -> bool:
    """
    Official v3 initialisation pattern:
      Langfuse(...)  →  get_client()  →  auth_check()  →  CallbackHandler()
    """
    global langfuse_client, langfuse_handler, LANGFUSE_ENABLED

    if not LANGFUSE_AVAILABLE:
        return False

    pk   = os.getenv("LANGFUSE_PUBLIC_KEY",  "").strip()
    sk   = os.getenv("LANGFUSE_SECRET_KEY",  "").strip()
    host = os.getenv(
        "LANGFUSE_HOST",
        os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    ).strip()

    if not pk or not sk:
        logger.warning(
            "[Langfuse] Keys missing in .env — tracing disabled.\n"
            "  Add: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY"
        )
        return False

    try:
        # ── STEP 2: Register the Langfuse singleton ───────────
        Langfuse(
            public_key=pk,
            secret_key=sk,
            host=host,
        )

        # ── STEP 3: Retrieve the registered client ────────────
        langfuse_client = get_client()

        # ── STEP 4: Verify credentials ────────────────────────
        if not langfuse_client.auth_check():
            logger.error(
                "[Langfuse] auth_check() FAILED — "
                "verify your keys and host URL in .env"
            )
            return False

        # ── STEP 5: Create handler (reuses same singleton) ────
        langfuse_handler = CallbackHandler()

        LANGFUSE_ENABLED = True
        logger.info(
            f"[Langfuse] ✅ Connected | host={host}"
        )
        return True

    except Exception as e:
        logger.error(f"[Langfuse] Initialisation failed: {e}")
        return False


def get_langfuse_handler() -> Optional[Any]:
    """
    Returns the LangChain CallbackHandler.
    Usage:
        handler = get_langfuse_handler()
        callbacks = [handler] if handler else []
        chain.invoke(input, config={"callbacks": callbacks})
    """
    return langfuse_handler if LANGFUSE_ENABLED else None


def flush_langfuse():
    """
    Flushes all buffered Langfuse events.
    Call this after every pipeline run and before app shutdown.
    """
    if LANGFUSE_ENABLED and langfuse_client:
        try:
            langfuse_client.flush()
            logger.info("[Langfuse] flush() — all events sent.")
        except Exception as e:
            logger.error(f"[Langfuse] flush() failed: {e}")


# ── Auto-flush on clean exit (safety net) ────────────────────
atexit.register(flush_langfuse)

# ── Run init when this module is imported ────────────────────
_init_langfuse()

__all__ = [
    "LANGFUSE_ENABLED",
    "langfuse_client",
    "langfuse_handler",
    "get_langfuse_handler",
    "flush_langfuse",
]