"""SK Broadband sector validator.

Checks structural validity, question-sensitive recency, cross-source title
duplicates, and source quality before a document reaches the analyzer.
`WebSearchContext` is used only to choose an age window; semantic relevance
is still judged downstream by the analyzer's `relevant_to_question` field.

Exact duplicates (same URL + near-identical content) are already deduped in
processor.py via a content fingerprint; the near-duplicate check here is a
narrower net for the case processor.py can't catch: different URLs (e.g.
syndicated copies across outlets) carrying the same headline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from common.contracts import SourceDocument, WebSearchContext
from common.recency import max_age_days as _shared_max_age_days
from common.recency import requires_verified_published_at as _shared_requires_verified_published_at

_MIN_CONTENT_LENGTH = 250
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


def _is_structurally_valid(document: SourceDocument) -> bool:
    if not document.source_id or not document.title:
        return False
    if not _has_valid_url(document.url):
        return False
    if not document.content or len(document.content.strip()) < _MIN_CONTENT_LENGTH:
        return False
    return True


def _max_age_days(search_context: WebSearchContext | None) -> int | None:
    # Delegates to common.recency (shared with source_router's query
    # planner, which needs the same question-sensitive judgment upstream of
    # collection, not just here as a post-hoc document filter) — see that
    # module's docstring for the extraction history. Behavior-preserving:
    # every branch/threshold is unchanged from before the extraction.
    if search_context is None:
        return _MAX_DOCUMENT_AGE_DAYS
    return _shared_max_age_days(
        search_context.question, search_context.as_of_date, search_context.report_purpose_id
    )


def _reference_time(search_context: WebSearchContext | None) -> datetime:
    if search_context and search_context.as_of_date:
        try:
            return datetime.fromisoformat(search_context.as_of_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _requires_verified_published_at(search_context: WebSearchContext | None) -> bool:
    if search_context is None:
        return False
    return _shared_requires_verified_published_at(search_context.question)


def _is_recent_enough(
    document: SourceDocument,
    search_context: WebSearchContext | None = None,
) -> bool:
    # Firecrawl does not always extract a date. Keep undated evidence by
    # default, but a strong "latest" request requires a verifiable date.
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
    title_key = " ".join(document.title.split()).lower()
    if title_key == "untitled":
        return f"untitled::{document.url or document.doc_id}"
    return title_key


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
    # More recent first; undated documents sort after every dated one at the
    # same reliability rank, but are still eligible (never dropped solely for
    # lacking a date).
    recency = document.published_at.timestamp() if document.published_at else float("-inf")
    return (reliability_rank, -recency)


def validate(
    source_documents: list[SourceDocument],
    search_context: WebSearchContext | None = None,
) -> list[SourceDocument]:
    structurally_valid = [document for document in source_documents if _is_structurally_valid(document)]
    recent_enough = [
        document for document in structurally_valid if _is_recent_enough(document, search_context)
    ]
    deduplicated = _drop_cross_source_title_duplicates(recent_enough)
    ranked = sorted(deduplicated, key=_quality_sort_key)
    return ranked[:_MAX_VALIDATED_DOCUMENTS]
