"""Sector-agnostic aggregation of DocumentAnalysis into a TrendSynthesis.

This performs structural aggregation only. It does not invent insights; it
collects fields already produced by sector analyzers and tags them so later
report/layout stages can distinguish key facts from risk, opportunity, impact,
and recommended actions.
"""

from __future__ import annotations

from common.contracts import DocumentAnalysis, TrendSynthesis


def _append_text(highlights: list[str], label: str, value: str | None, doc_id: str) -> None:
    if value:
        highlights.append(f"{label}: {value} [doc_id={doc_id}]")


def _append_items(highlights: list[str], label: str, values: list[str], doc_id: str) -> None:
    for value in values:
        if value:
            highlights.append(f"{label}: {value} [doc_id={doc_id}]")


def _tag(value: str, doc_id: str) -> str:
    return f"{value} [doc_id={doc_id}]"


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
    recommended_actions: list[str] = []
    monitoring_indicators: list[str] = []
    evidence: list[str] = []
    confidence_labels: list[str] = []
    doc_source_map: dict[str, str] = {}
    for analysis in document_analyses:
        doc_source_map[analysis.doc_id] = analysis.source_id or analysis.doc_id.split(":", 1)[0]
        _append_items(highlights, "Key Point", analysis.key_points, analysis.doc_id)
        _append_text(highlights, "Business Impact", analysis.business_impact, analysis.doc_id)
        _append_text(highlights, "Risk", analysis.risk, analysis.doc_id)
        _append_text(highlights, "Opportunity", analysis.opportunity, analysis.doc_id)
        _append_items(highlights, "Action", analysis.recommended_actions, analysis.doc_id)
        _append_items(highlights, "Monitoring", analysis.monitoring_indicators, analysis.doc_id)
        key_points.extend(_tag(value, analysis.doc_id) for value in analysis.key_points if value)
        if analysis.business_impact:
            business_impacts.append(_tag(analysis.business_impact, analysis.doc_id))
        if analysis.risk:
            risks.append(_tag(analysis.risk, analysis.doc_id))
        if analysis.opportunity:
            opportunities.append(_tag(analysis.opportunity, analysis.doc_id))
        recommended_actions.extend(_tag(value, analysis.doc_id) for value in analysis.recommended_actions if value)
        monitoring_indicators.extend(_tag(value, analysis.doc_id) for value in analysis.monitoring_indicators if value)
        evidence.extend(_tag(value, analysis.doc_id) for value in analysis.evidence if value)
        if analysis.analysis_confidence:
            confidence_labels.append(_tag(analysis.analysis_confidence, analysis.doc_id))

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
        recommended_actions=recommended_actions,
        monitoring_indicators=monitoring_indicators,
        evidence=evidence,
        confidence_labels=confidence_labels,
        doc_source_map=doc_source_map,
    )
