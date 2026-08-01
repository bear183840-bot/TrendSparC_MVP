"""Generate a complete, evidence-bound report from a structured synthesis."""

from __future__ import annotations

import json
import os
from copy import deepcopy

from audience.contracts import load_audience_profile
from common.contracts import GeneratedReport, GeneratedReportSection, ReportPlan, TrendSynthesis

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
}

_ACTION_SECTIONS = {"response_actions", "improvement_plan", "strategic_recommendation", "recommended_action"}
_TRACEABLE_FIELDS = (
    "key_points", "evidence", "risks", "opportunities", "actions", "monitoring_indicators",
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
    if not data.get("confidence"):
        data["confidence"] = fallback.confidence
    return GeneratedReportSection.model_validate(data)


def _fallback_report(
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
    limitation: str | None = None,
) -> GeneratedReport:
    profile = load_audience_profile(audience_id)
    limit = {"highlight_only": 2, "condensed": 3, "summary": 4}.get(profile.detail_level, 6)
    sections: list[GeneratedReportSection] = []
    for section_id in report_plan.sections:
        key_points = synthesis.key_points or synthesis.highlights
        kwargs: dict[str, list[str]] = {}
        if section_id in {"issue", "problem", "root_cause"}:
            kwargs["risks"] = _take(synthesis.risks, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id == "risk_and_opportunity":
            kwargs["risks"] = _take(synthesis.risks, limit)
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in {"impact", "market_status", "current_situation"}:
            kwargs["key_points"] = _take(synthesis.business_impacts or key_points, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in _ACTION_SECTIONS:
            kwargs["actions"] = _take(synthesis.recommended_actions, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
        elif section_id in {"opportunity", "trend", "near_term_outlook", "investment_signal"}:
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
        else:
            kwargs["key_points"] = _take(key_points, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        summary_values = next((values for values in kwargs.values() if values), [])
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
) -> GeneratedReport:
    """Use structured output when configured; otherwise create an evidence-safe report."""
    api_key = os.getenv("TRENDSPARC_REPORT_GENERATOR_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or synthesis.source_count == 0:
        return _fallback_report(synthesis, report_plan, audience_id)

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
                        "Keep every [doc_id=...] marker attached to its claim, never invent facts, and state uncertainty. "
                        "Copy names in canonical_entities exactly; never abbreviate, translate, or respell them. "
                        "Put recommendations in actions, risks in risks, opportunities in opportunities, and sources in evidence. "
                        "Return every required section_id exactly once. Write the report in the question's language."
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
        limitations = list(dict.fromkeys([*parsed["limitations"], *_diversity_limitations(synthesis)]))
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
        )
