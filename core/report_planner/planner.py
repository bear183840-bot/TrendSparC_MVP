"""Build a ReportPlan from synthesis, audience, and report purpose.

Report purpose is now an explicit contract produced by
core/report_purpose/classifier.py. `primary_intent` is still carried for
backwards compatibility, but new downstream code should read
`ReportPlan.report_purpose.purpose_id`.

Prompt lookup order:
1. prompts/report_purposes/<purpose_id>.md  (canonical, new work goes here)
2. prompts/report_structures/<purpose_id>.md (legacy compatibility)
"""

from __future__ import annotations

from pathlib import Path

from audience.contracts import load_audience_profile
from common.contracts import ReportPlan, ReportPurposeClassification, TrendSynthesis

_BASE_SECTIONS = ["overview"]
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPORT_PURPOSES_DIR = _PROJECT_ROOT / "prompts" / "report_purposes"
_LEGACY_REPORT_STRUCTURES_DIR = _PROJECT_ROOT / "prompts" / "report_structures"


_PURPOSE_LABELS = {
    "current_status": "현황 파악",
    "issue_response": "이슈 대응",
    "future_business": "미래사업",
    "root_cause": "문제 분석",
}

_SECTION_GROUPS = {
    "overview": "overview",
    "key_implication": "overview",
    "issue": "risk",
    "problem": "risk",
    "root_cause": "cause",
    "risk_and_opportunity": "risk",
    "impact": "impact",
    "response_actions": "action",
    "recommended_action": "action",
    "strategic_recommendation": "action",
    "improvement_plan": "action",
}


def _dedupe_semantic_sections(sections: list[str]) -> list[str]:
    """Keep purpose-specific sections ahead of overlapping audience aliases."""
    selected: list[str] = []
    groups: set[str] = set()
    for section in sections:
        group = _SECTION_GROUPS.get(section, section)
        if group in groups:
            continue
        groups.add(group)
        selected.append(section)
    return selected


def _load_intent_emphasis(purpose_id: str) -> str | None:
    for directory in (_REPORT_PURPOSES_DIR, _LEGACY_REPORT_STRUCTURES_DIR):
        path = directory / f"{purpose_id}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return None


def _coerce_report_purpose(
    synthesis: TrendSynthesis,
    report_purpose: ReportPurposeClassification | str,
) -> ReportPurposeClassification | None:
    if isinstance(report_purpose, ReportPurposeClassification):
        return report_purpose

    # Backwards-compatible path for older tests/callers that still pass a raw
    # intent string. Unknown strings are allowed to behave exactly as before:
    # ReportPlan.primary_intent carries the raw value, intent_emphasis is None,
    # and the new report_purpose field stays empty.
    purpose_id = report_purpose
    if purpose_id not in _PURPOSE_LABELS:
        return None

    return ReportPurposeClassification(
        request_id=synthesis.request_id,
        purpose_id=purpose_id,  # type: ignore[arg-type]
        display_name=_PURPOSE_LABELS[purpose_id],
        confidence="low",
        reason="backwards-compatible raw purpose string passed to plan_report",
        classifier_version="compat_raw_string",
        recommended_sections=[],
        dashboard_block_hints=[],
    )


def plan_report(
    synthesis: TrendSynthesis,
    audience_id: str,
    report_purpose: ReportPurposeClassification | str,
) -> ReportPlan:
    profile = load_audience_profile(audience_id)
    purpose = _coerce_report_purpose(synthesis, report_purpose)
    raw_purpose_id = report_purpose if isinstance(report_purpose, str) else report_purpose.purpose_id
    purpose_id = purpose.purpose_id if purpose is not None else raw_purpose_id
    purpose_sections = purpose.recommended_sections if purpose is not None else []
    sections = _dedupe_semantic_sections(_BASE_SECTIONS + list(purpose_sections) + list(profile.focus))

    return ReportPlan(
        request_id=synthesis.request_id,
        audience_id=profile.audience_id,
        primary_intent=purpose_id,
        report_purpose=purpose,
        sections=sections,
        format=profile.format_preference,
        intent_emphasis=_load_intent_emphasis(purpose_id),
    )
