"""Generate a complete, evidence-bound report from a structured synthesis."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy

from audience.contracts import load_audience_profile
from common.content_quality_validator import dated_items, dedupe_structured_across_sections
from common.contracts import GeneratedReport, GeneratedReportSection, ReportPlan, TrendSynthesis

_DOC_ID_RE = re.compile(r"\[doc_id=([^\]]+)\]")

_SECTION_TITLES = {
    "overview": "Executive Overview",
    "key_points": "Key Points",
    "current_situation": "Current Situation",
    "market_status": "Market Status",
    "near_term_outlook": "Near-term Outlook",
    "issue": "Issue",
    "impact": "Impact",
    "response_actions": "Action",
    "trend": "Trend",
    "opportunity": "Opportunity",
    "investment_signal": "Investment Signals",
    "strategic_recommendation": "Strategic Recommendations",
    "problem": "Problem",
    "root_cause": "Root Cause",
    "improvement_plan": "Improvement Plan",
    "key_implication": "Key Implication",
    "risk_and_opportunity": "Risk and Opportunity",
    "recommended_action": "Recommended Action",
    "key_metrics": "핵심 지표",
    "timeline": "타임라인",
    "decision_required": "결정 필요 사항",
    "risk": "리스크",
    "sources": "출처",
}

_ACTION_SECTIONS = {
    "response_actions", "improvement_plan", "strategic_recommendation",
    "recommended_action", "decision_required",
}
_TRACEABLE_FIELDS = (
    "key_points", "evidence", "risks", "opportunities", "actions", "monitoring_indicators",
)
# Structured fields (metric_points/comparison_points) are excluded here — they're
# lists of Pydantic objects, not "[doc_id=...]"-tagged strings, so they can't be
# joined into summary text the way the fields below can.
_TEXT_SUMMARY_FIELDS = (
    "key_points", "evidence", "risks", "opportunities", "strengths",
    "weaknesses", "actions", "monitoring_indicators",
)

_REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "executive_summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "section_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "opportunities": {"type": "array", "items": {"type": "string"}},
                    "actions": {"type": "array", "items": {"type": "string"}},
                    "monitoring_indicators": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": ["string", "null"]},
                },
                "required": [
                    "section_id", "title", "summary", "key_points", "evidence", "risks",
                    "opportunities", "actions", "monitoring_indicators", "confidence",
                ],
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "executive_summary", "sections", "limitations"],
}


def _take(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:limit]


def _take_raw(values: list, limit: int) -> list:
    """Slice without dedup — for structured (non-hashable-friendly) items like
    MetricPoint/ComparisonPoint, not plain strings."""
    return list(values)[:limit]


def _doc_id(value: str) -> str | None:
    match = _DOC_ID_RE.search(value)
    return match.group(1) if match else None


def _timeline_key_points(synthesis: TrendSynthesis, limit: int) -> list[str]:
    """Real dated evidence sentences + metric_series period labels only — never
    copies overview's key_points (that just duplicated Overview verbatim). If
    neither source yields a real point in time, returns [] so the timeline
    block's own empty-state ("근거에서 확인된 일정이 없습니다") shows honestly."""
    dated_evidence = dated_items(synthesis.evidence)
    metric_labels = [
        f"{point.period} — {point.label}: {point.value}{point.unit}"
        for point in synthesis.metric_series
        if point.period
    ]
    return _take([*dated_evidence, *metric_labels], limit)


def _ensure_all_actions_reachable(
    sections: list[GeneratedReportSection], synthesis: TrendSynthesis
) -> list[GeneratedReportSection]:
    """Guarantee every synthesis.recommended_actions item is reachable somewhere in
    the assembled report. OpenAI may only surface a subset of the analyzer-extracted
    actions per section; anything it dropped gets appended (with its original
    [doc_id=...] marker intact) to the first action-role section instead of silently
    disappearing. Matched by doc_id, not exact text, since the OpenAI writer may
    paraphrase the action while keeping the marker attached."""
    covered_doc_ids = {
        doc_id
        for section in sections
        for action in section.actions
        for doc_id in [_doc_id(action)]
        if doc_id is not None
    }
    missing = [action for action in synthesis.recommended_actions if _doc_id(action) not in covered_doc_ids]
    if not missing:
        return sections
    target_id = next(
        (section.section_id for section in sections if section.section_id in _ACTION_SECTIONS),
        None,
    )
    if target_id is None:
        return sections
    return [
        section.model_copy(update={"actions": [*section.actions, *missing]})
        if section.section_id == target_id
        else section
        for section in sections
    ]


