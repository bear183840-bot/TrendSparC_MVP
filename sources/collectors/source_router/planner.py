"""Solar Pro 3 — Search Planner. doc1 §4.

Plans WHAT to search before any web_search call happens, tagging each query
with an angle/purpose/priority. Priority-1 queries run first; priority-2/3
are only spent when Coverage/Gap Check says priority-1 wasn't enough (see
router.py). Falls back to a single direct-question query when no planner key
is configured or the call fails — the router must always have something to
search with.
"""

from __future__ import annotations

from typing import Literal

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import SearchPlan, SearchPlanQuery

_PURPOSE_IDS = {"current_status", "issue_response", "future_business", "root_cause"}
_AUDIENCE_IDS = {"practitioner", "executive", "management", "external"}
# Web search treats multiple quoted exact-phrase terms in one query as
# roughly an AND (same mechanism CLAUDE.md documents for Firecrawl, live-
# verified here for the GPT-5-mini-based web_search this router uses too) -
# quoting more than a couple of them in one query makes a document matching
# all of them at once vanishingly unlikely. Live-verified 2026-08-10: a
# query with 5 quoted key_terms ("20대" "30대" "40대" "TV광고" "IPTV 광고
# 효과") returned almost nothing across 8 search calls. 2 preserves the one
# pattern that genuinely needs two quoted terms together (a regulator name +
# a precise legal term, see prompts/planner.md's "Regulatory / institutional
# terminology queries" section).
_MAX_KEY_TERMS_PER_QUERY = 2


def _clamp_purpose_id(value: object) -> Literal[
    "current_status", "issue_response", "future_business", "root_cause"
] | None:
    """Same defensive-clamp spirit as coverage.py's module-private _clamp*
    helpers (not imported directly - that module's helpers are private to
    it, and this clamp is small enough not to be worth sharing)."""
    text = str(value or "").strip()
    return text if text in _PURPOSE_IDS else None  # type: ignore[return-value]


def _clamp_audience(value: object) -> Literal[
    "practitioner", "executive", "management", "external"
] | None:
    """Only the 4 selectable personas reach SearchPlan.audience.

    The pipeline's own fallback is `_default` (DEFAULT_AUDIENCE_ID) - the
    underscore-prefixed profile it uses when the caller named no audience,
    deliberately kept out of the selectable set. It is a real runtime value,
    not a bad input, so it has to become None here rather than blow up:
    "no persona was chosen" is exactly what this Optional field means, and
    STEP 2.6's audience adjustment has nothing to adjust toward. Without
    this clamp every run that did not pass --audience died with a
    ValidationError before the first search call.
    """
    text = str(value or "").strip()
    return text if text in _AUDIENCE_IDS else None  # type: ignore[return-value]


def _fallback_plan(
    question: str, *, audience: str | None = None, purpose_id: str | None = None
) -> SearchPlan:
    query = question.strip()
    if not query:
        return SearchPlan(
            intent=question,
            queries=[],
            audience=_clamp_audience(audience),
            purpose_id=_clamp_purpose_id(purpose_id),
        )
    return SearchPlan(
        intent=question,
        queries=[SearchPlanQuery(query=query, angle="direct", purpose="fallback", priority=1)],
        audience=_clamp_audience(audience),
        purpose_id=_clamp_purpose_id(purpose_id),
    )


def _apply_quoting(query: str, key_terms: list[str]) -> str:
    """Mechanically wraps each key_term that literally appears in `query` in
    quotation marks — see SearchPlanQuery.key_terms docstring for why this
    is done in code rather than left to the model's own quoting habits
    inside `query`. A term the model listed but didn't actually use in
    `query` (typo, paraphrase) is silently skipped rather than forced in —
    inserting it out of context could produce a nonsensical query."""
    result = query
    for term in key_terms:
        term = term.strip()
        if not term or term not in result:
            continue
        quoted = f'"{term}"'
        if quoted in result:
            continue  # model already quoted it itself - don't double-quote
        result = result.replace(term, quoted)
    return result


def plan_searches(
    question: str,
    *,
    audience: str | None = None,
    purpose_id: str | None = None,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> SearchPlan:
    """Plans WHAT to search, now also shaped by who the report is for
    (`audience`) and what kind of report it is (`purpose_id`) -
    prompts/planner.md's STEP 2.5/2.6 use these to expand/adjust the
    candidate angles STEP 2 already generates, not to replace them.

    `audience` is never inferred - only echoed back onto the returned
    SearchPlan, clamped to the 4 selectable personas (the pipeline's own
    `_default` fallback means "nobody picked one", which is None here).
    `purpose_id`, if not given, is classified by the same Solar call via
    `resolved_purpose_id` (defensively clamped to the 4 known values)."""
    audience = _clamp_audience(audience)
    data = _solar.call_json(
        _prompts.load("planner"),
        {
            "question": question,
            "audience": audience or "unspecified",
            "purpose_id": purpose_id or "infer",
        },
        caller="planner",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if not data:
        return _fallback_plan(question, audience=audience, purpose_id=purpose_id)
    raw_queries = data.get("queries") or data.get("search_plan") or []
    queries = []
    for item in raw_queries:
        if not isinstance(item, dict):
            continue
        raw_query = str(item.get("query", "")).strip()
        if not raw_query:
            continue
        key_terms = [
            str(term).strip() for term in item.get("key_terms") or [] if str(term).strip()
        ][:_MAX_KEY_TERMS_PER_QUERY]
        queries.append(
            SearchPlanQuery(
                query=_apply_quoting(raw_query, key_terms),
                angle=str(item.get("angle", "")).strip(),
                purpose=str(item.get("purpose", "")).strip(),
                priority=int(item.get("priority") or 1),
                key_terms=key_terms,
            )
        )
    if not queries:
        return _fallback_plan(question, audience=audience, purpose_id=purpose_id)
    resolved_purpose_id = purpose_id or _clamp_purpose_id(data.get("resolved_purpose_id"))
    return SearchPlan(
        intent=str(data.get("intent", question)),
        queries=queries,
        audience=audience,
        purpose_id=resolved_purpose_id,
    )
