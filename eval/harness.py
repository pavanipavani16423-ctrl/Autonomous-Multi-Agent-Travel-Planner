# ============================================================
# eval/harness.py — Prompt & pipeline quality gate
# ============================================================
# PURPOSE:
#   Run a fixed set of travel requests through the real pipeline, score the
#   results against thresholds, and exit non-zero if anything regressed.
#
# WHY THIS AND NOT A SELF-REWRITING PROMPT LOOP:
#   The valuable half of "self-improving prompts" is the measurement, not the
#   rewriting. Once you can tell whether a prompt change made things worse,
#   improving them is easy and safe. Without that, an automated rewriter is
#   just an unreviewed change with extra steps.
#
#   Everything scored here is deterministic — did each agent's output parse,
#   did the synthesis land, does the itinerary match the dates, was the plan
#   grounded. No LLM judge: a judge sharing a model family with the system it
#   grades is not independent enough to gate a release on.
#
#   Concretely, this would have caught the FinalPlanner bug that made every
#   run silently fall back to a canned summary for weeks (`synthesis_ok`).
#
# USAGE:
#   python -m eval.harness                 # full suite (~4 cases, ~15 min)
#   python -m eval.harness --quick         # 1 case
#   python -m eval.harness --compare       # metrics per prompt version
#   python -m eval.harness --history       # recent runs
#
# Exit code 0 = release, 1 = regression. Suitable for CI.
# ============================================================

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# A stock Windows console is cp1252 and raises UnicodeEncodeError on the
# arrows and dashes used below, killing the command mid-report. Force UTF-8
# and degrade anything unmappable rather than crashing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


from loguru import logger

from models.models import TravelRequest
from memory.metrics import plan_metrics, check_thresholds, THRESHOLDS
from memory.store import quality_by_prompt_version, recent_runs
from prompts.prompts import PROMPT_VERSION


def _future(days: int) -> str:
    """Dates must be in the future or input guardrails reject the request."""
    return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")


# ── The suite ────────────────────────────────────────────────
# Chosen to exercise genuinely different paths, not to pad the count:
#   grounded      — destination the corpus covers; grounding must be > 0
#   ungrounded    — destination it does not; must NOT invent grounding
#   short_trip    — 1 night, the itinerary/date edge case
#   large_group   — 8 travellers on a tight budget, stresses the costing
CASES: List[Dict[str, Any]] = [
    {
        "name": "grounded",
        "request": dict(
            origin="Mumbai", destination="Paris",
            departure_date=_future(45), return_date=_future(50),
            travellers=2, budget_usd=4000, travel_purpose="leisure",
            dietary_preference="vegetarian", accommodation_preference="mid-range",
        ),
        "expect": {"grounding_ratio_min": 0.34},
    },
    {
        "name": "ungrounded",
        "request": dict(
            origin="Mumbai", destination="Asuncion",
            departure_date=_future(60), return_date=_future(64),
            travellers=1, budget_usd=1500, travel_purpose="adventure",
            dietary_preference="no preference", accommodation_preference="budget",
        ),
        # The corpus has no Asuncion. Reporting grounding here would mean the
        # destination filter had let another city's facts through.
        # (Tashkent used to be this case, until it got ingested - pick a
        # destination that is genuinely absent, and re-check if you ingest it.)
        "expect": {"grounding_ratio_max": 0.0},
    },
    {
        "name": "short_trip",
        "request": dict(
            origin="Delhi", destination="Jaipur",
            departure_date=_future(30), return_date=_future(31),
            travellers=2, budget_usd=400, travel_purpose="family",
            dietary_preference="vegetarian", accommodation_preference="budget",
        ),
        "expect": {},
    },
    {
        "name": "large_group",
        "request": dict(
            origin="London", destination="Rome",
            departure_date=_future(70), return_date=_future(75),
            travellers=8, budget_usd=6000, travel_purpose="family",
            dietary_preference="no preference", accommodation_preference="budget",
        ),
        "expect": {},
    },
]


def run_case(case: Dict[str, Any], use_cache: bool,
             with_ragas: bool = False) -> Dict[str, Any]:
    """Execute one case and return its metrics plus per-case expectations."""
    from graph.graph import run_travel_pipeline

    request = TravelRequest(**case["request"])
    print(f"  running {case['name']:12} {request.origin} → {request.destination} …",
          end="", flush=True)

    started = time.time()
    state = run_travel_pipeline(request, use_cache=use_cache)
    elapsed = time.time() - started

    metrics = state.get("metrics") or plan_metrics(state, latency_s=elapsed)
    verdict = check_thresholds(metrics)

    # Case-specific expectations on top of the global thresholds.
    for key, bound in case.get("expect", {}).items():
        metric = key.rsplit("_", 1)[0]
        value = metrics.get(metric)
        if value is None:
            continue
        if key.endswith("_min") and value < bound:
            verdict["failures"].append(f"{metric}={value:g} below expected min {bound:g}")
        elif key.endswith("_max") and value > bound:
            verdict["failures"].append(f"{metric}={value:g} above expected max {bound:g}")
    verdict["passed"] = not verdict["failures"]

    print(f" {'PASS' if verdict['passed'] else 'FAIL'} ({elapsed:.0f}s"
          + (", cached" if state.get("from_cache") else "") + ")")

    ragas = None
    if with_ragas:
        # Deliberately outside the threshold gate: RAGAS is a judge, and a
        # judge sharing a model family with the system it grades is not
        # independent enough to block a release on. Reported, not enforced.
        from eval.ragas_eval import evaluate_run
        print(f"  {'':12} scoring retrieval with RAGAS…", end="", flush=True)
        ragas = evaluate_run(state)
        print(" " + (", ".join(f"{k}={v}" for k, v in ragas.items())
                     if ragas else "unavailable"))

    return {"name": case["name"], "metrics": metrics,
            "verdict": verdict, "ragas": ragas}


