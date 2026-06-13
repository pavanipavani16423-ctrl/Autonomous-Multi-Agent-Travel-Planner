# ============================================================
# evaluation.py — Production RAGAS Evaluation
# Compatible with: ragas==0.4.x + langfuse==2.36.2
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# ── Import from YOUR langfuse_setup (not tracer.py) ──────────
from langfuse_setup import (
    LANGFUSE_ENABLED,
    langfuse_client,
    get_langfuse_handler,
)

logger = logging.getLogger(__name__)

# ── Feature Flags ─────────────────────────────────────────────
EVAL_ENABLED         = os.getenv("EVAL_ENABLED",         "true").lower()  == "true"
EVAL_LOG_TO_LANGFUSE = os.getenv("EVAL_LOG_TO_LANGFUSE", "true").lower()  == "true"

# ── Thresholds ────────────────────────────────────────────────
THRESH_FAITHFULNESS  = float(os.getenv("EVAL_THRESH_FAITHFULNESS",  "0.70"))
THRESH_PRECISION     = float(os.getenv("EVAL_THRESH_PRECISION",     "0.60"))
THRESH_RELEVANCY     = float(os.getenv("EVAL_THRESH_RELEVANCY",     "0.65"))
THRESH_HALLUCINATION = float(os.getenv("EVAL_THRESH_HALLUCINATION", "0.30"))


# ── Result Container ──────────────────────────────────────────
@dataclass
class EvaluationResult:
    """
    Structured RAGAS scores for one production query.
    None = metric could not be computed (never means 0.0).
    """
    trace_id:            str
    query:               str
    faithfulness:        Optional[float] = None
    answer_relevancy:    Optional[float] = None
    context_precision:   Optional[float] = None
    hallucination_score: Optional[float] = None  # derived: 1 - faithfulness
    latency_ms:          float           = 0.0
    error:               Optional[str]   = None
    alerts:              list            = field(default_factory=list)
    skipped:             bool            = False

    def to_dict(self) -> dict:
        return {
            "trace_id":            self.trace_id,
            "query":               self.query,
            "faithfulness":        self.faithfulness,
            "answer_relevancy":    self.answer_relevancy,
            "context_precision":   self.context_precision,
            "hallucination_score": self.hallucination_score,
            "latency_ms":          round(self.latency_ms, 2),
            "error":               self.error,
            "alerts":              self.alerts,
            "skipped":             self.skipped,
        }

    def has_alerts(self) -> bool:
        return bool(self.alerts)

    def overall_score(self) -> float:
        """Average of all available scores."""
        scores = [s for s in [
            self.faithfulness,
            self.answer_relevancy,
            self.context_precision,
        ] if s is not None]
        return round(sum(scores) / len(scores), 4) if scores else 0.0


# ── LLM / Embeddings builders ─────────────────────────────────
def _build_ragas_llm():
    """Wrap Groq LLM for RAGAS. Called lazily."""
    from ragas.llms import LangchainLLMWrapper
    from langchain_groq import ChatGroq
    return LangchainLLMWrapper(
        ChatGroq(
            api_key=os.getenv("GROQ_API_KEY", ""),
            model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            temperature=0,
        )
    )


def _build_ragas_embeddings():
    """Wrap local sentence-transformer for RAGAS."""
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_community.embeddings import SentenceTransformerEmbeddings
    return LangchainEmbeddingsWrapper(
        SentenceTransformerEmbeddings(
            model_name=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        )
    )


# ── Score Extractor for RAGAS 0.4.x ──────────────────────────
def _extract_scores(ragas_result) -> dict:
    """
    Extract averaged metric scores from RAGAS 0.4.x EvaluationResult.

    RAGAS 0.4.3 EvaluationResult has:
      ._repr_dict  → Dict[str, float]  averaged scores  ← primary
      .scores      → List[Dict]        per-row scores   ← fallback 1
      .to_pandas() → DataFrame                          ← fallback 2
    """
    import math

    # Primary: _repr_dict
    if hasattr(ragas_result, "_repr_dict") and ragas_result._repr_dict:
        scores = {}
        for k, v in ragas_result._repr_dict.items():
            if v is not None:
                try:
                    f = float(v)
                    if not math.isnan(f):
                        scores[k] = f
                except (TypeError, ValueError):
                    pass
        if scores:
            logger.debug(f"[EVAL] Scores via _repr_dict: {scores}")
            return scores

    # Fallback 1: scores[0]
    if hasattr(ragas_result, "scores") and ragas_result.scores:
        row = ragas_result.scores[0]
        if isinstance(row, dict):
            scores = {}
            for k, v in row.items():
                if v is not None:
                    try:
                        f = float(v)
                        if not math.isnan(f):
                            scores[k] = f
                    except (TypeError, ValueError):
                        pass
            if scores:
                logger.debug(f"[EVAL] Scores via scores[0]: {scores}")
                return scores

    # Fallback 2: pandas
    if hasattr(ragas_result, "to_pandas"):
        try:
            df = ragas_result.to_pandas()
            scores = {}
            for col in df.columns:
                try:
                    f = float(df[col].iloc[0])
                    if not math.isnan(f):
                        scores[col] = f
                except (TypeError, ValueError):
                    pass
            if scores:
                logger.debug(f"[EVAL] Scores via to_pandas: {scores}")
                return scores
        except Exception as e:
            logger.debug(f"[EVAL] to_pandas failed: {e}")

    raise ValueError(f"Cannot extract scores from RAGAS result: {type(ragas_result)}")


