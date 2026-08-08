from types import SimpleNamespace

from reporting.dashboard_streamlit.generic_dashboard import _question_structure_order
from reporting.dashboard_streamlit.generic_dashboard import _question_comparison_slot


def _slot(slot_id: str, block_type: str):
    return SimpleNamespace(
        slot=SimpleNamespace(slot_id=slot_id),
        block_type=block_type,
    )


def _point(period: str):
    return SimpleNamespace(label="가입자 수", subject=None, period=period, unit="명", value=1)


def test_multi_period_question_puts_real_chart_before_rankings():
    slots = [_slot("ranking", "ranking_list"), _slot("market", "chart"), _slot("metrics", "kpi_grid")]
    requirement = SimpleNamespace(minimum_distinct_periods=5, comparison_anchors=["국내", "글로벌"])

    ordered = _question_structure_order(
        slots, requirement, [_point("2022년"), _point("2023년"), _point("2024년")]
    )

    assert [slot.slot.slot_id for slot in ordered] == ["market", "ranking", "metrics"]


def test_comparison_question_puts_supported_comparison_first_without_topic_words():
    slots = [_slot("metrics", "kpi_grid"), _slot("comparison", "grouped_bar")]
    requirement = SimpleNamespace(minimum_distinct_periods=0, comparison_anchors=["A", "B"])

    ordered = _question_structure_order(slots, requirement)

    assert [slot.slot.slot_id for slot in ordered] == ["comparison", "metrics"]


def test_requested_trend_does_not_promote_non_chart_as_if_series_existed():
    slots = [_slot("ranking", "ranking_list"), _slot("market", "narrative_list")]
    requirement = SimpleNamespace(minimum_distinct_periods=5, comparison_anchors=[])

    assert _question_structure_order(slots, requirement) == slots


def test_less_than_majority_of_long_horizon_is_not_promoted_as_the_answer():
    slots = [_slot("ranking", "ranking_list"), _slot("market", "chart")]
    requirement = SimpleNamespace(minimum_distinct_periods=10, comparison_anchors=[])
    points = [_point("2022년"), _point("2023년"), _point("2024년")]

    assert _question_structure_order(slots, requirement, points) == slots


def test_any_explicit_two_axes_get_a_text_comparison_without_topic_rules():
    section = SimpleNamespace(
        key_points=["북부 지역은 가입자가 증가했다.", "남부 지역은 해지율이 하락했다."],
        evidence=[], risks=[], opportunities=[], monitoring_indicators=[],
    )
    result = SimpleNamespace(
        generated_report=SimpleNamespace(executive_summary="", sections=[section]),
        documents=[], document_analyses=[],
    )
    synthesis = SimpleNamespace(key_points=[], evidence=[])

    slot = _question_comparison_slot(
        result, synthesis, "북부 vs 남부 비교", ["북부", "남부"]
    )

    assert slot is not None
    assert slot.block_type == "question_comparison"
    assert slot.items[0].startswith("북부\x1f북부 지역은")
    assert slot.items[1].startswith("남부\x1f남부 지역은")
