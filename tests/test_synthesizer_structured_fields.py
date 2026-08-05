"""TrendSynthesis aggregation of the new SWOT/metric/comparison fields.

Mirrors the existing risk/opportunity aggregation pattern in
core/synthesis/synthesizer.py — mechanical, no AI judgement. Parametrized
across several sector ids to prove the aggregation logic itself is
sector-agnostic (synthesize() never branches on sector_id).
"""

import pytest

from common.contracts import ComparisonPoint, DocumentAnalysis, GroundedClaim, MetricPoint
from core.synthesis.synthesizer import synthesize


def _analyses() -> list[DocumentAnalysis]:
    return [
        DocumentAnalysis(
            doc_id="doc:1",
            source_id="Source A",
            strength="IPTV 인프라 및 품질 우위",
            weakness="OTT 대비 콘텐츠 다양성 부족",
            metric_points=[MetricPoint(label="IPTV 가입자", period="2019", value=519.0, unit="만 명")],
            comparison_points=[ComparisonPoint(entity="SK브로드밴드", criterion="요금", value="9,900원", level="medium")],
        ),
        DocumentAnalysis(
            doc_id="doc:2",
            source_id="Source B",
            metric_points=[MetricPoint(label="IPTV 가입자", period="2023", value=946.0, unit="만 명")],
            comparison_points=[ComparisonPoint(entity="KT", criterion="요금", value="8,900원", level="low")],
        ),
    ]


@pytest.mark.parametrize(
    "sector_id", ["sk_hynix", "sk_broadband", "sk_planet", "sk_telecom", "sk_innovation", "general"]
)
def test_synthesis_aggregates_structured_fields_regardless_of_sector(sector_id):
    synthesis = synthesize("req_1", sector_id, _analyses())

    assert len(synthesis.strengths) == 1
    assert "IPTV 인프라" in synthesis.strengths[0]
    assert "[doc_id=doc:1]" in synthesis.strengths[0]
    assert len(synthesis.weaknesses) == 1
    assert "[doc_id=doc:1]" in synthesis.weaknesses[0]

    assert len(synthesis.metric_series) == 2
    assert {point.period for point in synthesis.metric_series} == {"2019", "2023"}
    assert {point.doc_id for point in synthesis.metric_series} == {"doc:1", "doc:2"}
    assert {point.source_id for point in synthesis.metric_series} == {"Source A", "Source B"}

    assert len(synthesis.comparison_points) == 2
    assert {point.entity for point in synthesis.comparison_points} == {"SK브로드밴드", "KT"}


def test_synthesis_leaves_structured_fields_empty_when_no_document_provides_them():
    synthesis = synthesize("req_2", "general", [DocumentAnalysis(doc_id="doc:1", summary="요약")])

    assert synthesis.strengths == []
    assert synthesis.weaknesses == []
    assert synthesis.metric_series == []
    assert synthesis.comparison_points == []


def test_synthesis_prefers_grounded_claims_over_conflicting_legacy_fields():
    analysis = DocumentAnalysis(
        doc_id="doc:grounded",
        source_id="검증 출처",
        source_title="검증 기사",
        source_url="https://example.com/grounded",
        reliability_tier="analyst_media",
        key_points=["검증되지 않은 기존 핵심 포인트"],
        risk="검증되지 않은 기존 위험",
        recommended_actions=["검증되지 않은 기존 액션"],
        grounded_claims=[
            GroundedClaim(
                claim_id="c1",
                claim_type="key_point",
                claim="검증된 핵심 포인트",
                evidence_quote="원문 핵심 근거",
                confidence="high",
            ),
            GroundedClaim(
                claim_id="c2",
                claim_type="risk",
                claim="검증된 위험",
                evidence_quote="원문 위험 근거",
                confidence="medium",
            ),
            GroundedClaim(
                claim_id="c3",
                claim_type="action",
                claim="검증된 액션",
                evidence_quote="원문 액션 근거",
                confidence="medium",
            ),
            GroundedClaim(
                claim_id="c4",
                claim_type="comparison",
                claim="A가 B보다 저렴하다",
                evidence_quote="A 요금은 B보다 낮다",
                confidence="high",
            ),
        ],
        comparison_points=[
            ComparisonPoint(
                entity="A",
                criterion="요금",
                value="더 낮음",
                evidence_claim_id="c4",
            ),
            ComparisonPoint(
                entity="X",
                criterion="요금",
                value="근거 없음",
                evidence_claim_id="missing",
            ),
        ],
        covered_information_needs=["시장 현황"],
        missing_information_needs=["향후 전망"],
        analysis_validation_status="verified",
    )

    synthesis = synthesize("req_grounded", "sk_broadband", [analysis])

    assert synthesis.key_points == ["검증된 핵심 포인트 [doc_id=doc:grounded]"]
    assert synthesis.risks == ["검증된 위험 [doc_id=doc:grounded]"]
    assert synthesis.recommended_actions == ["검증된 액션 [doc_id=doc:grounded]"]
    assert [point.entity for point in synthesis.comparison_points] == ["A"]
    assert all("검증되지 않은" not in value for value in synthesis.highlights)
    assert len(synthesis.grounded_claims) == 4
    assert synthesis.grounded_claims[0].synthesis_claim_id == "doc:grounded:c1"
    assert synthesis.grounded_claims[0].source_url == "https://example.com/grounded"
    assert synthesis.grounded_claims[0].reliability_tier == "analyst_media"
    assert synthesis.sources[0].source_title == "검증 기사"
    assert synthesis.covered_information_needs == ["시장 현황"]
    assert synthesis.missing_information_needs == ["향후 전망"]
    assert synthesis.analysis_validation_status_by_doc_id == {"doc:grounded": "verified"}
    assert synthesis.comparison_points[0].evidence_synthesis_claim_id == "doc:grounded:c4"
    assert synthesis.comparison_points[0].source_id == "검증 출처"
