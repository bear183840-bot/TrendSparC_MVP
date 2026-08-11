"""validator for the sk_hynix sector adapter.

Drops any SourceDocument that can't be attributed back to its source or
carries no substantial content — per the global rule that content with no
source attribution must not appear in analysis or synthesis output
(prompts/global_system_prompt.md, principle 2). Does not fetch or rewrite
content; only filters what the processor already normalized.

Also checks recency, cross-source near-duplicates, and source quality (via a
final rank + cap) — see sectors/sk_broadband/adapter/validator for the same
pattern applied first. Relevance to the actual question is intentionally NOT
judged here — `validate()` only receives documents, not the question or its
keywords, so a keyword-match "relevance" check here would just be an
unfounded guess; real relevance judgment happens downstream in the
analyzer's `relevant_to_question` field.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from common.contracts import SourceDocument, WebSearchContext

_MIN_CONTENT_LENGTH = 200  # below this a page is almost never a real article body
_MAX_DOCUMENT_AGE_DAYS = 730
_MAX_VALIDATED_DOCUMENTS = 8

# Ranks a document's source when trimming down to _MAX_VALIDATED_DOCUMENTS —
# mirrors the same 3-tier convention documented on PlannedSource.reliability_tier
# in common/contracts.py. Unset/unrecognized tiers rank last, never guessed.
_RELIABILITY_RANK = {"official": 0, "analyst_media": 1, "user_generated": 2}


def _has_valid_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_valid(document: SourceDocument) -> bool:
    if not document.source_id or not document.title or not _has_valid_url(document.url):
        return False
    if not document.content or len(document.content.strip()) < _MIN_CONTENT_LENGTH:
        return False
    return True


def _max_age_days(search_context: WebSearchContext | None) -> int | None:
    if search_context is None:
        return _MAX_DOCUMENT_AGE_DAYS
    question = search_context.question.lower()
    years = re.search(r"(?:최근|지난)\s*(\d+)\s*년", question)
    if years:
        return max(365, int(years.group(1)) * 366)
    months = re.search(r"(?:최근|지난)\s*(\d+)\s*개월", question)
    if months:
        return max(30, int(months.group(1)) * 31)
    if any(term in question for term in ("역사", "과거", "도입 배경", "장기 추이")):
        return None
    if any(term in question for term in ("오늘", "금일", "실시간", "방금", "이번 주", "금주", "가장 최신", "가장 최근")):
        return 30
    if "최신" in question:
        return 90
    if any(term in question for term in ("최근", "현재", "지금", "요즘", "이번 달")):
        return 180
    if search_context.as_of_date and search_context.as_of_date[:4] in question:
        return 365
    if search_context.report_purpose_id == "current_status":
        return 365
    return _MAX_DOCUMENT_AGE_DAYS


def _reference_time(search_context: WebSearchContext | None) -> datetime:
    if search_context and search_context.as_of_date:
        try:
            parsed = datetime.fromisoformat(search_context.as_of_date)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _requires_verified_published_at(search_context: WebSearchContext | None) -> bool:
    if search_context is None:
        return False
    question = search_context.question.lower()
    return any(term in question for term in ("오늘", "금일", "실시간", "방금", "이번 주", "금주", "가장 최신", "가장 최근"))


def _is_recent_enough(document: SourceDocument, search_context: WebSearchContext | None = None) -> bool:
    # Missing published_at is common (Firecrawl doesn't always extract a
    # date) and must not be penalized — only reject when we actually know
    # the document is stale, never guess staleness from absence of a date.
    if document.published_at is None:
        return not _requires_verified_published_at(search_context)
    published_at = document.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    max_age_days = _max_age_days(search_context)
    if max_age_days is None:
        return True
    return _reference_time(search_context) - published_at <= timedelta(days=max_age_days)


def _title_key(document: SourceDocument) -> str:
    return " ".join(document.title.split()).lower()


def _drop_cross_source_title_duplicates(documents: list[SourceDocument]) -> list[SourceDocument]:
    seen_titles: set[str] = set()
    kept: list[SourceDocument] = []
    for document in documents:
        key = _title_key(document)
        if key in seen_titles:
            continue
        seen_titles.add(key)
        kept.append(document)
    return kept


def _quality_sort_key(document: SourceDocument) -> tuple[int, float]:
    reliability_rank = _RELIABILITY_RANK.get(document.reliability_tier, len(_RELIABILITY_RANK))
    recency = document.published_at.timestamp() if document.published_at else float("-inf")
    return (reliability_rank, -recency)


def validate(
    source_documents: list[SourceDocument],
    search_context: WebSearchContext | None = None,
) -> list[SourceDocument]:
    structurally_valid = [document for document in source_documents if _is_valid(document)]
    recent_enough = [
        document for document in structurally_valid if _is_recent_enough(document, search_context)
    ]
    deduplicated = _drop_cross_source_title_duplicates(recent_enough)
    ranked = sorted(deduplicated, key=_quality_sort_key)
    return ranked[:_MAX_VALIDATED_DOCUMENTS]
