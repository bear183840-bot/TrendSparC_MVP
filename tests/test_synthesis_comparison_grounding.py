"""A comparison survives synthesis when its claim was verified.

The gate used to require the referenced claim be *typed* `comparison`. A
comparison recovered deterministically from a table row is grounded in the
row itself, which is a `metric` claim, so the whole set was discarded
between the analyzer and the synthesis.

Live-verified 2026-08-10: the 방송미디어통신위원회 보도자료 reached synthesis
carrying 52 comparison points and zero claims typed `comparison`. All 52
were dropped, `TrendSynthesis.comparison_points` came back empty, and both
경쟁구도 and 이용자구성 fell back to prose - after the analyzer had already
been fixed to produce them. The bug looked like an analyzer failure from the
dashboard and like a dashboard failure from the analyzer.

What must not come back is the opposite: a comparison pointing at nothing
this document verified is ungrounded and still has to go.
"""
from __future__ import annotations

import pytest

from common.contracts import ComparisonPoint, DocumentAnalysis, GroundedClaim
from core.synthesis.synthesizer import synthesize

ROW = "| IPTV | 21,414,521 | 59.11% |"


def _claim(claim_id: str, claim_type: str) -> GroundedClaim:
    return GroundedClaim(
        claim_id=claim_id, claim="IPTV 가입자 수는 21,414,521이다.",
        claim_type=claim_type, evidence_quote=ROW, evidence_passage_id="p1",
        confidence="high",
    )


def _analysis(claims: list[GroundedClaim], points: list[ComparisonPoint]) -> DocumentAnalysis:
    return DocumentAnalysis(
        doc_id="pdf1", source_id="방송미디어통신위원회",
        grounded_claims=claims, comparison_points=points,
    )


def _points(*claim_ids: str) -> list[ComparisonPoint]:
    return [
        ComparisonPoint(entity=f"사업자{index}", criterion="점유율 '25년 하반기",
                        value=f"{index}%", evidence_claim_id=claim_id)
        for index, claim_id in enumerate(claim_ids, 1)
    ]


# --- what has to survive -------------------------------------------------


def test_a_comparison_grounded_in_a_metric_claim_survives():
    """A table row is one claim; every comparison read off it points there."""
    analysis = _analysis(
        [_claim("pdf1:det-metric-5", "metric")],
        _points("pdf1:det-metric-5", "pdf1:det-metric-5"),
    )

    synthesis = synthesize("req", "sk_broadband", [analysis])

    assert len(synthesis.comparison_points) == 2


@pytest.mark.parametrize("claim_type", ["metric", "comparison", "key_point", "factor"])
def test_the_claim_type_is_not_what_decides(claim_type):
    analysis = _analysis([_claim("c1", claim_type)], _points("c1"))

    assert len(synthesize("req", "sk_broadband", [analysis]).comparison_points) == 1


@pytest.mark.parametrize(
    "sector_id",
    ["sk_hynix", "sk_broadband", "sk_planet", "sk_telecom", "sk_innovation", "general"],
)
def test_the_rule_is_the_same_in_every_sector(sector_id):
    analysis = _analysis([_claim("c1", "metric")], _points("c1"))

    assert len(synthesize("req", sector_id, [analysis]).comparison_points) == 1


# --- and what must still be dropped -------------------------------------


def test_a_comparison_pointing_at_no_verified_claim_is_dropped():
    analysis = _analysis([_claim("c1", "metric")], _points("c-does-not-exist"))

    assert synthesize("req", "sk_broadband", [analysis]).comparison_points == []


def test_a_comparison_with_no_claim_at_all_is_dropped():
    analysis = _analysis(
        [_claim("c1", "metric")],
        [ComparisonPoint(entity="KT", criterion="점유율", value="25.24%")],
    )

    assert synthesize("req", "sk_broadband", [analysis]).comparison_points == []


def test_only_the_ungrounded_ones_go():
    analysis = _analysis([_claim("c1", "metric")], _points("c1", "missing", "c1"))

    kept = synthesize("req", "sk_broadband", [analysis]).comparison_points

    assert [point.entity for point in kept] == ["사업자1", "사업자3"]


# --- provenance still attaches ------------------------------------------


def test_a_surviving_comparison_carries_its_document():
    analysis = _analysis([_claim("c1", "metric")], _points("c1"))

    point = synthesize("req", "sk_broadband", [analysis]).comparison_points[0]

    assert point.doc_id == "pdf1"
    assert point.evidence_synthesis_claim_id == "pdf1:c1"
    assert point.comparison_id
