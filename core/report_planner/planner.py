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
from common.content_quality_validator import dated_items
from common.contracts import (
    ReportPlan,
    ReportPurposeClassification,
    SectionEvidenceRefs,
    TrendSynthesis,
)
from core.report_purpose.classifier import recommended_sections_for

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
    "decision_required": "action",
}

_CLAIM_TYPES_BY_SECTION = {
    "overview": {"key_point", "business_impact"},
    "key_points": {"key_point"},
    "current_situation": {"key_point", "business_impact", "comparison", "metric"},
    "market_status": {"key_point", "business_impact", "comparison", "metric"},
    "near_term_outlook": {"opportunity", "monitoring", "key_point"},
    "issue": {"risk", "weakness", "key_point"},
    "problem": {"risk", "weakness", "key_point"},
    "root_cause": {"risk", "weakness", "key_point"},
    "risk": {"risk", "weakness"},
    "risk_and_opportunity": {"risk", "opportunity", "strength", "weakness"},
    "impact": {"business_impact", "risk", "opportunity"},
    "trend": {"key_point", "opportunity", "monitoring"},
    "opportunity": {"opportunity", "strength"},
    "investment_signal": {"opportunity", "business_impact", "monitoring"},
    "response_actions": {"action"},
    "recommended_action": {"action"},
    "strategic_recommendation": {"action"},
    "improvement_plan": {"action"},
    "decision_required": {"action"},
    "key_metrics": {"key_point", "business_impact", "monitoring", "metric"},
    "timeline": {"key_point", "monitoring"},
}

