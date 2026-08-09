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
    semantic_metric_key,
    relative_metric_context,
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
        metric("2024 global HBM market size", "2024", 18, "USD billion"),
        metric("global HBM market revenue", "2025", 28000, "USD million", value_type="estimate", is_forecast=True),
        metric("global HBM market expected size", "2026", 41, "USD billion", value_type="forecast", is_forecast=True),
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
    assert semantic_entity_key("삼성전자") == semantic_entity_key("Samsung Electronics")
    assert semantic_entity_key("SK하이닉스") == semantic_entity_key("SK hynix")
    assert semantic_entity_key("마이크론") == semantic_entity_key("Micron Technology")
    assert semantic_entity_key("Samsung Electronics") != semantic_entity_key("Samsung Display")
    assert semantic_entity_key("Samsung") != semantic_entity_key("Samsung Electronics")
    assert semantic_entity_key("SK") != semantic_entity_key("SK hynix")


def test_broadband_entities_use_explicit_bilingual_aliases_without_brand_guessing():
    assert semantic_entity_key("SK브로드밴드") == semantic_entity_key("SK Broadband")
    assert semantic_entity_key("에스케이브로드밴드") == semantic_entity_key("SKB")
    assert semantic_entity_key("케이티") == semantic_entity_key("KT Corporation")
    assert semantic_entity_key("LG유플러스") == semantic_entity_key("LG U+")
    assert semantic_entity_key("넷플릭스") == semantic_entity_key("Netflix")
    assert semantic_entity_key("티빙") == semantic_entity_key("TVING")
    assert semantic_entity_key("유튜브 쇼츠") == semantic_entity_key("YouTube Shorts")
    assert semantic_entity_key("네이버 클립") == semantic_entity_key("Naver Clip")
    # Services and their corporate owners are related, but not the same entity.
    assert semantic_entity_key("B tv") != semantic_entity_key("SK Broadband")
    assert semantic_entity_key("Genie TV") != semantic_entity_key("KT")
    assert semantic_entity_key("SK") != semantic_entity_key("SK Broadband")


def test_explicit_metric_aliases_merge_but_scope_and_measurement_do_not():
    assert semantic_metric_key("HBM market size") == semantic_metric_key("HBM 시장 규모")
    assert semantic_metric_key("HBM market revenue") == semantic_metric_key("HBM market size")
    assert semantic_metric_key("HBM market size") != semantic_metric_key("DRAM market size")
    assert semantic_metric_key("HBM market revenue") != semantic_metric_key("HBM shipment volume")
    assert semantic_metric_key("global HBM market revenue") != semantic_metric_key("Korea HBM market revenue")


def test_broadband_metric_aliases_merge_only_the_same_measurement():
    assert semantic_metric_key("유료 OTT 플랫폼 이용률") == semantic_metric_key("paid OTT usage rate")
    assert semantic_metric_key("IPTV 가입자 수") == semantic_metric_key("IPTV subscriber count")
    assert semantic_metric_key("광고 도달률") == semantic_metric_key("media reach")
    assert semantic_metric_key("브랜드 인지도") == semantic_metric_key("brand awareness")
    assert semantic_metric_key("광고 모델 선호도") == semantic_metric_key("model preference")
    assert semantic_metric_key("셋톱박스 단위원가") == semantic_metric_key("STB unit cost")

    assert semantic_metric_key("브랜드 인지도") != semantic_metric_key("브랜드 선호도")
    assert semantic_metric_key("모델 선호도") != semantic_metric_key("브랜드-모델 적합도")
    assert semantic_metric_key("롱폼 이용률") != semantic_metric_key("숏폼 이용률")
    assert semantic_metric_key("IPTV 가입자") != semantic_metric_key("초고속인터넷 가입자")
    assert semantic_metric_key("매체 도달률") != semantic_metric_key("플랫폼 이용률")
    assert semantic_metric_key("OTT 시장 점유율") != semantic_metric_key("IPTV 시장 점유율")


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


def test_landscape_rejects_unrelated_or_scope_mismatched_composites():
    trend = [metric("Global OTT market size", str(year), value, "USD billion")
             for year, value in ((2023, 10), (2024, 15), (2025, 22))]
    unrelated = [metric("Samsung CAPEX", "2025", 18, "USD billion")]
    korea_share = [
        metric("Korea OTT market share", "2025", 60, subject="A", share_of="Korea OTT market"),
        metric("Korea OTT market share", "2025", 40, subject="B", share_of="Korea OTT market"),
    ]
    global_share = [
        metric("Global OTT market share", "2025", 60, subject="A", share_of="Global OTT market"),
        metric("Global OTT market share", "2025", 40, subject="B", share_of="Global OTT market"),
    ]
    assert not has_landscape([*trend, *unrelated])
    assert not has_landscape([*trend, *korea_share])
    assert has_landscape([*trend, *global_share])


def test_relative_metrics_are_source_values_not_synthetic_absolute_points():
    relative = [
        metric("OTT 이용자 YoY 성장률", str(year), value, "%", is_relative=True,
               comparison_period="전년 대비", value_origin="source")
        for year, value in ((2024, 20), (2025, 35), (2026, 40))
    ]
    doubled = [metric("시장 성장 배수", "2026", 2, "배", is_relative=True,
                      value_type="forecast", value_origin="source")]
    assert has_timeseries(relative)
    assert not has_timeseries(doubled)
    assert relative_metric_context("2026년 전년 대비 40% 증가")[0] is True
    assert relative_metric_context("2026년 시장 규모는 40억 원")[0] is False
    assert all(point.value_origin == "source" for point in relative + doubled)


def test_same_metric_with_different_denominator_or_time_basis_stays_separate():
    points = [
        metric("시청 비중", "2025", 40, share_of="전체 가입자"),
        metric("시청 비중", "2025", 40, share_of="스포츠 시청자"),
        metric("시청 비중", "2025년 1분기", 42, share_of="전체 가입자"),
    ]
    assert len(group_metric_points_by_label(points)) == 3


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


def test_decision_matrix_accepts_only_explicit_qualitative_levels():
    explicit = [
        comparison("후보 A", "시장 매력도", "매우 높음", "high"),
        comparison("후보 A", "실행 용이성", "중간 수준", "medium"),
        comparison("후보 B", "시장 매력도", "낮음", "low"),
        comparison("후보 B", "실행 용이성", "높음", "high"),
    ]
    unsupported = [
        comparison("후보 A", "시장 규모", "40조원"),
        comparison("후보 A", "실행 용이성", "긍정적"),
        comparison("후보 B", "시장 규모", "20조원"),
        comparison("후보 B", "실행 용이성", "우수"),
    ]
    assert has_decision_matrix(explicit)
    assert not has_decision_matrix(unsupported)


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
