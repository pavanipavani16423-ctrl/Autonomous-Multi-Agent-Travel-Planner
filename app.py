# ============================================================
# app.py — Travel planner web app
# ============================================================
# Structured as a product, not a demo of its own architecture:
#
#   landing (hero + search)  →  planning (progress)  →  plan (results)
#
# Session state drives the transition so it reads as pages rather than as a
# sidebar that reruns a script. Nothing in the UI mentions agents, models,
# frameworks or vector stores — none of that is a reason to plan a trip, and
# a traveller has no way to act on it.
# ============================================================

import os
import sys
import time
from datetime import date, timedelta

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from models.models import TravelRequest
from graph.graph import run_travel_pipeline
from memory.store import recent_runs
from langfuse_setup import get_tracer, flush_langfuse
from ui.theme import CSS
from ui.pdf import build_itinerary_pdf

tracer = get_tracer()

st.set_page_config(
    page_title="Voyager · AI Travel Planner",
    page_icon="🧭",
    layout="centered",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# State
# ══════════════════════════════════════════════════════════════
for key, default in [("plan", None), ("result", None), ("elapsed", 0.0), ("request", None)]:
    st.session_state.setdefault(key, default)


def reset() -> None:
    for k in ("plan", "result", "elapsed", "request"):
        st.session_state[k] = None


def esc(text) -> str:
    """Minimal escaping — plan text is model-authored and goes into markup."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ══════════════════════════════════════════════════════════════
# Landing — hero + search
# ══════════════════════════════════════════════════════════════
def render_search() -> None:
    st.markdown(
        """
        <div style="margin-bottom:2.2rem;">
          <div class="brand"><span class="brand-mark">✦</span><span class="brand-name">Voyager</span><span class="brand-sub">AI Travel Planner</span></div>
          <h1>Tell us where you're going.<br/><span class="h1-accent">We'll plan the rest.</span></h1>
          <p class="lede">A complete day-by-day itinerary with places to stay, what to eat
          and a realistic budget — built around your dates, your money and how you like
          to travel.</p>
          <div class="hero-facts">
            <span><b>52</b> destinations researched</span>
            <span><b>Day-by-day</b> itineraries</span>
            <span><b>Real</b> budget breakdowns</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("trip", clear_on_submit=False):
        c1, c2 = st.columns(2)
        origin = c1.text_input("Flying from", placeholder="Mumbai")
        destination = c2.text_input("Going to", placeholder="Dubai")

        c1, c2, c3 = st.columns([1, 1, 0.8])
        departure = c1.date_input("Departure", value=date.today() + timedelta(days=30))
        return_dt = c2.date_input("Return", value=date.today() + timedelta(days=35))
        travellers = c3.number_input("Travellers", min_value=1, max_value=20, value=2)

        c1, c2 = st.columns([1, 1])
        budget = c1.number_input(
            "Total budget (USD)", min_value=100, max_value=100_000, value=2500, step=100
        )
        # Real values only — the old placeholder options ("Select Purpose")
        # were passed straight into the request when left untouched.
        purpose = c2.selectbox(
            "Trip type", ["Leisure", "Adventure", "Family", "Business", "Honeymoon"]
        )

        c1, c2 = st.columns(2)
        dietary = c1.selectbox(
            "Dietary preference",
            ["No preference", "Vegetarian", "Vegan", "Halal", "Kosher"],
        )
        stay = c2.selectbox("Style of stay", ["Mid-range", "Budget", "Luxury"])

        notes = st.text_area(
            "Anything else we should know?",
            placeholder="Travelling with a toddler · want to avoid long drives · celebrating an anniversary",
            height=80,
        )

        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1, 2])
        submitted = c1.form_submit_button("Plan my trip", use_container_width=True)
        fresh = c2.checkbox(
            "Re-plan from scratch",
            value=False,
            help="Ignore a previously saved plan for this exact trip.",
        )

    if submitted:
        if not origin.strip() or not destination.strip():
            st.markdown(
                '<div class="notice notice-warn">Please enter where you\'re '
                "flying from and where you're going.</div>",
                unsafe_allow_html=True,
            )
            return
        start_planning(
            origin, destination, departure, return_dt, travellers, budget,
            purpose, dietary, stay, notes, fresh,
        )

    history = recent_runs(5)
    if history:
        st.markdown("<div style='height:1.4rem'></div>", unsafe_allow_html=True)
        with st.expander("Recent trips"):
            for r in history:
                st.markdown(
                    f"<div style='padding:0.3rem 0;font-size:0.9rem;'>"
                    f"<b>{esc(r['origin'])} → {esc(r['destination'])}</b>"
                    f"<span class='caption'> · {esc(r['departure_date'])}"
                    f" · {r['travellers']} traveller(s)</span></div>",
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════
# Planning
# ══════════════════════════════════════════════════════════════
# Written from the traveller's point of view. The old copy narrated the
# system ("RetrievalAgent — fetching from Hybrid RAG"), which tells someone
# waiting for an itinerary nothing they can use.
STEPS = [
    (8,  "Checking your dates and budget"),
    (20, "Reading up on {dest}"),
    (34, "Looking at the weather for your dates"),
    (50, "Mapping out your days"),
    (66, "Finding places to stay"),
    (80, "Working out the costs"),
    (92, "Picking out where to eat"),
    (97, "Writing up your itinerary"),
]


def start_planning(origin, destination, departure, return_dt, travellers,
                   budget, purpose, dietary, stay, notes, fresh) -> None:
    try:
        request = TravelRequest(
            origin=origin.strip(),
            destination=destination.strip(),
            departure_date=departure.strftime("%Y-%m-%d"),
            return_date=return_dt.strftime("%Y-%m-%d"),
            travellers=int(travellers),
            budget_usd=float(budget),
            travel_purpose=purpose.lower(),
            dietary_preference=dietary.lower(),
            accommodation_preference=stay.lower(),
            special_requests=notes.strip() or None,
        )
    except Exception as e:
        st.markdown(
            f'<div class="notice notice-warn">We couldn\'t read that: {esc(e)}</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""<div style="margin-bottom:1.4rem;">
              <div class="eyebrow">Planning</div>
              <h2>{esc(request.origin)} → {esc(request.destination)}</h2>
              <p class="caption">This usually takes three to five minutes.
              You can leave this open.</p>
            </div>""",
        unsafe_allow_html=True,
    )

    bar = st.progress(0)
    slot = st.empty()

    import threading
    running = [True]

    def tick():
        """
        Indicative only — the pipeline reports no per-stage progress, so this
        walks the known order on a timer and holds at the last step rather
        than showing 100% while work continues.
        """
        t0, i = time.time(), 0
        while running[0]:
            pct, label = STEPS[min(i, len(STEPS) - 1)]
            slot.markdown(
                f'<div class="step"><span class="step-dot"></span>'
                f'<span>{esc(label.format(dest=request.destination))}</span>'
                f'<span class="step-time">{time.time()-t0:0.0f}s</span></div>',
                unsafe_allow_html=True,
            )
            bar.progress(min(pct, 97))
            time.sleep(2.2)
            if i < len(STEPS) - 1:
                i += 1

    threading.Thread(target=tick, daemon=True).start()

    started = time.time()
    with tracer.trace(
        name=f"travel_plan_{request.destination}",
        input_data={
            "origin": request.origin, "destination": request.destination,
            "departure": request.departure_date, "return": request.return_date,
            "travellers": request.travellers, "budget_usd": request.budget_usd,
        },
        metadata={"model": os.getenv("LLM_MODEL", ""), "surface": "web"},
        tags=["travel-planner", "web"],
    ) as ctx:
        result = run_travel_pipeline(
            request, use_cache=not fresh, trace_id=ctx.get("trace_id", "")
        )
        tracer.set_output({"has_plan": result.get("final_plan") is not None})

    running[0] = False
    elapsed = time.time() - started
    bar.progress(100)
    slot.empty()

    plan = result.get("final_plan")
    if plan is not None:
        tracer.score_quality(
            trace_id=ctx.get("trace_id"),
            data_sources=plan.data_sources,
            rag_grounding=plan.rag_grounding,
            warnings=len(plan.warnings or []),
            latency_s=elapsed,
        )
    flush_langfuse()

    st.session_state.update(
        plan=plan, result=result, elapsed=elapsed, request=request
    )
    st.rerun()


# ══════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════
MISSING_HINT = {
    "rate_limit": (
        "The AI service is rate-limiting us right now.",
        "Wait a moment and try again.",
    ),
    "empty_response": (
        "The model ran out of room before finishing this section.",
        "Re-planning usually fixes it. If it keeps happening, raise "
        "LLM_MAX_TOKENS in your .env.",
    ),
    "auth": (
        "We couldn't reach the AI service.",
        "The API key looks missing or invalid — check GROQ_API_KEY in your .env.",
    ),
    "error": (
        "Something went wrong building this section.",
        "Re-planning usually fixes it.",
    ),
}


def llm_failures() -> list:
    result = st.session_state.result or {}
    return result.get("llm_errors", []) or []


def failure_kinds() -> set:
    """Which kinds of LLM failure happened during this run."""
    return {e.get("kind", "error") for e in llm_failures()}


def failure_message() -> tuple:
    """
    (title, body) describing why sections are missing.

    Rate limits get specific treatment: a daily cap and a per-minute burst
    are the same HTTP status but completely different advice, and the wait
    time comes from the provider rather than a guess.
    """
    failures = llm_failures()
    kinds = {f.get("kind", "error") for f in failures}

    if "rate_limit" in kinds:
        rl = next(f for f in failures if f.get("kind") == "rate_limit")
        wait = rl.get("retry_after") or "a few minutes"
        if rl.get("daily"):
            return (
                "You've used up today's AI quota.",
                f"The free Groq tier allows 200,000 tokens per day and a full plan "
                f"needs around 20,000. It resets in {wait}. You can also raise the "
                f"limit on your Groq billing page.",
            )
        return (
            "The AI service is rate-limiting us right now.",
            f"The free tier allows 8,000 tokens per minute and a full plan needs "
            f"more than that, so calls get queued. Try again in {wait}.",
        )

    for k in ("auth", "empty_response", "error"):
        if k in kinds:
            return MISSING_HINT[k]
    return MISSING_HINT["error"]


def replan() -> None:
    """Re-run the stored request, skipping the cache so a failed plan is not reused."""
    req = st.session_state.request
    if req is None:
        reset(); st.rerun(); return
    with st.spinner("Re-planning…"):
        started = time.time()
        result = run_travel_pipeline(req, use_cache=False)
    st.session_state.update(
        plan=result.get("final_plan"), result=result,
        elapsed=time.time() - started, request=req,
    )
    st.rerun()


def render_missing(what: str) -> None:
    """
    Explain WHY a section is empty.

    Every one of these is an upstream failure the pipeline swallowed on
    purpose so a single bad call could not kill the run. Swallowing it in the
    UI too is what turned a rate limit into an unexplained blank tab.
    """
    kinds = failure_kinds()
    kind = ("rate_limit" if "rate_limit" in kinds
            else "auth" if "auth" in kinds
            else "empty_response" if "empty_response" in kinds
            else "error" if kinds else None)

    if kind is None:
        st.markdown(
            f'<div class="empty"><div class="empty-title">No {what} in this plan</div>'
            f'<div class="empty-body">Try re-planning — this section came back blank.</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    title, body = failure_message()
    st.markdown(
        f'<div class="empty"><div class="empty-title">{title}</div>'
        f'<div class="empty-body">{body}</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Try again", key=f"retry_{what}", type="secondary"):
        replan()


SOURCE_LABEL = {
    "weather": "weather", "maps": "travel times", "hotel": "hotel prices",
    "restaurant": "restaurants", "flight": "flight prices",
}


def render_trust(plan) -> None:
    """
    Say plainly which parts of the plan are real.

    Phrased for a traveller, not an engineer: "sample data" rather than
    "mock", and framed as what to do about it.
    """
    sources = plan.data_sources or {}
    mocked = plan.mocked_sources
    if sources and mocked:
        names = ", ".join(SOURCE_LABEL.get(m, m) for m in mocked)
        st.markdown(
            f'<div class="notice notice-warn">'
            f"<b>Some figures are examples, not live data.</b><br/>"
            f"The {esc(names)} shown here come from sample data, so treat them as "
            f"a guide to what to expect rather than prices to book on. Everything "
            f"else in the plan is real.</div>",
            unsafe_allow_html=True,
        )

    grounding = plan.rag_grounding or {}
    if grounding and not any(grounding.values()):
        st.markdown(
            '<div class="notice notice-info">'
            "<b>This destination isn't in our guidebook yet.</b><br/>"
            "We've planned it from general knowledge rather than our own research, "
            "so double-check opening times and prices before you commit.</div>",
            unsafe_allow_html=True,
        )


def render_plan() -> None:
    plan = st.session_state.plan
    req = st.session_state.request
    result = st.session_state.result or {}
    cached = result.get("from_cache")

    if plan is None:
        st.markdown(
            '<div class="notice notice-warn"><b>We couldn\'t finish this plan.</b><br/>'
            "Please try again in a moment.</div>",
            unsafe_allow_html=True,
        )
        for e in result.get("errors", []):
            st.markdown(f'<div class="caption">{esc(e)}</div>', unsafe_allow_html=True)
        if st.button("Start over", type="secondary"):
            reset(); st.rerun()
        return

    nights = (
        date.fromisoformat(req.return_date) - date.fromisoformat(req.departure_date)
    ).days

    # ── Header ────────────────────────────────────────────
    st.markdown(
        f"""<div class="trip-head">
              <div class="eyebrow">Your itinerary</div>
              <div class="trip-route">{esc(req.origin)} → {esc(req.destination)}</div>
              <div class="trip-meta">{esc(req.departure_date)} – {esc(req.return_date)}
                · {nights} nights · {req.travellers} traveller(s)</div>
              <div class="trip-summary">{esc(plan.executive_summary)}</div>
            </div>""",
        unsafe_allow_html=True,
    )

    total = getattr(plan.budget, "total_trip_cost_usd", None) if plan.budget else None
    st.markdown(
        f"""<div class="stats">
              <div><div class="stat-k">Estimated cost</div>
                   <div class="stat-v">{'$' + format(total, ',.0f') if total else '—'}</div></div>
              <div><div class="stat-k">Your budget</div>
                   <div class="stat-v">${req.budget_usd:,.0f}</div></div>
              <div><div class="stat-k">Nights</div>
                   <div class="stat-v">{nights}</div></div>
              <div><div class="stat-k">Travellers</div>
                   <div class="stat-v">{req.travellers}</div></div>
            </div>""",
        unsafe_allow_html=True,
    )
    if cached:
        st.markdown(
            '<div class="caption" style="margin-bottom:0.8rem;">'
            "Saved from an earlier plan for these exact details.</div>",
            unsafe_allow_html=True,
        )

    kinds = failure_kinds()
    missing = [n for n, v in [
        ("itinerary", plan.route), ("stay", plan.hotels),
        ("food", plan.food), ("weather", plan.weather), ("budget", plan.budget),
    ] if v is None]
    if missing:
        title, body = failure_message()
        st.markdown(
            f'<div class="notice notice-warn"><b>This plan is incomplete — '
            f'{esc(", ".join(missing))} {"are" if len(missing) > 1 else "is"} missing.'
            f'</b><br/>{title} {body}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Try again", key="retry_top", type="secondary"):
            replan()

    render_trust(plan)

    tabs = st.tabs(["Itinerary", "Where to stay", "Food & drink", "Weather", "Budget"])

    with tabs[0]:
        render_itinerary(plan)
    with tabs[1]:
        render_stay(plan)
    with tabs[2]:
        render_food(plan)
    with tabs[3]:
        render_weather(plan)
    with tabs[4]:
        render_budget(plan, req)

    st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
    slug = req.destination.lower().replace(" ", "-")
    c1, c2, c3 = st.columns([1.2, 1, 1])

    # PDF first: it is the artefact a traveller can actually use — print it,
    # forward it, open it at the gate. JSON stays available for anyone wiring
    # this into something else.
    try:
        c1.download_button(
            "Download itinerary (PDF)",
            data=build_itinerary_pdf(plan, req),
            file_name=f"{slug}-itinerary.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    except Exception as e:
        c1.markdown(
            f'<div class="caption">Could not build the PDF ({esc(e)}).</div>',
            unsafe_allow_html=True,
        )

    c2.download_button(
        "Data (JSON)",
        data=plan.model_dump_json(indent=2),
        file_name=f"{slug}-itinerary.json",
        mime="application/json",
        use_container_width=True,
    )
    if c3.button("Plan another trip", type="secondary", use_container_width=True):
        reset(); st.rerun()

    warnings = [w for w in (plan.warnings or []) if not w.startswith("[DataSources]")]
    if warnings:
        with st.expander(f"Things worth checking ({len(warnings)})"):
            for w in warnings:
                clean = w.split("] ", 1)[-1] if w.startswith("[") else w
                st.markdown(
                    f'<div style="padding:0.3rem 0;font-size:0.9rem;color:#9AA5B8;">'
                    f"· {esc(clean)}</div>",
                    unsafe_allow_html=True,
                )


def render_itinerary(plan) -> None:
    route = plan.route
    if not route:
        render_missing("itinerary")
        return

    if route.best_route_summary:
        st.markdown(
            f'<div class="card card-tight"><div class="stat-k">Getting there</div>'
            f'<div style="margin-top:0.4rem;line-height:1.6;">{esc(route.best_route_summary)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    for day in route.day_wise_itinerary:
        acts = "".join(f'<div class="act">{esc(a)}</div>' for a in day.activities)
        st.markdown(
            f"""<div class="day">
                  <div class="day-head">
                    <span class="day-n">Day {day.day}</span>
                    <span class="day-date">{esc(day.date)}</span>
                    <span class="day-cost">${day.estimated_cost_usd:,.0f}</span>
                  </div>
                  {acts}
                  <div class="day-foot">
                    <span>Getting around · {esc(day.transportation)}</span>
                    <span>Staying · {esc(day.accommodation)}</span>
                  </div>
                </div>""",
            unsafe_allow_html=True,
        )


def render_stay(plan) -> None:
    hotels = plan.hotels
    if not hotels:
        render_missing("accommodation")
        return

    if hotels.recommended_area:
        st.markdown(
            f'<div class="card card-tight"><div class="stat-k">Best area to base yourself</div>'
            f'<div style="margin-top:0.4rem;line-height:1.6;">{esc(hotels.recommended_area)}</div></div>',
            unsafe_allow_html=True,
        )

    for label, group in [
        ("Good value", hotels.budget_hotels),
        ("A step up", hotels.premium_hotels),
        ("Good for families", hotels.family_hotels),
    ]:
        if not group:
            continue
        st.markdown(f'<div class="stat-k" style="margin:1.1rem 0 0.5rem;">{label}</div>',
                    unsafe_allow_html=True)
        for h in group:
            tags = "".join(f'<span class="tag">{esc(a)}</span>' for a in (h.amenities or [])[:5])
            st.markdown(
                f"""<div class="listing">
                      <div class="listing-top">
                        <span class="listing-name">{esc(h.name)}</span>
                        <span class="caption">★ {h.rating:g}</span>
                        <span class="listing-price">${h.price_per_night_usd:,.0f}<span
                          class="caption"> / night</span></span>
                      </div>
                      <div class="listing-sub">{esc(h.location_description)}</div>
                      <div class="listing-sub" style="color:#6B7789;">{esc(h.booking_tip)}</div>
                      <div class="listing-tags">{tags}</div>
                    </div>""",
                unsafe_allow_html=True,
            )


def render_food(plan) -> None:
    food = plan.food
    if not food:
        render_missing("food")
        return

    if food.average_meal_cost_usd:
        st.markdown(
            f'<div class="card card-tight"><div class="stat-k">Typical meal</div>'
            f'<div class="stat-v">${food.average_meal_cost_usd:,.0f}'
            f'<span class="caption" style="font-size:0.85rem;"> per person</span></div></div>',
            unsafe_allow_html=True,
        )

    for label, items in [
        ("Don't leave without trying", food.local_specialties),
        ("Vegetarian", food.vegetarian_dishes),
        ("Meat & seafood", food.non_vegetarian_dishes),
        ("Street food", food.street_food_recommendations),
    ]:
        if not items:
            continue
        tags = "".join(f'<span class="tag">{esc(i)}</span>' for i in items)
        st.markdown(
            f'<div style="margin-bottom:0.9rem;"><div class="stat-k" '
            f'style="margin-bottom:0.4rem;">{label}</div>{tags}</div>',
            unsafe_allow_html=True,
        )

    if food.restaurant_suggestions:
        st.markdown('<div class="stat-k" style="margin:1.2rem 0 0.5rem;">Where to eat</div>',
                    unsafe_allow_html=True)
        for r in food.restaurant_suggestions:
            st.markdown(
                f"""<div class="listing">
                      <div class="listing-top">
                        <span class="listing-name">{esc(r.name)}</span>
                        <span class="caption">★ {r.rating:g} · {esc(r.price_range)}</span>
                      </div>
                      <div class="listing-sub">{esc(r.cuisine_type)} — try the
                        {esc(r.must_try_dish)}</div>
                      <div class="listing-sub" style="color:#6B7789;">{esc(r.location_hint)}</div>
                    </div>""",
                unsafe_allow_html=True,
            )

    if food.food_safety_tips:
        with st.expander("Eating safely"):
            for t in food.food_safety_tips:
                st.markdown(f'<div class="act">{esc(t)}</div>', unsafe_allow_html=True)


def render_weather(plan) -> None:
    w = plan.weather
    if not w:
        render_missing("weather")
        return

    st.markdown(
        f"""<div class="card">
              <div class="stats">
                <div><div class="stat-k">Conditions</div>
                     <div class="stat-v">{esc(w.condition)}</div></div>
                <div><div class="stat-k">Temperature</div>
                     <div class="stat-v">{w.current_temp_celsius:g}°C</div></div>
                <div><div class="stat-k">Humidity</div>
                     <div class="stat-v">{w.humidity_percent}%</div></div>
                <div><div class="stat-k">Wind</div>
                     <div class="stat-v">{w.wind_speed_kmh:.0f} km/h</div></div>
              </div>
            </div>""",
        unsafe_allow_html=True,
    )

    if w.travel_warnings:
        for warn in w.travel_warnings:
            st.markdown(
                f'<div class="notice notice-warn">{esc(warn)}</div>',
                unsafe_allow_html=True,
            )

    if w.clothing_suggestions:
        tags = "".join(f'<span class="tag">{esc(c)}</span>' for c in w.clothing_suggestions)
        st.markdown(
            f'<div style="margin:1rem 0;"><div class="stat-k" '
            f'style="margin-bottom:0.4rem;">What to pack</div>{tags}</div>',
            unsafe_allow_html=True,
        )

    if w.forecast_7days:
        st.markdown('<div class="stat-k" style="margin:1.2rem 0 0.5rem;">Day by day</div>',
                    unsafe_allow_html=True)
        rows = ""
        for d in w.forecast_7days[:7]:
            hi = d.get("temp_high", d.get("high", "—"))
            lo = d.get("temp_low", d.get("low", "—"))
            cond = d.get("condition", d.get("description", ""))
            rows += (
                f'<div style="display:flex;padding:0.5rem 0;border-bottom:1px solid #232A38;'
                f'font-size:0.92rem;"><span style="width:9rem;color:#9AA5B8;">'
                f'{esc(d.get("date","—"))}</span><span style="flex:1;">{esc(cond)}</span>'
                f'<span style="color:#9AA5B8;">{esc(hi)}° / {esc(lo)}°</span></div>'
            )
        st.markdown(f'<div class="card card-tight">{rows}</div>', unsafe_allow_html=True)


def render_budget(plan, req) -> None:
    b = plan.budget
    if not b:
        render_missing("budget")
        return

    bd = b.per_person_breakdown
    over = b.total_trip_cost_usd > req.budget_usd
    st.markdown(
        f"""<div class="card">
              <div class="stats">
                <div><div class="stat-k">Total trip</div>
                     <div class="stat-v" style="color:{'#CC6B6B' if over else '#5FB88A'};">
                       ${b.total_trip_cost_usd:,.0f}</div></div>
                <div><div class="stat-k">Per person</div>
                     <div class="stat-v">${bd.total_usd:,.0f}</div></div>
                <div><div class="stat-k">Your budget</div>
                     <div class="stat-v">${req.budget_usd:,.0f}</div></div>
              </div>
              <div class="caption" style="margin-top:0.6rem;">
                {'Over budget by $' + format(b.total_trip_cost_usd - req.budget_usd, ',.0f')
                 if over else
                 '$' + format(req.budget_usd - b.total_trip_cost_usd, ',.0f') + ' to spare'}
                 · {esc(b.currency_info)}</div>
            </div>""",
        unsafe_allow_html=True,
    )

    rows = ""
    for label, value in [
        ("Flights", bd.flights_usd), ("Accommodation", bd.accommodation_usd),
        ("Food", bd.food_usd), ("Local transport", bd.local_transport_usd),
        ("Activities", bd.activities_usd), ("Other", bd.miscellaneous_usd),
    ]:
        pct = (value / bd.total_usd * 100) if bd.total_usd else 0
        rows += (
            f'<div style="padding:0.55rem 0;border-bottom:1px solid #232A38;">'
            f'<div style="display:flex;font-size:0.93rem;">'
            f'<span style="flex:1;">{label}</span>'
            f'<span style="color:#9AA5B8;">${value:,.0f}</span></div>'
            f'<div style="height:3px;background:#232A38;border-radius:2px;margin-top:0.4rem;">'
            f'<div style="height:3px;width:{pct:.0f}%;background:#E0A458;border-radius:2px;">'
            f'</div></div></div>'
        )
    st.markdown(
        f'<div class="card card-tight"><div class="stat-k" style="margin-bottom:0.5rem;">'
        f'Per person</div>{rows}</div>',
        unsafe_allow_html=True,
    )

    if b.saving_tips:
        st.markdown('<div class="stat-k" style="margin:1.2rem 0 0.5rem;">Ways to spend less</div>',
                    unsafe_allow_html=True)
        for tip in b.saving_tips:
            st.markdown(f'<div class="act">{esc(tip)}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# Route
# ══════════════════════════════════════════════════════════════
if st.session_state.plan is None and st.session_state.result is None:
    render_search()
else:
    render_plan()
