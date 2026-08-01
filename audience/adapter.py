"""Adapt a TrendSynthesis + ReportPlan into an AudienceAdaptation.

Driven entirely by the audience's registered profile — never by comparing
audience_id against a literal name.
"""

from __future__ import annotations

from audience.contracts import load_audience_profile
from common.contracts import AudienceAdaptation, ReportPlan, TrendSynthesis

_DETAIL_LIMITS = {
    "highlight_only": 2,
    "condensed": 3,
    "summary": 4,
}

_SECTION_GOALS = {
    "overview": "질문에 대한 결론과 전체 맥락",
    "key_points": "중요 근거와 변화 신호",
    "current_situation": "현재 확인된 사실과 상태",
    "market_status": "시장 구조와 경쟁 위치",
    "near_term_outlook": "단기 변화와 모니터링 포인트",
    "issue": "대응이 필요한 핵심 이슈",
    "impact": "사업·고객·운영 영향",
    "response_actions": "우선순위와 실행 주체가 있는 대응안",
    "trend": "중장기 기술·시장 변화",
    "opportunity": "근거가 확인된 사업 기회",
    "investment_signal": "투자 판단 신호와 불확실성",
    "strategic_recommendation": "의사결정 가능한 전략 대안",
    "problem": "관찰된 문제와 범위",
    "root_cause": "근거로 연결된 원인 구조",
    "improvement_plan": "검증 가능한 개선 조치",
}


def _visible_highlights(highlights: list[str], detail_level: str) -> list[str]:
    limit = _DETAIL_LIMITS.get(detail_level)
    return highlights if limit is None else highlights[:limit]


def adapt_for_audience(
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
) -> AudienceAdaptation:
    profile = load_audience_profile(audience_id)

    purpose = report_plan.report_purpose
    visible_highlights = _visible_highlights(synthesis.highlights, profile.detail_level)
    adapted_sections = {}
    for section in report_plan.sections:
        adapted_sections[section] = {
            "section_goal": _SECTION_GOALS.get(section, section.replace("_", " ")),
            "purpose_id": purpose.purpose_id if purpose else report_plan.primary_intent,
            "purpose_description": purpose.description if purpose else None,
            "tone": profile.tone,
            "detail_level": profile.detail_level,
            "audience_focus": list(profile.focus),
            "audience_guidance": profile.description,
            "summary": synthesis.synthesis_text,
            "highlights": list(visible_highlights),
            "source_count": synthesis.source_count,
        }

    return AudienceAdaptation(
        request_id=report_plan.request_id,
        audience_id=profile.audience_id,
        tone=profile.tone,
        adapted_sections=adapted_sections,
    )