# ── Core RAGAS Call ───────────────────────────────────────────
def _run_ragas_sync(question: str, answer: str, contexts: list) -> dict:
    """
    Run RAGAS 0.4.x with 3 reference-free metrics.

    RAGAS 0.4.3 API:
      - Columns: user_input, response, retrieved_contexts
      - Pass llm= and embeddings= to evaluate() directly
      - allow_nest_asyncio=False in production threads
    """
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        Faithfulness,
        ResponseRelevancy,
        LLMContextPrecisionWithoutReference,
    )

    ragas_llm        = _build_ragas_llm()
    ragas_embeddings = _build_ragas_embeddings()

    dataset = Dataset.from_dict({
        "user_input":         [question],
        "response":           [answer],
        "retrieved_contexts": [contexts],
    })

    logger.info(f"[EVAL] Running RAGAS evaluation...")

    ragas_result = evaluate(
        dataset=dataset,
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            LLMContextPrecisionWithoutReference(),
        ],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
        raise_exceptions=False,
        show_progress=True,
        allow_nest_asyncio=False,
    )

    logger.info(f"[EVAL] Raw result: {ragas_result}")
    return _extract_scores(ragas_result)


# ── Threshold Monitor ─────────────────────────────────────────
def _check_thresholds(result: EvaluationResult) -> None:
    """Fire alerts for out-of-threshold scores."""
    if result.faithfulness is not None and result.faithfulness < THRESH_FAITHFULNESS:
        msg = f"⚠️ Low faithfulness ({result.faithfulness:.0%}) — answer not grounded in context"
        logger.warning(f"[EVAL][ALERT] {msg} | trace={result.trace_id}")
        result.alerts.append(msg)

    if result.hallucination_score is not None and result.hallucination_score > THRESH_HALLUCINATION:
        msg = f"🚨 High hallucination risk ({result.hallucination_score:.0%})"
        logger.warning(f"[EVAL][ALERT] {msg} | trace={result.trace_id}")
        result.alerts.append(msg)

    if result.context_precision is not None and result.context_precision < THRESH_PRECISION:
        msg = f"⚠️ Low context precision ({result.context_precision:.0%}) — noisy retrieval"
        logger.warning(f"[EVAL][ALERT] {msg} | trace={result.trace_id}")
        result.alerts.append(msg)

    if result.answer_relevancy is not None and result.answer_relevancy < THRESH_RELEVANCY:
        msg = f"⚠️ Low answer relevancy ({result.answer_relevancy:.0%}) — off-topic answer"
        logger.warning(f"[EVAL][ALERT] {msg} | trace={result.trace_id}")
        result.alerts.append(msg)


# ── Langfuse Score Logger ─────────────────────────────────────
def _log_scores_to_langfuse(result: EvaluationResult) -> None:
    """Post each RAGAS score as a named score on the Langfuse trace."""
    if not EVAL_LOG_TO_LANGFUSE:
        return
    if not LANGFUSE_ENABLED or not langfuse_client:
        logger.debug("[EVAL] Langfuse disabled — skipping score logging")
        return
    if not result.trace_id:
        logger.debug("[EVAL] No trace_id — skipping score logging")
        return

    score_map = {
        "ragas_faithfulness":      result.faithfulness,
        "ragas_answer_relevancy":  result.answer_relevancy,
        "ragas_context_precision": result.context_precision,
        "ragas_hallucination":     result.hallucination_score,
        "ragas_overall":           result.overall_score(),
    }

    for name, value in score_map.items():
        if value is not None:
            try:
                langfuse_client.score(
                    trace_id=result.trace_id,
                    name=name,
                    value=round(value, 4),
                    comment=f"RAGAS auto-eval | latency={result.latency_ms:.0f}ms",
                )
                logger.debug(f"[EVAL] Logged to Langfuse: {name}={value:.4f}")
            except Exception as e:
                logger.warning(f"[EVAL] Failed to log {name} to Langfuse: {e}")

    # Log alert count as a score
    if result.alerts:
        try:
            langfuse_client.score(
                trace_id=result.trace_id,
                name="ragas_alert_count",
                value=float(len(result.alerts)),
                comment=" | ".join(result.alerts),
            )
        except Exception as e:
            logger.warning(f"[EVAL] Failed to log alert count: {e}")

    logger.info(f"[EVAL] ✅ Scores logged to Langfuse | trace_id={result.trace_id}")