def _diversity_limitations(synthesis: TrendSynthesis) -> list[str]:
    if synthesis.source_count and synthesis.unique_source_count == 1:
        source_label = synthesis.source_ids[0] if synthesis.source_ids else "단일 출처"
        return [
            f"수집 문서는 {synthesis.source_count}건이지만 고유 출처는 {synthesis.unique_source_count}개({source_label})뿐입니다. "
            "경쟁 현황과 전략 판단은 추가 출처로 교차 검증해야 합니다."
        ]
    return []


def _repair_section(
    section: GeneratedReportSection,
    fallback: GeneratedReportSection,
) -> GeneratedReportSection:
    """Normalize semantic placement and reject untraceable generated bullets."""
    data = section.model_dump()
    if section.section_id in _ACTION_SECTIONS and not data["actions"] and data["key_points"]:
        data["actions"] = data["key_points"]
        data["key_points"] = []
    fallback_data = fallback.model_dump()
    for field in _TRACEABLE_FIELDS:
        traced = [item for item in data[field] if "[doc_id=" in item]
        data[field] = traced or fallback_data[field]
    # Structured facts (metric_points/comparison_points/strengths/weaknesses) are never
    # requested from the OpenAI report writer (see _REPORT_SCHEMA) — always take them
    # from the rule-based fallback, which copies them unmodified from synthesis. This
    # keeps numbers/comparisons exactly as the analyzer extracted them, never rewritten.
    for field in ("strengths", "weaknesses", "metric_points", "comparison_points"):
        data[field] = fallback_data[field]
    if not data.get("confidence"):
        data["confidence"] = fallback.confidence
    return GeneratedReportSection.model_validate(data)


def _missing_needs_limitation(missing_information_needs: list[str] | None) -> list[str]:
    """Honest '확인 안 됨' disclosure for information needs the collector
    genuinely couldn't find grounded evidence for, after its full search
    budget - never fabricated, never silently dropped, never allowed to
    block the rest of the report (see sk_broadband's collector, which now
    accepts a partial result instead of all-or-nothing)."""
    if not missing_information_needs:
        return []
    return [
        "다음 정보는 근거를 확인하지 못해 반영하지 못했습니다 (확인 안 됨): "
        + ", ".join(missing_information_needs)
    ]


