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
from common.contracts import (
    DocumentAnalysis,
    SynthesisClaim,
    SynthesisConclusion,
    SynthesisSource,
    TrendSynthesis,
)
from core.sector_router.affiliates import drop_other_affiliates_metrics
from common.metric_quality import display_metric_points


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
    factors: list[str] = []
    recommended_actions: list[str] = []
    monitoring_indicators: list[str] = []
    evidence: list[str] = []
    confidence_labels: list[str] = []
    doc_source_map: dict[str, str] = {}
    doc_url_map: dict[str, str] = {}
    grounded_claims: list[SynthesisClaim] = []
    sources: list[SynthesisSource] = []
    covered_information_needs: list[str] = []
    all_information_needs: list[str] = []
    analysis_validation_status_by_doc_id: dict[str, str] = {}
    for analysis in document_analyses:
        source_id = analysis.source_id or analysis.doc_id.split(":", 1)[0]
        doc_source_map[analysis.doc_id] = source_id
        if analysis.source_url:
            doc_url_map[analysis.doc_id] = analysis.source_url
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
            claim_ids_in_doc = {claim.claim_id for claim in analysis.grounded_claims}
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
                    # Namespaced like every other cross-document reference, so
                    # a parent still resolves once claims from several
                    # documents share one list. A link whose parent didn't
                    # survive the analyzer's verification is left unset here
                    # rather than pointing at an id that no longer exists.
                    parent_synthesis_claim_id=(
                        f"{analysis.doc_id}:{claim.parent_claim_id}"
                        if claim.parent_claim_id in claim_ids_in_doc
                        else None
                    ),
                    importance=claim.importance,
                    importance_basis=claim.importance_basis,
                    doc_id=analysis.doc_id,
                    source_id=source_id,
                    source_title=analysis.source_title,
                    source_url=claim.source_url or analysis.source_url,
                    reliability_tier=analysis.reliability_tier,
                )
                for claim in analysis.grounded_claims
            )
            analysis_key_points = _grounded_values(analysis, "key_point")
            # One claim per item, not "; ".join(...). A document stating three
            # distinct risks used to arrive downstream as a single risk - the
            # claims survived in grounded_claims, but every field the report
            # actually reads saw one entry, so a press release with a full
            # results table contributed the same as one with a single remark.
            analysis_business_impacts = _grounded_values(analysis, "business_impact")
            analysis_risks = _grounded_values(analysis, "risk")
            analysis_opportunities = _grounded_values(analysis, "opportunity")
            analysis_strengths = _grounded_values(analysis, "strength")
            analysis_weaknesses = _grounded_values(analysis, "weakness")
            analysis_factors = _grounded_values(analysis, "factor")
            analysis_actions = _grounded_values(analysis, "action")
            analysis_monitoring = _grounded_values(analysis, "monitoring")
            analysis_evidence = [claim.evidence_quote for claim in analysis.grounded_claims]
            metric_claim_by_quote = {
                claim.evidence_quote: claim.claim_id
                for claim in analysis.grounded_claims
                if claim.claim_type == "metric"
            }
            comparison_claim_ids = {
                claim.claim_id
                for claim in analysis.grounded_claims
                if claim.claim_type == "comparison"
            }
            parallel_claim_ids = {
                claim.claim_id
                for claim in analysis.grounded_claims
                if claim.claim_type in {"factor", "key_point"}
            }
            analysis_comparisons = [
                point
                for point in analysis.comparison_points
                if point.evidence_claim_id in comparison_claim_ids
                or (
                    point.derived_from_parallel_claim
                    and point.evidence_claim_id in parallel_claim_ids
                )
            ]
        else:
            # Backward-compatible path for sector analyzers that have not yet
            # adopted grounded claims.
            analysis_key_points = analysis.key_points
            # Legacy path: DocumentAnalysis carries one string per field, so
            # there is only ever one item to pass on.
            analysis_business_impacts = [analysis.business_impact] if analysis.business_impact else []
            analysis_risks = [analysis.risk] if analysis.risk else []
            analysis_opportunities = [analysis.opportunity] if analysis.opportunity else []
            analysis_strengths = [analysis.strength] if analysis.strength else []
            analysis_weaknesses = [analysis.weakness] if analysis.weakness else []
            analysis_factors = analysis.factors
            analysis_actions = analysis.recommended_actions
            analysis_monitoring = analysis.monitoring_indicators
            analysis_evidence = analysis.evidence
            metric_claim_by_quote = {}
            analysis_comparisons = analysis.comparison_points

        _append_items(highlights, "Key Point", analysis_key_points, analysis.doc_id)
        _append_items(highlights, "Business Impact", analysis_business_impacts, analysis.doc_id)
        _append_items(highlights, "Risk", analysis_risks, analysis.doc_id)
        _append_items(highlights, "Opportunity", analysis_opportunities, analysis.doc_id)
        _append_items(highlights, "Strength", analysis_strengths, analysis.doc_id)
        _append_items(highlights, "Weakness", analysis_weaknesses, analysis.doc_id)
        _append_items(highlights, "Factor", analysis_factors, analysis.doc_id)
        _append_items(highlights, "Action", analysis_actions, analysis.doc_id)
        _append_items(highlights, "Monitoring", analysis_monitoring, analysis.doc_id)
        key_points.extend(_tag(value, analysis.doc_id) for value in analysis_key_points if value)
        business_impacts.extend(_tag(v, analysis.doc_id) for v in analysis_business_impacts if v)
        risks.extend(_tag(v, analysis.doc_id) for v in analysis_risks if v)
        opportunities.extend(_tag(v, analysis.doc_id) for v in analysis_opportunities if v)
        strengths.extend(_tag(v, analysis.doc_id) for v in analysis_strengths if v)
        weaknesses.extend(_tag(v, analysis.doc_id) for v in analysis_weaknesses if v)
        factors.extend(_tag(v, analysis.doc_id) for v in analysis_factors if v)
        verified_claim_ids = {claim.claim_id for claim in analysis.grounded_claims}
        for metric_index, point in enumerate(analysis.metric_points, 1):
            evidence_claim_id = (
                point.evidence_claim_id
                if point.evidence_claim_id in verified_claim_ids
                else None
            )
            metric_series.append(
                point.model_copy(
                    update={
                        "metric_id": point.metric_id or f"{analysis.doc_id}:metric:{metric_index}",
                        "evidence_claim_id": evidence_claim_id,
                        "evidence_synthesis_claim_id": (
                            f"{analysis.doc_id}:{evidence_claim_id}"
                            if evidence_claim_id
                            else None
                        ),
                        "doc_id": analysis.doc_id,
                        "source_id": source_id,
                        "source_url": analysis.source_url,
                    }
                )
            )
        # The analyzer's own structured-output pass doesn't catch every
        # number - a revenue/profit figure stated inline as prose in this
        # document's own evidence sentences (e.g. "2025년 매출: 4조
        # 5,406억원 (전년 대비 3% 증가)") would otherwise stay untouched free
        # text, invisible to KPI ranking/chart shape classification. Regex-
        # extracted, never estimated - see content_quality_validator.
        extracted_index = len(analysis.metric_points)
        for evidence_text in analysis_evidence:
            for point in extract_metric_points_from_evidence([evidence_text]):
                extracted_index += 1
                evidence_claim_id = metric_claim_by_quote.get(evidence_text)
                metric_series.append(
                    point.model_copy(
                        update={
                            "metric_id": f"{analysis.doc_id}:metric:{extracted_index}",
                            "evidence_claim_id": evidence_claim_id,
                            "evidence_synthesis_claim_id": (
                                f"{analysis.doc_id}:{evidence_claim_id}"
                                if evidence_claim_id
                                else None
                            ),
                            "evidence_quote": evidence_text,
                            "doc_id": analysis.doc_id,
                            "source_id": source_id,
                            "source_url": analysis.source_url,
                        }
                    )
                )
        comparison_points.extend(
            point.model_copy(
                update={
                    "comparison_id": point.comparison_id or f"{analysis.doc_id}:comparison:{index}",
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
            for index, point in enumerate(analysis_comparisons, 1)
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
    metric_series = drop_other_affiliates_metrics(metric_series, sector_id)
    # Regex recovery reads verified evidence, but evidence can contain copied
    # navigation URLs or a whole prose fragment before the number. Keep those
    # claims for audit while excluding only their broken chart dimensions.
    metric_series = display_metric_points(metric_series)
    conclusions = [
        SynthesisConclusion(
            conclusion_id=f"rule:{claim.synthesis_claim_id}",
            conclusion=claim.claim,
            supporting_claim_ids=[claim.synthesis_claim_id],
            confidence=claim.confidence,
        )
        for claim in grounded_claims
        if claim.claim
    ]

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
        factors=factors,
        recommended_actions=recommended_actions,
        monitoring_indicators=monitoring_indicators,
        evidence=evidence,
        confidence_labels=confidence_labels,
        doc_source_map=doc_source_map,
        doc_url_map=doc_url_map,
        grounded_claims=grounded_claims,
        conclusions=conclusions,
        sources=sources,
        covered_information_needs=covered_information_needs,
        missing_information_needs=[
            need for need in all_information_needs if need not in covered_information_needs
        ],
        analysis_validation_status_by_doc_id=analysis_validation_status_by_doc_id,
    )
