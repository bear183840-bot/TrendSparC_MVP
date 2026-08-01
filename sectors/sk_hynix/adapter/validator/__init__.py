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

from datetime import datetime, timedelta, timezone

from common.contracts import SourceDocument

_MIN_CONTENT_LENGTH = 200  # below this a page is almost never a real article body
_MAX_DOCUMENT_AGE_DAYS = 730
_MAX_VALIDATED_DOCUMENTS = 8

# Ranks a document's source when trimming down to _MAX_VALIDATED_DOCUMENTS —
# mirrors the same 3-tier convention documented on PlannedSource.reliability_tier
# in common/contracts.py. Unset/unrecognized tiers rank last, never guessed.
_RELIABILITY_RANK = {"official": 0, "analyst_media": 1, "user_generated": 2}


def _is_valid(document: SourceDocument) -> bool:
    if not document.source_id or not document.url:
        return False
    if not document.content or len(document.content) < _MIN_CONTENT_LENGTH:
        return False
    return True


def _is_recent_enough(document: SourceDocument) -> bool:
    # Missing published_at is common (Firecrawl doesn't always extract a
    # date) and must not be penalized — only reject when we actually know
    # the document is stale, never guess staleness from absence of a date.
    if document.published_at is None:
        return True
    published_at = document.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - published_at <= timedelta(days=_MAX_DOCUMENT_AGE_DAYS)


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


def validate(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    structurally_valid = [document for document in source_documents if _is_valid(document)]
    recent_enough = [document for document in structurally_valid if _is_recent_enough(document)]
    deduplicated = _drop_cross_source_title_duplicates(recent_enough)
    ranked = sorted(deduplicated, key=_quality_sort_key)
    return ranked[:_MAX_VALIDATED_DOCUMENTS]
