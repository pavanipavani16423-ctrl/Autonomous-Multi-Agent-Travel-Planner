# ============================================================
# langfuse_setup.py — Fixed: Langfuse v2 + RAGAS Integration
# ============================================================
import os
import atexit
from typing import Optional, Any, Dict
from dotenv import load_dotenv

load_dotenv()

# ── Globals ──────────────────────────────────────────────────
LANGFUSE_ENABLED  = False
langfuse_client   = None
langfuse_handler  = None

# ── Try import ───────────────────────────────────────────────
try:
    from langfuse import Langfuse
    from langfuse.callback import CallbackHandler
    _LANGFUSE_PKG = True
except ImportError:
    _LANGFUSE_PKG = False
    print("[Langfuse] Not installed. Run: pip install langfuse==2.36.2")

def _init():
    global LANGFUSE_ENABLED, langfuse_client, langfuse_handler

    if not _LANGFUSE_PKG:
        return

    pk   = os.getenv("LANGFUSE_PUBLIC_KEY",  "").strip()
    sk   = os.getenv("LANGFUSE_SECRET_KEY",  "").strip()

    # FIX 1: Check ALL possible host key names in .env
    host = (
        os.getenv("LANGFUSE_HOST_URL") or
        os.getenv("LANGFUSE_BASE_URL") or
        os.getenv("LANGFUSE_HOST") or
        "https://us.cloud.langfuse.com"
    ).strip()

    if not pk or not sk:
        print("[Langfuse] Keys missing in .env — tracing disabled.")
        return

    try:
        langfuse_client = Langfuse(
            public_key=pk,
            secret_key=sk,
            host=host,
        )
        # FIX 2: Actually verify connection works
        auth_ok = langfuse_client.auth_check()
        if not auth_ok:
            print("[Langfuse] Auth check failed — check your keys.")
            return

        langfuse_handler = CallbackHandler(
            public_key=pk,
            secret_key=sk,
            host=host,
        )
        LANGFUSE_ENABLED = True
        print(f"[Langfuse] ✅ Connected  |  host={host}")
    except Exception as e:
        print(f"[Langfuse] Init failed: {e}")

_init()


