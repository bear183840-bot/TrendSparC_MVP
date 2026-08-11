"""Question-sensitive recency window, shared across two consumers that each
need the same "how far back is 'recent' for this question" judgment at a
different point in the pipeline:

- `sectors/sk_broadband/adapter/validator` uses it post-hoc, to filter
  already-collected documents by age.
- `sources/collectors/source_router/planner.py` uses it upstream, to hint
  the query-generation model about how recent the evidence it searches for
  should be (see that module's `_assemble_system_prompt`).

Extracted 2026-08-11 from `sectors/sk_broadband/adapter/validator/__init__.py`,
where this logic originated and is still the only production caller of
`_is_recent_enough()`. This module is a behavior-preserving extraction: every
branch, regex, and threshold below is byte-for-byte identical to the
original. The functions here take plain primitives (not `WebSearchContext`)
so that `sources/collectors/source_router/` — which deliberately does not
import `common.contracts` domain shapes into its own package (see
`sources/collectors/source_router/contracts.py`'s module docstring) — can
call this module without violating that boundary.
"""

from __future__ import annotations

import re

_MAX_DOCUMENT_AGE_DAYS = 730

# A strong "latest" request: requires a verifiable date downstream and caps
# the window to 30 days.
_LATEST_TERMS = ("오늘", "금일", "실시간", "방금", "이번 주", "금주", "가장 최신", "가장 최근")


def max_age_days(
    question: str | None,
    as_of_date: str | None = None,
    report_purpose_id: str | None = None,
) -> int | None:
    """Returns the recency window in days a question implies, or `None` if
    unbounded (e.g. a historical/background question). Exact port of
    `sectors/sk_broadband/adapter/validator/__init__.py`'s original
    `_max_age_days(search_context)`, generalized from `WebSearchContext` to
    plain primitives — the original's `search_context is None` early return
    is preserved here as a `question` falsiness check, since the only
    caller of the original always had a non-empty `question` string when
    `search_context` was not None.
    """
    if not question:
        return _MAX_DOCUMENT_AGE_DAYS
    lowered = question.lower()
    ranged_years = re.search(r"(?:최근|지난)\s*(\d+)\s*년", lowered)
    if ranged_years:
        return max(365, int(ranged_years.group(1)) * 366)
    ranged_months = re.search(r"(?:최근|지난)\s*(\d+)\s*개월", lowered)
    if ranged_months:
        return max(30, int(ranged_months.group(1)) * 31)
    if any(term in lowered for term in ("역사", "과거", "도입 배경", "장기 추이")):
        return None
    if any(term in lowered for term in _LATEST_TERMS):
        return 30
    if "최신" in lowered:
        return 90
    if any(term in lowered for term in ("최근", "현재", "지금", "요즘", "이번 달")):
        return 180
    if as_of_date and as_of_date[:4] in lowered:
        return 365
    if report_purpose_id == "current_status":
        return 365
    return _MAX_DOCUMENT_AGE_DAYS


def requires_verified_published_at(question: str | None) -> bool:
    """Exact port of the original `_requires_verified_published_at`: a
    strong "latest" request requires a verifiable published date rather
    than defaulting to keeping undated evidence."""
    if not question:
        return False
    lowered = question.lower()
    return any(term in lowered for term in _LATEST_TERMS)


def format_recency_hint(days: int | None) -> str:
    """Human-readable Korean hint for prompt injection, e.g. for
    `sources/collectors/source_router/planner.py`'s Solar payload. Not used
    by the validator (which only needs the numeric window), so this stays
    separate from `max_age_days()` rather than folded into it."""
    if days is None:
        return "특별한 기간 제약 없음"
    return f"최근 {days}일 이내"
