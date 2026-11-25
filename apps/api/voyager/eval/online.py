"""Online quality for every run: cheap, immediate, honest. The six SPEC scores:

* Faithfulness       - LLM judge (critic) share of activities supported by evidence; without a judge,
                       the share of activities whose citations resolve to real evidence
* Answer relevancy   - LLM judge fit to interests/pace/diet, blended 50/50 with a deterministic
                       interest-coverage heuristic (do the plan's activities touch the stated interests?)
* Context precision  - average precision of each guidebook search: were the passages the plan
                       actually cited ranked first? (relevance = cited in the final plan)
* Citation coverage  - share of activities, stays and food picks with at least one valid citation
* Budget fit         - 1.0 within the limit, falling linearly to 0 at 150% of the limit
* Overall            - weighted mean of the above

Offline Ragas (voyager.eval.run) computes the reference-free Ragas versions of the first three.
"""

from __future__ import annotations

from typing import Any

from voyager.schemas import Check, Quality, QualityScore, rating_for

INTEREST_WORDS: dict[str, tuple[str, ...]] = {
    "food": ("food", "eat", "market", "dinner", "lunch", "street", "restaurant", "cafe", "tasting"),
    "temples": ("temple", "shrine", "church", "mosque", "cathedral", "pagoda", "monastery"),
    "nature": ("park", "garden", "hike", "river", "forest", "beach", "lake", "mountain", "nature"),
    "nightlife": ("bar", "night", "club", "izakaya", "pub", "live music", "evening"),
    "art": ("museum", "gallery", "art", "craft"),
    "shopping": ("market", "shop", "bazaar", "mall", "souvenir", "street"),
    "history": ("history", "castle", "palace", "fort", "heritage", "old town", "museum", "ruins", "historic"),
    "adventure": ("hike", "kayak", "climb", "cycle", "bike", "trek", "adventure"),
}


def _avg_precision(ids: list[str], relevant: set[str]) -> float | None:
    if not ids:
        return None
    hits, total = 0, 0.0
    for i, pid in enumerate(ids, 1):
        if pid in relevant:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


def interest_coverage(interests: list[str], acts: list[dict[str, Any]]) -> float:
    if not interests:
        return 1.0
    text = " ".join(f"{a['title']} {a.get('description', '')} {a['category']}" for a in acts).lower()
    hit = 0
    for i in interests:
        words = INTEREST_WORDS.get(i, (i,))
        if any(w in text for w in words):
            hit += 1
    return hit / len(interests)


def _score(name: str, value: float, explain: str) -> QualityScore:
    value = max(0.0, min(1.0, float(value)))
    return QualityScore(name=name, value=round(value, 3), rating=rating_for(value), explain=explain)


def compute_quality(state: dict[str, Any], parts: dict[str, Any], checks: list[Check]) -> Quality:
    evidence = state.get("evidence") or {}
    acts = [a for d in parts["days"] for a in d["activities"]]
    req = state["request"]
    critic = state.get("critic") or {}
    judge = critic.get("judge") or {}
    judged = bool(critic.get("judged"))

    valid_acts = sum(1 for a in acts if any(c in evidence for c in a["citations"]))
    act_cov = valid_acts / len(acts) if acts else 0.0
    items = acts + parts["stays"] + parts["food"]
    cited_items = sum(1 for x in items if any(c in evidence for c in (x.get("citations") or [])))
    grounding = cited_items / len(items) if items else 0.0

    if judged:
        faith = float(judge.get("faithfulness", act_cov))
        faith_explain = f"LLM judge: {faith:.0%} of activities are supported by the cited evidence."
    else:
        faith = act_cov
        faith_explain = f"No judge available: {faith:.0%} of activities cite real evidence (heuristic)."

    cover = interest_coverage(req.get("interests") or [], acts)
    if judged:
        rel = 0.5 * float(judge.get("relevancy", cover)) + 0.5 * cover
        rel_explain = f"Judge fit {float(judge.get('relevancy', 0)):.0%}, interests covered {cover:.0%}."
    else:
        rel = cover
        rel_explain = f"{cover:.0%} of your interests appear in the activities (heuristic)."

    cited_wv = {c for x in items for c in (x.get("citations") or []) if c.startswith("wv-")}
    cited_wv |= set(parts["pre_trip"].get("citations") or [])
    aps = [ap for rec in (state.get("retrieval") or {}).values()
           if (ap := _avg_precision(rec.get("ids") or [], cited_wv)) is not None]
    ctx_prec = sum(aps) / len(aps) if aps else 0.0
    prec_explain = (f"Across {len(aps)} guidebook searches, cited passages ranked first {ctx_prec:.0%} of the time."
                    if aps else "No guidebook searches (destination not covered).")

    cite_explain = f"{cited_items}/{len(items)} activities, stays and food picks cite a guidebook or map source."

    bud = state.get("budget") or {}
    util = float(bud.get("utilisation") or 0)
    fit = 1.0 if util <= 1.0 else max(0.0, 1.0 - (util - 1.0) * 2)
    fit_explain = (f"Total is {util:.0%} of your budget." + (" Within budget." if util <= 1 else " Over budget.")
                   if bud else "Budget unavailable.")

    overall = 0.25 * faith + 0.20 * rel + 0.15 * ctx_prec + 0.20 * grounding + 0.20 * fit
    scores = [
        _score("Faithfulness", faith, faith_explain),
        _score("Answer relevancy", rel, rel_explain),
        _score("Context precision", ctx_prec, prec_explain),
        _score("Citation coverage", grounding, cite_explain),
        _score("Budget fit", fit, fit_explain),
        _score("Overall", overall, "Weighted mean: faithfulness 25%, relevancy 20%, citations 20%, "
                                   "budget 20%, context precision 15%."),
    ]
    guidebook = (state.get("brief") or {}).get("guidebook", "none")
    factor = {"covered": 1.0, "expanded": 0.9, "none": 0.65}.get(guidebook, 0.65)
    critic_ok = critic.get("passed", True)
    confidence = overall * factor * (1.0 if critic_ok else 0.85)
    return Quality(confidence=round(min(1.0, confidence), 3), grounding_coverage=round(grounding, 3),
                   guidebook=guidebook if guidebook in ("covered", "expanded", "none") else "none",
                   checks=checks, scores=scores)
