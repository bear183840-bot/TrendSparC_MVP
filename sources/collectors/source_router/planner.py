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


def plan_searches(question: str, *, model_override: str | None = None) -> SearchPlan:
    data = _solar.call_json(
        _prompts.load("planner"), {"question": question}, caller="planner", model_override=model_override
    )
    if not data:
        return _fallback_plan(question)
    raw_queries = data.get("queries") or data.get("search_plan") or []
    queries = [
        SearchPlanQuery(
            query=str(item.get("query", "")).strip(),
            angle=str(item.get("angle", "")).strip(),
            purpose=str(item.get("purpose", "")).strip(),
            priority=int(item.get("priority") or 1),
        )
        for item in raw_queries
        if isinstance(item, dict) and str(item.get("query", "")).strip()
    ]
    if not queries:
        return _fallback_plan(question)
    return SearchPlan(intent=str(data.get("intent", question)), queries=queries)
