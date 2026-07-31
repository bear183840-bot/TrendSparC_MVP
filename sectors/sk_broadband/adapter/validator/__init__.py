"""SK Broadband sector validator."""

from __future__ import annotations

from urllib.parse import urlparse

from common.contracts import SourceDocument

_MIN_CONTENT_LENGTH = 250


def _has_valid_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_valid(document: SourceDocument) -> bool:
    if not document.source_id or not document.title:
        return False
    if not _has_valid_url(document.url):
        return False
    if not document.content or len(document.content.strip()) < _MIN_CONTENT_LENGTH:
        return False
    return True


def validate(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    return [document for document in source_documents if _is_valid(document)]
