from __future__ import annotations

from audience.presentation import load_audience_presentation, order_slots_for_audience
from common.block_shapes import (
    benchmark_grid,
    comparison_points_not_covered_by_ranking,
    has_benchmark_grid,
    has_ranking_list,
    ranking_list_groups,
)
from common.contracts import ComparisonPoint, MetricPoint
from common.purpose_slots import ResolvedSlot, Slot
from reporting.dashboard_streamlit.blocks.registry import known_types
from reporting.dashboard_streamlit.generic_dashboard import _partition_dashboard_slots


def test_profiles_change_density_without_removing_block_capability():
    practitioner = load_audience_presentation("practitioner")
    executive = load_audience_presentation("executive")
    management = load_audience_presentation("management")

    assert practitioner.kpi_limit > executive.kpi_limit >= management.kpi_limit
    assert practitioner.narrative_limit > executive.narrative_limit >= management.narrative_limit
    assert practitioner.summary_label == "실무 요약"
    assert executive.summary_label == "의사결정 요약"
    assert management.summary_label == "전략 요약"


def test_profile_section_preferences_reorder_supported_slots_stably():
    slots = [
        ResolvedSlot(Slot("summary", "요약", "", ("narrative_list",), ("overview",)),
                     ("narrative_list",), "overview", []),
        ResolvedSlot(Slot("market", "시장", "", ("chart",), ("market_status",)),
                     ("chart",), "market_status", []),
        ResolvedSlot(Slot("risk", "위험", "", ("matrix",), ("risk",)),
                     ("matrix",), "risk", []),
        ResolvedSlot(Slot("action", "전략", "", ("action_list",), ("strategic_recommendation",)),
                     ("action_list",), "strategic_recommendation", []),
    ]

    ordered = order_slots_for_audience(slots, load_audience_presentation("management"))

    assert [slot.slot.slot_id for slot in ordered] == ["summary", "risk", "action", "market"]


def test_four_or_more_subjects_earn_a_generic_ranking_list():
    points = [
        MetricPoint(label="이용률", subject=name, period="2025년", value=value, unit="%")
        for name, value in (("A", 40), ("B", 30), ("C", 20), ("D", 10))
    ]

    assert ranking_list_groups(points) == [points]


def test_mixed_subquestions_collapsed_under_one_label_do_not_become_a_ranking():
    points = [
        MetricPoint(label="이용자", subject="한국 콘텐츠", period="2025", value=83.8, unit="%"),
        MetricPoint(label="이용자", subject="단일 시즌", period="2025", value=71.4, unit="%"),
        MetricPoint(label="이용자", subject="한국 콘텐츠(83.8%)를 해외 콘텐츠", period="2025", value=61.8, unit="%"),
        MetricPoint(label="이용자", subject=None, period="2025", value=60.3, unit="%"),
    ]

    assert ranking_list_groups(points, minimum_items=2) == []


def test_benchmark_combines_shared_numeric_and_qualitative_dimensions():
    metrics = [
        MetricPoint(label="가입자", subject=entity, period="2025년", value=value, unit="만명")
        for entity, value in (("A사", 900), ("B사", 700))
    ]
    comparisons = [
        ComparisonPoint(entity=entity, criterion="신사업 영역", value=value)
        for entity, value in (("A사", "AI"), ("B사", "미디어"))
    ]

    entities, dimensions, cells = benchmark_grid(comparisons, metrics)

    assert entities == ["A사", "B사"]
    assert dimensions == ["신사업 영역", "가입자"]
    assert cells[("가입자", "A사")] == "900만명"
    assert has_benchmark_grid(comparisons, metrics)


def test_rank_only_comparisons_do_not_duplicate_as_benchmark():
    metrics = [
        MetricPoint(label="이용률", subject=entity, period="2025년", value=value, unit="%")
        for entity, value in (("A", 40), ("B", 30), ("C", 20))
    ]
    comparisons = [
        ComparisonPoint(entity=entity, criterion="플랫폼 순위", value=f"{rank}위")
        for rank, entity in enumerate(("A", "B", "C"), start=1)
    ]

    assert not has_benchmark_grid(comparisons, metrics)
    assert comparison_points_not_covered_by_ranking(comparisons, metrics) == []
    assert has_ranking_list([], comparisons)


def test_new_blocks_are_registered_in_the_same_design_registry():
    assert {
        "ranking_list", "keyword_tags", "composition_breakdown", "benchmark_table"
    } <= known_types()


def test_first_screen_has_fixed_slot_budget_and_detail_keeps_all_supported_slots():
    slots = [
        ResolvedSlot(Slot("summary", "요약", "", ("narrative_list",), ("overview",)),
                     ("narrative_list",), "overview", []),
        ResolvedSlot(Slot("metrics", "지표", "", ("kpi_grid",), ("key_metrics",)),
                     ("kpi_grid",), "key_metrics", []),
        *[
            ResolvedSlot(Slot(f"s{i}", f"블록 {i}", "", ("chart",), ("market_status",)),
                         ("chart",), "market_status", [])
            for i in range(4)
        ],
    ]

    primary, detail = _partition_dashboard_slots(slots, primary_limit=2)

    assert [slot.slot.slot_id for slot in primary] == ["s0", "s1"]
    assert [slot.slot.slot_id for slot in detail] == ["metrics", "s0", "s1", "s2", "s3"]
