"""SK Broadband sector processor."""

from __future__ import annotations

import re
from hashlib import sha1

from common.contracts import SourceDocument

_BOILERPLATE_PATTERNS = [
    re.compile(r"무단전재\s*및\s*재배포\s*금지", re.IGNORECASE),
    re.compile(r"저작권자?\s*ⓒ[^\n]+", re.IGNORECASE),
    re.compile(r"Copyright\s*\(?.*?\)?\s*All rights reserved\.?", re.IGNORECASE),
    re.compile(r"기자\s*[\w.+-]+@[\w.-]+", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w.-]+"),
]


def _collapse_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_boilerplate(text: str) -> str:
    cleaned = text
    for pattern in _BOILERPLATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned


def _remove_repeated_lines(text: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        normalized = line.strip()
        if not normalized:
            lines.append("")
            continue
        key = normalized.lower()
        if len(normalized) >= 20 and key in seen:
            continue
        seen.add(key)
        lines.append(normalized)
    return "\n".join(lines)


def _clean_content(content: str | None) -> str | None:
    if content is None:
        return None
    return _collapse_whitespace(_remove_repeated_lines(_remove_boilerplate(content)))


def _content_fingerprint(document: SourceDocument) -> str:
    basis = (document.url or "") + "\n" + (document.content or "")[:1000]
    return sha1(basis.encode("utf-8")).hexdigest()


def _normalize(document: SourceDocument) -> SourceDocument:
    return document.model_copy(update={
        "title": document.title.strip() if document.title else "Untitled",
        "content": _clean_content(document.content),
    })


def process(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    seen_doc_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    normalized: list[SourceDocument] = []
    for document in source_documents:
        if document.doc_id in seen_doc_ids:
            continue
        candidate = _normalize(document)
        fingerprint = _content_fingerprint(candidate)
        if fingerprint in seen_fingerprints:
            continue
        seen_doc_ids.add(candidate.doc_id)
        seen_fingerprints.add(fingerprint)
        normalized.append(candidate)
    return normalized
