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
from core.request_pipeline.pipeline import run_pipeline


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
        "--summary-only",
        action="store_true",
        help="print a compact execution summary instead of the full PipelineResult JSON",
    )
    args = parser.parse_args()

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
