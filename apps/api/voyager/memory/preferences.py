"""Preference profile per client_id (diet, pace, stay style, interests), learned from requests and
refinements, used to pre-fill `parse`. Plus the plan-cache key."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from voyager.rag.text import destination_key
from voyager.schemas import TripRequest

DIETS = ("vegetarian", "vegan", "halal", "jain", "kosher", "gluten-free")


def learn_from_request(profile: dict[str, Any], req: TripRequest) -> dict[str, Any]:
    p = dict(profile)
    interests = Counter(p.get("interests") or {})
    interests.update(req.interests)
    p["interests"] = dict(interests.most_common(10))
    p["diet"] = sorted(set(req.diet) | set(p.get("diet") or [])) if req.diet else p.get("diet", [])
    p["pace"] = req.pace
    p["stay_style"] = req.stay_style
    p["currency"] = req.currency
    if req.origin:
        p["origin"] = req.origin
    p["trips"] = int(p.get("trips", 0)) + 1
    return p


def learn_from_feedback(profile: dict[str, Any], message: str) -> dict[str, Any]:
    p = dict(profile)
    text = message.lower()
    diet = set(p.get("diet") or [])
    for d in DIETS:
        if re.search(rf"\b{d}\b", text):
            if re.search(rf"\b(not|no longer|don't need)\b[^.]*\b{d}\b", text):
                diet.discard(d)
            else:
                diet.add(d)
    p["diet"] = sorted(diet)
    if re.search(r"\b(slower|relax(ed)?|less packed|fewer|more downtime|take it easy)\b", text):
        p["pace"] = "relaxed"
    elif re.search(r"\b(more packed|busier|more activities|faster|pack more)\b", text):
        p["pace"] = "packed"
    if re.search(r"\b(cheaper|budget|save money|less expensive)\b", text):
        p["stay_style"] = "budget"
    elif re.search(r"\b(luxury|fancier|upscale|5[- ]star)\b", text):
        p["stay_style"] = "luxury"
    return p


def prefill(profile: dict[str, Any]) -> dict[str, Any]:
    """Defaults for a parsed request (only fields the text didn't specify are filled by the caller)."""
    out: dict[str, Any] = {}
    if profile.get("diet"):
        out["diet"] = profile["diet"]
    for k in ("pace", "stay_style", "currency", "origin"):
        if profile.get(k):
            out[k] = profile[k]
    if profile.get("interests"):
        out["interests"] = [k for k, _ in sorted(profile["interests"].items(), key=lambda kv: -kv[1])][:4]
    return out


def cache_key(req: TripRequest) -> str:
    """Identical request -> identical key (normalised destination, dates, party, budget, prefs)."""
    data = {
        "d": destination_key(req.destination), "o": destination_key(req.origin or ""), "s": req.start_date,
        "e": req.end_date, "a": req.adults, "c": req.children, "b": round(req.budget, 2), "cur": req.currency,
        "i": sorted(req.interests), "p": req.pace, "diet": sorted(req.diet), "st": req.stay_style,
        "n": (req.notes or "").strip().lower(),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
