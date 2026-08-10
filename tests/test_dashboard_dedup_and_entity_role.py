"""Two live-verified bugs from the 2026-08-11 dashboard review, both general
rules rather than IPTV-specific hacks.

1. Executive Summary's headline KPI and Key Metrics' first card showed the
   identical 21,535,256 under two labels ("IPTV 가입자 수" vs "IPTV 총계
   가입자수" - a sentence restatement vs. a table's own total-row wording).
   `kpi_evidence_key` dedup was pure label-string comparison and missed it.

2. Competitive Landscape mixed heterogeneous entity roles: real operators
   (KT/SKB/LGU+), the table's own subtotal/total rows ("IPTV 총계", "전체
   합계"), and media-type composition slices (IPTV/SO/위성, whose 점유율
   sums to ~100% of one whole) all appeared as if they were peer
   competitors.
"""
from __future__ import annotations

from common.contracts import ComparisonPoint, MetricPoint
from common.content_quality_validator import (
    exclude_non_competitor_comparisons,
    is_composition_group,
    is_total_row_entity,
)
from common.purpose_slots import kpi_evidence_key


def _point(label: str, value: float, **kwargs) -> MetricPoint:
    base = dict(label=label, period="2025년", value=value, unit="명")
    base.update(kwargs)
    return MetricPoint(**base)


def _cmp(entity: str, criterion: str, value: str) -> ComparisonPoint:
    return ComparisonPoint(entity=entity, criterion=criterion, value=value)


# --- KPI dedup: label variants of the same reading -----------------------


def test_a_total_row_wording_matches_its_sentence_restatement():
    """"IPTV 총계 가입자수" (table total-row phrasing) and "IPTV 가입자 수"
    (sentence phrasing) are the same reading, live-verified: both carried
    21,535,256."""
    sentence = _point("IPTV 가입자 수", 21_535_256)
    table_total = _point("IPTV 총계 가입자수", 21_535_256)

    assert kpi_evidence_key(sentence) == kpi_evidence_key(table_total)


def test_a_different_metric_is_still_a_different_identity():
    a = _point("가입자 수", 21_535_256)
    b = _point("영업이익", 3_741)

    assert kpi_evidence_key(a) != kpi_evidence_key(b)


def test_the_same_label_at_a_different_period_is_still_one_identity():
    """Existing contract, must survive this change: rank_kpi_candidates
    already folds every period of one label into one latest-plus-delta
    card, so the cross-section dedup key stays period-agnostic."""
    early = _point("가입자 수", 20_000_000, period="2024년")
    late = _point("가입자 수", 21_535_256, period="2025년")

    assert kpi_evidence_key(early) == kpi_evidence_key(late)


def test_a_subtotal_wording_does_not_collide_with_an_unrelated_metric():
    total_row = _point("IPTV 총계 가입자수", 21_535_256)
    unrelated = _point("영업이익 총계", 3_741)

    assert kpi_evidence_key(total_row) != kpi_evidence_key(unrelated)


# --- Competitive Landscape entity-role validation -------------------------


def test_total_row_entities_are_recognized_across_the_closed_word_set():
    for entity in ("IPTV 총계", "SO 소계", "전체 합계", "KT스카이라이프 전체 합계"):
        assert is_total_row_entity(entity), entity
    for entity in ("KT", "SK브로드밴드", "LG유플러스", "IPTV"):
        assert not is_total_row_entity(entity), entity


def test_a_percentage_group_summing_to_100_is_a_composition():
    slices = [
        _cmp("IPTV", "점유율 '25년 하반기", "59.57%"),
        _cmp("SO", "점유율 '25년 하반기", "33.01%"),
        _cmp("위성", "점유율 '25년 하반기", "7.41%"),
    ]
    assert is_composition_group(slices)


def test_a_competitor_comparison_under_100_is_not_a_composition():
    """KT/SKB/LGU+ shares also sum under 100 but are genuinely different
    entities being compared, not slices of one whole - the distinguishing
    fact is what the criterion asks, but structurally both look the same
    to a pure sum test, so this pins that a real comparison is not
    incorrectly caught."""
    rows = [
        _cmp("KT", "점유율 '25년 하반기", "25.24%"),
        _cmp("SK브로드밴드", "점유율 '25년 하반기", "18.51%"),
    ]
    # Two of three real operators - deliberately not summing near 100,
    # which is the actual live shape (a partial table extract).
    assert not is_composition_group(rows)


def test_total_rows_are_dropped_from_competitive_landscape():
    points = [
        _cmp("KT", "가입자수 '25년 하반기", "9,123,463"),
        _cmp("SK브로드밴드", "가입자수 '25년 하반기", "6,691,354"),
        _cmp("IPTV 총계", "가입자수 '25년 하반기", "21,535,256"),
    ]
    kept = exclude_non_competitor_comparisons(points, market_keywords=None)

    assert {p.entity for p in kept} == {"KT", "SK브로드밴드"}


def test_a_composition_shaped_criterion_is_dropped_entirely():
    points = [
        _cmp("IPTV", "점유율 '25년 하반기", "59.57%"),
        _cmp("SO", "점유율 '25년 하반기", "33.01%"),
        _cmp("위성", "점유율 '25년 하반기", "7.41%"),
        _cmp("KT", "가입자수 '25년 하반기", "9,123,463"),
        _cmp("SK브로드밴드", "가입자수 '25년 하반기", "6,691,354"),
    ]
    kept = exclude_non_competitor_comparisons(points, market_keywords=None)

    assert {p.entity for p in kept} == {"KT", "SK브로드밴드"}


def test_the_same_composition_entity_set_is_dropped_even_in_raw_counts():
    """One table often states a composition twice - a % column and a raw
    count column for the same three entities. Only the % column sums to
    ~100 on its own; the count column is caught by sharing the identical
    entity set with an already-identified composition criterion."""
    points = [
        _cmp("IPTV", "점유율 '25년 하반기", "59.57%"),
        _cmp("SO", "점유율 '25년 하반기", "33.01%"),
        _cmp("위성", "점유율 '25년 하반기", "7.41%"),
        _cmp("IPTV", "가입자 수 '25년 하반기", "21,535,256"),
        _cmp("SO", "가입자 수 '25년 하반기", "11,935,236"),
        _cmp("위성", "가입자 수 '25년 하반기", "2,679,578"),
    ]
    kept = exclude_non_competitor_comparisons(points, market_keywords=None)

    assert kept == []


def test_real_operator_comparisons_survive_untouched():
    points = [
        _cmp("KT", "가입자수 '25년 하반기", "9,123,463"),
        _cmp("SK브로드밴드", "가입자수 '25년 하반기", "6,691,354"),
        _cmp("LG유플러스", "가입자수 '25년 하반기", "5,720,439"),
    ]
    kept = exclude_non_competitor_comparisons(points, market_keywords=None)

    assert {p.entity for p in kept} == {"KT", "SK브로드밴드", "LG유플러스"}


def test_market_keyword_exclusion_still_composes_with_the_new_filters():
    points = [
        _cmp("IPTV 시장", "가입자수 '25년 하반기", "21,535,256"),
        _cmp("KT", "가입자수 '25년 하반기", "9,123,463"),
    ]
    kept = exclude_non_competitor_comparisons(points, market_keywords=["IPTV 시장"])

    assert {p.entity for p in kept} == {"KT"}