_METRIC_SECTIONS = {"current_situation", "market_status", "impact", "key_metrics", "timeline", "investment_signal"}
# Sections that can carry an entity-vs-entity comparison. The diagnostic
# sections belong here as much as the descriptive ones: a root-cause report's
# comparison is usually the causes ranked against each other, and with only
# the descriptive sections listed that ranking was routed to "impact", where
# it lost the block-type tie to the metric chart and rendered nowhere - while
# the "root_cause" section, having no comparison data of its own, fell back to
# a SWOT matrix that says nothing about causation.
#
# report_generator imports this rather than keeping its own copy; the two had
# already drifted, so editing one silently did nothing.
COMPARISON_SECTIONS = {
    "current_situation", "market_status", "impact", "root_cause", "problem", "issue",
}
_COMPARISON_SECTIONS = COMPARISON_SECTIONS
_CONTENT_SENSITIVE_SECTIONS = {
    "key_metrics": "검증된 수치 자료가 없음",
    "timeline": "서로 다른 시점의 근거가 충분하지 않음",
    "market_status": "시장 수치 또는 비교 근거가 없음",
    "risk_and_opportunity": "위험·기회 근거가 없음",
    "recommended_action": "검증된 행동 근거가 없음",
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


def _has_timeline_evidence(synthesis: TrendSynthesis) -> bool:
    periods_by_label: dict[str, set[str]] = {}
    for point in synthesis.metric_series:
        if point.label and point.period:
            periods_by_label.setdefault(point.label, set()).add(point.period)
    if any(len(periods) >= 2 for periods in periods_by_label.values()):
        return True
    claim_dates = {
        claim.as_of_date for claim in synthesis.grounded_claims if claim.as_of_date
    }
    if len(claim_dates) >= 2:
        return True
    # Dated evidence prose counts too. report_generator._timeline_key_points
    # builds the timeline section from exactly these sentences, so judging
    # timeline-worthiness only on structured dates meant a report could be
    # denied the section the generator was perfectly able to fill.
    return len(dated_items(synthesis.evidence)) >= 2


def _has_claim_slot(sections: list[str], claim_types: set[str]) -> bool:
    return any(
        bool(_CLAIM_TYPES_BY_SECTION.get(section, set()) & claim_types)
        for section in sections
    )


def _content_backed_sections(
    synthesis: TrendSynthesis, existing_sections: list[str]
) -> list[str]:
    sections: list[str] = []
    claim_types = {claim.claim_type for claim in synthesis.grounded_claims}
    if synthesis.metric_series and not any(
        section in _METRIC_SECTIONS for section in existing_sections
    ):
        sections.append("key_metrics")
    if synthesis.comparison_points and not any(
        section in _COMPARISON_SECTIONS for section in existing_sections
    ):
        sections.append("market_status")
    if _has_timeline_evidence(synthesis) and "timeline" not in existing_sections:
        sections.append("timeline")
    strategic_types = {"risk", "opportunity", "strength", "weakness"}
    if claim_types & strategic_types and not _has_claim_slot(
        existing_sections, claim_types & strategic_types
    ):
        sections.append("risk_and_opportunity")
    if (
        "action" in claim_types or synthesis.recommended_actions
    ) and not _has_claim_slot(existing_sections, {"action"}):
        sections.append("recommended_action")
    if (synthesis.sources or synthesis.source_ids) and "sources" not in existing_sections:
        sections.append("sources")
    return sections


def _section_evidence_refs(
    section: str, synthesis: TrendSynthesis
) -> SectionEvidenceRefs:
    allowed_types = _CLAIM_TYPES_BY_SECTION.get(section)
    if section == "sources":
        claims = list(synthesis.grounded_claims)
    elif allowed_types is None:
        claims = []
    else:
        claims = [
            claim for claim in synthesis.grounded_claims
            if claim.claim_type in allowed_types
        ]
    if section == "timeline":
        claims = [claim for claim in claims if claim.as_of_date]
    claim_ids = [claim.synthesis_claim_id for claim in claims]
    claim_id_set = set(claim_ids)
    conclusion_ids = [
        conclusion.conclusion_id
        for conclusion in synthesis.conclusions
        if section == "overview"
        or claim_id_set.intersection(conclusion.supporting_claim_ids)
    ]
    metric_ids = []
    if section in _METRIC_SECTIONS:
        metric_ids = [
            point.metric_id for point in synthesis.metric_series if point.metric_id
        ]
        if section == "timeline" and not _has_timeline_evidence(synthesis):
            metric_ids = []
    comparison_ids = [
        point.comparison_id
        for point in synthesis.comparison_points
        if section in _COMPARISON_SECTIONS and point.comparison_id
    ]
    return SectionEvidenceRefs(
        conclusion_ids=list(dict.fromkeys(conclusion_ids)),
        claim_ids=list(dict.fromkeys(claim_ids)),
        metric_ids=list(dict.fromkeys(metric_ids)),
        comparison_ids=list(dict.fromkeys(comparison_ids)),
    )


# What each content-sensitive section is *actually* filled from, beyond the
# id-based refs. A ref id is internal bookkeeping the synthesizer assigns;
# the section's content is the data itself. Judging on ids alone dropped
# sections whose data was right there - `recommended_action` was added by
# _recommended_sections() because synthesis.recommended_actions was non-empty
# and then immediately omitted here for having no action-typed claim, and
# `key_metrics` was omitted whenever the metric points carried no metric_id.
_SECTION_CONTENT_FIELDS: dict[str, tuple[str, ...]] = {
    "key_metrics": ("metric_series",),
    "market_status": ("metric_series", "comparison_points"),
    "risk_and_opportunity": ("risks", "opportunities", "strengths", "weaknesses"),
    "recommended_action": ("recommended_actions",),
}


def _has_section_evidence(
    section: str, refs: SectionEvidenceRefs, synthesis: TrendSynthesis
) -> bool:
    if section == "timeline":
        # Dated evidence prose counts alongside structured refs, because
        # report_generator._timeline_key_points fills the section from those
        # sentences - judging on refs alone dropped timelines the generator
        # could have written.
        return bool(refs.metric_ids or refs.claim_ids) or _has_timeline_evidence(synthesis)
    if any(
        getattr(synthesis, field, None) for field in _SECTION_CONTENT_FIELDS.get(section, ())
    ):
        return True
    return bool(
        refs.conclusion_ids or refs.claim_ids or refs.metric_ids or refs.comparison_ids
    )


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
        # Resolve the purpose's own sections rather than leaving this empty.
        # It could stay empty while the audience's fixed structure supplied
        # the shape; now that the purpose supplies it, an empty list would
        # reduce a string-purpose caller's report to overview + sources.
        recommended_sections=recommended_sections_for(purpose_id),
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
    if purpose is not None and purpose.secondary_purpose_id:
        # A compound question (e.g. "현황은? 그리고 어떻게 개선하지?") needs both
        # purposes' sections, not just the winner's - see
        # content_quality_validator.detect_secondary_purpose.
        purpose_sections = [*purpose_sections, *recommended_sections_for(purpose.secondary_purpose_id)]
    # Purpose decides the report's shape; audience decides how it reads.
    #
    # This used to branch on `profile.report_structure`, which every one of
    # the four selectable audiences defines - so on the real user path the
    # purpose contributed nothing at all and "현황파악" and "원인분석" produced
    # byte-identical section lists. Now the same purpose yields the same
    # sections for every audience, and the audience shapes only the writing:
    # `profile.focus`/`tone`/`detail_level` reach report_generator through the
    # audience payload and the per-audience prompt, not the section list.
    planned_sections = _BASE_SECTIONS + list(purpose_sections)

    candidate_sections = _dedupe_semantic_sections(
        [*planned_sections, *_content_backed_sections(synthesis, planned_sections)]
    )
    # Sections whose whole point is structured evidence (a metrics panel, a
    # timeline) are dropped when that evidence is missing, *even when the
    # purpose asked for them* - a purpose saying "this report is about the
    # numbers" doesn't conjure numbers, and an empty 핵심 지표 panel is worse
    # than an honest "근거 없어 제외" note. Everything else the purpose asked
    # for is kept so the report still has its intended shape.
    required_groups = {
        _SECTION_GROUPS.get(section, section)
        for section in [*_BASE_SECTIONS, *purpose_sections]
        if section not in _CONTENT_SENSITIVE_SECTIONS
    }
    sections: list[str] = []
    section_evidence_map: dict[str, SectionEvidenceRefs] = {}
    omitted_sections: dict[str, str] = {}
    for section in candidate_sections:
        refs = _section_evidence_refs(section, synthesis)
        group = _SECTION_GROUPS.get(section, section)
        omission_reason = _CONTENT_SENSITIVE_SECTIONS.get(section)
        if (
            omission_reason
            and group not in required_groups
            and not _has_section_evidence(section, refs, synthesis)
        ):
            omitted_sections[section] = omission_reason
            continue
        sections.append(section)
        section_evidence_map[section] = refs

    return ReportPlan(
        request_id=synthesis.request_id,
        audience_id=profile.audience_id,
        primary_intent=purpose_id,
        report_purpose=purpose,
        sections=sections,
        section_evidence_map=section_evidence_map,
        omitted_sections=omitted_sections,
        format=profile.format_preference,
        intent_emphasis=_load_intent_emphasis(purpose_id),
    )
