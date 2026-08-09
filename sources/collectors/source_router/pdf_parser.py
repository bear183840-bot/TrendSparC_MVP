"""Upstage Document Parse — PDF → structured document representation, plus
the Small/Large/Huge progressive-narrowing routing from doc1 §11-§17.

*** API SPEC — live-verified 2026-08-09 ***
Endpoint (`_DEFAULT_BASE_URL`) and `model`/`mode` param names/values were
confirmed against a real account via scripts/verify_document_parse_pdf.py
(a user-provided official Upstage sample matched this endpoint exactly) and
against Upstage's own cookbook (github.com/UpstageAI/cookbook,
aws/jumpstart/02_document_parse.ipynb). Two real findings from that session
that shaped the code below:

1. **`output_formats` is required, or markdown/text come back empty.**
   Every element's `content` object (and the top-level `content` object) has
   `html`/`markdown`/`text` keys, but `markdown`/`text` are BOTH empty
   strings unless the request explicitly includes
   `output_formats: '["markdown", "html", "text"]'` — confirmed identical
   across standard/enhanced/auto modes, so this isn't mode-specific. Without
   it, `_parse_response()` always returned None (every real PDF would look
   un-inspectable).
2. **Elements nest their text under `element["content"]["markdown"/"text"/
   "html"]` — never a flat `element["text"]`.** The pre-2026-08-09 version of
   `_sections_from_elements()` read `element.get("text", "")`, which is
   always "" against the real response shape — so heading titles fell back
   to generic "Section N" and every section body was silently empty, even
   before the output_formats gap above. `_element_text()` below fixes this
   and doubles as the fallback path if a future Upstage response ever
   regresses (see model choice note next).

**Model/mode: `document-parse-nightly` + `mode="auto"`, chosen deliberately
over the pinned `document-parse` (stable, dated `-260630` build).** Compared
live on the same PDF: `auto` reproduced the stable build's output exactly on
pages it classified "standard", and produced richer semantic HTML
(`<th scope=...>`, preserved `<br>` line breaks) only on pages it classified
"enhanced" — so `auto` costs nothing in quality vs. always-standard while
adding real value on complex pages, without forcing every page through the
heavier path the way `mode="enhanced"` would. The tradeoff accepted here:
`-nightly` is a floating pre-release build that can change behavior without
a version bump, unlike the dated stable build. `_element_text()`'s
markdown -> text -> html fallback and its loud stderr warning (search for
"NIGHTLY MODEL DRIFT") are the safety net for that — if Upstage ever changes
what the nightly build returns, this fails loud and specific instead of
silently degrading to empty sections again.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import requests

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import (
    ChunkSelection,
    DocumentChunk,
    DocumentSection,
    ParsedDocument,
    SectionSelection,
)

_API_KEY_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_UPSTAGE_DOCPARSE_API_KEY"
_BASE_URL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_UPSTAGE_DOCPARSE_BASE_URL"
_DEFAULT_BASE_URL = "https://api.upstage.ai/v1/document-digitization"

# See API SPEC docstring above for why nightly+auto was chosen over the
# pinned stable build, and why output_formats must be sent explicitly.
_MODEL = "document-parse-nightly"
_MODE = "auto"
# markdown listed first: this is our preferred field (readable, preserves
# table structure as pipe syntax) — _element_text()/_parse_response() read
# it first and only fall back to text/html if it's missing.
_OUTPUT_FORMATS = '["markdown", "html", "text"]'

_HEADING_CATEGORIES = {"heading1", "heading2", "title"}


# ---------------------------------------------------------------------------
# Upstage Document Parse call (see API SPEC docstring above)
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
            data={"model": _MODEL, "mode": _MODE, "output_formats": _OUTPUT_FORMATS},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.pdf_parser] Document Parse call failed: {exc}", file=sys.stderr)
        return None
    # Always-on visibility into what the nightly build actually did for this
    # call — the cheapest possible tripwire for "did Upstage change nightly's
    # behavior underneath us". usage.enhanced/usage.standard show exactly
    # which pages mode="auto" picked.
    print(
        f"[source_router.pdf_parser] Document Parse response: model={payload.get('model')!r} "
        f"usage={payload.get('usage')!r}",
        file=sys.stderr,
    )
    return payload


def _element_text(element: dict[str, Any]) -> str:
    """Prefer markdown, then plain text, then a naive HTML-tag-strip as a
    last resort — the fallback chain IS the drift safety net: if a future
    Upstage response stops populating markdown/text despite output_formats
    requesting them (nightly-build behavior change), this still recovers
    something instead of silently producing an empty section, and says so
    loudly rather than failing quiet."""
    content = element.get("content") or {}
    markdown = str(content.get("markdown") or "").strip()
    if markdown:
        return markdown
    text = str(content.get("text") or "").strip()
    if text:
        return text
    html = str(content.get("html") or "")
    if not html:
        return ""
    print(
        "[source_router.pdf_parser] NIGHTLY MODEL DRIFT WARNING: element "
        f"id={element.get('id')} page={element.get('page')} category={element.get('category')!r} "
        "had no markdown/text despite output_formats requesting them - falling back to a naive "
        "HTML tag strip. Re-run scripts/verify_document_parse_pdf.py if this keeps happening.",
        file=sys.stderr,
    )
    return re.sub(r"<[^>]+>", " ", html).strip()


_MARKDOWN_HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s+")


def _clean_heading_title(text: str) -> str:
    """_element_text() returns raw markdown, and a heading element's own
    markdown is itself markdown heading syntax (e.g. "# 2. Some Title") -
    strip the leading #'s so DocumentSection.title reads as a plain title,
    not markdown source. Live-verified 2026-08-09: real heading1 elements
    from document-parse-nightly come back exactly this way."""
    return _MARKDOWN_HEADING_PREFIX_RE.sub("", text).strip()


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
        text = _element_text(element)
        if category in _HEADING_CATEGORIES:
            _flush()
            current = {
                "section_id": f"S{len(sections) + 1}",
                "title": _clean_heading_title(text) or f"Section {len(sections) + 1}",
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
    markdown = str(content.get("markdown") or "").strip() if isinstance(content, dict) else ""
    if not markdown:
        text = str(content.get("text") or "").strip() if isinstance(content, dict) else ""
        html = str(content.get("html") or "") if isinstance(content, dict) else ""
        if text:
            markdown = text
        elif html:
            print(
                "[source_router.pdf_parser] NIGHTLY MODEL DRIFT WARNING: top-level content.markdown/"
                "content.text were both empty despite output_formats requesting them - falling back "
                "to a naive HTML tag strip for the whole document. Re-run "
                "scripts/verify_document_parse_pdf.py if this keeps happening.",
                file=sys.stderr,
            )
            markdown = re.sub(r"<[^>]+>", " ", html).strip()
        else:
            print(
                "[source_router.pdf_parser] Document Parse response had no markdown/text/html content at all",
                file=sys.stderr,
            )
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


def _str_list(raw) -> list[str]:
    return [str(value).strip() for value in raw or [] if str(value).strip()]


def select_sections(
    question: str,
    sections: list[DocumentSection],
    *,
    max_sections: int = 4,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> list[SectionSelection]:
    """Falls back to the first `max_sections` sections in document order when
    no planner key is configured, the call fails, or every returned id is
    hallucinated — never blocks on this judgment call. Returns the model's
    own reasoning/evidence_role per section (prompt C), not just bare ids —
    the fallback path leaves those fields empty since there's no judgment
    behind it."""
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
        timeout_seconds=timeout_seconds,
    )
    if data:
        valid_ids = {s.section_id for s in sections}
        selected = [
            SectionSelection(
                section_id=str(item.get("section_id", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
                evidence_role=_str_list(item.get("evidence_role")),
                requires_chunk_selection=bool(item.get("requires_chunk_selection", False)),
            )
            for item in data.get("selected_sections", []) or []
            if isinstance(item, dict) and str(item.get("section_id", "")).strip() in valid_ids
        ][:max_sections]
        if selected:
            return selected
    return [SectionSelection(section_id=s.section_id) for s in sections[:max_sections]]


def select_chunks(
    question: str,
    chunks: list[DocumentChunk],
    *,
    max_chunks: int = 3,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> list[ChunkSelection]:
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
        _prompts.load("chunk_selection"),
        payload,
        caller="pdf_parser.select_chunks",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if data:
        valid_ids = {c.chunk_id for c in chunks}
        selected = [
            ChunkSelection(
                chunk_id=str(item.get("chunk_id", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
                evidence_role=_str_list(item.get("evidence_role")),
            )
            for item in data.get("selected_chunks", []) or []
            if isinstance(item, dict) and str(item.get("chunk_id", "")).strip() in valid_ids
        ][:max_chunks]
        if selected:
            return selected
    return [ChunkSelection(chunk_id=c.chunk_id) for c in chunks[:max_chunks]]
