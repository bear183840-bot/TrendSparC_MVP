"""validator for the sk_telecom sector adapter.

Drops any SourceDocument that can't be attributed back to its source or
carries no substantial content — per the global rule that content with no
source attribution must not appear in analysis or synthesis output
(prompts/global_system_prompt.md, principle 2). Does not fetch or rewrite
content; only filters what the processor already normalized.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from common.contracts import SourceDocument

_MIN_CONTENT_LENGTH = 200  # 최소 글자 수 기준 (200자 미만은 단순 안내문이나 오류 페이지일 가능성이 높음)
_MAX_DOCUMENT_AGE_DAYS = 730
_MAX_VALIDATED_DOCUMENTS = 8
_RELIABILITY_RANK = {"official": 0, "analyst_media": 1, "user_generated": 2}


def _is_valid(document: SourceDocument) -> bool:
    parsed = urlparse(document.url or "")
    if not document.source_id or not document.title or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if not document.content or len(document.content) < _MIN_CONTENT_LENGTH:
        return False
    return True


def _is_recent_enough(document: SourceDocument) -> bool:
    if document.published_at is None:
        return True
    published_at = document.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - published_at <= timedelta(days=_MAX_DOCUMENT_AGE_DAYS)


def _title_key(document: SourceDocument) -> str:
    return " ".join(document.title.split()).casefold()


def _quality_sort_key(document: SourceDocument) -> tuple[int, float]:
    rank = _RELIABILITY_RANK.get(document.reliability_tier, len(_RELIABILITY_RANK))
    published_at = document.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return (rank, -(published_at.timestamp() if published_at else float("-inf")))


def validate(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    """수집/전처리된 SK텔레콤 문서 중 출처 정보가 명확하고 유의미한 정보량을 가진 문서만 검증합니다."""
    seen_titles: set[str] = set()
    kept: list[SourceDocument] = []
    for document in source_documents:
        if not _is_valid(document) or not _is_recent_enough(document):
            continue
        title_key = _title_key(document)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        kept.append(document)
    return sorted(kept, key=_quality_sort_key)[:_MAX_VALIDATED_DOCUMENTS]
