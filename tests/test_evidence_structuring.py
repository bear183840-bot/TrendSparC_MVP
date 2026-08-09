"""Evidence structure should survive wording variation without invented data."""

from common.block_shapes import (
    decision_matrix,
    has_benchmark_grid,
    has_decision_matrix,
    has_grouped_bars,
    has_landscape,
    has_level_matrix,
    has_radar,
    has_share_split,
    has_timeseries,
    item_bar_groups,
    has_comparison,
    time_bar_groups,
    timeline_entries,
)
from common.content_quality_validator import (
    canonical_time_id,
    classify_metric_shape,
    group_metric_points_by_label,
    select_chartable_series,
    semantic_entity_key,
)
from common.contracts import ComparisonPoint, MetricPoint, SynthesisClaim
from common.block_shapes import has_cause_tree


def metric(label, period, value, unit="%", subject=None, **kwargs):
    return MetricPoint(
        label=label, period=period, value=value, unit=unit,
        subject=subject, **kwargs,
    )


def comparison(entity, criterion, value, level=None):
    return ComparisonPoint(entity=entity, criterion=criterion, value=value, level=level)


def claim(claim_id, text, parent=None):
    return SynthesisClaim(
        synthesis_claim_id=claim_id, claim_id=claim_id, claim_type="key_point",
        claim=text, evidence_quote=text, confidence="high",
        parent_synthesis_claim_id=parent, doc_id="d1", source_id="s1",
    )


def test_semantic_time_series_groups_bilingual_market_size_labels():
    points = [
        metric("2024 HBM market size", "2024", 18, "USD billion"),
        metric("global HBM market revenue", "2025", 28000, "USD million", value_type="estimate", is_forecast=True),
        metric("HBM market expected size", "2026", 41, "USD billion", value_type="forecast", is_forecast=True),
    ]
    grouped = group_metric_points_by_label(points)
    assert len(grouped) == 1
    normalized = next(iter(grouped.values()))
    assert [point.value for point in normalized] == [18000, 28000, 41000]
    assert {point.unit for point in normalized} == {"USD million"}
    assert has_timeseries(points)


def test_sparse_series_keeps_only_real_periods():
    points = [metric("시장 규모", year, value, "억원", is_forecast=year == "2027")
              for year, value in (("2022", 10), ("2024", 18), ("2027", 35))]
    selected = select_chartable_series(points)
    assert [point.period for point in selected] == ["2022년", "2024년", "2027년"]
    assert len(selected) == 3


def test_time_and_safe_entity_aliases_are_canonicalized_without_fuzzy_matching():
    assert canonical_time_id("FY2026") == "2026년"
    assert canonical_time_id("2026 fiscal year") == "2026년"
    assert canonical_time_id("2026년 회계연도") == "2026년"
    assert semantic_entity_key("Samsung Electronics, Inc.") == semantic_entity_key("Samsung Electronics")
    assert semantic_entity_key("Samsung Electronics") != semantic_entity_key("Samsung Display")


def test_two_time_points_and_current_target_are_bar_shapes():
    timed = [metric("점유율", "2024", 30), metric("점유율", "2025", 40)]
    states = [metric("수율", "현재", 82), metric("수율", "목표", 90, value_type="target", is_forecast=True)]
    assert classify_metric_shape(timed) == "bar"
    assert classify_metric_shape(states) == "bar"
    assert time_bar_groups(states)


def test_entity_comparison_can_be_item_bar_and_explicit_share_split():
    points = [
        metric("HBM 점유율", "2025", 35, subject="Samsung", share_of="Global HBM market"),
        metric("HBM 점유율", "2025", 48, subject="SK hynix", share_of="Global HBM market"),
        metric("HBM 점유율", "2025", 17, subject="Micron", share_of="Global HBM market"),
    ]
    assert item_bar_groups(points)
    assert has_share_split(points)


