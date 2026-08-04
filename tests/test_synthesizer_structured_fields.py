"""TrendSynthesis aggregation of the new SWOT/metric/comparison fields.

Mirrors the existing risk/opportunity aggregation pattern in
core/synthesis/synthesizer.py — mechanical, no AI judgement. Parametrized
across several sector ids to prove the aggregation logic itself is
sector-agnostic (synthesize() never branches on sector_id).
"""

import pytest

from common.contracts import ComparisonPoint, DocumentAnalysis, MetricPoint
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

    assert len(synthesis.comparison_points) == 2
    assert {point.entity for point in synthesis.comparison_points} == {"SK브로드밴드", "KT"}


def test_synthesis_leaves_structured_fields_empty_when_no_document_provides_them():
    synthesis = synthesize("req_2", "general", [DocumentAnalysis(doc_id="doc:1", summary="요약")])

    assert synthesis.strengths == []
    assert synthesis.weaknesses == []
    assert synthesis.metric_series == []
    assert synthesis.comparison_points == []
