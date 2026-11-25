"""Every LLM call goes through `structured()`: Pydantic-validated output, never an exception.

    1. JSON mode on Groq (response_format=json_object) with the schema in the system prompt
    2. parse with json-repair (handles fences, trailing commas, truncation) -> model_validate
    3. on a validation error: one repair turn that shows the model its own error
    4. still failing (or no key / offline): the agent's deterministic fallback, labelled as such

Groq's free tier allows ~8K tokens/minute per model, so a small client-side token bucket spaces
calls out instead of hammering 429s (the SDK still honours Retry-After if one slips through).
Every call carries the Langfuse LangChain callback, so it shows up as a generation with tokens.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import json_repair
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from voyager.config import get_settings
from voyager.observability.tracing import get_tracer

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class CallStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    fallbacks: int = 0
    by_agent: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, agent: str, inp: int, out: int, ms: int) -> None:
        self.calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        a = self.by_agent.setdefault(agent, {"calls": 0, "input": 0, "output": 0, "ms": 0})
        a["calls"] += 1
        a["input"] += inp
        a["output"] += out
        a["ms"] += ms


RUN_STATS: contextvars.ContextVar[CallStats | None] = contextvars.ContextVar("voyager_llm_stats", default=None)


class TokenBucket:
    """Sliding 60 s window of tokens per model (Groq free tier: 8K TPM)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.events: deque[tuple[float, int]] = deque()
        self.lock = asyncio.Lock()

    def _used(self, now: float) -> int:
        while self.events and now - self.events[0][0] > 60:
            self.events.popleft()
        return sum(n for _, n in self.events)

    async def acquire(self, tokens: int) -> float:
        waited = 0.0
        tokens = min(tokens, self.per_minute)
        async with self.lock:
            while True:
                now = time.monotonic()
                if self._used(now) + tokens <= self.per_minute:
                    self.events.append((now, tokens))
                    return waited
                wait = max(0.25, 60 - (now - self.events[0][0]) + 0.05)
                wait = min(wait, 5.0)
                await asyncio.sleep(wait)
                waited += wait

    def wait_estimate(self, tokens: int) -> float:
        """Seconds until `tokens` would fit in the window (0 = now)."""
        now = time.monotonic()
        used = self._used(now)
        tokens = min(tokens, self.per_minute)
        if used + tokens <= self.per_minute:
            return 0.0
        freed = 0
        for ts, n in self.events:
            freed += n
            if used - freed + tokens <= self.per_minute:
                return max(0.0, 60 - (now - ts))
        return 60.0

    def settle(self, estimated: int, actual: int) -> None:
        """Replace the newest matching estimate with the real usage."""
        for i in range(len(self.events) - 1, -1, -1):
            if self.events[i][1] == min(estimated, self.per_minute):
                self.events[i] = (self.events[i][0], actual)
                return


_BUCKETS: dict[str, TokenBucket] = {}
SPILL_AFTER_S = 8.0
ChatFactory = Callable[[str, int], Any]
_CHAT_FACTORY: ChatFactory | None = None


def set_chat_factory(factory: ChatFactory | None) -> None:
    """Tests inject a fake chat model: factory(model_name, max_tokens) -> object with `ainvoke`."""
    global _CHAT_FACTORY
    _CHAT_FACTORY = factory


def _bucket(model: str) -> TokenBucket:
    if model not in _BUCKETS:
        _BUCKETS[model] = TokenBucket(7600)
    return _BUCKETS[model]


class FakeChat:
    """Deterministic offline LLM: answers with the agent's fallback serialised as JSON, so the
    parse/validate path is exercised exactly as with a real model."""

    def __init__(self, payload: Callable[[], str]) -> None:
        self.payload = payload

    async def ainvoke(self, messages: list[Any], config: Any = None) -> AIMessage:
        return AIMessage(content=self.payload(), usage_metadata={"input_tokens": 0, "output_tokens": 0,
                                                                  "total_tokens": 0})


def _groq(model: str, max_tokens: int, json_mode: bool = True) -> Any:
    from langchain_groq import ChatGroq

    s = get_settings()
    extra: dict[str, Any] = {}
    if model.startswith("openai/gpt-oss"):
        extra["reasoning_effort"] = s.llm_reasoning_effort
    return ChatGroq(model=model, api_key=s.groq_api_key, temperature=0.3, max_tokens=max_tokens,
                    timeout=s.llm_timeout_s, max_retries=s.llm_max_retries,
                    model_kwargs={"response_format": {"type": "json_object"}} if json_mode else {}, **extra)


