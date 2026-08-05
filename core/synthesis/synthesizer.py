"""Sector-agnostic aggregation of DocumentAnalysis into a TrendSynthesis.

This performs structural aggregation only. It does not invent insights; it
collects fields already produced by sector analyzers and tags them so later
report/layout stages can distinguish key facts from risk, opportunity, impact,
and recommended actions.
"""

from __future__ import annotations

from common.content_quality_validator import (
    dedupe_structured_across_sections,
    extract_metric_points_from_evidence,
)
from common.contracts import DocumentAnalysis, SynthesisClaim, SynthesisSource, TrendSynthesis


def _append_text(highlights: list[str], label: str, value: str | None, doc_id: str) -> None:
    if value:
        highlights.append(f"{label}: {value} [doc_id={doc_id}]")


def _append_items(highlights: list[str], label: str, values: list[str], doc_id: str) -> None:
    for value in values:
        if value:
            highlights.append(f"{label}: {value} [doc_id={doc_id}]")


def _tag(value: str, doc_id: str) -> str:
    return f"{value} [doc_id={doc_id}]"


def _grounded_values(analysis: DocumentAnalysis, claim_type: str) -> list[str]:
    return [
        claim.claim
        for claim in analysis.grounded_claims
        if claim.claim_type == claim_type
    ]


def _grounded_joined(analysis: DocumentAnalysis, claim_type: str) -> str | None:
    values = _grounded_values(analysis, claim_type)
    return "; ".join(values) if values else None


