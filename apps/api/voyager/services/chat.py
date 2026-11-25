"""The Voyager assistant behind `POST /api/chat`: a grounded, streaming Q&A over the traveller's plan,
the Wikivoyage guidebook and a short note on how Voyager itself works.

    guard     injection -> refuse, PII -> redacted, scope -> polite refusal (the same rules as trip requests)
    context   the trip's plan from the store (compact text) + hybrid-RAG passages for the destination
              (the trip's, or a city named in the message), numbered [1]..[n] so the answer can cite them
    intent    answer | refine | plan | off_topic: obvious questions skip the model, the rest go to the
              small model through the gateway's `structured()` (rules when offline or it fails)
    answer    streamed token by token from the small model (`model_chain("small")`, moving past models
              whose daily quota is spent); offline / no key -> a deterministic, still-grounded reply
    actions   a change request becomes `action: refine` and a new trip `action: plan`: the UI shows a
              button, the user decides (human in the loop, never automatic)

One Langfuse trace per message (name "chat", session = trip id or client id).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from voyager.config import API_DIR, get_settings
from voyager.guardrails import injection, pii, scope
from voyager.llm.gateway import _EXHAUSTED, _is_daily_limit, _retry_after_s, model_chain, structured
from voyager.observability.tracing import get_tracer
from voyager.rag.store import CITY_COUNTRY, Passage, get_guidebook
from voyager.rag.text import destination_key
from voyager.schemas import ChatBody

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
Intent = Literal["answer", "refine", "plan", "off_topic"]

MAX_HISTORY = 10
MAX_PASSAGES = 4
MIN_PASSAGE_SCORE = 0.02  # reranker relevance (sigmoid of the cross-encoder logit)
ANSWER_MAX_TOKENS = 900  # gpt-oss counts its (low-effort) reasoning inside this budget
PLAN_CONTEXT_CHARS = 9000  # ~2.4K tokens; long trips get shorter activity lines

ABOUT_VOYAGER = """\
Voyager is a multi-agent AI trip planner. A LangGraph graph runs: guard (input guardrails: prompt injection, \
PII redaction, scope, date/budget sanity) -> brief (normalises the request, geocodes, checks guidebook \
coverage and, for a city that is not covered, fetches its Wikivoyage article and indexes it on demand) -> five \
specialists in parallel: destination (highlights, cited facts), weather (Open-Meteo forecast or same-dates \
historical normals), stays (OpenStreetMap places + guidebook "Sleep"), food (OpenStreetMap + guidebook \
"Eat/Drink", respecting diet) and logistics (getting there/around, visa, safety, packing, currency via \
Frankfurter) -> itinerary (day-by-day plan, weather- and pace-aware, geo-clustered) -> budget, a separate \
Budget Analyst agent called over the A2A protocol, which costs the plan from a curated cost table (country \
tier x style), compares it with the limit and suggests savings -> critic (day count, dates, budget fit, \
citation coverage, wrong-city leakage, geo sanity; sends a weak itinerary back once) -> finalize (confidence \
and quality scores). Live data comes from three MCP tool servers: weather, places and money. The guidebook \
is ~9,000 Wikivoyage passages in Qdrant, searched with hybrid retrieval (bge-small dense + BM25 sparse, \
reciprocal-rank fusion, MiniLM cross-encoder rerank). Every run is traced in Langfuse and scored (Ragas \
faithfulness, answer relevancy, context precision, plus citation coverage and budget fit). Every stay, food \
pick, weather day and cost carries provenance: live, guidebook, estimate, cached or unavailable. Prices are \
estimates, never live quotes. Refinements ("make day 2 more relaxed") re-run itinerary -> budget -> critic -> \
finalize from the saved checkpoint. The LLMs are open models on Groq (gpt-oss-120b / gpt-oss-20b)."""

REFUSE_INJECTION = ("That reads like instructions for me rather than a travel question, so I'll pass on it. "
                    "Ask me anything about your trip, the guidebook, or how Voyager plans.")
REFUSE_SCOPE = ("I'm Voyager's travel assistant, so I can only help with trips: your plan, destinations in the "
                "guidebook, and how Voyager's agents work. What would you like to know about your travels?")

# ---- rules: the intent fallback and the fast path ---------------------------------------------------
QUESTION_RX = re.compile(
    r"^\s*(why|what|what's|how|when|where|which|who|is|are|was|were|does|do|did|will|would|should|could|can|"
    r"explain|tell me|any)\b", re.I)
REQUEST_RX = re.compile(r"^\s*(can|could|would|will) you\b|\bplease\b|^\s*(i want|i'd like|i would like|let's|"
                        r"let us)\b", re.I)
CHANGE_RX = re.compile(
    r"\b(make|change|swap|replace|switch|add|remove|drop|skip|move|cut|reduce|lower|shorten|extend|fewer|"
    r"cheaper|instead|slower|avoid|include|exclude|upgrade|downgrade|less (packed|busy|walking|rushed)|"
    r"more (relaxed|time|food|temples?|museums?|nature|nightlife|shopping|vegetarian|vegan|street food))\b",
    re.I)
PLAN_RX = re.compile(r"\b(plan|organi[sz]e|itinerary for|trip to|holiday in|vacation in|getaway to|"
                     r"weekend in|days? in|nights? in)\b", re.I)
DURATION_RX = re.compile(r"\b(\d+|a|one|two|three|four|five|six|seven|ten)[\s-]+(days?|nights?|weeks?)\b|"
                         r"\bweekend\b", re.I)
CITE_RX = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")


class ChatIntent(BaseModel):
    intent: Intent = Field(description="answer = a question; refine = change the CURRENT trip plan; "
                                       "plan = plan a NEW trip; off_topic = not about travel or Voyager")
    instruction: str = Field("", max_length=300,
                             description="refine: the change as one imperative instruction for the planning "
                                         "agents, keeping the user's specifics. plan: the trip request in one "
                                         "sentence. Otherwise empty.")


def rule_intent(message: str, has_trip: bool) -> ChatIntent:
    """Deterministic classifier: the offline path, the LLM fallback, and the fast path for plain questions."""
    question = bool(QUESTION_RX.search(message)) or message.rstrip().endswith("?")
    asks = bool(REQUEST_RX.search(message))
    change = bool(CHANGE_RX.search(message))
    if has_trip and change and (asks or not question):
        return ChatIntent(intent="refine", instruction=message[:300])
    if PLAN_RX.search(message) and (DURATION_RX.search(message) or mentioned_city(message)) and (
            asks or not question or re.match(r"^\s*(plan|organi[sz]e)\b", message, re.I)):
        return ChatIntent(intent="plan", instruction=message[:300])
    return ChatIntent(intent="answer")


def obvious_question(message: str) -> bool:
    """A plain question with no change verbs needs no classifier call (saves a model round trip)."""
    return bool(QUESTION_RX.search(message)) and not REQUEST_RX.search(message) and not CHANGE_RX.search(
        message) and not PLAN_RX.search(message)


INTENT_SYSTEM = """You route messages for Voyager, an AI travel planner's chat assistant.
Classify the user's LATEST message:
- "refine": they want to CHANGE their current trip plan (pace, a day, hotels, food, budget, activities). Only \
possible when has_trip is true.
- "plan": they want a NEW trip planned (a destination and/or duration, e.g. "plan 3 days in Goa under 30k").
- "answer": a question or anything else about travel, the trip, destinations, or how Voyager / its agents work.
- "off_topic": clearly unrelated to travel and to Voyager (coding help, homework, finance, medical, etc.).
For refine, write `instruction` as one imperative sentence for the planning agents that keeps every specific \
(day numbers, budget, names). For plan, put the trip request in `instruction`. Otherwise leave it empty."""


# ---- context ---------------------------------------------------------------------------------------
def _clean(text: Any, limit: int) -> str:
    """Drop the plan's inline "Citations: [...]" trailers and squash whitespace."""
    s = re.sub(r"\s*Citations?:\s*\[[^\n]*", "", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _money(m: dict[str, Any] | None) -> str:
    if not m:
        return "?"
    amount = float(m.get("amount") or 0)
    return f"{amount:,.0f} {m.get('currency', '')}".strip()


def plan_context(plan: dict[str, Any]) -> str:
    """A compact, model-friendly digest of a TripPlan (the ground truth for "your plan" answers)."""
    r = plan.get("request") or {}
    d = plan.get("destination") or {}
    lines = [
        f"TITLE: {plan.get('title', '')} (revision v{plan.get('revision', 0)})",
        f"WHERE/WHEN: {d.get('name', r.get('destination', ''))}, {d.get('country', '')} · "
        f"{r.get('start_date')} to {r.get('end_date')} · {r.get('adults', 1)} adults, {r.get('children', 0)} children"
        f" · from {r.get('origin') or 'not given'}",
        f"PREFERENCES: budget {r.get('budget')} {r.get('currency')} total · pace {r.get('pace')} · stay style "
        f"{r.get('stay_style')} · diet {', '.join(r.get('diet') or []) or 'none'} · interests "
        f"{', '.join(r.get('interests') or []) or 'none'}" + (f" · notes: {_clean(r['notes'], 200)}" if r.get("notes")
                                                              else ""),
        f"SUMMARY: {_clean(plan.get('summary'), 400)}",
    ]
    if plan.get("weather_overview"):
        lines.append(f"WEATHER: {_clean(plan['weather_overview'], 300)}")
    days = plan.get("days") or []
    desc_len = 110 if len(days) <= 5 else 60 if len(days) <= 9 else 0
    for day in days:
        w = day.get("weather") or {}
        wtxt = (f"; weather {w.get('summary')} {w.get('t_min'):.0f}-{w.get('t_max'):.0f}°C, rain {w.get('precip_mm')} mm"
                f" ({w.get('provenance')})" if w else "")
        walk = f", ~{day['walking_km']} km walking" if day.get("walking_km") else ""
        lines.append(f"DAY {day.get('day')} {day.get('date')} — {day.get('title')} (theme: {day.get('theme')}{wtxt}; "
                     f"day cost {_money(day.get('day_cost'))} estimate{walk}; {len(day.get('activities') or [])} stops)")
        for a in day.get("activities") or []:
            where = f" @ {a['place']}" if a.get("place") and a.get("place") != a.get("title") else ""
            lines.append(f"  {a.get('time')} {a.get('slot')}: {a.get('title')}{where} [{a.get('category')}, "
                         f"{'indoor' if a.get('indoor') else 'outdoor'}, {a.get('duration_min')} min, "
                         f"{_money(a.get('cost'))}]" + (f" {_clean(a.get('description'), desc_len)}" if desc_len else ""))
    stays = plan.get("stays") or []
    if stays:
        lines.append("STAYS (nightly prices are estimates from a curated cost table, not live quotes):")
        for s in stays:
            rating = f", rated {s['rating']}" if s.get("rating") else ""
            lines.append(f"  {s.get('name')} ({s.get('kind')}, {s.get('area')}{rating}) ~{_money(s.get('price_per_night'))}"
                         f"/night [{s.get('provenance')}] — why: {_clean(s.get('why'), 140)}")
    food = plan.get("food") or []
    if food:
        lines.append("FOOD:")
        for f in food:
            lines.append(f"  {f.get('name')} ({f.get('cuisine')}, {f.get('area') or '?'}, price level "
                         f"{'$' * int(f.get('price_level') or 1)}) must try: {f.get('must_try')}; diet ok: "
                         f"{', '.join(f.get('diet_ok') or []) or '-'} [{f.get('provenance')}]")
    b = plan.get("budget") or {}
    if b:
        lines.append(f"BUDGET (by {b.get('analyst')}): total {_money(b.get('total'))} of limit {_money(b.get('limit'))} "
                     f"({float(b.get('utilisation') or 0):.0%} used, {'within' if b.get('within_budget') else 'OVER'} "
                     f"budget), {_money(b.get('per_person'))} per person. Lines:")
        for line in b.get("lines") or []:
            lines.append(f"  {line.get('category')}: {_money(line.get('amount'))} — {_clean(line.get('note'), 140)}")
        if b.get("savings_tips"):
            lines.append("  savings tips: " + " | ".join(_clean(t, 140) for t in b["savings_tips"][:4]))
    p = plan.get("pre_trip") or {}
    if p:
        gt = p.get("getting_there") or {}
        lines.append(f"PRE-TRIP: getting there: {gt.get('mode')}, {gt.get('duration')}, {_money(gt.get('cost'))} "
                     f"(estimate) — {_clean(gt.get('note'), 200)}")
        lines.append(f"  getting around: {_clean(p.get('getting_around'), 260)}")
        lines.append(f"  visa: {_clean(p.get('visa'), 220)}")
        lines.append(f"  currency: {_clean(p.get('currency_note'), 160)}")
        for key in ("packing", "safety", "local_tips", "best_areas"):
            if p.get(key):
                lines.append(f"  {key.replace('_', ' ')}: " + "; ".join(_clean(x, 90) for x in p[key][:8]))
    q = plan.get("quality") or {}
    if q:
        failed = [f"{c.get('name')} ({_clean(c.get('detail'), 120)})" for c in q.get("checks") or [] if not c.get("passed")]
        scores = ", ".join(f"{s.get('name')} {float(s.get('value') or 0):.2f} {s.get('rating')}" for s in q.get("scores") or [])
        lines.append(f"QUALITY: confidence {float(q.get('confidence') or 0):.0%}, grounding coverage "
                     f"{float(q.get('grounding_coverage') or 0):.0%}, guidebook {q.get('guidebook')}; scores: {scores}; "
                     f"failed checks: {'; '.join(failed) or 'none'}")
    text = "\n".join(lines)
    return text if len(text) <= PLAN_CONTEXT_CHARS else text[:PLAN_CONTEXT_CHARS] + "\n[plan digest truncated]"


def request_context(req: dict[str, Any], status: str) -> str:
    return (f"The plan is not ready yet (status: {status}). Request so far: {req.get('destination')} from "
            f"{req.get('start_date')} to {req.get('end_date')}, {req.get('adults', 1)} adults, budget {req.get('budget')} "
            f"{req.get('currency')}, pace {req.get('pace')}, stay style {req.get('stay_style')}.")


@lru_cache(maxsize=1)
def demo_plan() -> dict[str, Any] | None:
    """The sample trip the web app replays at /trip/demo (it is never in the trip store)."""
    candidates = [get_settings().data_dir / "sample-plan.json"] + [p / "docs" / "sample-plan.json"
                                                                     for p in [API_DIR, *API_DIR.parents]]
    for path in candidates:
        if Path(path).is_file():
            try:
                return json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def _city_names() -> list[tuple[str, str]]:
    """(lowercased name to look for, destination key) for every guidebook city plus the curated country list."""
    book = get_guidebook()
    names: dict[str, str] = {}
    for key, c in book.cities.items():
        names[key] = key
        names[destination_key(c.get("name", key))] = key
        for alias in c.get("aliases") or ():
            names[destination_key(alias)] = key
    for key in CITY_COUNTRY:
        names.setdefault(key, key)
    return sorted(names.items(), key=lambda kv: -len(kv[0]))


def mentioned_city(message: str) -> str | None:
    text = destination_key(message.replace(",", " "))
    for name, key in _city_names():
        if len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", text):
            return key
    return None


def clean_history(body: ChatBody) -> list[dict[str, str]]:
    """Last 10 turns, PII-redacted, with any turn that reads like an injection dropped (the client owns
    this list, so a forged "assistant" turn is untrusted input too)."""
    out: list[dict[str, str]] = []
    for turn in body.history[-MAX_HISTORY:]:
        content = turn.content.strip()[:1500]
        if not content or injection.detect(content).flagged:
            continue
        out.append({"role": turn.role, "content": pii.redact(content)[0]})
    return out


def sources_block(passages: list[Passage]) -> str:
    if not passages:
        return "(no guidebook passages matched this question)"
    return "\n".join(f"[{i}] {p.destination_name} — {p.section}: {_clean(p.text, 650)}"
                     for i, p in enumerate(passages, 1))


def system_prompt(*, intent: Intent, plan_text: str | None, passages: list[Passage], destination: str | None) -> str:
    mode = {
        "refine": ("The traveller is asking to CHANGE their plan. You cannot change it yourself. In 1-3 sentences, "
                   "say what would change (name the specific day or items from YOUR TRIP PLAN) and that pressing "
                   "\"Apply to my plan\" sends it to the itinerary, budget and critic agents. Never claim it is done."),
        "plan": ("The traveller wants a NEW trip planned. In 1-2 sentences, say you can start it and that "
                 "\"Start planning\" turns their request into a draft they can check before the agents begin. "
                 "You may add one relevant guidebook fact with its citation."),
        "answer": "Answer the question.",
        "off_topic": "Politely decline in one sentence and offer travel help instead.",
    }[intent]
    return f"""You are the Voyager assistant, the chat helper inside Voyager, a multi-agent AI trip planner.
Ground every answer in the context below: YOUR TRIP PLAN (what Voyager's agents produced for this traveller), \
GUIDEBOOK passages (Wikivoyage, numbered) and ABOUT VOYAGER (how the system works).

Rules:
- Cite guidebook facts with the passage number in square brackets right after the sentence, like "Gion is best \
at dusk [2]." Only use numbers listed under GUIDEBOOK. Do not cite the plan or ABOUT VOYAGER.
- If something is not in the context, say so plainly ("your plan doesn't include that", "the guidebook passages \
I have don't cover that") and suggest a next step. Never invent places, opening hours, distances or prices.
- Prices and costs in the plan are estimates (curated cost table, checked by the Budget Analyst agent), not live \
quotes: say "estimated" when you mention money, and never state a price that is not in the context.
- Only discuss travel, this trip and how Voyager works; decline anything else in one sentence.
- Be concise, warm and practical: 2-6 sentences or a short "- " bullet list. Use **bold** sparingly. No headings, \
no tables, no emoji.
- Task: {mode}

YOUR TRIP PLAN:
{plan_text or "(no trip is open: the user is browsing Voyager, so answer generally or about Voyager)"}

GUIDEBOOK{f" (passages for {destination.title()})" if destination else ""}:
{sources_block(passages)}

ABOUT VOYAGER:
{ABOUT_VOYAGER}"""


# ---- deterministic reply (offline mode, no Groq key, or the model is unreachable) ------------------
def offline_reply(*, intent: Intent, message: str, plan: dict[str, Any] | None, passages: list[Passage],
                  instruction: str, why: str) -> str:
    if intent == "refine":
        return (f"I can hand this change to the planning agents: **“{instruction or message}”**. Press **Apply to my "
                "plan** and the itinerary, budget and critic agents re-run on your current plan. Nothing changes "
                "until you do.")
    if intent == "plan":
        return ("I can start that trip. Press **Start planning** and Voyager reads your request into a draft you can "
                "check and edit before the agents begin.")
    if intent == "off_topic":
        return REFUSE_SCOPE
    parts = [f"_({why}, so this is a direct lookup rather than a written answer.)_"]
    if plan:
        b = plan.get("budget") or {}
        parts.append(f"Your plan: **{plan.get('title')}**, {len(plan.get('days') or [])} days, an estimated "
                     f"{_money(b.get('total'))} of your {_money(b.get('limit'))} budget, with "
                     f"{len(plan.get('stays') or [])} stays and {len(plan.get('food') or [])} food picks.")
    if passages:
        parts.append("From the guidebook:")
        parts.extend(f"- {_clean(p.text.split(':', 1)[-1], 220)} [{i}]" for i, p in enumerate(passages[:2], 1))
    elif not plan:
        parts.append("Voyager plans trips with a team of agents: guardrails, a brief, five parallel specialists "
                     "(destination, weather, stays, food, logistics) using live MCP tools and a Qdrant guidebook, then "
                     "an itinerary, a Budget Analyst agent over A2A and a critic.")
    else:
        parts.append("The guidebook passages I have don't cover that question.")
    return "\n\n".join(parts)


# ---- the model --------------------------------------------------------------------------------------
def _chat_model(model: str) -> Any:
    from langchain_groq import ChatGroq

    s = get_settings()
    extra: dict[str, Any] = {}
    if model.startswith("openai/gpt-oss"):
        extra["reasoning_effort"] = "low"
    # one retry only: a chat should move to the next model fast rather than back off for long
    return ChatGroq(model=model, api_key=s.groq_api_key, temperature=0.3, max_tokens=ANSWER_MAX_TOKENS,
                    timeout=s.llm_timeout_s, max_retries=1, streaming=True, **extra)


async def _stream_llm(messages: list[Any], emit: Emit) -> tuple[str, str]:
    """Stream the answer; returns (full text, model). Raises when every model failed before any token."""
    tracer = get_tracer()
    config = {"callbacks": tracer.callbacks(), "run_name": "chat.answer", "metadata": {"agent": "chat"}}
    last: Exception | None = None
    for model in model_chain("small"):
        parts: list[str] = []
        try:
            async for chunk in _chat_model(model).astream(messages, config=config):
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    parts.append(text)
                    await emit("token", {"text": text})
            if parts:
                return "".join(parts), model
            last = RuntimeError(f"{model} returned an empty answer")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider error, timeout, rate limit
            if parts:
                raise  # already streaming: don't splice a second model's answer onto the first
            last = exc
            err = str(exc)
            if _is_daily_limit(err):
                _EXHAUSTED[model] = time.monotonic() + _retry_after_s(err)
            logger.warning("chat: %s failed (%s: %s), trying the next model", model, type(exc).__name__, err[:200])
    raise last or RuntimeError("no model available")


async def _emit_text(text: str, emit: Emit) -> None:
    """Deterministic replies stream too (word by word), so the UI has a single code path."""
    for piece in re.findall(r"\S+\s*|\s+", text):
        await emit("token", {"text": piece})
        await asyncio.sleep(0)


def cited(text: str, passages: list[Passage]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Citations the answer actually used, plus marker -> citation id (only these get chips)."""
    refs: dict[str, str] = {}
    for m in CITE_RX.finditer(text):
        for n in re.split(r"\s*,\s*", m.group(1)):
            i = int(n)
            if 1 <= i <= len(passages):
                refs[str(i)] = passages[i - 1].id
    seen: list[str] = []
    for cid in refs.values():
        if cid not in seen:
            seen.append(cid)
    by_id = {p.id: p for p in passages}
    out = []
    for c in seen:
        cit = by_id[c].citation()
        # passages keep Wikivoyage sub-headings ("=== Meditation ===") inline: show them as plain labels
        cit["snippet"] = re.sub(r"\s+", " ", re.sub(r"={2,}\s*([^=\n]+?)\s*={2,}", r"\1:", cit["snippet"])).strip()
        out.append(cit)
    return out, refs


# ---- the pipeline -----------------------------------------------------------------------------------
async def _load_trip(store: Any, trip_id: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """(plan, context text). The demo trip comes from the bundled sample plan."""
    if not trip_id:
        return None, None
    trip = await store.get_trip(trip_id)
    if trip is None and trip_id == "demo":
        plan = demo_plan()
        return plan, plan_context(plan) if plan else None
    if trip is None:
        return None, None
    if trip.get("plan"):
        return trip["plan"], plan_context(trip["plan"])
    return None, request_context(trip.get("request") or {}, trip.get("status", "running"))


async def _retrieve(message: str, history: list[dict[str, str]], destination: str | None) -> list[Passage]:
    if not destination:
        return []
    query = message
    if len(message.split()) < 6:  # "and for food?" -> borrow the previous question's topic
        prev = next((t["content"] for t in reversed(history) if t["role"] == "user"), "")
        query = f"{prev[:200]} {message}".strip()
    tracer = get_tracer()
    with tracer.section("rag.search", as_type="retriever", input={"query": query, "destination": destination}) as span:
        try:
            res = await get_guidebook().asearch(query, destination, k=MAX_PASSAGES + 2)
        except Exception as exc:  # noqa: BLE001 - no guidebook -> answer from the plan alone
            logger.warning("chat retrieval failed: %s", exc)
            return []
        passages = [p for p in res.passages if p.score >= MIN_PASSAGE_SCORE and not injection.quarantine_passage(p.text)]
        passages = passages[:MAX_PASSAGES]
        span.update(output={"hits": len(passages), "top_score": res.top_score, "ids": [p.id for p in passages]})
    return passages


async def _classify(message: str, history: list[dict[str, str]], has_trip: bool) -> tuple[ChatIntent, str]:
    if obvious_question(message):
        return ChatIntent(intent="answer"), "rules:question"
    recent = "\n".join(f"{t['role']}: {t['content'][:200]}" for t in history[-4:])
    user = f"has_trip: {str(has_trip).lower()}\nrecent turns:\n{recent or '(none)'}\nlatest message: {message}"
    with get_tracer().section("chat.intent", input={"message": message, "has_trip": has_trip}) as span:
        result, method = await structured("chat-intent", ChatIntent, INTENT_SYSTEM, user,
                                          fallback=lambda: rule_intent(message, has_trip), size="small", max_tokens=400)
        if result.intent == "refine" and not has_trip:
            result = rule_intent(message, False)  # nothing to refine: a question or a new trip
        span.update(output={"intent": result.intent, "instruction": result.instruction, "method": method})
    return result, method


async def run_chat(body: ChatBody, store: Any, emit: Emit) -> None:
    started = time.perf_counter()
    s = get_settings()
    tracer = get_tracer()
    message, pii_found = pii.redact(body.message)
    session = body.trip_id or body.client_id or "anonymous"
    with tracer.run_trace(trip_id=session, revision=0, input={"message": message, "trip_id": body.trip_id},
                          user_id=body.client_id, metadata={"trip_id": body.trip_id or "", "kind": "chat"},
                          name="chat", tags=["voyager", "chat"]) as root:
        # 1. guardrails --------------------------------------------------------------------------------
        with tracer.section("chat.guard", input={"message": message}) as span:
            inj = injection.detect(message)
            ok, why = scope.in_scope(message)
            span.update(output={"injection": inj.hits, "in_scope": ok, "pii": pii_found})
        if inj.flagged or not ok:
            reply = REFUSE_INJECTION if inj.flagged else REFUSE_SCOPE
            await _emit_text(reply, emit)
            root.update(output={"refused": "injection" if inj.flagged else "scope"})
            await emit("done", {"intent": "refused", "model": "guardrails", "grounded": False,
                                "ms": int((time.perf_counter() - started) * 1000)})
            return
        history = clean_history(body)

        # 2. context + intent (concurrently) -----------------------------------------------------------
        plan, plan_text = await _load_trip(store, body.trip_id)
        trip_city = None
        if plan:
            trip_city = (plan.get("destination") or {}).get("name") or (plan.get("request") or {}).get("destination")
        named = mentioned_city(message)
        destination = named or (destination_key(trip_city) if trip_city else None)
        (intent_res, method), passages = await asyncio.gather(
            _classify(message, history, has_trip=plan is not None),
            _retrieve(message, history, destination))
        intent: Intent = intent_res.intent
        instruction = (intent_res.instruction or message).strip()[:400]

        # 3. answer ------------------------------------------------------------------------------------
        if s.offline or not s.groq_api_key:
            why = "Offline mode: the language model is switched off" if s.offline else \
                "No language model is configured on this server"
            text = offline_reply(intent=intent, message=message, plan=plan, passages=passages,
                                 instruction=instruction, why=why)
            await _emit_text(text, emit)
            model = "offline" if s.offline else "rules"
        else:
            msgs: list[Any] = [SystemMessage(content=system_prompt(intent=intent, plan_text=plan_text,
                                                                   passages=passages, destination=destination))]
            for t in history:
                msgs.append(HumanMessage(content=t["content"]) if t["role"] == "user" else AIMessage(content=t["content"]))
            msgs.append(HumanMessage(content=message))
            with tracer.section("chat.answer", input={"intent": intent, "passages": [p.id for p in passages]}) as span:
                try:
                    text, model = await _stream_llm(msgs, emit)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - every model failed before a token: rules reply
                    logger.warning("chat: falling back to a deterministic reply: %s", exc)
                    text = offline_reply(intent=intent, message=message, plan=plan, passages=passages,
                                         instruction=instruction,
                                         why="The language model is busy right now (free-tier limit)")
                    await _emit_text(text, emit)
                    model = "rules"
                span.update(output={"chars": len(text), "model": model})

        # 4. sources + action --------------------------------------------------------------------------
        citations, refs = cited(text, passages)
        if citations:
            await emit("sources", {"citations": citations, "refs": refs})
        if intent == "refine" and plan is not None:
            await emit("action", {"type": "refine", "message": instruction})
        elif intent == "plan":
            await emit("action", {"type": "plan", "message": instruction})
        ms = int((time.perf_counter() - started) * 1000)
        root.update(output={"reply": text[:2000], "intent": intent, "citations": [c["id"] for c in citations]})
        tracer.score(trace_id=tracer.current_trace_id(), name="Chat citations", value=float(len(citations)),
                     comment=f"intent={intent} via {method}; passages offered={len(passages)}")
        await emit("done", {"intent": intent, "model": model, "grounded": bool(citations or plan_text),
                            "ms": ms})


async def chat_events(body: ChatBody, store: Any) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Run the pipeline in its own task (so the Langfuse context lives in one coroutine) and relay its
    events. A client disconnect closes this generator, which cancels the task."""
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def emit(kind: str, data: dict[str, Any]) -> None:
        await queue.put((kind, data))

    async def runner() -> None:
        try:
            await run_chat(body, store, emit)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - always end the stream with an event
            logger.exception("chat failed")
            await queue.put(("error", {"message": f"The assistant hit an error ({type(exc).__name__}). Try again."}))
            await queue.put(("done", {"intent": "error", "model": "", "grounded": False, "ms": 0}))
        finally:
            await queue.put(None)  # Langfuse exports in the background; no blocking flush per message

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