def model_name(size: str) -> str:
    s = get_settings()
    return s.model_large if size == "large" else s.model_small


# Models whose *daily* quota is spent (Groq TPD/RPD 429) -> monotonic time when they may work again.
_EXHAUSTED: dict[str, float] = {}


def _is_daily_limit(err: str) -> bool:
    e = err.lower()
    return ("429" in e or "rate_limit" in e or "rate limit" in e) and ("per day" in e or "tpd" in e or "rpd" in e)


def _retry_after_s(err: str) -> float:
    """Parse Groq's 'try again in 1h2m10.5s' hint; default one hour."""
    m = re.search(r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", err)
    if not m or not any(m.groups()):
        return 3600.0
    h, mi, se = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + se


def model_chain(size: str) -> list[str]:
    """Preferred model first, then the other size, then the backup; skips daily-exhausted models."""
    s = get_settings()
    first, other = (s.model_large, s.model_small) if size == "large" else (s.model_small, s.model_large)
    chain = list(dict.fromkeys(m for m in (first, other, s.model_backup) if m))
    now = time.monotonic()
    live = [m for m in chain if _EXHAUSTED.get(m, 0) <= now]
    return live or chain[:1]


def describe_mode() -> str:
    s = get_settings()
    if s.offline:
        return "offline-fake-llm"
    if not s.groq_api_key:
        return "rules (no GROQ_API_KEY)"
    return f"groq:{s.model_large} + {s.model_small}"


def _schema_hint(schema: type[BaseModel]) -> str:
    return ("\n\nRespond with ONE JSON object only (no prose, no code fences) that validates against "
            "this JSON schema:\n" + json.dumps(schema.model_json_schema(), separators=(",", ":")))


def parse_json(text: str, schema: type[T]) -> T:
    """json-repair then validate. Raises ValueError/ValidationError on failure."""
    if not text or not text.strip():
        raise ValueError("empty response")
    data = _reshape(json_repair.loads(text), schema)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return schema.model_validate(data)


def _reshape(data: Any, schema: type[BaseModel]) -> Any:
    """Undo the usual near-misses: a bare array for the one list field (`[...]` -> `{"days": [...]}`),
    a one-element array around the object, or the object nested under a single wrapper key."""
    fields = schema.model_fields
    required = {k for k, f in fields.items() if f.is_required()}
    list_fields = [k for k, f in fields.items() if getattr(f.annotation, "__origin__", None) is list]
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict) and (required & set(data[0]) or not required):
            return data[0]
        if len(list_fields) == 1:
            return {list_fields[0]: data}
        return data
    if isinstance(data, dict) and required and not (required & set(data)) and len(data) == 1:
        inner = next(iter(data.values()))
        if isinstance(inner, dict | list):
            return _reshape(inner, schema)
    if isinstance(data, dict):  # `"diet": null` for a field with a default -> use the default
        data = {k: v for k, v in data.items() if not (v is None and k in fields and not fields[k].is_required())}
        for k in list_fields:  # "safety": "one; two" -> ["one", "two"]
            if isinstance(data.get(k), str):
                data[k] = [x.strip(" -•") for x in re.split(r"\n|;", data[k]) if x.strip(" -•")]
    return data


