# ============================================================
# memory/store.py — Persistent run history + plan cache
# ============================================================
# PURPOSE:
#   A durable record of every plan the system has produced, and a cache so an
#   identical request is answered instantly instead of re-running the graph.
#
# WHY:
#   Before this, nothing survived a run. `MemorySaver` was constructed fresh
#   inside run_travel_pipeline(), so LangGraph's checkpoints were discarded
#   the moment the call returned — asking for the same trip twice cost the
#   same ~4 minutes and ~19k tokens both times.
#
#   It also gives the quality harness somewhere to compare against: metrics
#   are stored next to the prompt version that produced them, so "did this
#   prompt change make things worse" becomes a SQL query rather than a
#   recollection.
#
# SQLite on purpose — one file, no service to run, and the whole point is
# that it outlives the process.
# ============================================================

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "memory.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    request_key     TEXT NOT NULL,
    origin          TEXT,
    destination     TEXT,
    departure_date  TEXT,
    return_date     TEXT,
    travellers      INTEGER,
    budget_usd      REAL,
    prompt_version  TEXT,
    trace_id        TEXT,
    latency_s       REAL,
    plan_json       TEXT,
    metrics_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_key     ON runs(request_key);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_version ON runs(prompt_version);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def request_key(request: Any) -> str:
    """
    Stable hash of the fields that actually change the plan.

    Only these fields participate: two requests differing solely in, say, a
    free-text note still describe the same trip, but a different budget or
    diet produces a genuinely different plan and must miss the cache.
    """
    parts = [
        str(getattr(request, f, ""))
        for f in (
            "origin", "destination", "departure_date", "return_date",
            "travellers", "budget_usd", "travel_purpose",
            "dietary_preference", "accommodation_preference",
        )
    ]
    joined = "|".join(p.strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def save_run(
    request: Any,
    plan: Any,
    metrics: Optional[Dict[str, Any]] = None,
    prompt_version: str = "",
    trace_id: str = "",
    latency_s: Optional[float] = None,
) -> str:
    """Persist one completed run. Returns its run_id."""
    run_id = str(uuid.uuid4())[:12]
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO runs (
                    run_id, created_at, request_key, origin, destination,
                    departure_date, return_date, travellers, budget_usd,
                    prompt_version, trace_id, latency_s, plan_json, metrics_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    request_key(request),
                    getattr(request, "origin", ""),
                    getattr(request, "destination", ""),
                    getattr(request, "departure_date", ""),
                    getattr(request, "return_date", ""),
                    int(getattr(request, "travellers", 0) or 0),
                    float(getattr(request, "budget_usd", 0) or 0),
                    prompt_version,
                    trace_id,
                    latency_s,
                    plan.model_dump_json() if plan is not None else None,
                    json.dumps(metrics or {}),
                ),
            )
        logger.info(f"[Memory] Saved run {run_id} for {getattr(request,'destination','?')}")
    except Exception as e:
        # Never let bookkeeping break a successful plan.
        logger.warning(f"[Memory] Could not save run: {e}")
    return run_id


def get_cached_plan(request: Any, max_age_hours: int = 168) -> Optional[Any]:
    """
    Return a stored plan for an identical request, or None.

    Cached plans expire (default 7 days) because a travel plan embeds
    weather and prices that go stale. The staleness window is generous
    precisely because the tool data here is usually fixtures anyway; shorten
    it once real API keys are configured.
    """
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours))
        cutoff_s = cutoff.isoformat(timespec="seconds") + "Z"
        with _connect() as conn:
            row = conn.execute(
                """SELECT plan_json, run_id, created_at FROM runs
                   WHERE request_key = ? AND plan_json IS NOT NULL
                     AND created_at >= ?
                   ORDER BY created_at DESC LIMIT 1""",
                (request_key(request), cutoff_s),
            ).fetchone()
        if not row:
            return None

        from models.models import TravelPlan
        plan = TravelPlan.model_validate_json(row["plan_json"])
        logger.info(
            f"[Memory] Cache HIT for {getattr(request,'destination','?')} "
            f"(run {row['run_id']} from {row['created_at']})"
        )
        return plan
    except Exception as e:
        logger.warning(f"[Memory] Cache lookup failed ({e}) — running fresh")
        return None