# ── Simple Tracer ─────────────────────────────────────────────
class _SimpleTracer:

    def __init__(self):
        self._trace    = None
        self._trace_id = None

    class _TraceCtx:
        def __init__(self, tracer_ref, **kwargs):
            self._ref    = tracer_ref
            self._kwargs = kwargs

        def __enter__(self):
            if LANGFUSE_ENABLED and langfuse_client:
                try:
                    t = langfuse_client.trace(
                        name    = self._kwargs.get("name", "travel_plan"),
                        input   = self._kwargs.get("input_data", {}),
                        metadata= self._kwargs.get("metadata", {}),
                        tags    = self._kwargs.get("tags", []),
                    )
                    self._ref._trace    = t
                    self._ref._trace_id = t.id
                    return {"trace_id": t.id}
                except Exception as e:
                    print(f"[Langfuse] trace start failed: {e}")
            return {"trace_id": None}

        def __exit__(self, *args):
            flush_langfuse()

    def trace(self, name="", input_data=None, metadata=None, tags=None, **kwargs):
        return self._TraceCtx(
            self,
            name       = name,
            input_data = input_data or {},
            metadata   = metadata   or {},
            tags       = tags       or [],
        )

    def log_agent_span(self, agent_name: str, input_data: dict, output_data: dict):
        """Log each agent call as a span inside the trace."""
        if not LANGFUSE_ENABLED or not self._trace:
            return
        try:
            self._trace.span(
                name   = agent_name,
                input  = input_data,
                output = output_data,
            )
        except Exception as e:
            print(f"[Langfuse] agent span failed: {e}")

    def log_guardrail_span(self, name: str, passed: bool, reason: str = ""):
        if not LANGFUSE_ENABLED or not self._trace:
            return
        try:
            self._trace.span(
                name   = f"guardrail_{name}",
                input  = {"check": name},
                output = {"passed": passed, "reason": reason},
            )
        except Exception as e:
            print(f"[Langfuse] guardrail span failed: {e}")

    def set_output(self, output: dict):
        if not LANGFUSE_ENABLED or not self._trace:
            return
        try:
            self._trace.update(output=output)
        except Exception as e:
            print(f"[Langfuse] set_output failed: {e}")

    def score_plan(self, trace_id: Optional[str],
                   overall_confidence: float,
                   agent_scores: dict):
        if not LANGFUSE_ENABLED or not langfuse_client or not trace_id:
            return
        try:
            langfuse_client.score(
                trace_id = trace_id,
                name     = "overall_confidence",
                value    = overall_confidence,
            )
            for agent, score in agent_scores.items():
                langfuse_client.score(
                    trace_id = trace_id,
                    name     = f"{agent}_confidence",
                    value    = float(score),
                )
        except Exception as e:
            print(f"[Langfuse] score_plan failed: {e}")

    # ── FIX 3: RAGAS scores pushed to Langfuse properly ──────
    def score_ragas(self, trace_id: Optional[str], ragas_scores: Dict[str, float]):
        """
        Push RAGAS evaluation scores to Langfuse.
        Scores visible in Langfuse → Scores dashboard.

        Expected ragas_scores keys:
            answer_relevancy, faithfulness, context_recall,
            context_precision, answer_correctness
        """
        if not LANGFUSE_ENABLED or not langfuse_client or not trace_id:
            print("[RAGAS] Langfuse not enabled — scores not pushed.")
            return
        try:
            for metric, value in ragas_scores.items():
                langfuse_client.score(
                    trace_id = trace_id,
                    name     = f"ragas_{metric}",   # e.g. ragas_faithfulness
                    value    = float(value),
                    comment  = f"RAGAS evaluation: {metric}",
                )
            print(f"[RAGAS] ✅ Pushed {len(ragas_scores)} scores to Langfuse trace {trace_id[:8]}...")
            langfuse_client.flush()
        except Exception as e:
            print(f"[Langfuse] score_ragas failed: {e}")

    # Keep old method name for backward compatibility
    def score_rag(self, trace_id: Optional[str], scores: dict):
        return self.score_ragas(trace_id, scores)

    @property
    def trace_id(self):
        return self._trace_id


# ── Singleton ─────────────────────────────────────────────────
_tracer = _SimpleTracer()

def get_tracer() -> _SimpleTracer:
    return _tracer

def get_langfuse_handler():
    return langfuse_handler if LANGFUSE_ENABLED else None

def flush_langfuse():
    if LANGFUSE_ENABLED and langfuse_client:
        try:
            langfuse_client.flush()
        except Exception as e:
            print(f"[Langfuse] flush failed: {e}")

atexit.register(flush_langfuse)

__all__ = [
    "LANGFUSE_ENABLED",
    "langfuse_client",
    "langfuse_handler",
    "get_tracer",
    "get_langfuse_handler",
    "flush_langfuse",
]
# ============================================================
# ragas_eval.py — RAGAS Evaluation + Push to Langfuse
# ============================================================
# Run this AFTER generating a travel plan to evaluate RAG quality
# and push scores to Langfuse automatically.
# ============================================================

import os
from typing import List, Dict, Optional
from dotenv import load_dotenv
load_dotenv()

from langfuse_setup import get_tracer, LANGFUSE_ENABLED, langfuse_client

