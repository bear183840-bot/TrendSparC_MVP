"""Narrow, low-cost smoke test for the real Upstage Document Parse call used
by sources/collectors/source_router/pdf_parser.py - run this BEFORE testing
the full source_router pipeline on a PDF, to answer two specific questions
cheaply (1 real API call per invocation, billed by Upstage per page):

  1. Does the response return tables as markdown (pipe-table syntax inside
     content.markdown), or only as plain/flattened text?
  2. Can an "enhanced" mode actually be requested? There is no
     live-confirmed parameter name for this in this codebase yet - pass
     candidate parameters via --extra-json and this script reports exactly
     what changed, instead of the code guessing a parameter name.

Does not touch ai_search_harness.py, does not import router.py/coverage.py/
web_search.py - this only exercises pdf_parser.py's Document Parse call in
isolation, on a local PDF file you provide.

Usage:
    python scripts/verify_document_parse_pdf.py --pdf-path path\\to\\file.pdf
    python scripts/verify_document_parse_pdf.py --pdf-path file.pdf --extra-json "{\"ocr\": \"force\"}"
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

import requests

from sources.collectors.source_router.pdf_parser import (
    _API_KEY_ENV_VAR,
    _BASE_URL_ENV_VAR,
    _DEFAULT_BASE_URL,
    _parse_response,
)

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _call_raw(pdf_bytes: bytes, filename: str, extra_params: dict, timeout_seconds: int) -> dict | None:
    """Same endpoint/headers as pdf_parser._call_document_parse, but exposed
    here so the full raw response (not just the parsed markdown/sections) can
    be inspected and saved for this diagnostic."""
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key:
        raise SystemExit(
            f"{_API_KEY_ENV_VAR} is not set in .env - nothing to call. Fill it in and re-run."
        )
    base_url = os.environ.get(_BASE_URL_ENV_VAR, "").strip() or _DEFAULT_BASE_URL
    data = {"model": "document-parse", **extra_params}
    print(f"[verify_document_parse_pdf] POST {base_url} data={data}", file=sys.stderr)
    with open(filename, "rb") as fh:
        response = requests.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"document": (Path(filename).name, fh, "application/pdf")},
            data=data,
            timeout=timeout_seconds,
        )
    print(f"[verify_document_parse_pdf] status={response.status_code}", file=sys.stderr)
    if not response.ok:
        # The whole point of this call may be "does my key/plan have access to
        # this model/mode" - the answer usually lives in the error body (a
        # permission/plan message vs. a generic bad-request), so print it
        # before failing instead of letting raise_for_status() swallow it.
        print(f"[verify_document_parse_pdf] error body: {response.text[:2000]}", file=sys.stderr)
    response.raise_for_status()
    return response.json()


def _has_markdown_table(markdown: str) -> bool:
    lines = markdown.splitlines()
    for i in range(len(lines) - 1):
        if _TABLE_ROW_RE.match(lines[i]) and _TABLE_SEPARATOR_RE.match(lines[i + 1]) and "-" in lines[i + 1]:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf-path", required=True, help="Path to the local PDF file to test")
    parser.add_argument(
        "--extra-json",
        default="",
        help='Optional extra request params as a JSON object, e.g. \'{"ocr": "force"}\' '
        "- merged into the request alongside model=document-parse. Leave empty for the baseline call.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")

    extra_params = json.loads(args.extra_json) if args.extra_json.strip() else {}

    payload = _call_raw(pdf_path.read_bytes(), str(pdf_path), extra_params, args.timeout_seconds)

    scratchpad_dir = PROJECT_ROOT / "scratchpad"
    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_out_path = scratchpad_dir / f"document_parse_raw_{timestamp}.json"
    raw_out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    content = payload.get("content") or {}
    markdown = content.get("markdown") if isinstance(content, dict) else None
    elements = payload.get("elements") or []
    table_elements = [e for e in elements if str(e.get("category", "")).lower() == "table"]

    print("[verify_document_parse_pdf] --- top-level response keys ---", file=sys.stderr)
    print(f"[verify_document_parse_pdf] {sorted(payload.keys())}", file=sys.stderr)
    print("[verify_document_parse_pdf] --- Q1: tables as markdown? ---", file=sys.stderr)
    print(f"[verify_document_parse_pdf] table-category elements found: {len(table_elements)}", file=sys.stderr)
    print(
        f"[verify_document_parse_pdf] content.markdown contains pipe-table syntax: "
        f"{_has_markdown_table(markdown) if markdown else 'no markdown field at all'}",
        file=sys.stderr,
    )
    if table_elements:
        first = table_elements[0]
        print(f"[verify_document_parse_pdf] first table element keys: {sorted(first.keys())}", file=sys.stderr)
        print(f"[verify_document_parse_pdf] first table element (truncated): {json.dumps(first, ensure_ascii=False)[:1000]}", file=sys.stderr)

    print("[verify_document_parse_pdf] --- Q2: extra params effect ---", file=sys.stderr)
    print(f"[verify_document_parse_pdf] extra params sent this run: {extra_params or '(none - baseline call)'}", file=sys.stderr)
    print(
        "[verify_document_parse_pdf] compare this run's raw JSON against a baseline run's raw JSON "
        "(both saved under scratchpad/) to see what actually changed.",
        file=sys.stderr,
    )
    print(f"[verify_document_parse_pdf] full raw response written to: {raw_out_path}", file=sys.stderr)

    # Also run it through the real pdf_parser parsing path so we know the
    # production code handles this exact response without crashing.
    parsed = _parse_response(payload, source_url=str(pdf_path), chars_per_token_estimate=2.2)
    if parsed is None:
        print("[verify_document_parse_pdf] WARNING: pdf_parser._parse_response() returned None for this response (no markdown content key found)", file=sys.stderr)
    else:
        print(
            f"[verify_document_parse_pdf] pdf_parser._parse_response() OK: "
            f"token_count={parsed.token_count} sections={len(parsed.sections)}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
