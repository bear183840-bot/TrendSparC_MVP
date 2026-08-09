"""Upstage Document Parse — PDF → structured document representation, plus
the Small/Large/Huge progressive-narrowing routing from doc1 §11-§17.

*** API SPEC WARNING ***
Upstage Document Parse is a different product from the Solar chat-completion
API used everywhere else in this repo (core/entity/ai_based.py,
sources/collectors/source_router/_solar.py, etc.) — it is a REST endpoint
with multipart file upload, not an OpenAI-compatible chat endpoint. The
endpoint path and response shape below (`_DEFAULT_BASE_URL`, `_call_document_
parse`, `_parse_response`) are a best-effort reading of Upstage's public
Document Parse documentation as of this writing and have NOT been
live-verified — confirm against the current docs at
https://console.upstage.ai before the first real call, and adjust those two
functions if the actual response shape differs. Everything downstream of
`_parse_response` (size classification, section/chunk building, selection)
is independent of that detail and does not need to change if the endpoint
shape does.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import requests

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import DocumentChunk, DocumentSection, ParsedDocument

_API_KEY_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_UPSTAGE_DOCPARSE_API_KEY"
_BASE_URL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_UPSTAGE_DOCPARSE_BASE_URL"
_DEFAULT_BASE_URL = "https://api.upstage.ai/v1/document-digitization"

_HEADING_CATEGORIES = {"heading1", "heading2", "title"}


# ---------------------------------------------------------------------------
# Upstage Document Parse call (see API SPEC WARNING above)
# ---------------------------------------------------------------------------


def _call_document_parse(pdf_bytes: bytes, filename: str, timeout_seconds: int) -> dict[str, Any] | None:
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key:
        print("[source_router.pdf_parser] Upstage Document Parse API key not set", file=sys.stderr)
        return None
    base_url = os.environ.get(_BASE_URL_ENV_VAR, "").strip() or _DEFAULT_BASE_URL
    try:
        response = requests.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"document": (filename, pdf_bytes, "application/pdf")},
            data={"model": "document-parse"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.pdf_parser] Document Parse call failed: {exc}", file=sys.stderr)
        return None


def _estimate_token_count(text: str, chars_per_token: float) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / max(chars_per_token, 0.1)))


def _sections_from_elements(
    elements: list[dict[str, Any]], chars_per_token_estimate: float
) -> list[DocumentSection]:
    """Prefer the parser's own heading structure over an LLM-invented one —
    doc1 §16. Returns [] when the response has no heading-level elements;
    the caller then treats the whole document as unsectioned (falls back to
    full_text)."""
    sections: list[DocumentSection] = []
    current: dict[str, Any] | None = None
    body_parts: list[str] = []

    def _flush() -> None:
        if current is None:
            return
        full_text = "\n".join(body_parts).strip()
        sections.append(
            DocumentSection(
                **current,
                preview=full_text[:200],
                full_text=full_text,
                token_count=_estimate_token_count(full_text, chars_per_token_estimate),
            )
        )

    for element in elements:
        category = str(element.get("category", "")).lower()
        page = element.get("page")
        text = str(element.get("text", "")).strip()
        if category in _HEADING_CATEGORIES:
            _flush()
            current = {
                "section_id": f"S{len(sections) + 1}",
                "title": text or f"Section {len(sections) + 1}",
                "pages": str(page) if page is not None else "",
            }
            body_parts = []
        elif current is not None and text:
            body_parts.append(text)
    _flush()
    return sections


def _parse_response(
    payload: dict[str, Any], source_url: str, chars_per_token_estimate: float
) -> ParsedDocument | None:
    content = payload.get("content") or {}
    markdown = content.get("markdown") if isinstance(content, dict) else None
    if not markdown:
        print("[source_router.pdf_parser] Document Parse response had no markdown content", file=sys.stderr)
        return None
    sections = _sections_from_elements(payload.get("elements") or [], chars_per_token_estimate)
    return ParsedDocument(
        source_url=source_url,
        document_title=str(payload.get("title", "")),
        token_count=_estimate_token_count(markdown, chars_per_token_estimate),
        full_text=markdown,
        sections=sections,
    )


def parse_pdf(
    pdf_bytes: bytes,
    *,
    source_url: str,
    filename: str = "document.pdf",
    chars_per_token_estimate: float = 2.2,
    timeout_seconds: int = 120,
) -> ParsedDocument | None:
    """None on missing key or any call/parse failure — caller treats this
    PDF as un-inspectable rather than crashing the router."""
    payload = _call_document_parse(pdf_bytes, filename, timeout_seconds)
    if payload is None:
        return None
    return _parse_response(payload, source_url, chars_per_token_estimate)


# ---------------------------------------------------------------------------
# Small/Large/Huge routing (doc1 §11-§14)
# ---------------------------------------------------------------------------


def classify_size(token_count: int, small_max_tokens: int, large_max_tokens: int) -> str:
    if token_count <= small_max_tokens:
        return "small"
    if token_count <= large_max_tokens:
        return "large"
    return "huge"


def build_chunk_map(
    section: DocumentSection,
    *,
    chars_per_token_estimate: float,
    target_chunk_tokens: int = 4_000,
) -> list[DocumentChunk]:
    """Splits on paragraph boundaries up to a target chunk size — preserves
    document structure rather than a fixed-character cut (doc1 §17)."""
    text = section.full_text or ""
    if not text:
        return []
    target_chars = int(target_chunk_tokens * chars_per_token_estimate)
    paragraphs = [paragraph for paragraph in text.split("\n") if paragraph.strip()]
    chunks: list[DocumentChunk] = []
    buffer: list[str] = []
    buffer_len = 0

    def _flush() -> None:
        if not buffer:
            return
        chunk_text = "\n".join(buffer)
        chunks.append(
            DocumentChunk(
                chunk_id=f"{section.section_id}-C{len(chunks) + 1}",
                section_id=section.section_id,
                heading=section.title,
                pages=section.pages,
                token_count=_estimate_token_count(chunk_text, chars_per_token_estimate),
                preview=chunk_text[:200],
                text=chunk_text,
            )
        )

    for paragraph in paragraphs:
        buffer.append(paragraph)
        buffer_len += len(paragraph)
        if buffer_len >= target_chars:
            _flush()
            buffer, buffer_len = [], 0
    _flush()
    return chunks


# ---------------------------------------------------------------------------
# Solar Pro 3 Section/Chunk Selection (doc1 §13/§14/§18)
# ---------------------------------------------------------------------------


def select_sections(
    question: str,
    sections: list[DocumentSection],
    *,
    max_sections: int = 4,
    model_override: str | None = None,
) -> list[str]:
    """Falls back to the first `max_sections` sections in document order when
    no planner key is configured or the call fails — never blocks on this
    judgment call."""
    if not sections:
        return []
    payload = {
        "question": question,
        "sections": [
            {"section_id": s.section_id, "title": s.title, "pages": s.pages, "preview": s.preview}
            for s in sections
        ],
    }
    data = _solar.call_json(
        _prompts.load("section_selection"),
        payload,
        caller="pdf_parser.select_sections",
        model_override=model_override,
    )
    if data:
        valid_ids = {s.section_id for s in sections}
        selected = [
            str(item.get("section_id", "")).strip()
            for item in data.get("selected_sections", []) or []
            if isinstance(item, dict)
        ]
        selected = [section_id for section_id in selected if section_id in valid_ids][:max_sections]
        if selected:
            return selected
    return [s.section_id for s in sections[:max_sections]]


def select_chunks(
    question: str,
    chunks: list[DocumentChunk],
    *,
    max_chunks: int = 3,
    model_override: str | None = None,
) -> list[str]:
    """Same fallback contract as select_sections."""
    if not chunks:
        return []
    payload = {
        "question": question,
        "chunks": [
            {"chunk_id": c.chunk_id, "heading": c.heading, "pages": c.pages, "preview": c.preview}
            for c in chunks
        ],
    }
    data = _solar.call_json(
        _prompts.load("chunk_selection"), payload, caller="pdf_parser.select_chunks", model_override=model_override
    )
    if data:
        valid_ids = {c.chunk_id for c in chunks}
        selected = [str(chunk_id).strip() for chunk_id in data.get("selected_chunks", []) or []]
        selected = [chunk_id for chunk_id in selected if chunk_id in valid_ids][:max_chunks]
        if selected:
            return selected
    return [c.chunk_id for c in chunks[:max_chunks]]
