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

_ORG_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z]{2,}(?:\s[A-Z][A-Za-z]{2,})*\b|[가-힣]{2,}(?:전자|하이닉스|텔레콤|브로드밴드)"
)
_TECH_PATTERN = re.compile(r"\b(HBM[0-9A-Z]*|DRAM|NAND|EUV|5G|6G|AI|IoT)\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9.+-]*")

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
    ("regulatory_policy", ("규제", "정책", "법")),
    (
        "competitor_comparison",
        (
            "비교", "대비", "격차", "경쟁사", "타사", "다른 기업", "다른 회사",
            "경쟁 업체", "경쟁업체", "누가 앞", "어디까지 왔", "수준 차이",
        ),
    ),
    (
        "market_landscape",
        ("시장", "업계", "산업", "점유율", "경쟁 구도", "시장 규모", "market", "industry"),
    ),
]
_DEFAULT_PERSPECTIVE = "company_update"

_SEARCH_STOPWORDS = {
    "그", "그거", "이거", "저거", "뭐", "무엇", "어느", "정도", "어느정도",
    "다른", "기업", "기업들", "회사", "회사들", "업체", "업체들",
    "어때", "어떻게", "뭐야", "알려줘", "해줘", "있어", "있나", "있는지",
    "개발하고", "개발하는", "수준", "수준으로", "현재", "지금",
}

_COLLOQUIAL_TOPIC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("다른 기업", "다른 회사", "타사", "경쟁사", "경쟁 업체", "경쟁업체"), "경쟁사"),
    (("어느 정도 수준", "어느정도 수준", "수준 차이", "어디까지"), "기술 수준"),
    (("개발하고 있어", "개발 중", "개발 상황", "개발 수준"), "개발 현황"),
]


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


def _extract_search_keywords(question: str, organizations: list[str], technologies: list[str]) -> list[str]:
    lowered = question.lower()
    canonical = [
        replacement
        for signals, replacement in _COLLOQUIAL_TOPIC_RULES
        if any(signal.lower() in lowered for signal in signals)
    ]
    excluded = {value.casefold() for value in [*organizations, *technologies]}
    raw = []
    for token in _WORD_PATTERN.findall(question):
        normalized = token.casefold()
        if normalized in excluded or token in _SEARCH_STOPWORDS or len(token) < 2:
            continue
        raw.append(token)
    return list(dict.fromkeys([*canonical, *raw]))


def extract_entities(request: UserRequest) -> EntityExtractionResult:
    question = request.question
    technologies = sorted({m.upper() for m in _TECH_PATTERN.findall(question)})
    technology_names = {value.casefold() for value in technologies}
    organizations = sorted({
        value for value in _ORG_PATTERN.findall(question)
        if value.casefold() not in technology_names
    })
    keywords = _extract_search_keywords(question, organizations, technologies)
    primary_intent = _classify_intent_rule_based(question)
    perspective = _classify_perspective_rule_based(question)
    return EntityExtractionResult(
        request_id=request.request_id,
        primary_intent=primary_intent,
        perspective=perspective,
        organizations=organizations,
        technologies=technologies,
        keywords=keywords,
        # The no-AI fallback cannot safely infer how many sub-questions the
        # user intended.  Keeping the complete original ask as one requirement
        # is conservative and still prevents downstream stages from treating a
        # merely adjacent document as a complete answer.
        answer_requirements=[question.strip()] if question.strip() else [],
    )
