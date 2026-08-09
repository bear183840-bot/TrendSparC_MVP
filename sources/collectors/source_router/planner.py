"""Solar Pro 3 — Search Planner. doc1 §4.

Plans WHAT to search before any web_search call happens, tagging each query
with an angle/purpose/priority. Priority-1 queries run first; priority-2/3
are only spent when Coverage/Gap Check says priority-1 wasn't enough (see
router.py). Falls back to a single direct-question query when no planner key
is configured or the call fails — the router must always have something to
search with.
"""

from __future__ import annotations

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import SearchPlan, SearchPlanQuery


def _fallback_plan(question: str) -> SearchPlan:
    query = question.strip()
    if not query:
        return SearchPlan(intent=question, queries=[])
    return SearchPlan(
        intent=question,
        queries=[SearchPlanQuery(query=query, angle="direct", purpose="fallback", priority=1)],
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
    question: str, *, model_override: str | None = None, timeout_seconds: int = 30
) -> SearchPlan:
    data = _solar.call_json(
        _prompts.load("planner"),
        {"question": question},
        caller="planner",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if not data:
        return _fallback_plan(question)
    raw_queries = data.get("queries") or data.get("search_plan") or []
    queries = []
    for item in raw_queries:
        if not isinstance(item, dict):
            continue
        raw_query = str(item.get("query", "")).strip()
        if not raw_query:
            continue
        key_terms = [str(term).strip() for term in item.get("key_terms") or [] if str(term).strip()]
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
        return _fallback_plan(question)
    return SearchPlan(intent=str(data.get("intent", question)), queries=queries)
