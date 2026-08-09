"""Solar Pro 3 — Coverage/Gap Check, doc1 §6, plus doc2 §7/§8's additive
extensions (evidence_depth split feeds evidence_depth in contracts.py;
semantic/structural split is on CoverageDecision directly).

Also owns `extract_key_facts` — the "Solar Evidence/Gap Check" step doc1
§10/§12 runs after an HTML/PDF full-text inspection, turning raw original-
source text into the same structured KeyFact shape web_search.py produces,
so router.py can merge summary-level and original-source-level evidence into
one uniform WebSearchResult list.
"""

from __future__ import annotations

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    KeyFact,
    SearchPlan,
    SourceToInspect,
    WebSearchResult,
)


def _fallback_decision(results: list[WebSearchResult], min_results: int) -> CoverageDecision:
    """Conservative, budget-safe fallback used when no planner key is
    configured or the call failed: sufficient once we have at least
    `min_results` non-empty results, never asks for full-text (there is no
    judgment behind that extra cost without a real assessment) — this keeps
    the router's loop able to terminate even with zero AI keys set."""
    sufficient = len([result for result in results if result.summary or result.key_facts]) >= min_results
    return CoverageDecision(
        sufficient=sufficient,
        semantic_sufficient=sufficient,
        needs_full_text=False,
        reason="fallback: no planner API key configured or call failed",
    )


def check_coverage(
    question: str,
    search_plan: SearchPlan,
    results: list[WebSearchResult],
    *,
    min_results_for_fallback_sufficiency: int = 2,
    model_override: str | None = None,
) -> CoverageDecision:
    payload = {
        "question": question,
        "search_plan": search_plan.model_dump(),
        "results": [result.model_dump() for result in results],
    }
    data = _solar.call_json(
        _prompts.load("coverage"), payload, caller="coverage", model_override=model_override
    )
    if not data:
        return _fallback_decision(results, min_results_for_fallback_sufficiency)

    known_urls = {result.url for result in results}
    sources_to_inspect = [
        SourceToInspect(
            url=str(item.get("url", "")).strip(), reason=str(item.get("reason", "")).strip()
        )
        for item in data.get("sources_to_inspect", []) or []
        if isinstance(item, dict) and str(item.get("url", "")).strip() in known_urls
    ]
    return CoverageDecision(
        sufficient=bool(data.get("sufficient", False)),
        covered=[str(value) for value in data.get("covered", []) if str(value).strip()],
        missing=[str(value) for value in data.get("missing", []) if str(value).strip()],
        needs_full_text=bool(data.get("needs_full_text", False)) and bool(sources_to_inspect),
        sources_to_inspect=sources_to_inspect,
        next_queries=[str(value) for value in data.get("next_queries", []) if str(value).strip()],
        semantic_sufficient=data.get("semantic_sufficient"),
        structural_sufficient=data.get("structural_sufficient"),
        reason=str(data.get("reason", "")).strip(),
    )


def extract_key_facts(
    question: str, text: str, *, max_chars: int = 6_000, model_override: str | None = None
) -> list[KeyFact]:
    """Turn full original-source text into structured facts. Empty list on
    missing key/failure — the caller keeps the raw-text summary either way,
    this only adds structure when it's available."""
    data = _solar.call_json(
        _prompts.load("evidence_extraction"),
        {"question": question, "text": text[:max_chars]},
        caller="coverage.extract_key_facts",
        model_override=model_override,
    )
    if not data:
        return []
    facts: list[KeyFact] = []
    for item in data.get("key_facts", []) or []:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        facts.append(
            KeyFact(
                text=str(item.get("text", "")).strip(),
                metric=item.get("metric") or None,
                value=item.get("value"),
                unit=item.get("unit") or None,
                time=item.get("time") or None,
                value_type=item.get("value_type") or None,
            )
        )
    return facts
