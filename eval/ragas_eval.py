# ============================================================
# eval/ragas_eval.py — RAGAS scoring over real pipeline output
# ============================================================
# WHAT WAS HERE BEFORE:
#   Three separate attempts, none of which ever produced a score.
#     • evaluation.py — a complete EvaluationService that nothing imports.
#     • langfuse_setup.py — a helper reading `route.summary` and
#       `food.must_try_dishes`, neither of which is a field on those models,
#       so it raised AttributeError before reaching RAGAS.
#     • the old Streamlit tab — five hardcoded questions about Paris and
#       Tokyo, with a fallback that printed canned scores (0.87/0.82/0.79)
#       on any exception. That is what "RAG Eval" was showing.
#
# WHAT THIS DOES INSTEAD:
#   Scores the retrieval that actually happened: the three questions
#   RetrievalAgent asked, the passages it got back, and what the agents wrote
#   from them. Nothing hardcoded, and no fallback to invented numbers — if it
#   cannot run, it says so and returns nothing.
#
# WHY IT IS NOT RUN ON EVERY PLAN:
#   RAGAS is an LLM judge. Scoring one plan costs several more model calls on
#   top of the seven a plan already makes, against a 200k-tokens-per-day free
#   tier. A judge belongs in an eval pass you run deliberately, not in the
#   request path of every user.
#
# USAGE:
#   python -m eval.harness --ragas
# ============================================================

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from loguru import logger


def _judge():
    """LLM + embeddings for the metrics. Same Groq model; embeddings local."""
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from models.models import get_llm
    from config import rag_config

    llm = LangchainLLMWrapper(get_llm(temperature=0))
    emb = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name=rag_config.embedding_model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    )
    return llm, emb


def _samples(state: dict) -> List[Dict[str, Any]]:
    """
    Build (question, answer, contexts) triples from one finished run.

    Pairs each retrieval question with the section it fed, using the real
    field names — the previous helper guessed at `route.summary` and
    `food.must_try_dishes`, and neither exists.
    """
    request = state.get("request")
    contexts = state.get("rag_contexts") or {}
    if not request:
        return []

    dest = request.destination
    route, hotels, food = state.get("route"), state.get("hotels"), state.get("food")

    def answer_route() -> str:
        if not route:
            return ""
        days = "; ".join(
            f"Day {d.day}: {', '.join(d.activities[:3])}"
            for d in route.day_wise_itinerary[:4]
        )
        return f"{route.best_route_summary} {days}".strip()

    def answer_hotels() -> str:
        if not hotels:
            return ""
        picks = "; ".join(
            f"{h.name} (${h.price_per_night_usd:.0f}/night, {h.location_description})"
            for h in (hotels.budget_hotels + hotels.premium_hotels)[:3]
        )
        return f"Stay around {hotels.recommended_area}. {picks}".strip()

    def answer_food() -> str:
        if not food:
            return ""
        dishes = ", ".join(food.local_specialties[:5])
        places = ", ".join(r.name for r in food.restaurant_suggestions[:3])
        return f"Local specialities: {dishes}. Try: {places}".strip()

    plan = [
        (f"What should a traveller know about visiting {dest}?",
         answer_route(), contexts.get("general_context", "")),
        (f"Where should I stay in {dest} and what do hotels cost?",
         answer_hotels(), contexts.get("hotel_context", "")),
        (f"What food and restaurants is {dest} known for?",
         answer_food(), contexts.get("food_context", "")),
    ]

    samples = []
    for question, answer, context in plan:
        # Skip anything with no answer or no retrieved passage — scoring an
        # empty section measures the rate limit, not the retrieval.
        if not answer or not context:
            continue
        passages = [c.strip() for c in context.split("\n\n") if c.strip()]
        if not passages:
            continue
        samples.append({
            "user_input": question,
            "response": answer,
            "retrieved_contexts": passages,
        })
    return samples


def evaluate_run(state: dict) -> Optional[Dict[str, float]]:
    """
    Score one finished run's retrieval.

    Returns {faithfulness, answer_relevancy} or None when it could not run.
    Never returns placeholder numbers — a score that isn't measured is worse
    than no score, because it looks like evidence.
    """
    try:
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import Faithfulness, ResponseRelevancy
    except ImportError:
        logger.warning("[RAGAS] Not installed — run: pip install ragas")
        return None

    samples = _samples(state)
    if not samples:
        if state.get("from_cache"):
            # A cached plan stores the itinerary, not the passages behind it.
            # Scoring retrieval needs the retrieved text, so this has to be a
            # fresh run — the harness passes use_cache=False for --ragas.
            logger.warning(
                "[RAGAS] This plan came from the cache, which does not keep "
                "the retrieved passages. Re-run with use_cache=False to score it."
            )
        else:
            logger.warning(
                "[RAGAS] Nothing to score: no section had both retrieved "
                "context and an answer (the LLM calls may have been rate-limited)."
            )
        return None

    grounded = (state.get("rag_contexts") or {}).get("grounded") or {}
    if grounded and not any(grounded.values()):
        logger.info(
            "[RAGAS] Retrieval was ungrounded for this destination — "
            "faithfulness will measure the model's own knowledge, not the corpus."
        )

    try:
        llm, emb = _judge()
        result = evaluate(
            dataset=EvaluationDataset.from_list(samples),
            metrics=[Faithfulness(), ResponseRelevancy()],
            llm=llm,
            embeddings=emb,
            raise_exceptions=False,
            show_progress=False,
        )
        df = result.to_pandas()
        scores: Dict[str, float] = {}
        for column, name in (("faithfulness", "faithfulness"),
                             ("answer_relevancy", "answer_relevancy"),
                             ("response_relevancy", "answer_relevancy")):
            if column in df.columns:
                value = df[column].dropna()
                if len(value):
                    scores[name] = round(float(value.mean()), 4)
        if not scores:
            logger.warning("[RAGAS] Ran, but every metric came back empty")
            return None
        scores["samples"] = len(samples)
        return scores
    except Exception as e:
        logger.error(f"[RAGAS] Evaluation failed: {e}")
        return None


__all__ = ["evaluate_run"]
