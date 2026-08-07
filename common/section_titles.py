"""The one place a section id becomes a human-readable title.

There were two tables. `core/report_generator/generator.py` held 23 entries
that titled the actual report sections; `reporting/dashboard_streamlit/
components.py` held 5 that labelled the "dropped for lack of evidence" notice.
They overlapped on three ids with different values ("market_status" was both
"Market Status" and "시장 현황"), and the 18 ids missing from the small table
rendered as raw ids like `investment_signal` in an otherwise Korean UI.

Titles are Korean throughout. `prompts/global_system_prompt.md` principle 5
requires Korean output with no exceptions, and the old table was inconsistent
with itself - "Executive Overview" and "Root Cause" sat beside "리스크" and
"출처" in the same report. Proper nouns and established acronyms stay as-is,
which is the same carve-out that principle grants.
"""

from __future__ import annotations

SECTION_TITLES: dict[str, str] = {
    # shared / structural
    "executive_summary": "핵심 요약",
    "overview": "종합 개요",
    "key_points": "핵심 내용",
    "sources": "출처",
    "timeline": "타임라인",
    "key_metrics": "핵심 지표",
    # current_status
    "current_situation": "현재 상황",
    "market_status": "시장 현황",
    "near_term_outlook": "단기 전망",
    # issue_response
    "issue": "이슈",
    "impact": "영향",
    "response_actions": "대응 조치",
    # future_business
    "trend": "시장 변화",
    "opportunity": "기회",
    "investment_signal": "투자 신호",
    "strategic_recommendation": "전략 권고",
    # root_cause
    "problem": "문제 정의",
    "root_cause": "근본 원인",
    "improvement_plan": "개선 방안",
    # cross-purpose
    "key_implication": "핵심 시사점",
    "risk": "리스크",
    "risk_and_opportunity": "리스크·기회",
    "recommended_action": "권고 과제",
    "decision_required": "결정 필요 사항",
}


def section_title(section_id: str) -> str:
    """Title for a section id, falling back to a readable form of the id.

    The fallback exists so a newly introduced section is legible before anyone
    registers a title for it - never a silent blank header.
    """
    return SECTION_TITLES.get(section_id) or section_id.replace("_", " ").strip().title()
