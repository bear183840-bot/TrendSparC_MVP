"""Classify what kind of report the user's question needs.

This module intentionally sits between sector routing and source planning.
Sector routing answers "which domain should handle the question?" while report
purpose classification answers "what kind of decision-support output should be
built?".

The current implementation is a deterministic skeleton that maps the existing
entity primary_intent into one of the four mentor-approved report purposes. The
interface is stable so the team can later replace the internals with a runtime
prompt or LLM classifier without changing downstream contracts.
"""

from __future__ import annotations

from pathlib import Path

from common.content_quality_validator import PRESCRIPTIVE_INTENT_SIGNALS, detect_secondary_purpose
from common.contracts import EntityExtractionResult, ReportPurposeClassification, SectorRoute

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPORT_PURPOSE_PROMPT_DIR = _PROJECT_ROOT / "prompts" / "report_purposes"
_CLASSIFIER_VERSION = "rule_based_v2"

_PURPOSE_DEFINITIONS: dict[str, dict] = {
    "current_status": {
        "display_name": "현황 파악",
        "description": "현재 상황, 시장 상태, 주요 변화와 전망을 파악하는 보고 목적",
        # KPI and time series lead: a 현황/추이 question is answered by the
        # numbers first and the narrative second. `key_metrics` and
        # `timeline` are content-sensitive, so they drop out honestly when
        # the evidence has no figures rather than rendering empty panels.
        "recommended_sections": [
            "key_metrics", "market_status", "timeline", "current_situation", "near_term_outlook",
        ],
        "dashboard_block_hints": ["metrics", "chart", "timeline", "source_evidence"],
    },
    "issue_response": {
        "display_name": "이슈 대응",
        "description": "특정 이슈의 영향과 대응 방안을 정리하는 보고 목적",
        "recommended_sections": ["issue", "impact", "response_actions"],
        "dashboard_block_hints": ["issue_summary", "impact_map", "action_items"],
    },
    "future_business": {
        "display_name": "미래사업",
        "description": "신사업, 투자, 기술/시장 기회를 탐색하는 보고 목적",
        "recommended_sections": ["trend", "opportunity", "investment_signal", "strategic_recommendation"],
        "dashboard_block_hints": ["opportunity_map", "technology_signal", "recommendation"],
    },
    "root_cause": {
        "display_name": "문제 분석",
        "description": "문제의 원인, 영향, 개선 방향을 분석하는 보고 목적",
        "recommended_sections": ["problem", "root_cause", "impact", "improvement_plan"],
        "dashboard_block_hints": ["cause_tree", "impact_summary", "improvement_actions"],
    },
}

_PRIMARY_INTENT_TO_PURPOSE = {
    "current_status": "current_status",
    "status": "current_status",
    "market_landscape": "current_status",
    "issue_response": "issue_response",
    "issue": "issue_response",
    "risk_response": "issue_response",
    "future_business": "future_business",
    "opportunity": "future_business",
    "strategy": "future_business",
    "root_cause": "root_cause",
    "problem_analysis": "root_cause",
    "cause_analysis": "root_cause",
}

_KEYWORD_FALLBACKS: list[tuple[str, tuple[str, ...]]] = [
    ("issue_response", ("이슈", "리스크", "위험", "대응", "규제", "영향", "논란")),
    ("future_business", ("미래", "전망", "신사업", "투자", "기회", "추천", "전략")),
    ("root_cause", ("원인", "왜", "문제", "개선", "해결", "하락", "감소")),
    ("current_status", ("현황", "시장", "동향", "요즘", "현재", "트렌드")),
]

# These signals express an explicit request for response planning. They take
# precedence over a broad AI/entity intent such as root_cause because a question
# can mention risks and actions without asking why a problem happened.
_EXPLICIT_ISSUE_RESPONSE_SIGNALS = ("이슈", "리스크", "위험", "대응", "조치", "issue", "risk", "response")

