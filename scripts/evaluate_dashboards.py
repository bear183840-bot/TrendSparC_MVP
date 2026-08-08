"""Evaluate one saved mentor-question run, or smoke-test all synthesis fixtures."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.dashboard_evaluation import evaluate_dashboard_result, load_evaluation_manifest
from core.request_pipeline.pipeline import PipelineResult, run_pipeline_from_synthesis
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture

DEFAULT_MANIFEST = ROOT / "evals" / "sk_broadband_mentor_questions.json"


def _fixture_suite() -> dict:
    for variable in ("TRENDSPARC_REPORT_GENERATOR_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(variable, None)
    rows = []
    for path in sorted((ROOT / "tests" / "fixtures").glob("synthesis_*.json")):
        synthesis, question, audience_id, purpose = load_synthesis_fixture(path)
        result = run_pipeline_from_synthesis(question, synthesis, audience_id, purpose)
        trace = result.block_delivery_trace
        rows.append({
            "fixture": path.name,
            "purpose_id": purpose.purpose_id,
            "audience_id": audience_id,
            "delivered_block_types": trace.delivered_block_types,
            "required_last_resort_slots": [
                slot.slot_id for slot in trace.slots if not slot.optional and slot.last_resort
            ],
        })
    return {"fixture_count": len(rows), "fixtures": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendSparC dashboard E2E evaluator")
    parser.add_argument("--result", type=Path, help="saved PipelineResult JSON")
    parser.add_argument("--case-id", help="case id from the mentor question manifest")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--fixture-suite", action="store_true",
                        help="run all nine synthesis fixtures for free")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()

    if args.fixture_suite:
        payload = _fixture_suite()
    else:
        if not args.result or not args.case_id:
            parser.error("--result and --case-id are required unless --fixture-suite is used")
        cases = {case.case_id: case for case in load_evaluation_manifest(args.manifest)}
        if args.case_id not in cases:
            parser.error(f"unknown case id: {args.case_id}")
        result = PipelineResult.model_validate_json(args.result.read_text(encoding="utf-8"))
        payload = evaluate_dashboard_result(result, cases[args.case_id]).model_dump(mode="json")

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
