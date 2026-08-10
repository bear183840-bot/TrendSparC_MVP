"""Isolated, low-cost smoke test for sources/collectors/source_router/
planner.py's Search Planner (Solar Pro 3) - one call only, no web_search
execution, no coverage checks, no source inspection. Useful for iterating on
prompts/planner.md and immediately seeing what queries it produces, without
paying for a full research() run.

Does not touch ai_search_harness.py or the rest of the router pipeline.

Usage:
    python scripts/verify_planner_queries.py
    python scripts/verify_planner_queries.py --question "..."
    python scripts/verify_planner_queries.py --purpose-id issue_response --audience executive
"""

from __future__ import annotations

import argparse
import sys
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

import os

from sources.collectors.source_router import _solar
from sources.collectors.source_router import planner as planner_module

_DEFAULT_QUESTION = "중앙그룹 회생 사태에 따른 IPTV사의 대응 방안"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question", default=_DEFAULT_QUESTION)
    parser.add_argument(
        "--audience", default=None,
        choices=["practitioner", "executive", "management", "external"],
        help="Who the resulting report would be shown to (default: unspecified, skips STEP 2.6)",
    )
    parser.add_argument(
        "--purpose-id", default=None, dest="purpose_id",
        choices=["current_status", "issue_response", "future_business", "root_cause"],
        help="What kind of report this is (default: let the planner classify it itself)",
    )
    args = parser.parse_args()

    if not os.environ.get(_solar.API_KEY_ENV_VAR, "").strip():
        raise SystemExit(
            f"{_solar.API_KEY_ENV_VAR} is not set in .env - plan_searches() would just silently "
            "fall back to a single direct-question query, which isn't a real test of planner.md. "
            "Fill it in and re-run."
        )

    plan = planner_module.plan_searches(args.question, audience=args.audience, purpose_id=args.purpose_id)

    print(f"question: {args.question}")
    print(f"intent: {plan.intent}")
    print(f"audience: {plan.audience}")
    print(f"purpose_id: {plan.purpose_id}")
    print(f"query_count: {len(plan.queries)}")
    print()
    for priority in (1, 2, 3):
        queries = plan.by_priority(priority)
        if not queries:
            continue
        print(f"--- priority {priority} ({len(queries)}) ---")
        for q in queries:
            print(f"  query:   {q.query}")
            print(f"  angle:   {q.angle}")
            print(f"  purpose: {q.purpose}")
            print()


if __name__ == "__main__":
    main()
