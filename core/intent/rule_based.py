"""1st-pass, rule-based intent classification.

Deliberately simple keyword matching. This is the always-available fallback
that runs with no external dependency and no API key. The 2nd-pass AI-based
classifier (see ai_based.py) may refine this later; it must never be required
for the pipeline to produce a result.
"""

from __future__ import annotations

from common.contracts import IntentResult, UserRequest

_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("comparison", ("비교", "compare", "vs", "대비")),
    ("future_outlook", ("전망", "outlook", "향후", "forecast")),
    ("risk_assessment", ("리스크", "위험", "risk")),
    ("trend_analysis", ("트렌드", "동향", "trend")),
    ("current_status", ("현황", "현재", "status")),
]

_DEFAULT_INTENT = "fact_lookup"


def classify_intent_rule_based(request: UserRequest) -> IntentResult:
    question = request.question.lower()
    for intent, keywords in _KEYWORD_RULES:
        if any(keyword.lower() in question for keyword in keywords):
            return IntentResult(
                request_id=request.request_id,
                primary_intent=intent,
                confidence=0.6,
                method="rule_based",
                raw_signal={"matched_keyword_group": intent},
            )
    return IntentResult(
        request_id=request.request_id,
        primary_intent=_DEFAULT_INTENT,
        confidence=0.3,
        method="rule_based",
        raw_signal={"matched_keyword_group": None},
    )
