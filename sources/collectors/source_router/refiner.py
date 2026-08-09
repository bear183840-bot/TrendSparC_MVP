"""Small query refiner between question-first planning and web search.

The planner remains authoritative for the user's question.  This module only
checks whether two or three compact semantic evidence needs are represented by
the plan.  It never receives block contracts, renderer rules, registry data or
dashboard layout instructions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sources.collectors.source_router import _solar
from sources.collectors.source_router.contracts import (
    EvidenceNeed,
    QueryRefinement,
    SearchPlan,
    SearchPlanQuery,
)

_REFINER_PROMPT = """You refine an existing web-search plan without replacing it.
Inputs are only the original question, explicit answer requirements, existing
queries, and up to three semantic evidence needs.

Return one JSON object:
{
  "action": "KEEP" | "ADD" | "REWRITE",
  "covered_evidence_need_ids": ["..."],
  "missing_evidence_need_ids": ["..."],
  "add_queries": [{"query": "...", "evidence_need_ids": ["..."]}],
  "rewrites": [{"replace_query": "...", "query": "...", "evidence_need_ids": ["..."]}],
  "reason": "short reason"
}

Rules:
- Never remove or rewrite a direct query.
- KEEP when existing queries already cover the evidence needs.
- ADD only for an important missing need.
- REWRITE only a redundant or low-value supporting query.
- Do not add optional context when direct requirements are not covered.
- Queries must be concise and searchable. Never mention blocks or dashboards.
"""

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_STOPWORDS = {
    "관련", "대한", "위한", "통한", "현재", "현황", "분석", "자료", "근거",
    "질문", "보고서", "필요", "확인", "같은", "실제", "주요", "the", "and",
    "for", "with", "from",
}


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(value or "")
        if len(token) > 1 and token.casefold() not in _STOPWORDS
    }


def _covered(query: str, need: EvidenceNeed) -> bool:
    wanted = _tokens(need.text)
    if not wanted:
        return True
    present = _tokens(query)
    threshold = 1 if len(wanted) <= 2 else 2
    return len(wanted & present) >= threshold


def _dedupe_text(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).split()).strip(" ;,.")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def build_evidence_needs(
    question: str,
    answer_requirements: Iterable[str] = (),
    evidence_requirements: Iterable[str] = (),
    *,
    purpose_id: str | None = None,
) -> list[EvidenceNeed]:
    """Compress existing semantic requirements into at most three needs."""
    answers = _dedupe_text(answer_requirements)
    evidence = _dedupe_text(evidence_requirements)
    needs: list[EvidenceNeed] = []

    direct_values = answers or [question.strip()]
    for index, value in enumerate(direct_values[:3], 1):
        needs.append(EvidenceNeed(
            evidence_need_id=f"direct-{index}",
            text=value,
            requirement_type="direct",
            priority=1,
            answer_requirement_ids=[f"answer-{index}"],
        ))

    remaining = 3 - len(needs)
    for index, value in enumerate(evidence, 1):
        if remaining <= 0:
            break
        if any(_tokens(value) <= _tokens(item.text) for item in needs if _tokens(value)):
            continue
        needs.append(EvidenceNeed(
            evidence_need_id=f"support-{index}",
            text=value,
            requirement_type="supporting",
            priority=2,
        ))
        remaining -= 1

    if remaining > 0 and purpose_id == "issue_response":
        needs.append(EvidenceNeed(
            evidence_need_id="support-issue",
            text="해당 이슈의 실제 영향 규모와 근거가 확인된 대응 사례 또는 선택지",
            requirement_type="supporting",
            priority=2,
        ))
    return needs[:3]


def _fallback_additions(
    question: str, plan: SearchPlan, needs: list[EvidenceNeed]
) -> tuple[list[SearchPlanQuery], list[str], list[str]]:
    covered_ids: list[str] = []
    missing_ids: list[str] = []
    additions: list[SearchPlanQuery] = []
    existing_text = [query.query for query in plan.queries]
    for need in needs:
        if any(_covered(query, need) for query in existing_text):
            covered_ids.append(need.evidence_need_id)
            continue
        missing_ids.append(need.evidence_need_id)
        additions.append(SearchPlanQuery(
            query=f"{question.strip()} {need.text}".strip(),
            angle="evidence_gap",
            purpose=need.text,
            priority=2,
            query_role="supporting",
            evidence_need_ids=[need.evidence_need_id],
        ))
    return additions, covered_ids, missing_ids


def _mark_original_roles(plan: SearchPlan, needs: list[EvidenceNeed]) -> list[SearchPlanQuery]:
    direct_need_ids = [need.evidence_need_id for need in needs if need.requirement_type == "direct"]
    direct_query_count = max(1, len(direct_need_ids))
    marked: list[SearchPlanQuery] = []
    for index, query in enumerate(plan.queries):
        # Priority-1 means "run early" in the PR contract, not that every
        # broad angle is an explicit user deliverable. Protect one query per
        # direct requirement; the remaining planner angles stay supporting.
        is_direct = query.priority == 1 and index < direct_query_count
        marked.append(query.model_copy(update={
            "query_role": "direct" if is_direct else "supporting",
            "evidence_need_ids": (
                list(query.evidence_need_ids)
                or ([direct_need_ids[min(index, len(direct_need_ids) - 1)]] if is_direct and direct_need_ids else [])
            ),
        }))
    return marked


def refine_search_plan(
    question: str,
    plan: SearchPlan,
    answer_requirements: Iterable[str] = (),
    evidence_requirements: Iterable[str] = (),
    *,
    purpose_id: str | None = None,
    max_total_queries: int = 12,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> SearchPlan:
    """Return a bounded plan while preserving every direct planner query."""
    needs = build_evidence_needs(
        question,
        answer_requirements,
        evidence_requirements,
        purpose_id=purpose_id,
    )
    base = plan.model_copy(update={
        "queries": _mark_original_roles(plan, needs),
        "evidence_needs": needs,
    })
    fallback_additions, covered_ids, missing_ids = _fallback_additions(question, base, needs)
    data = _solar.call_json(
        _REFINER_PROMPT,
        {
            "question": question,
            "answer_requirements": list(answer_requirements),
            "existing_queries": [
                {"query": query.query, "role": query.query_role}
                for query in base.queries
            ],
            "evidence_needs": [need.model_dump() for need in needs],
        },
        caller="refiner",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )

    additions = fallback_additions
    rewrites: dict[str, SearchPlanQuery] = {}
    method = "rule_fallback"
    reason = "deterministic coverage check"
    if isinstance(data, dict):
        valid_need_ids = {need.evidence_need_id for need in needs}
        parsed_additions: list[SearchPlanQuery] = []
        for item in data.get("add_queries") or []:
            if not isinstance(item, dict) or not str(item.get("query") or "").strip():
                continue
            need_ids = [
                str(value) for value in item.get("evidence_need_ids") or []
                if str(value) in valid_need_ids
            ]
            parsed_additions.append(SearchPlanQuery(
                query=str(item["query"]).strip(),
                angle="evidence_gap",
                purpose="; ".join(
                    need.text for need in needs if need.evidence_need_id in need_ids
                ),
                priority=2,
                query_role="supporting",
                evidence_need_ids=need_ids,
            ))
        for item in data.get("rewrites") or []:
            if not isinstance(item, dict):
                continue
            old = str(item.get("replace_query") or "").strip()
            new = str(item.get("query") or "").strip()
            original = next((query for query in base.queries if query.query == old), None)
            if not old or not new or original is None or original.query_role == "direct":
                continue
            rewrites[old] = original.model_copy(update={
                "query": new,
                "evidence_need_ids": [
                    str(value) for value in item.get("evidence_need_ids") or []
                    if str(value) in valid_need_ids
                ],
            })
        if parsed_additions or rewrites or str(data.get("action") or "").upper() == "KEEP":
            additions = parsed_additions
            covered_ids = [
                str(value) for value in data.get("covered_evidence_need_ids") or []
                if str(value) in valid_need_ids
            ]
            missing_ids = [
                str(value) for value in data.get("missing_evidence_need_ids") or []
                if str(value) in valid_need_ids
            ]
            method = "ai"
            reason = str(data.get("reason") or "").strip()

    rewritten_queries = [rewrites.get(query.query, query) for query in base.queries]
    direct = [query for query in rewritten_queries if query.query_role == "direct"]
    supporting = [query for query in rewritten_queries if query.query_role != "direct"]
    capacity = max(0, max_total_queries - len(direct))
    selected_supporting: list[SearchPlanQuery] = []
    seen = {query.query.casefold() for query in direct}
    for query in [*supporting, *additions]:
        key = query.query.casefold()
        if key in seen or len(selected_supporting) >= capacity:
            continue
        seen.add(key)
        selected_supporting.append(query)

    final_queries = [*direct, *selected_supporting]
    added_text = [query.query for query in additions if query in selected_supporting]
    rewritten_text = [query.query for query in rewrites.values() if query in selected_supporting]
    if rewritten_text:
        action = "REWRITE"
    elif added_text:
        action = "ADD"
    else:
        action = "KEEP"
    return base.model_copy(update={
        "queries": final_queries,
        "refinement": QueryRefinement(
            action=action,
            added_queries=added_text,
            rewritten_queries=rewritten_text,
            covered_evidence_need_ids=covered_ids,
            missing_evidence_need_ids=missing_ids,
            method=method,
            reason=reason,
        ),
    })