def print_report(results: List[Dict[str, Any]]) -> bool:
    """Render the scorecard. Returns True when every case passed."""
    print("\n" + "=" * 78)
    print(f"QUALITY REPORT — prompt version {PROMPT_VERSION}")
    print("=" * 78)

    cols = ["section_completeness", "synthesis_ok", "grounding_ratio",
            "live_data_ratio", "itinerary_ok", "latency_s"]
    print(f"{'case':13}" + "".join(f"{c[:15]:>17}" for c in cols))
    print("-" * 78)
    for r in results:
        m = r["metrics"]
        row = "".join(
            f"{(f'{m[c]:g}' if isinstance(m.get(c), (int, float)) and not isinstance(m.get(c), bool) else str(m.get(c))):>17}"
            for c in cols
        )
        print(f"{r['name']:13}{row}")

    if any(r.get("ragas") for r in results):
        print()
        print(f"{'case':13}{'faithfulness':>17}{'answer relevancy':>19}{'samples':>10}")
        print("-" * 78)
        for r in results:
            g = r.get("ragas")
            if not g:
                print(f"{r['name']:13}{'—':>17}{'—':>19}{'—':>10}")
                continue
            print(f"{r['name']:13}{g.get('faithfulness','—'):>17}"
                  f"{g.get('answer_relevancy','—'):>19}{g.get('samples','—'):>10}")

    failed = [r for r in results if not r["verdict"]["passed"]]
    print("-" * 78)
    if failed:
        print(f"\n{len(failed)} of {len(results)} cases FAILED:\n")
        for r in failed:
            print(f"  {r['name']}:")
            for f in r["verdict"]["failures"]:
                print(f"    - {f}")
        print("\nRESULT: BLOCKED — do not ship this prompt change.")
        return False

    print(f"\nAll {len(results)} cases passed "
          f"({results[0]['verdict']['checked']} thresholds each).")
    print("RESULT: OK to release.")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline quality gate.")
    parser.add_argument("--ragas", action="store_true",
                        help="Also score retrieval quality with RAGAS "
                             "(LLM judge — several extra model calls per case).")
    parser.add_argument("--quick", action="store_true",
                        help="Run only the first case.")
    parser.add_argument("--case", help="Run one named case.")
    parser.add_argument("--no-cache", action="store_true",
                        help="Force fresh runs instead of reusing stored plans.")
    parser.add_argument("--compare", action="store_true",
                        help="Show stored metrics grouped by prompt version.")
    parser.add_argument("--history", action="store_true",
                        help="Show recent runs.")
    args = parser.parse_args(argv)

    if args.compare:
        rows = quality_by_prompt_version()
        if not rows:
            print("No runs recorded yet. Run the harness or generate a plan first.")
            return 1
        print(f"\n{'version':14}{'runs':>6}{'complete':>10}{'synth':>8}"
              f"{'ground':>8}{'live':>8}{'warns':>8}{'latency':>9}")
        print("-" * 71)
        for r in rows:
            def fmt(v):
                return f"{v:g}" if isinstance(v, (int, float)) else "-"
            print(f"{r['prompt_version']:14}{r['runs']:>6}"
                  f"{fmt(r['section_completeness']):>10}{fmt(r['synthesis_ok']):>8}"
                  f"{fmt(r['grounding_ratio']):>8}{fmt(r['live_data_ratio']):>8}"
                  f"{fmt(r['guardrail_warnings']):>8}{fmt(r['latency_s']):>9}")
        return 0

    if args.history:
        rows = recent_runs(15)
        if not rows:
            print("No runs recorded yet.")
            return 1
        print(f"\n{'when':21}{'trip':34}{'version':10}{'latency':>9}")
        print("-" * 74)
        for r in rows:
            trip = f"{r['origin']} -> {r['destination']}"
            lat = f"{r['latency_s']:.0f}s" if r["latency_s"] else "-"
            print(f"{r['created_at']:21}{trip[:33]:34}"
                  f"{(r['prompt_version'] or '-'):10}{lat:>9}")
        return 0

    cases = CASES
    if args.case:
        cases = [c for c in CASES if c["name"] == args.case]
        if not cases:
            print(f"No case named '{args.case}'. "
                  f"Available: {', '.join(c['name'] for c in CASES)}")
            return 1
    elif args.quick:
        cases = CASES[:1]

    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    print(f"\nRunning {len(cases)} case(s) against prompt version {PROMPT_VERSION}")
    print(f"Thresholds: {', '.join(f'{k}>={v:g}' for k, v in THRESHOLDS.items())}\n")

    # RAGAS scores the passages a run retrieved, and a cached plan does not
    # keep them — so --ragas necessarily means a fresh run.
    use_cache = not args.no_cache and not args.ragas
    if args.ragas and not args.no_cache:
        print("(--ragas needs the retrieved passages, so the cache is bypassed)")
        print()

    results = [run_case(c, use_cache=use_cache, with_ragas=args.ragas)
               for c in cases]
    return 0 if print_report(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
