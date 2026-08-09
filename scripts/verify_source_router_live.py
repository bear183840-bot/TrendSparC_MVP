"""Low-cost live smoke test for sources/collectors/source_router/ (doc1's
new, standalone Search Planner -> web_search -> Coverage/Gap Check ->
(HTML/PDF original-source inspection) router).

This does NOT touch sources/collectors/ai_search_harness.py (the existing
sk_broadband harness) and does not wire the router into any pipeline/sector
- pure standalone verification, same as the router package itself. See
C:\\Users\\noogs\\.claude\\plans\\query-gentle-sketch.md for the full design
history.

Costs real API money once real keys are filled into .env - this script does
NOT run unless TRENDSPARC_SOURCE_ROUTER_SEARCH_API_KEY (GPT-5 mini, the only
component that can actually perform a web search) is set; every other key is
optional and only degrades that one stage to its silent fallback (documented
via a stderr warning, not a crash).

The SourceRouterConfig used here is deliberately cut down from config.py's
defaults (max_priority1_queries=5, max_gap_loop_iterations=3,
max_web_search_calls=8) to a minimal smoke-test budget - this is NOT a change
to the router's real defaults, just this script's own instance, to keep the
first live run's cost low while confirming the keys/wiring actually work
end-to-end.

Usage:
    python scripts/verify_source_router_live.py
    python scripts/verify_source_router_live.py --question "..."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and not sys.stderr.isatty():
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sources.collectors.source_router import SourceRouterConfig, run_source_router

_DEFAULT_QUESTION = "SK브로드밴드 최근 IPTV 서비스 동향은?"

# The only hard requirement - without this, execute_web_search() can't run at
# all, so there is nothing for the router to do.
_REQUIRED_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_API_KEY"

# Missing any of these just means that stage silently falls back (planner ->
# question-as-single-query, coverage -> conservative len(results)>0 check,
# PDF inspection -> skipped) - still runs end-to-end, just degraded.
_OPTIONAL_ENV_VARS = {
    "TRENDSPARC_SOURCE_ROUTER_PLANNER_API_KEY": "Search Planner / Coverage-Gap Check / Evidence Verification / "
    "Section-Chunk Selection (Solar Pro 3) all fall back to their non-AI defaults",
    "FIRECRAWL_API_KEY": "HTML original-source inspection will be skipped (returns None per URL)",
    "TRENDSPARC_SOURCE_ROUTER_UPSTAGE_DOCPARSE_API_KEY": "PDF original-source inspection will be skipped (returns None per URL)",
}


def _check_env() -> None:
    if not os.environ.get(_REQUIRED_ENV_VAR, "").strip():
        raise SystemExit(
            f"{_REQUIRED_ENV_VAR} is not set in .env - this is the GPT-5 mini "
            "web_search key and nothing can run without it. Fill it in .env "
            "(see .env.example) and re-run."
        )
    for var, consequence in _OPTIONAL_ENV_VARS.items():
        if not os.environ.get(var, "").strip():
            print(f"[verify_source_router_live] WARNING: {var} not set - {consequence}.", file=sys.stderr)


def _summarize(result) -> dict:
    depth_counts: dict[str, int] = {}
    for item in result.results:
        depth_counts[item.evidence_depth] = depth_counts.get(item.evidence_depth, 0) + 1
    return {
        "question": result.question,
        "result_count": len(result.results),
        "evidence_depth_counts": depth_counts,
        "rounds_completed": result.rounds_completed,
        "stop_reason": result.stop_reason,
        "final_coverage_sufficient": result.final_coverage.sufficient if result.final_coverage else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", default=_DEFAULT_QUESTION, help="Question to route (default: a low-cost smoke-test question)")
    parser.add_argument(
        "--full-budget",
        action="store_true",
        help="Use SourceRouterConfig's real defaults (max_priority1_queries=5, "
        "max_gap_loop_iterations=3, max_web_search_calls=8) instead of this script's "
        "cut-down smoke-test budget. Costs more - only pass this when the cut-down "
        "budget already ran clean and you want to see what the router does with its "
        "actual intended budget.",
    )
    args = parser.parse_args()

    _check_env()

    config = (
        SourceRouterConfig()
        if args.full_budget
        else SourceRouterConfig(
            max_priority1_queries=2,
            max_gap_loop_iterations=2,
            max_web_search_calls=3,
        )
    )

    print(f"[verify_source_router_live] question={args.question!r}", file=sys.stderr)
    print(
        f"[verify_source_router_live] budget: max_priority1_queries={config.max_priority1_queries} "
        f"max_gap_loop_iterations={config.max_gap_loop_iterations} max_web_search_calls={config.max_web_search_calls} "
        f"max_urls_per_query={config.max_urls_per_query} max_results={config.max_results}",
        file=sys.stderr,
    )

    result = run_source_router(args.question, config=config)

    scratchpad_dir = PROJECT_ROOT / "scratchpad"
    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = scratchpad_dir / f"source_router_live_verification_{timestamp}.json"
    out_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = _summarize(result)
    print("[verify_source_router_live] --- summary ---", file=sys.stderr)
    for key, value in summary.items():
        print(f"[verify_source_router_live] {key}: {value}", file=sys.stderr)
    print(f"[verify_source_router_live] full result written to: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