def run_ragas_evaluation(
    questions: List[str],
    answers: List[str],
    contexts: List[List[str]],
    ground_truths: List[str],
    trace_id: Optional[str] = None,
) -> Dict[str, float]:
    """
    Run RAGAS evaluation and push scores to Langfuse.

    Parameters
    ----------
    questions    : List of user questions asked
    answers      : List of answers generated by agents
    contexts     : List of context lists retrieved by RAG
    ground_truths: List of expected correct answers
    trace_id     : Langfuse trace ID to attach scores to

    Returns
    -------
    Dict of metric_name → score
    """
    try:
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            faithfulness,
            context_recall,
            context_precision,
            answer_correctness,
        )
        from datasets import Dataset
    except ImportError:
        print("[RAGAS] Not installed. Run: pip install ragas datasets")
        return {}

    print("[RAGAS] Running evaluation...")

    # Build HuggingFace Dataset
    data = {
        "question"    : questions,
        "answer"      : answers,
        "contexts"    : contexts,
        "ground_truth": ground_truths,
    }
    dataset = Dataset.from_dict(data)

    # Run RAGAS evaluation
    try:
        result = evaluate(
            dataset,
            metrics=[
                answer_relevancy,
                faithfulness,
                context_recall,
                context_precision,
                answer_correctness,
            ],
        )

        scores = {
            "answer_relevancy"  : float(result["answer_relevancy"]),
            "faithfulness"      : float(result["faithfulness"]),
            "context_recall"    : float(result["context_recall"]),
            "context_precision" : float(result["context_precision"]),
            "answer_correctness": float(result["answer_correctness"]),
        }

        print("[RAGAS] ✅ Scores:")
        for k, v in scores.items():
            print(f"  {k}: {v:.3f}")

        # Push to Langfuse
        tracer = get_tracer()
        if trace_id:
            tracer.score_ragas(trace_id, scores)
        elif tracer.trace_id:
            tracer.score_ragas(tracer.trace_id, scores)
        else:
            # Push directly via langfuse_client if no trace
            if LANGFUSE_ENABLED and langfuse_client:
                # Create a dedicated RAGAS trace
                t = langfuse_client.trace(
                    name="ragas_evaluation",
                    metadata={"questions_count": len(questions)},
                    tags=["ragas", "evaluation"],
                )
                tracer.score_ragas(t.id, scores)
                print(f"[RAGAS] Created dedicated trace: {t.id}")

        return scores

    except Exception as e:
        print(f"[RAGAS] Evaluation failed: {e}")
        return {}


def evaluate_travel_plan_rag(state: dict) -> Dict[str, float]:
    """
    Convenience function — evaluates RAG quality from a travel plan state.
    Call this in app.py after run_travel_pipeline() returns.

    Usage in app.py:
        state = run_travel_pipeline(request)
        ragas_scores = evaluate_travel_plan_rag(state)
    """
    request  = state.get("request")
    route    = state.get("route")
    weather  = state.get("weather")
    food     = state.get("food")
    tracer   = get_tracer()

    if not request:
        return {}

    dest = request.destination

    # Build evaluation data from agent outputs
    questions = [
        f"What is the best route to visit {dest}?",
        f"What is the weather like in {dest}?",
        f"What food should I eat in {dest}?",
    ]

    answers = [
        route.summary   if route   else f"Visit key attractions in {dest}",
        f"{weather.condition}, {weather.current_temp_celsius}°C"
                        if weather else f"Pleasant weather expected in {dest}",
        ", ".join(food.must_try_dishes[:3])
                        if food and hasattr(food, 'must_try_dishes')
                        else f"Local cuisine of {dest}",
    ]

    contexts = [
        [state.get("rag_contexts", {}).get("general_context", f"{dest} travel info")],
        [state.get("rag_contexts", {}).get("general_context", f"{dest} weather info")],
        [state.get("rag_contexts", {}).get("food_context",    f"{dest} food info")],
    ]

    ground_truths = [
        f"A well-planned itinerary covering major attractions in {dest}",
        f"Accurate weather information for {dest} during travel dates",
        f"Local food recommendations for {dest}",
    ]

    return run_ragas_evaluation(
        questions     = questions,
        answers       = answers,
        contexts      = contexts,
        ground_truths = ground_truths,
        trace_id      = tracer.trace_id,
    )






