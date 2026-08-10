"""Canonical metric identity and identity-based merging."""
import pytest

from common.contracts import MetricPoint
from common.metric_identity import (
    canonical_period,
    canonical_unit,
    conflicting_metric_groups,
    metric_identity,
    normalize_metric_points,
)


def _point(**kwargs) -> MetricPoint:
    base = dict(label="IPTV 가입자 수", period="2025년 상반기", value=21414521.0,
                unit="단말장치・단자", subject="IPTV", doc_id="d1", source_url="u1")
    base.update(kwargs)
    return MetricPoint(**base)


# ------------------------------------------------------------- E/F/G period
def test_percent_spellings_canonicalize():
    assert canonical_unit("%") == canonical_unit("％") == "%"
    assert canonical_unit("퍼센트") == "%"
    assert canonical_unit("퍼센트포인트") == "%p"


def test_half_year_spellings_canonicalize():
    for written in ("2025년 상반기", "2025 H1", "2025년 1H", "'25년 상반기"):
        assert canonical_period(written) == "2025년 상반기", written
    assert canonical_period("2025 H2") == "2025년 하반기"


def test_a_year_is_not_its_own_first_half():
    assert canonical_period("2025년") == "2025년"
    assert canonical_period("2025년") != canonical_period("2025년 상반기")


def test_unknown_period_becomes_none_and_never_borrows_another():
    assert canonical_period("시점 미상") is None
    assert canonical_period(None) is None
    assert canonical_period("") is None


# --------------------------------------------------------------- H/I units
def test_unit_none_stays_none():
    assert canonical_unit(None) is None
    assert canonical_unit("  ") is None
    assert _point(unit=None).unit is None


def test_scale_is_never_converted():
    assert canonical_unit("억원") != canonical_unit("원")
    assert canonical_unit("조원") != canonical_unit("억원")
    # Only the space differs - the same unit written two ways.
    assert canonical_unit("억 원") == canonical_unit("억원")


def test_the_sources_own_unit_is_never_renamed():
    assert canonical_unit("단말장치・단자") != canonical_unit("명")
    assert "명" not in (canonical_unit("단말장치・단자") or "")


# ------------------------------------------------------- A. exact duplicate
def test_the_same_reading_from_two_documents_becomes_one_point():
    points = [_point(doc_id="d1", source_url="u1"), _point(doc_id="d2", source_url="u2")]

    merged = normalize_metric_points(points)

    assert len(merged) == 1
    assert merged[0].value == 21414521.0


def test_merging_keeps_every_source(): # K. provenance
    points = [_point(doc_id="d1", source_url="u1"), _point(doc_id="d2", source_url="u2")]

    merged = normalize_metric_points(points)[0]

    assert merged.supporting_doc_ids == ["d1", "d2"]
    assert merged.supporting_source_urls == ["u1", "u2"]
    assert merged.doc_id == "d1"  # existing readers keep a single doc_id


def test_spelling_variants_merge_as_one_reading():
    points = [
        _point(period="2025년 상반기", unit="%", value=59.11, doc_id="d1"),
        _point(period="2025 H1", unit="％", value=59.11, doc_id="d2"),
    ]

    merged = normalize_metric_points(points)

    assert len(merged) == 1
    assert merged[0].supporting_doc_ids == ["d1", "d2"]


# ------------------------------------------------ B. conflict is preserved
def test_the_same_identity_with_different_values_is_never_collapsed():
    points = [_point(value=21414521.0, doc_id="d1"), _point(value=21310000.0, doc_id="d2")]

    merged = normalize_metric_points(points)

    assert len(merged) == 2
    assert {p.value for p in merged} == {21414521.0, 21310000.0}
    assert {p.doc_id for p in merged} == {"d1", "d2"}


def test_a_conflict_can_be_reported():
    points = [_point(value=21414521.0), _point(value=21310000.0)]

    groups = conflicting_metric_groups(points)

    assert len(groups) == 1
    assert len(groups[0]) == 2


# ------------------------------------------------------- C/D separate facts
def test_different_periods_stay_separate():
    points = [_point(period="2024년 하반기", value=1.0), _point(period="2025년 상반기", value=1.0)]

    assert len(normalize_metric_points(points)) == 2


def test_different_subjects_stay_separate():
    points = [_point(subject="IPTV", value=1.0), _point(subject="SO", value=1.0)]

    assert len(normalize_metric_points(points)) == 2


def test_different_measurements_never_merge():
    """"가입자 수" and "점유율" are not the same metric."""
    a = _point(label="IPTV 가입자 수", unit="단말장치・단자", value=21414521.0)
    b = _point(label="IPTV 점유율", unit="%", value=59.11)

    assert metric_identity(a) != metric_identity(b)
    assert len(normalize_metric_points([a, b])) == 2


def test_value_is_not_part_of_identity():
    """Otherwise a disagreement would be undetectable by construction."""
    a, b = _point(value=1.0), _point(value=2.0)

    assert metric_identity(a) == metric_identity(b)


def test_unknown_period_points_do_not_absorb_dated_ones():
    points = [_point(period="시점 미상", value=1.0), _point(period="2025년 상반기", value=1.0)]

    assert len(normalize_metric_points(points)) == 2


# --------------------------------- J. invariant: only verified metrics ship
def test_unverified_analyses_contribute_no_normalized_metric():
    """Ordering is what protects this today - pin it as an invariant.

    Normalization runs after validation, so a document the analyzer could
    not ground has no metric in the synthesis output. That is a property of
    where the call sits, and a future reordering would break it silently;
    this test fails instead.
    """
    from common.contracts import DocumentAnalysis
    from core.synthesis.synthesizer import synthesize

    unverified = DocumentAnalysis(
        doc_id="bad:1", source_id="bad", summary="s",
        metric_points=[MetricPoint(label="유령 지표", period="2025년 상반기",
                                   value=99.0, unit="%", subject="유령")],
        analysis_validation_status="insufficient_grounding",
        usable_for_synthesis=False,
        relevant_to_question=True,
    )
    verified = DocumentAnalysis(
        doc_id="good:1", source_id="good", summary="s",
        metric_points=[MetricPoint(label="IPTV 가입자 수", period="2025년 상반기",
                                   value=21414521.0, unit="단말장치・단자", subject="IPTV")],
        analysis_validation_status="verified",
        usable_for_synthesis=True,
        relevant_to_question=True,
    )

    synthesis = synthesize("req", "sk_broadband", [verified])
    labels = {point.label for point in synthesis.metric_series}

    assert "IPTV 가입자 수" in labels
    assert "유령 지표" not in labels
    # And the caller is what filters: an unusable analysis must not be handed
    # to synthesize() in the first place.
    assert unverified.usable_for_synthesis is False