def test_landscape_accepts_trend_plus_share_or_separate_headline_kpi():
    trend = [metric("시장 규모", str(year), value, "억원")
             for year, value in ((2023, 10), (2024, 15), (2025, 22))]
    shares = [
        metric("시장 점유율", "2025", 50, subject="A", share_of="전체 시장"),
        metric("시장 점유율", "2025", 30, subject="B", share_of="전체 시장"),
        metric("시장 점유율", "2025", 20, subject="C", share_of="전체 시장"),
    ]
    headline = [metric("CAGR", "2025", 22)]
    assert has_landscape([*trend, *shares])
    assert has_landscape([*trend, *headline])
    assert not has_landscape(trend)


def test_mixed_unit_company_facts_are_benchmark_not_grouped_bar():
    points = [
        metric("점유율", "2025", 35, "%", "Samsung"),
        metric("CAPEX", "2025", 20, "USD billion", "Samsung"),
        metric("점유율", "2025", 48, "%", "SK hynix"),
        metric("CAPEX", "2025", 15, "USD billion", "SK hynix"),
    ]
    assert not has_grouped_bars(points)
    assert has_benchmark_grid([], points)


def test_non_company_multi_criterion_comparison_is_benchmarkable():
    points = [
        comparison(entity, criterion, value)
        for entity, values in {
            "HBM4": ("높음", "성숙", "강함", "높음"),
            "CXL": ("중간", "초기", "중간", "중간"),
            "Advanced Packaging": ("높음", "성숙", "강함", "높음"),
        }.items()
        for criterion, value in zip(
            ("성장성", "기술 성숙도", "경쟁 강도", "투자 요구"), values
        )
    ]
    assert has_benchmark_grid(points, [])


def test_customer_segments_are_eligible_for_segment_table():
    points = [
        comparison(entity, criterion, value)
        for entity, values in {
            "신규 가입자": ("높음", "스포츠"),
            "기존 가입자": ("중간", "드라마"),
        }.items()
        for criterion, value in zip(("미디어 이용", "콘텐츠 선호"), values)
    ]
    assert has_comparison(points, demographic=True)


def test_decision_matrix_requires_two_grounded_axes_for_two_candidates():
    complete = [
        comparison("후보 A", "시장 매력도", "80"),
        comparison("후보 A", "당사 경쟁력", "65"),
        comparison("후보 B", "시장 매력도", "55"),
        comparison("후보 B", "당사 경쟁력", "90"),
    ]
    one_axis = [point for point in complete if point.criterion == "시장 매력도"]
    assert has_decision_matrix(complete)
    assert decision_matrix(complete)[1:3] == ("시장 매력도", "당사 경쟁력")
    assert not has_decision_matrix(one_axis)


def test_cause_tree_needs_an_explicit_verified_parent_edge():
    explicit = [claim("cause", "AI server shipments increased"),
                claim("effect", "HBM demand increased", parent="cause")]
    correlation = [claim("a", "AI server shipments increased"),
                   claim("b", "HBM prices also increased")]
    assert has_cause_tree(explicit)
    assert not has_cause_tree(correlation)


def test_product_roadmap_is_a_timeline_without_inventing_intermediate_dates():
    evidence = ["2025년 HBM3E 출시", "2026년 HBM4 출시", "2027년 HBM4E 출시"]
    entries = timeline_entries(evidence, [])
    assert [period for period, _ in entries] == ["2025년", "2026년", "2027년"]


def test_numeric_values_do_not_create_levels_without_a_threshold_contract():
    points = [comparison("Company A", "시장 점유율", "40%"),
              comparison("Company B", "시장 점유율", "20%")]
    assert not has_level_matrix(points)
    assert not has_radar(points)


def test_semantic_grouping_reuses_endpoint_without_creating_extra_points():
    points = [
        metric("HBM 시장 규모", "2024", 18, "USD billion"),
        metric("HBM market revenue", "2025", 28, "USD billion"),
        metric("HBM market size forecast", "2026", 41, "USD billion", is_forecast=True),
    ]
    grouped = group_metric_points_by_label(points)
    assert len(grouped) == 1
    assert len(next(iter(grouped.values()))) == 3
