"""processor for the sk_innovation sector adapter.

Normalizes SourceDocument objects fetched by the collector: strips
whitespace from title/content and drops exact duplicate doc_ids. Does not
fetch new content or judge document quality — fetching happens in
collector, and content-quality filtering happens in validator.
"""

from __future__ import annotations

from common.contracts import SourceDocument


def _normalize(document: SourceDocument) -> SourceDocument:
    updates = {}
    if document.title and document.title != document.title.strip():
        updates["title"] = document.title.strip()
    if document.content and document.content != document.content.strip():
        updates["content"] = document.content.strip()
    return document.model_copy(update=updates) if updates else document


def process(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    """수집된 SK이노베이션 문서들의 공백을 정리하고 중복 문서를 제거합니다."""
    seen_doc_ids: set[str] = set()
    normalized: list[SourceDocument] = []
    for document in source_documents:
        if document.doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(document.doc_id)
        normalized.append(_normalize(document))
    return normalized
