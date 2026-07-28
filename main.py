"""Dry-run CLI entrypoint for the TrendSparC_MVP scaffold.

Prints the full per-stage trace (and, when available, the intermediate
contract objects) for a single UserRequest, so the pipeline's structure can
be exercised end-to-end without any external API keys.

Usage:
    python main.py --question "SK하이닉스 HBM 시장 전망은?" --audience practitioner
    python main.py --request-file examples/requests/sample_request.json
    python main.py --question "..." --sector sk_totally_made_up
    python main.py --question "..." --force-fail-stage intent
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

from common.contracts import UserRequest
from core.request_pipeline.pipeline import run_pipeline


def _build_request(args: argparse.Namespace) -> UserRequest:
    if args.request_file:
        payload = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
        return UserRequest.model_validate(payload)

    if not args.question:
        raise SystemExit("either --question or --request-file is required")

    return UserRequest(
        request_id=f"req_cli_{uuid.uuid4().hex[:8]}",
        question=args.question,
        target_audience=args.audience,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendSparC_MVP dry-run pipeline CLI")
    parser.add_argument("--question", help="user question text")
    parser.add_argument("--request-file", help="path to a JSON file matching the UserRequest contract")
    parser.add_argument("--audience", default=None, help="target audience id (default: practitioner)")
    parser.add_argument("--sector", default=None, help="explicit sector id to route to")
    parser.add_argument("--force-fail-stage", default=None, help="deliberately fail a named stage, for testing")
    parser.add_argument("--no-dry-run", action="store_true", help="attempt real sector adapter invocation (still template_only today)")
    args = parser.parse_args()

    request = _build_request(args)
    result = run_pipeline(
        request,
        dry_run=not args.no_dry_run,
        requested_sector_id=args.sector,
        force_fail_stage=args.force_fail_stage,
    )

    print(result.model_dump_json(indent=2, exclude_none=False))
    return 1 if result.halted_at_stage else 0


if __name__ == "__main__":
    sys.exit(main())
