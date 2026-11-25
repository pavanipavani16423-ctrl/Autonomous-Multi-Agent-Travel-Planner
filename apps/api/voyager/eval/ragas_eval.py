"""Ragas 0.4 (metric collections) wired to Groq and the local bge-small embedder.

The judge is `RAGAS_JUDGE_MODEL` (default qwen/qwen3.8-27b, which has its own free-tier quota so the
evaluation doesn't starve the planner), with gpt-oss-20b as a fallback. Calls are spaced with the same
token bucket the planner uses; every call is traced in Langfuse through the LangChain callback.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import InstructorBaseRagasLLM

from voyager.config import get_settings
from voyager.llm.gateway import _bucket, parse_json
from voyager.observability.tracing import get_tracer
from voyager.rag import embeddings as emb

T = TypeVar("T", bound=BaseModel)


def judge_models() -> list[str]:
    primary = os.environ.get("RAGAS_JUDGE_MODEL", "qwen/qwen3.8-27b")
    return list(dict.fromkeys([primary, get_settings().model_small]))


class GroqJudge(InstructorBaseRagasLLM):
    def __init__(self) -> None:
        from langchain_groq import ChatGroq

        s = get_settings()
        self.models = judge_models()
        self.chats = {}
        for m in self.models:
            extra: dict[str, Any] = {}
            if m.startswith("openai/gpt-oss"):
                extra["reasoning_effort"] = "low"
            elif m.startswith("qwen/"):
                extra["reasoning_effort"] = "none"  # no hidden thinking tokens against the TPM limit
            self.chats[m] = ChatGroq(model=m, api_key=s.groq_api_key, temperature=0, max_tokens=1800,
                                     timeout=90, max_retries=3,
                                     model_kwargs={"response_format": {"type": "json_object"}}, **extra)
        self.calls = 0
        self.tokens = 0
        self.failures = 0
        self._next = 0

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        hint = ("\n\nReturn ONLY a JSON object matching this JSON schema:\n"
                + json.dumps(response_model.model_json_schema(), separators=(",", ":")))
        last: Exception | None = None
        # round robin: each free-tier model has its own tokens-per-minute budget
        start = self._next % len(self.models)
        self._next += 1
        for m in self.models[start:] + self.models[:start]:
            for _ in range(2):
                est = int(len(prompt) / 3.6) + 900
                bucket = _bucket(m)
                await bucket.acquire(est)
                try:
                    msg = await self.chats[m].ainvoke([HumanMessage(content=prompt + hint)],
                                                      config={"callbacks": get_tracer().callbacks(),
                                                              "run_name": f"ragas.{response_model.__name__}"})
                    usage = getattr(msg, "usage_metadata", None) or {}
                    used = int(usage.get("total_tokens", 0)) or est
                    bucket.settle(est, used)
                    self.calls += 1
                    self.tokens += used
                    return parse_json(msg.content if isinstance(msg.content, str) else json.dumps(msg.content),
                                      response_model)
                except Exception as exc:  # noqa: BLE001 - try again / next model
                    bucket.settle(est, 0)
                    self.failures += 1
                    last = exc
                    if "rate" in str(exc).lower() or "429" in str(exc):
                        await asyncio.sleep(8)
        raise RuntimeError(f"judge failed: {last}")

    def generate(self, prompt: str, response_model: type[T]) -> T:
        return asyncio.run(self.agenerate(prompt, response_model))


class LocalEmbeddings(BaseRagasEmbedding):
    def embed_text(self, text: str, **kwargs: Any) -> list[float]:
        return emb.embed_query(text)

    async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)


async def score_sample(judge: GroqJudge, user_input: str, response: str, contexts: list[str],
                       reference: str | None) -> dict[str, float | None]:
    from ragas.metrics.collections import AnswerRelevancy, ContextRecall, ContextUtilization, Faithfulness

    out: dict[str, float | None] = {}

    async def run(name: str, coro: Any) -> None:
        try:
            res = await coro
            out[name] = round(float(res.value), 3) if res.value is not None else None
        except Exception as exc:  # noqa: BLE001 - one failed metric must not lose the others
            out[name] = None
            out[f"{name}_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"  # type: ignore[assignment]

    await run("faithfulness", Faithfulness(llm=judge).ascore(user_input=user_input, response=response,
                                                             retrieved_contexts=contexts))
    await run("answer_relevancy", AnswerRelevancy(llm=judge, embeddings=LocalEmbeddings(), strictness=2).ascore(
        user_input=user_input, response=response))
    await run("context_precision", ContextUtilization(llm=judge).ascore(user_input=user_input, response=response,
                                                                        retrieved_contexts=contexts))
    if reference:
        await run("context_recall", ContextRecall(llm=judge).ascore(user_input=user_input, reference=reference,
                                                                    retrieved_contexts=contexts))
    return out