def synthesize(
    request_id: str,
    sector_id: str,
    document_analyses: list[DocumentAnalysis],
) -> TrendSynthesis:
    source_ids = list(
        dict.fromkeys(
            analysis.source_id or analysis.doc_id.split(":", 1)[0]
            for analysis in document_analyses
        )
    )
    highlights: list[str] = []
    key_points: list[str] = []
    business_impacts: list[str] = []
    risks: list[str] = []
    opportunities: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    metric_series: list = []
    comparison_points: list = []
    recommended_actions: list[str] = []
    monitoring_indicators: list[str] = []
    evidence: list[str] = []
    confidence_labels: list[str] = []
    doc_source_map: dict[str, str] = {}
    grounded_claims: list[SynthesisClaim] = []
    sources: list[SynthesisSource] = []
    covered_information_needs: list[str] = []
    all_information_needs: list[str] = []
    analysis_validation_status_by_doc_id: dict[str, str] = {}
    for analysis in document_analyses:
        source_id = analysis.source_id or analysis.doc_id.split(":", 1)[0]
        doc_source_map[analysis.doc_id] = source_id
        sources.append(
            SynthesisSource(
                doc_id=analysis.doc_id,
                source_id=source_id,
                source_title=analysis.source_title,
                source_url=analysis.source_url,
                reliability_tier=analysis.reliability_tier,
            )
        )
        if analysis.analysis_validation_status:
            analysis_validation_status_by_doc_id[analysis.doc_id] = analysis.analysis_validation_status
        for need in [*analysis.covered_information_needs, *analysis.missing_information_needs]:
            if need not in all_information_needs:
                all_information_needs.append(need)
        for need in analysis.covered_information_needs:
            if need not in covered_information_needs:
                covered_information_needs.append(need)
        if analysis.grounded_claims:
            grounded_claims.extend(
                SynthesisClaim(
                    synthesis_claim_id=f"{analysis.doc_id}:{claim.claim_id}",
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    claim=claim.claim,
                    evidence_quote=claim.evidence_quote,
                    evidence_location=claim.evidence_location,
                    as_of_date=claim.as_of_date,
                    confidence=claim.confidence,
                    doc_id=analysis.doc_id,
                    source_id=source_id,
                    source_title=analysis.source_title,
                    source_url=claim.source_url or analysis.source_url,
                    reliability_tier=analysis.reliability_tier,
                )
                for claim in analysis.grounded_claims
            )
            analysis_key_points = _grounded_values(analysis, "key_point")
            analysis_business_impact = _grounded_joined(analysis, "business_impact")
            analysis_risk = _grounded_joined(analysis, "risk")
            analysis_opportunity = _grounded_joined(analysis, "opportunity")
            analysis_strength = _grounded_joined(analysis, "strength")
            analysis_weakness = _grounded_joined(analysis, "weakness")
            analysis_actions = _grounded_values(analysis, "action")
            analysis_monitoring = _grounded_values(analysis, "monitoring")
            analysis_evidence = [claim.evidence_quote for claim in analysis.grounded_claims]
            comparison_claim_ids = {
                claim.claim_id
                for claim in analysis.grounded_claims
                if claim.claim_type == "comparison"
            }
            analysis_comparisons = [
                point
                for point in analysis.comparison_points
                if point.evidence_claim_id in comparison_claim_ids
            ]
        else:
            # Backward-compatible path for sector analyzers that have not yet
            # adopted grounded claims.
            analysis_key_points = analysis.key_points
            analysis_business_impact = analysis.business_impact
            analysis_risk = analysis.risk
            analysis_opportunity = analysis.opportunity
            analysis_strength = analysis.strength
            analysis_weakness = analysis.weakness
            analysis_actions = analysis.recommended_actions
            analysis_monitoring = analysis.monitoring_indicators
            analysis_evidence = analysis.evidence
            analysis_comparisons = analysis.comparison_points

        _append_items(highlights, "Key Point", analysis_key_points, analysis.doc_id)
        _append_text(highlights, "Business Impact", analysis_business_impact, analysis.doc_id)
        _append_text(highlights, "Risk", analysis_risk, analysis.doc_id)
        _append_text(highlights, "Opportunity", analysis_opportunity, analysis.doc_id)
        _append_text(highlights, "Strength", analysis_strength, analysis.doc_id)
        _append_text(highlights, "Weakness", analysis_weakness, analysis.doc_id)
        _append_items(highlights, "Action", analysis_actions, analysis.doc_id)
        _append_items(highlights, "Monitoring", analysis_monitoring, analysis.doc_id)
        key_points.extend(_tag(value, analysis.doc_id) for value in analysis_key_points if value)
        if analysis_business_impact:
            business_impacts.append(_tag(analysis_business_impact, analysis.doc_id))
        if analysis_risk:
            risks.append(_tag(analysis_risk, analysis.doc_id))
        if analysis_opportunity:
            opportunities.append(_tag(analysis_opportunity, analysis.doc_id))
        if analysis_strength:
            strengths.append(_tag(analysis_strength, analysis.doc_id))
        if analysis_weakness:
            weaknesses.append(_tag(analysis_weakness, analysis.doc_id))
        metric_series.extend(
            point.model_copy(
                update={
                    "doc_id": analysis.doc_id,
                    "source_id": source_id,
                    "source_url": analysis.source_url,
                }
            )
            for point in analysis.metric_points
        )
        # The analyzer's own structured-output pass doesn't catch every
        # number - a revenue/profit figure stated inline as prose in this
        # document's own evidence sentences (e.g. "2025년 매출: 4조
        # 5,406억원 (전년 대비 3% 증가)") would otherwise stay untouched free
        # text, invisible to KPI ranking/chart shape classification. Regex-
        # extracted, never estimated - see content_quality_validator.
        metric_series.extend(
            point.model_copy(
                update={
                    "doc_id": analysis.doc_id,
                    "source_id": source_id,
                    "source_url": analysis.source_url,
                }
            )
            for point in extract_metric_points_from_evidence(analysis_evidence)
        )
        comparison_points.extend(
            point.model_copy(
                update={
                    "evidence_synthesis_claim_id": (
                        f"{analysis.doc_id}:{point.evidence_claim_id}"
                        if point.evidence_claim_id
                        else None
                    ),
                    "doc_id": analysis.doc_id,
                    "source_id": source_id,
                    "source_url": analysis.source_url,
                }
            )
            for point in analysis_comparisons
        )
        recommended_actions.extend(_tag(value, analysis.doc_id) for value in analysis_actions if value)
        monitoring_indicators.extend(_tag(value, analysis.doc_id) for value in analysis_monitoring if value)
        evidence.extend(_tag(value, analysis.doc_id) for value in analysis_evidence if value)
        if analysis.analysis_confidence:
            confidence_labels.append(_tag(analysis.analysis_confidence, analysis.doc_id))

    # The regex extraction above can rediscover a fact the analyzer's own
    # structured-output pass already captured for the same document -
    # collapse exact duplicates (same label/period/value/unit/doc_id) rather
    # than showing the identical number twice in one KPI row/chart.
    metric_series = dedupe_structured_across_sections([metric_series])[0]

    return TrendSynthesis(
        request_id=request_id,
        sector_id=sector_id,
        highlights=highlights,
        synthesis_text=None,
        source_count=len(document_analyses),
        unique_source_count=len(source_ids),
        source_ids=source_ids,
        key_points=key_points,
        business_impacts=business_impacts,
        risks=risks,
        opportunities=opportunities,
        strengths=strengths,
        weaknesses=weaknesses,
        metric_series=metric_series,
        comparison_points=comparison_points,
        recommended_actions=recommended_actions,
        monitoring_indicators=monitoring_indicators,
        evidence=evidence,
        confidence_labels=confidence_labels,
        doc_source_map=doc_source_map,
        grounded_claims=grounded_claims,
        sources=sources,
        covered_information_needs=covered_information_needs,
        missing_information_needs=[
            need for need in all_information_needs if need not in covered_information_needs
        ],
        analysis_validation_status_by_doc_id=analysis_validation_status_by_doc_id,
    )
