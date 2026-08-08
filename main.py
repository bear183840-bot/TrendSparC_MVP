"""Dry-run CLI entrypoint for the TrendSparC_MVP scaffold.

Prints the full per-stage trace (and, when available, the intermediate
contract objects) for a single UserRequest, so the pipeline's structure can
be exercised end-to-end without any external API keys.

Usage:
    python main.py --question "SK하이닉스 HBM 시장 전망은?" --audience practitioner
    python main.py --request-file examples/requests/sample_request.json
    python main.py --question "..." --sector sk_totally_made_up
    python main.py --question "..." --force-fail-stage intent
    python main.py --synthesis-fixture tests/fixtures/synthesis_revenue_trend.json --summary-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and not sys.stderr.isatty():
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from common.contracts import UserRequest
from core.request_pipeline.pipeline import run_pipeline, run_pipeline_from_synthesis
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" ._")
    return cleaned[:80] or "source"


def _save_source_documents(result, output_root: Path) -> Path:
    request_dir = output_root / result.request_id
    request_dir.mkdir(parents=True, exist_ok=True)
    index_entries = []
    for index, document in enumerate(result.collected_source_documents, start=1):
        filename = f"{index:02d}_{_safe_filename(document.source_id)}.md"
        title = (document.title or "Untitled").replace("\n", " ").strip()
        metadata = [
            f"# {title}",
            "",
            f"- source_id: {document.source_id}",
            f"- url: {document.url or ''}",
            f"- reliability_tier: {document.reliability_tier or ''}",
            f"- published_at: {document.published_at.isoformat() if document.published_at else ''}",
            "",
            "## Firecrawl 원문",
            "",
        ]
        (request_dir / filename).write_text(
            "\n".join(metadata) + (document.content or ""),
            encoding="utf-8",
        )
        index_entries.append(
            {
                "file": filename,
                "doc_id": document.doc_id,
                "source_id": document.source_id,
                "title": document.title,
                "url": document.url,
                "reliability_tier": document.reliability_tier,
                "published_at": document.published_at.isoformat() if document.published_at else None,
            }
        )
    (request_dir / "index.json").write_text(
        json.dumps(index_entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return request_dir


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


def _run_from_fixture(args: argparse.Namespace):
    """Run report_planner -> layout_generator from a saved synthesis.

    Free by default: report_generator is the one stage downstream of synthesis
    that can call OpenAI, so its keys are cleared for the process unless
    --with-report-llm is passed. Clearing beats mocking here because the
    generator's own rule-based fallback is then exercised, which is the path
    that actually ships when a key is missing.
    """
    synthesis, question, audience_id, purpose = load_synthesis_fixture(args.synthesis_fixture)
    if args.audience:
        audience_id = args.audience
    if not args.with_report_llm:
        for variable in ("TRENDSPARC_REPORT_GENERATOR_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(variable, None)
    print(
        f"[synthesis-fixture] {Path(args.synthesis_fixture).name} | audience={audience_id} "
        f"| purpose={purpose.purpose_id} | report_generator="
        f"{'openai' if args.with_report_llm else 'rule_based (free)'}",
        file=sys.stderr,
    )
    return run_pipeline_from_synthesis(
        question, synthesis, audience_id, purpose, force_fail_stage=args.force_fail_stage
    )


def _resume_from_saved_run(args: argparse.Namespace):
    """Restart a saved run at the analyzer, over documents it already has."""
    from core.request_pipeline.pipeline import PipelineResult, run_pipeline_from_documents
    from core.run_archive import ARCHIVE_DIR, archive_run

    saved = PipelineResult.model_validate_json(args.resume_from.read_text(encoding="utf-8"))
    question = args.question
    if not question:
        record = ARCHIVE_DIR / f"{saved.request_id}.json"
        if record.exists():
            question = json.loads(record.read_text(encoding="utf-8")).get("question")
    if not question:
        raise SystemExit("--resume-from needs --question (the saved run's archive has no record of it)")
    audience = args.audience or (saved.generated_report.audience_id if saved.generated_report else "practitioner")
    print(
        f"[resume] {args.resume_from.name} | {len(saved.collected_source_documents or [])} documents "
        f"| audience={audience} | 검색·스크레이핑 생략",
        file=sys.stderr,
    )
    result = run_pipeline_from_documents(saved, question, audience, force_fail_stage=args.force_fail_stage)
    # A resumed run is a run: it belongs in the archive so it can be reopened
    # from the dashboard like any other, rather than existing only as a file
    # someone has to remember to upload.
    archive_run(result, question, audience)
    return result


def main() -> int:
    # Load local credentials only for an actual CLI invocation. Keeping this
    # out of module import prevents tests and helper imports from inheriting
    # real API keys from a developer's .env file.
    load_dotenv()
    parser = argparse.ArgumentParser(description="TrendSparC_MVP dry-run pipeline CLI")
    parser.add_argument("--question", help="user question text")
    parser.add_argument("--request-file", help="path to a JSON file matching the UserRequest contract")
    parser.add_argument("--audience", default=None, help="target audience id (default: practitioner)")
    parser.add_argument("--sector", default=None, help="explicit sector id to route to")
    parser.add_argument("--force-fail-stage", default=None, help="deliberately fail a named stage, for testing")
    parser.add_argument("--no-dry-run", action="store_true", help="attempt real sector adapter invocation (still template_only today)")
    parser.add_argument(
        "--save-source-documents",
        type=Path,
        default=None,
        metavar="DIR",
        help="save raw collector documents as Markdown under DIR/<request_id>/",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        default=None,
        metavar="PATH",
        help="re-run analyzer onward over the documents a saved --save-result run already "
             "collected. Skips search and scraping (the expensive half); the analyzer, "
             "synthesis refinement and report writer still call OpenAI.",
    )
    parser.add_argument(
        "--save-result",
        type=Path,
        default=None,
        metavar="PATH",
        help="write the full PipelineResult JSON to PATH so the dashboard can open the "
             "same run (streamlit: 저장된 실행 결과 열기). storage/requests/ keeps only a "
             "summary, which is not enough to redraw the report.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="print a compact execution summary instead of the full PipelineResult JSON",
    )
    parser.add_argument(
        "--synthesis-fixture",
        type=Path,
        default=None,
        metavar="PATH",
        help="dev only: skip collection/analysis/synthesis and run report_planner onward "
             "from a saved TrendSynthesis JSON. Free regardless of --no-dry-run.",
    )
    parser.add_argument(
        "--with-report-llm",
        action="store_true",
        help="with --synthesis-fixture, let report_generator make its real OpenAI call "
             "(costs money) instead of forcing the rule-based path",
    )
    args = parser.parse_args()

    if args.resume_from is not None:
        result = _resume_from_saved_run(args)
    elif args.synthesis_fixture is not None:
        result = _run_from_fixture(args)
    else:
        request = _build_request(args)
        result = run_pipeline(
            request,
            dry_run=not args.no_dry_run,
            requested_sector_id=args.sector,
            force_fail_stage=args.force_fail_stage,
        )

    if args.save_source_documents is not None:
        saved_dir = _save_source_documents(result, args.save_source_documents)
        print(f"[source_documents] saved to {saved_dir.resolve()}", file=sys.stderr)

    if args.save_result is not None:
        args.save_result.parent.mkdir(parents=True, exist_ok=True)
        args.save_result.write_text(
            result.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )
        print(f"[save-result] {args.save_result.resolve()}", file=sys.stderr)

    if args.summary_only:
        print(
            json.dumps(
                {
                    "request_id": result.request_id,
                    "halted_at_stage": result.halted_at_stage,
                    "collected_source_document_count": len(result.collected_source_documents),
                    "analyzed_document_count": len(result.document_analyses),
                    "trace": [trace.model_dump(mode="json") for trace in result.trace],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(result.model_dump_json(indent=2, exclude_none=False))
    return 1 if result.halted_at_stage else 0


if __name__ == "__main__":
    sys.exit(main())