# ── EvaluationService ─────────────────────────────────────────
class EvaluationService:
    """
    Production-safe RAGAS evaluation service.
    Reference-free metrics only — no ground truth needed.

    Usage in Streamlit:
        svc = get_eval_service()
        svc.evaluate_fire_and_forget(trace_id, query, answer, contexts)
    """

    def __init__(self):
        if not EVAL_ENABLED:
            logger.info("[EVAL] Disabled via EVAL_ENABLED=false")

    def evaluate(
        self,
        trace_id: str,
        query:    str,
        answer:   str,
        contexts: list,
    ) -> EvaluationResult:
        """
        Run RAGAS synchronously. Never raises — always returns EvaluationResult.
        Logs scores to Langfuse automatically.
        """
        if not EVAL_ENABLED:
            return EvaluationResult(trace_id=trace_id, query=query, skipped=True)

        # Normalise answer
        if isinstance(answer, list):
            answer = " ".join(
                item.get("highlight", "") if isinstance(item, dict) else str(item)
                for item in answer
            )
        answer = str(answer).strip()

        if not answer or not contexts:
            logger.warning("[EVAL] Skipping — empty answer or no contexts")
            return EvaluationResult(
                trace_id=trace_id, query=query,
                skipped=True, error="Empty answer or context"
            )

        t0     = time.perf_counter()
        result = EvaluationResult(trace_id=trace_id, query=query)

        try:
            scores = _run_ragas_sync(
                question=query,
                answer=answer,
                contexts=contexts,
            )

            # Map RAGAS 0.4.3 keys → result fields
            result.faithfulness = scores.get("faithfulness")

            result.answer_relevancy = (
                scores.get("answer_relevancy")
                or scores.get("response_relevancy")
            )
            result.context_precision = (
                scores.get("llm_context_precision_without_reference")
                or scores.get("context_precision")
            )

            # Derive hallucination
            if result.faithfulness is not None:
                result.hallucination_score = round(1.0 - result.faithfulness, 4)

        except Exception as e:
            result.error = str(e)
            logger.error(f"[EVAL] RAGAS failed | trace_id={trace_id}: {e}", exc_info=True)

        finally:
            result.latency_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                f"[EVAL] Done {result.latency_ms:.0f}ms | "
                f"faithfulness={result.faithfulness} | "
                f"relevancy={result.answer_relevancy} | "
                f"precision={result.context_precision} | "
                f"hallucination={result.hallucination_score}"
            )

        _check_thresholds(result)

        try:
            _log_scores_to_langfuse(result)
        except Exception as e:
            logger.warning(f"[EVAL] Langfuse logging failed (non-critical): {e}")

        return result

    async def evaluate_async(
        self,
        trace_id: str,
        query:    str,
        answer:   str,
        contexts: list,
    ) -> EvaluationResult:
        """Async wrapper — RAGAS runs in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.evaluate(
                trace_id=trace_id,
                query=query,
                answer=answer,
                contexts=contexts,
            )
        )

    def evaluate_fire_and_forget(
        self,
        trace_id: str,
        query:    str,
        answer:   str,
        contexts: list,
    ) -> None:
        """
        Launch evaluation in background daemon thread.
        Returns immediately — scores appear in Langfuse ~10-20s later.
        USE THIS IN STREAMLIT.
        """
        def _run():
            try:
                self.evaluate(
                    trace_id=trace_id,
                    query=query,
                    answer=answer,
                    contexts=contexts,
                )
            except Exception as e:
                logger.error(f"[EVAL] Background thread error: {e}", exc_info=True)

        t = threading.Thread(
            target=_run,
            daemon=True,
            name=f"ragas-eval-{trace_id[:8]}"
        )
        t.start()
        logger.info(f"[EVAL] Background thread started | trace_id={trace_id}")


# ── Singleton ─────────────────────────────────────────────────
_eval_service: Optional[EvaluationService] = None


def get_eval_service() -> EvaluationService:
    global _eval_service
    if _eval_service is None:
        _eval_service = EvaluationService()
    return _eval_service


__all__ = [
    "EvaluationResult",
    "EvaluationService",
    "get_eval_service",
]