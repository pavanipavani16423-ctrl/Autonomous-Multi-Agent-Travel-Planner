"""Daily-quota handling: a model whose Groq daily token budget is spent is parked and the
next model in the chain answers, instead of the agent dropping to its rule-based fallback."""

from __future__ import annotations

import time

from voyager.llm import gateway

TPD_ERROR = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` "
             "on tokens per day (TPD): Limit 200000, Used 199594. Please try again in 15m31.824s.'}}")


def test_daily_limit_is_recognised_and_retry_parsed():
    assert gateway._is_daily_limit(TPD_ERROR)
    assert not gateway._is_daily_limit("Error code: 429 - tokens per minute (TPM): Limit 8000")
    assert abs(gateway._retry_after_s(TPD_ERROR) - (15 * 60 + 31.824)) < 0.01
    assert gateway._retry_after_s("Please try again in 1h2m3s") == 3723
    assert gateway._retry_after_s("no hint") == 3600


def test_chain_skips_exhausted_models(monkeypatch):
    monkeypatch.setattr(gateway, "_EXHAUSTED", {})
    small = gateway.model_chain("small")
    assert small[0] == gateway.model_name("small") and len(small) == 3
    gateway._EXHAUSTED[small[0]] = time.monotonic() + 600
    assert gateway.model_chain("small")[0] == gateway.model_name("large")
    assert gateway.model_chain("large")[0] == gateway.model_name("large")
    # quota windows expire
    gateway._EXHAUSTED[small[0]] = time.monotonic() - 1
    assert gateway.model_chain("small")[0] == small[0]