_PURPOSE_SIGNALS: dict[str, tuple[str, ...]] = {
    "issue_response": ("이슈", "리스크", "위험", "대응", "조치", "완화", "규제 대응", "issue", "risk", "response"),
    "future_business": (
        "미래", "전망", "신사업", "투자", "기회", "성장", "로드맵", "future", "outlook", "forecast", "opportunity",
        *PRESCRIPTIVE_INTENT_SIGNALS,
    ),
    "root_cause": ("원인", "왜", "이유", "근본", "병목", "하락 원인", "감소 원인", "root cause", "why"),
    "current_status": ("현황", "현재", "동향", "시장", "경쟁 구도", "점유율", "실적", "추이", "status", "trend"),
}
_PURPOSE_TIE_PRIORITY = ("issue_response", "root_cause", "future_business", "current_status")
_SECONDARY_PURPOSE_THRESHOLD = 4


def recommended_sections_for(purpose_id: str) -> list[str]:
    """Public lookup so other stages (report_planner) can pull a purpose's
    recommended sections - e.g. for a detected secondary purpose - without
    duplicating _PURPOSE_DEFINITIONS."""
    definition = _PURPOSE_DEFINITIONS.get(purpose_id)
    return list(definition["recommended_sections"]) if definition else []


def _prompt_path_for(purpose_id: str) -> str | None:
    path = _REPORT_PURPOSE_PROMPT_DIR / f"{purpose_id}.md"
    if not path.is_file():
        return None
    return str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/")


def _infer_from_question_terms(entities: EntityExtractionResult) -> str | None:
    terms = " ".join([*entities.keywords, *entities.technologies, *entities.organizations]).lower()
    if not terms:
        return None
    for purpose_id, signals in _KEYWORD_FALLBACKS:
        if any(signal.lower() in terms for signal in signals):
            return purpose_id
    return None


def classify_report_purpose(
    request_id: str,
    entities: EntityExtractionResult,
    sector_route: SectorRoute | None = None,
    question: str | None = None,
) -> ReportPurposeClassification:
    """Return a stable report-purpose contract for downstream planning.

    `sector_route` is accepted now so a future classifier can use sector profile
    context. The current rule-based skeleton does not branch on sector name.
    """

    terms = " ".join([question or "", *entities.keywords, *entities.technologies, *entities.organizations]).lower()
    mapped_primary_purpose = _PRIMARY_INTENT_TO_PURPOSE.get(entities.primary_intent)
    scores = {purpose_id: 0 for purpose_id in _PURPOSE_DEFINITIONS}
    matched_signals: dict[str, list[str]] = {purpose_id: [] for purpose_id in _PURPOSE_DEFINITIONS}
    if mapped_primary_purpose:
        scores[mapped_primary_purpose] += 4
    for purpose_id, signals in _PURPOSE_SIGNALS.items():
        for signal in signals:
            if signal.lower() in terms:
                scores[purpose_id] += 2
                matched_signals[purpose_id].append(signal)
    # An explicit response or causal request is more decisive than a broad AI
    # label. This is generic across sectors and question subjects.
    if any(signal.lower() in terms for signal in _EXPLICIT_ISSUE_RESPONSE_SIGNALS):
        scores["issue_response"] += 3
    if any(signal.lower() in terms for signal in ("원인", "왜", "이유", "근본", "root cause", "why")):
        scores["root_cause"] += 3

    purpose_id = max(_PURPOSE_TIE_PRIORITY, key=lambda candidate: scores[candidate])
    top_score = scores[purpose_id]
    runner_up = max(score for candidate, score in scores.items() if candidate != purpose_id)
    if top_score == 0:
        purpose_id = "current_status"
        reason = "fallback to current_status because no report purpose signal matched"
        confidence = "low"
    else:
        reason = (
            f"scored from primary_intent='{entities.primary_intent}' and signals="
            f"{matched_signals[purpose_id]}; scores={scores}"
        )
        confidence = "high" if top_score >= 4 and top_score - runner_up >= 2 else "medium"

    secondary_purpose_id = detect_secondary_purpose(scores, purpose_id, threshold=_SECONDARY_PURPOSE_THRESHOLD)

    definition = _PURPOSE_DEFINITIONS[purpose_id]
    return ReportPurposeClassification(
        request_id=request_id,
        purpose_id=purpose_id,
        display_name=definition["display_name"],
        description=definition["description"],
        confidence=confidence,
        reason=reason,
        classifier_version=_CLASSIFIER_VERSION,
        recommended_sections=list(definition["recommended_sections"]),
        dashboard_block_hints=list(definition["dashboard_block_hints"]),
        prompt_path=_prompt_path_for(purpose_id),
        secondary_purpose_id=secondary_purpose_id,
    )