def _fallback_report(
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
    limitation: str | None = None,
    missing_information_needs: list[str] | None = None,
) -> GeneratedReport:
    profile = load_audience_profile(audience_id)
    limit = {"highlight_only": 2, "condensed": 3, "summary": 4}.get(profile.detail_level, 6)
    section_ids: list[str] = []
    kwargs_list: list[dict[str, list]] = []
    for section_id in report_plan.sections:
        key_points = synthesis.key_points or synthesis.highlights
        kwargs: dict[str, list] = {}
        if section_id in {"issue", "problem", "root_cause", "risk"}:
            kwargs["risks"] = _take(synthesis.risks, limit)
            kwargs["weaknesses"] = _take(synthesis.weaknesses, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id == "risk_and_opportunity":
            kwargs["risks"] = _take(synthesis.risks, limit)
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["strengths"] = _take(synthesis.strengths, limit)
            kwargs["weaknesses"] = _take(synthesis.weaknesses, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in {"impact", "market_status", "current_situation"}:
            kwargs["key_points"] = _take(synthesis.business_impacts or key_points, limit)
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
            kwargs["comparison_points"] = _take_raw(synthesis.comparison_points, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in _ACTION_SECTIONS:
            kwargs["actions"] = _take(synthesis.recommended_actions, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
        elif section_id == "key_metrics":
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id == "timeline":
            kwargs["key_points"] = _timeline_key_points(synthesis, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id == "sources":
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in {"opportunity", "trend", "near_term_outlook", "investment_signal"}:
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
        else:
            kwargs["key_points"] = _take(key_points, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        section_ids.append(section_id)
        kwargs_list.append(kwargs)

    # Single ownership: the same evidence-stated metric/comparison shouldn't
    # get mechanically copied into every section whose branch above happens
    # to request "metric_points"/"comparison_points" from the same synthesis
    # list - keep it only in the first (i.e. earliest in report_plan.sections
    # order) section that asked for it.
    deduped_metric_points = dedupe_structured_across_sections(
        [kwargs.get("metric_points", []) for kwargs in kwargs_list]
    )
    deduped_comparison_points = dedupe_structured_across_sections(
        [kwargs.get("comparison_points", []) for kwargs in kwargs_list]
    )
    for kwargs, metric_points, comparison_points in zip(kwargs_list, deduped_metric_points, deduped_comparison_points):
        if "metric_points" in kwargs:
            kwargs["metric_points"] = metric_points
        if "comparison_points" in kwargs:
            kwargs["comparison_points"] = comparison_points

    sections: list[GeneratedReportSection] = []
    for section_id, kwargs in zip(section_ids, kwargs_list):
        summary_values = next(
            (kwargs[field] for field in _TEXT_SUMMARY_FIELDS if kwargs.get(field)), []
        )
        sections.append(
            GeneratedReportSection(
                section_id=section_id,
                title=_SECTION_TITLES.get(section_id, section_id.replace("_", " ").title()),
                summary=" ".join(summary_values[:2]) or synthesis.synthesis_text or "분석 가능한 근거가 부족합니다.",
                confidence=", ".join(_take(synthesis.confidence_labels, 2)) or None,
                **kwargs,
            )
        )
    limitations = _diversity_limitations(synthesis)
    if synthesis.source_count == 0:
        limitations.append("분석에 사용할 수집 문서가 없어 결론을 확정할 수 없습니다.")
    limitations.extend(_missing_needs_limitation(missing_information_needs))
    if limitation:
        limitations.append(limitation)
    purpose_id = report_plan.report_purpose.purpose_id if report_plan.report_purpose else report_plan.primary_intent
    return GeneratedReport(
        request_id=synthesis.request_id,
        sector_id=synthesis.sector_id,
        audience_id=profile.audience_id,
        purpose_id=purpose_id,
        title=f"{synthesis.sector_id} {purpose_id} 보고서",
        executive_summary=synthesis.synthesis_text or "분석 가능한 근거가 부족합니다.",
        sections=sections,
        source_count=synthesis.source_count,
        unique_source_count=synthesis.unique_source_count,
        limitations=limitations,
        generation_mode="rule_based",
    )


def generate_report(
    question: str,
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
    canonical_entities: list[str] | None = None,
    missing_information_needs: list[str] | None = None,
) -> GeneratedReport:
    """Use structured output when configured; otherwise create an evidence-safe report."""
    api_key = os.getenv("TRENDSPARC_REPORT_GENERATOR_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or synthesis.source_count == 0:
        return _fallback_report(synthesis, report_plan, audience_id, missing_information_needs=missing_information_needs)

    try:
        from openai import OpenAI

        profile = load_audience_profile(audience_id)
        purpose_id = report_plan.report_purpose.purpose_id if report_plan.report_purpose else report_plan.primary_intent
        payload = {
            "question": question,
            "canonical_entities": list(dict.fromkeys(canonical_entities or [])),
            "sector_id": synthesis.sector_id,
            "purpose": {
                "id": purpose_id,
                "secondary_id": (
                    report_plan.report_purpose.secondary_purpose_id if report_plan.report_purpose else None
                ),
                "instructions": report_plan.intent_emphasis,
                "required_sections": report_plan.sections,
            },
            "audience": profile.model_dump(),
            "synthesis": synthesis.model_dump(),
        }
        schema = deepcopy(_REPORT_SCHEMA)
        section_schema = schema["properties"]["sections"]
        section_schema["minItems"] = len(report_plan.sections)
        section_schema["maxItems"] = len(report_plan.sections)
        section_schema["items"]["properties"]["section_id"]["enum"] = list(report_plan.sections)
        response = OpenAI(api_key=api_key).responses.create(
            model=os.getenv("TRENDSPARC_REPORT_GENERATOR_MODEL", "gpt-4o-mini"),
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are TrendSparC's final report writer. Write distinct, complete content for every "
                        "requested section, calibrated to the audience and purpose. Use only the supplied synthesis. "
                        "payload.audience.description and payload.purpose.instructions are not background color to "
                        "skim - they are the authoritative style/structure rules for this exact report. "
                        "audience.description lays out, in numbered sections, that audience's required information "
                        "density, vocabulary level, section length, and closing call-to-action; follow it precisely "
                        "rather than defaulting to a generic tone. purpose.instructions (when non-empty) specifies "
                        "which of this purpose's angles to emphasize and how to structure each section's content - "
                        "follow it for what to highlight and how to frame it, not just which section_ids to include. "
                        "Two reports for the same synthesis but different audience_id or purpose_id must read "
                        "differently in wording, emphasis, and depth, not just in which sections are present. "
                        "When payload.purpose.secondary_id is set, the question asks for two things at once "
                        "(e.g. current status AND how to respond) - do not let the primary purpose crowd out "
                        "the secondary one. Sections with section_id in response_actions, improvement_plan, "
                        "strategic_recommendation, recommended_action, or decision_required must then contain "
                        "at least 4 distinct items in actions, each ending with its own [doc_id=...] citation "
                        "drawn from synthesis.recommended_actions - do not under-fill them to 1-2 items. "
                        "Keep every [doc_id=...] marker attached to its claim, never invent facts, and state uncertainty. "
                        "Copy names in canonical_entities exactly; never abbreviate, translate, or respell them. "
                        "Put recommendations in actions, risks in risks, opportunities in opportunities, and sources in evidence. "
                        "Return every required section_id exactly once and in the supplied order. "
                        "For an executive report, use: so-what summary, key metrics, timeline, decision required, risk, sources. "
                        "Include only evidenced KPI values and timeline events; otherwise label what still needs verification. "
                        "Treat unsupported recommendations as proposals to review, not established decisions. "
                        "The output-language rule is strict: write the title, executive summary, every section, "
                        "and every limitation in the question's language. For a Korean question, all narrative "
                        "text must be Korean; keep only proper names and standard acronyms such as NVIDIA, HBM, "
                        "AI, and ARPU in English. Before returning JSON, verify every narrative field against "
                        "the question's language."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "trend_report",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        parsed = json.loads(response.output_text)
        fallback = _fallback_report(synthesis, report_plan, audience_id)
        fallback_by_id = {section.section_id: section for section in fallback.sections}
        returned_by_id = {
            section["section_id"]: GeneratedReportSection.model_validate(section)
            for section in parsed["sections"]
            if section.get("section_id") in fallback_by_id
        }
        missing = [section_id for section_id in report_plan.sections if section_id not in returned_by_id]
        sections = [
            _repair_section(returned_by_id.get(section_id, fallback_by_id[section_id]), fallback_by_id[section_id])
            for section_id in report_plan.sections
        ]
        sections = _ensure_all_actions_reachable(sections, synthesis)
        limitations = list(
            dict.fromkeys(
                [
                    *parsed["limitations"],
                    *_diversity_limitations(synthesis),
                    *_missing_needs_limitation(missing_information_needs),
                ]
            )
        )
        if missing:
            limitations.append(
                "OpenAI가 누락한 섹션을 수집 근거 기반 규칙 결과로 보완했습니다: " + ", ".join(missing)
            )
        return GeneratedReport(
            request_id=synthesis.request_id,
            sector_id=synthesis.sector_id,
            audience_id=profile.audience_id,
            purpose_id=purpose_id,
            source_count=synthesis.source_count,
            unique_source_count=synthesis.unique_source_count,
            generation_mode="openai",
            title=parsed["title"],
            executive_summary=parsed["executive_summary"],
            sections=sections,
            limitations=limitations,
        )
    except Exception as exc:
        return _fallback_report(
            synthesis,
            report_plan,
            audience_id,
            limitation=(
                "OpenAI 보고서 생성에 실패해 규칙 기반 결과를 사용했습니다: "
                f"{type(exc).__name__}: {str(exc)[:240]}"
            ),
            missing_information_needs=missing_information_needs,
        )