async def structured(agent: str, schema: type[T], system: str, user: str, *, fallback: Callable[[], T],
                     size: str = "small", max_tokens: int = 1500) -> tuple[T, str]:
    """Returns (validated result, method) with method in {"llm", "llm-repaired", "fallback:<why>",
    "offline"}. Never raises."""
    s = get_settings()
    stats = RUN_STATS.get()
    model = model_chain(size)[0] if _CHAT_FACTORY is None and not s.offline else model_name(size)
    spilled = model != model_name(size)
    if s.offline and _CHAT_FACTORY is None:
        chat: Any = FakeChat(lambda: fallback().model_dump_json())
        mode = "offline"
    elif _CHAT_FACTORY is not None:
        chat, mode = _CHAT_FACTORY(model, max_tokens), "llm"
    elif not s.groq_api_key:
        if stats:
            stats.fallbacks += 1
        return fallback(), "fallback:no-llm-key"
    else:
        chat, mode = _groq(model, max_tokens), "llm"

    sys_prompt = system + _schema_hint(schema)
    if mode == "llm" and size == "large" and _CHAT_FACTORY is None:
        est0 = int((len(sys_prompt) + len(user)) / 3.6) + int(max_tokens * 0.6)
        if _bucket(model).wait_estimate(est0) > SPILL_AFTER_S and _bucket(model_name("small")).wait_estimate(est0) < 2:
            # the large model's per-minute token budget is spent: answer with the small one now
            logger.info("%s: %s rate-limited, spilling to %s", agent, model, model_name("small"))
            model = model_name("small")
            chat = _groq(model, max_tokens)
            spilled = True
    messages: list[Any] = [SystemMessage(content=sys_prompt), HumanMessage(content=user)]
    callbacks = get_tracer().callbacks()
    config = {"callbacks": callbacks, "run_name": f"{agent}", "metadata": {"agent": agent}}
    last_error = ""
    switches = 0
    for attempt in range(3):
        if attempt == 2 and not switches:
            break  # two tries per model; a third only after moving off a daily-exhausted model
        est = int((len(sys_prompt) + len(user)) / 3.6) + int(max_tokens * 0.6)
        bucket = _bucket(model) if mode == "llm" else None
        waited = await bucket.acquire(est) if bucket else 0.0
        started = time.perf_counter()
        try:
            msg = await asyncio.wait_for(chat.ainvoke(messages, config=config), timeout=s.llm_timeout_s + 30)
            usage = getattr(msg, "usage_metadata", None) or {}
            inp, out = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            if bucket:
                bucket.settle(est, inp + out if (inp + out) else est)
            ms = int((time.perf_counter() - started) * 1000)
            if stats:
                stats.add(agent, inp, out, ms)
            logger.info("llm %s %s: %d in / %d out tokens, %d ms (waited %.1fs for the rate limit)",
                        agent, model, inp, out, ms, waited)
            content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            try:
                result = parse_json(content, schema)
                method = mode if attempt == 0 else "llm-repaired"
                return result, (f"{method}:via-{model}" if spilled else method)
            except (ValueError, ValidationError) as exc:
                last_error = f"invalid output: {str(exc)[:600]}"
                where = ([".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors()[:4]]
                         if isinstance(exc, ValidationError) else [str(exc)[:200]])
                logger.info("%s: output did not validate, asking for a repair: %s", agent, "; ".join(where))
                messages = messages + [AIMessage(content=content[:4000]), HumanMessage(content=(
                    "Your JSON did not validate:\n" + str(exc)[:1200] +
                    "\nReturn the corrected JSON object only."))]
        except Exception as exc:  # noqa: BLE001 - provider error, timeout, rate limit
            last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            if bucket:
                bucket.settle(est, 0)  # a failed call must not keep its token reservation
            if stats:
                stats.failures += 1
            logger.warning("%s LLM call failed (attempt %d): %s", agent, attempt + 1, last_error)
            if mode == "llm" and _CHAT_FACTORY is None and _is_daily_limit(str(exc)):
                # this model's daily quota is gone: park it and move to the next model in the chain
                _EXHAUSTED[model] = time.monotonic() + _retry_after_s(str(exc))
                nxt = next((m for m in model_chain(size) if m != model), None)
                if nxt:
                    logger.warning("%s: %s daily quota exhausted, switching to %s", agent, model, nxt)
                    model, spilled, switches = nxt, True, switches + 1
                    chat = _groq(model, max_tokens)
                    continue
            if "rate_limit" in last_error.lower() or "429" in last_error:
                await asyncio.sleep(4)
            if mode == "llm" and _CHAT_FACTORY is None and ("generate JSON" in last_error or "json_validate" in last_error):
                # Groq's server-side JSON mode refused the generation: retry as plain text + json-repair
                chat = _groq(model, max_tokens, json_mode=False)
    logger.warning("%s: falling back to rules (%s)", agent, last_error)
    if stats:
        stats.fallbacks += 1
    return fallback(), f"fallback:{last_error[:80]}"