def recent_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """Most recent runs, newest first, without the (large) plan JSON."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT run_id, created_at, origin, destination,
                          departure_date, return_date, travellers, budget_usd,
                          prompt_version, latency_s, metrics_json
                   FROM runs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
            out.append(d)
        return out
    except Exception as e:
        logger.warning(f"[Memory] Could not read history: {e}")
        return []


def quality_by_prompt_version() -> List[Dict[str, Any]]:
    """
    Average the stored metrics per prompt version.

    This is what makes prompt changes measurable rather than vibes-based:
    ship a new PROMPT_VERSION, run a few plans, compare the rows.
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT prompt_version, metrics_json, latency_s FROM runs"
            ).fetchall()
    except Exception as e:
        logger.warning(f"[Memory] Could not aggregate: {e}")
        return []

    buckets: Dict[str, List[dict]] = {}
    for r in rows:
        try:
            m = json.loads(r["metrics_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if m:
            buckets.setdefault(r["prompt_version"] or "(unversioned)", []).append(m)

    summary = []
    for version, ms in sorted(buckets.items()):
        def avg(key: str) -> Optional[float]:
            vals = [float(m[key]) for m in ms
                    if isinstance(m.get(key), (int, float, bool))]
            return round(sum(vals) / len(vals), 3) if vals else None

        summary.append({
            "prompt_version": version,
            "runs": len(ms),
            "section_completeness": avg("section_completeness"),
            "synthesis_ok": avg("synthesis_ok"),
            "grounding_ratio": avg("grounding_ratio"),
            "live_data_ratio": avg("live_data_ratio"),
            "itinerary_ok": avg("itinerary_ok"),
            "guardrail_warnings": avg("guardrail_warnings"),
            "latency_s": avg("latency_s"),
        })
    return summary


def ungrounded_demand(min_requests: int = 1) -> List[Dict[str, Any]]:
    """
    Destinations people actually asked for that the knowledge base could not answer.

    This is the one distillation of episodic memory that is safe to act on here.
    The tempting version — summarising past plans into "durable facts" and
    feeding them back into the vector store — would promote the model's own
    output (hallucinations and fixture prices included) to retrievable ground
    truth, and destroy the property that every retrieved chunk traces to a
    real source. This instead extracts a *fact about demand*, which is
    observed rather than generated, and hands it to a human to act on.

    Returns [{destination, requests, last_asked}] ranked by demand.
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT destination, created_at, metrics_json FROM runs "
                "WHERE destination IS NOT NULL AND destination != ''"
            ).fetchall()
    except Exception as e:
        logger.warning(f"[Memory] Could not read demand: {e}")
        return []

    demand: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            m = json.loads(r["metrics_json"] or "{}")
        except json.JSONDecodeError:
            continue
        ratio = m.get("grounding_ratio")
        if ratio is None or ratio > 0:
            continue          # it was grounded, or we never measured it
        key = r["destination"].strip().lower()
        entry = demand.setdefault(
            key, {"destination": r["destination"].strip().title(),
                  "requests": 0, "last_asked": ""}
        )
        entry["requests"] += 1
        entry["last_asked"] = max(entry["last_asked"], r["created_at"] or "")

    # Drop anything since ingested — the gap is already closed.
    try:
        from rag.ingest import corpus_destinations
        from rag.rag import _destination_key
        covered = {_destination_key(d) for d in corpus_destinations()}
        demand = {
            k: v for k, v in demand.items()
            if _destination_key(k) not in covered
        }
    except Exception as e:
        logger.debug(f"[Memory] Could not cross-check the corpus: {e}")

    out = [v for v in demand.values() if v["requests"] >= min_requests]
    return sorted(out, key=lambda d: (-d["requests"], d["destination"]))


def stats() -> Dict[str, Any]:
    """Headline counts for the UI."""
    try:
        with _connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS runs,
                          COUNT(DISTINCT destination) AS destinations,
                          AVG(latency_s) AS avg_latency
                   FROM runs"""
            ).fetchone()
        return {
            "runs": row["runs"] or 0,
            "destinations": row["destinations"] or 0,
            "avg_latency": round(row["avg_latency"], 1) if row["avg_latency"] else None,
        }
    except Exception:
        return {"runs": 0, "destinations": 0, "avg_latency": None}


__all__ = [
    "save_run", "get_cached_plan", "recent_runs",
    "quality_by_prompt_version", "ungrounded_demand", "stats",
    "request_key", "DB_PATH", "DB_DIR",
]
