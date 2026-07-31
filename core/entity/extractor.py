"""Generic entity extraction (+ rule-based intent classification) shared
across all sectors.

This is deliberately shallow (keyword/regex only) — it is shared
infrastructure, not sector-specific business logic. Sector adapters may layer
their own entity resolution on top via their own contracts, but the pipeline
always has this baseline available with no external dependency and no API
key. The AI-based pass (see ai_based.py) may refine both the keywords and
the intent later; neither is ever required for the pipeline to produce a
result.
"""

from __future__ import annotations

import re

from common.contracts import EntityExtractionResult, UserRequest

_ORG_PATTERN = re.compile(r"[A-Z][A-Za-z]{2,}(?:\s[A-Z][A-Za-z]{2,})*|[가-힣]{2,}(?:전자|하이닉스|텔레콤|브로드밴드)")
_TECH_PATTERN = re.compile(r"\b(HBM|DRAM|NAND|EUV|5G|6G|AI|IoT)\b", re.IGNORECASE)

_INTENT_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("issue_response", ("이슈", "대응", "문제", "issue")),
    ("future_business", ("미래", "향후", "전망", "신사업", "outlook", "forecast")),
    ("root_cause", ("원인", "왜", "root cause")),
    ("current_status", ("현황", "현재", "동향", "트렌드", "status", "trend")),
]
_DEFAULT_INTENT = "current_status"

# perspective is distinct from primary_intent: it's about *what the question
# is examining* (the whole market vs. one company vs. a comparison vs. a
# regulation), not *why* it's being asked. See EntityExtractionResult.perspective.
_PERSPECTIVE_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("market_landscape", ("현황", "동향", "점유율", "경쟁 구도", "시장 규모", "트렌드")),
    ("competitor_comparison", ("비교", "대비", "격차")),
    ("regulatory_policy", ("규제", "정책", "법")),
]
_DEFAULT_PERSPECTIVE = "company_update"


def _classify_intent_rule_based(question: str) -> str:
    lowered = question.lower()
    for intent, keywords in _INTENT_KEYWORD_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return intent
    return _DEFAULT_INTENT


def _classify_perspective_rule_based(question: str) -> str:
    lowered = question.lower()
    for perspective, keywords in _PERSPECTIVE_KEYWORD_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return perspective
    return _DEFAULT_PERSPECTIVE


def extract_entities(request: UserRequest) -> EntityExtractionResult:
    question = request.question
    organizations = sorted(set(_ORG_PATTERN.findall(question)))
    technologies = sorted({m.upper() for m in _TECH_PATTERN.findall(question)})
    keywords = sorted(set(question.split()))
    primary_intent = _classify_intent_rule_based(question)
    perspective = _classify_perspective_rule_based(question)
    return EntityExtractionResult(
        request_id=request.request_id,
        primary_intent=primary_intent,
        perspective=perspective,
        organizations=organizations,
        technologies=technologies,
        keywords=keywords,
    )
