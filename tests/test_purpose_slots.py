"""Fixed skeleton, flexible block: the slot-candidate resolution rules.

Each purpose's slot order is fixed so two reports of the same purpose are
comparable; the block filling a slot is whichever candidate the data actually
supports. "정보 없음" is reached only after every candidate for that slot's
intent has been tried.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.contracts import ReportPurposeClassification
from core.report_generator.generator import generate_report
from core.report_planner.planner import plan_report
from core.report_purpose.classifier import recommended_sections_for
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture
from reporting.dashboard_streamlit.purpose_slots import (
    DESIGN_LIBRARY_BLOCKS,
    LAST_RESORT,
    PURPOSE_SLOTS,
    resolve_slots,
    under_evidenced,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _resolve(fixture_name: str, mutate=None):
    synthesis, question, audience_id, purpose = load_synthesis_fixture(
        _FIXTURES / f"synthesis_{fixture_name}.json"
    )
    if mutate is not None:
        mutate(synthesis)
    plan = plan_report(synthesis, audience_id, purpose)
    report = generate_report(question, synthesis, plan, audience_id)
    resolved = resolve_slots(purpose.purpose_id, synthesis, report)
    return {slot.slot.slot_id: slot for slot in resolved}, resolved


# --- the skeleton itself ------------------------------------------------


def test_every_purpose_has_the_agreed_slot_order():
    assert [slot.slot_id for slot in PURPOSE_SLOTS["current_status"]] == [
        "summary", "ranking", "market", "metrics", "competitor", "factors",
        "keywords", "response",
    ]
    assert [slot.slot_id for slot in PURPOSE_SLOTS["issue_response"]] == [
        "problem", "cause", "impact", "options", "recommendation",
    ]
    assert [slot.slot_id for slot in PURPOSE_SLOTS["future_business"]] == [
        "market_shift", "opportunity", "capability", "roadmap", "risk",
    ]
    assert [slot.slot_id for slot in PURPOSE_SLOTS["root_cause"]] == [
        "problem", "cause", "drivers", "improvement",
    ]


def test_every_candidate_is_a_real_block_type():
    known = {block for blocks in DESIGN_LIBRARY_BLOCKS.values() for block in blocks}
    known |= {"radar", "narrative_list"}
    for slots in PURPOSE_SLOTS.values():
        for slot in slots:
            assert set(slot.candidates) <= known, slot


def test_narrative_list_is_the_last_candidate_wherever_it_appears():
    """It is the catch-all, so anything after it would be unreachable."""
    for slots in PURPOSE_SLOTS.values():
        for slot in slots:
            if "narrative_list" in slot.candidates:
                assert slot.candidates[-1] == "narrative_list", slot


def test_no_slot_offers_a_block_that_answers_a_different_question():
    """A KPI card must never be a fallback for a causal or comparative slot."""
    for purpose_id, slots in PURPOSE_SLOTS.items():
        for slot in slots:
            if slot.slot_id in {"cause", "options", "competitor", "capability"}:
                assert not {"kpi_grid", "kpi_single"} & set(slot.candidates), (purpose_id, slot)


# --- first choice wins when the data is there ---------------------------


@pytest.mark.parametrize(
    "fixture_name, slot_id, expected",
    [
        ("revenue_trend", "metrics", "kpi_grid"),
        ("revenue_trend", "market", "chart"),
        # matrix is claimed by the "문제" slot above, so this moves to table.
        ("iptv_competition", "options", "table"),
        ("iptv_competition", "recommendation", "action_list"),
        ("future_business", "opportunity", "matrix"),
        # timeline is claimed by "시장 변화", so this moves to action_list.
        ("future_business", "roadmap", "action_list"),
        ("root_cause", "cause", "cause_map"),
        ("root_cause", "improvement", "action_list"),
    ],
)
def test_first_choice_candidate_is_used_when_its_data_exists(fixture_name, slot_id, expected):
    by_id, _ = _resolve(fixture_name)
    assert by_id[slot_id].block_type == expected


def test_no_fixture_leaves_the_majority_of_its_slots_empty():
    for fixture_name in ("revenue_trend", "iptv_competition", "future_business", "root_cause"):
        _, resolved = _resolve(fixture_name)
        assert not under_evidenced(resolved), fixture_name


# --- falling through to the second and third candidate ------------------


def _strip_metrics(synthesis):
    synthesis.metric_series = []


def _strip_all_structured(synthesis):
    synthesis.metric_series = []
    synthesis.comparison_points = []
    synthesis.strengths = []
    synthesis.weaknesses = []
    synthesis.opportunities = []
    synthesis.risks = []
    synthesis.recommended_actions = []
    synthesis.business_impacts = []


def test_metrics_slot_falls_from_kpi_grid_to_single_card():
    def keep_one(synthesis):
        synthesis.metric_series = synthesis.metric_series[:1]

    by_id, _ = _resolve("revenue_trend", keep_one)
    assert by_id["metrics"].block_type == "kpi_single"


def test_market_slot_falls_from_chart_to_timeline_when_the_figures_go():
    by_id, _ = _resolve("revenue_trend", _strip_metrics)
    # Dated evidence prose survives, so the slot's intent is still served.
    assert by_id["market"].block_type == "timeline"


def test_narrative_text_carries_a_slot_when_no_structured_data_remains():
    by_id, _ = _resolve("iptv_competition", _strip_all_structured)
    filled = [slot for slot in by_id.values() if slot.block_type == "narrative_list"]
    assert filled, "every slot fell to 정보 없음 despite narrative evidence"


def test_last_resort_only_after_every_candidate_was_tried():
    """The 'competition' collection failure from the live log: nothing at all
    for that slot, in any form."""

    def strip_everything(synthesis):
        _strip_all_structured(synthesis)
        synthesis.key_points = []
        synthesis.evidence = []
        synthesis.highlights = []
        synthesis.monitoring_indicators = []

    _, resolved = _resolve("iptv_competition", strip_everything)

    assert all(slot.block_type == LAST_RESORT for slot in resolved)
    assert under_evidenced(resolved) is True


# --- the under-evidenced threshold --------------------------------------


class _Slot:
    def __init__(self, empty):
        self.block_type = LAST_RESORT if empty else "chart"

    @property
    def is_last_resort(self):
        return self.block_type == LAST_RESORT


@pytest.mark.parametrize(
    "empties, total, expected",
    [(0, 5, False), (2, 5, False), (3, 5, True), (2, 4, True), (1, 3, False)],
)
def test_under_evidenced_threshold(empties, total, expected):
    resolved = [_Slot(index < empties) for index in range(total)]
    assert under_evidenced(resolved) is expected


def test_threshold_is_configurable():
    resolved = [_Slot(index < 1) for index in range(5)]
    assert under_evidenced(resolved) is False
    assert under_evidenced(resolved, ratio=0.2) is True


def test_no_slots_is_not_reported_as_under_evidenced():
    assert under_evidenced([]) is False


# --- single ownership: a shared-data block is drawn once ----------------


def test_a_structural_block_is_not_drawn_twice_from_the_same_data():
    """Both 문제 and 선택지 list matrix first, and both would have rendered the
    identical SWOT built from the same four synthesis fields."""
    _, resolved = _resolve("iptv_competition")
    structural = [
        slot.block_type for slot in resolved
        if slot.block_type not in {"narrative_list", LAST_RESORT}
    ]

    assert len(structural) == len(set(structural)), structural


def test_narrative_list_is_exempt_from_single_ownership():
    """Structural blocks are claimed once because they redraw one shared pool
    on the synthesis. narrative_list reads each slot's own section, so more
    than one slot may use it.

    This does not assert the texts differ: with every structured field
    stripped, the remaining sections genuinely fall back to the same
    key_points, and claiming otherwise would assert something the data cannot
    provide. Keeping the sections distinct is report_generator's job (see its
    per-section field split), not the slot resolver's.
    """
    _, resolved = _resolve("iptv_competition", _strip_all_structured)
    narratives = [slot for slot in resolved if slot.block_type == "narrative_list"]

    assert len(narratives) > 1


# --- period is free text, and is not always a time ----------------------


def test_subject_valued_periods_do_not_create_a_timeline():
    """app_churn stores the compared subject in `period` ("B tv+ 앱" vs
    "경쟁 OTT 앱 평균"), and none of its evidence carries a date.

    Both report_planner and the timeline block used to read those as two
    distinct points in time, so a report with no chronology at all was given
    a Timeline section listing "B tv+ 앱" as though it were a moment.
    """
    from common.content_quality_validator import is_time_period
    from reporting.dashboard_streamlit import components

    synthesis, _, _, _ = load_synthesis_fixture(
        _FIXTURES / "synthesis_app_churn_root_cause.json"
    )

    assert not any(is_time_period(point.period) for point in synthesis.metric_series)
    assert components.has_timeline(synthesis.evidence, synthesis.metric_series) is False


def test_before_after_periods_still_count_as_a_sequence():
    from common.content_quality_validator import is_time_period

    assert is_time_period("도입 전") is True
    assert is_time_period("개편 이후") is True
    assert is_time_period("2026년 1분기") is True
    assert is_time_period("B tv+ 앱") is False
    assert is_time_period("경쟁 OTT 앱 평균") is False
    assert is_time_period("이용자 설문") is False


def test_app_churn_fixture_fills_every_root_cause_slot():
    by_id, resolved = _resolve("app_churn_root_cause")

    assert by_id["cause"].block_type == "cause_map"
    assert by_id["improvement"].block_type == "action_list"
    assert not any(slot.is_last_resort for slot in resolved)


# --- age brackets in `period` are a comparison, not a trend --------------


def test_age_bracket_periods_are_not_read_as_a_trend():
    """brand_marketing measures TV 도달률 against 20대 and 50대 이상.

    Two points, but not two points in time - calling that a chart claims a
    movement the data never described.
    """
    from common.content_quality_validator import is_time_period
    from core.layout_generator.generator import _candidate_content_types

    synthesis, _, _, _ = load_synthesis_fixture(_FIXTURES / "synthesis_brand_marketing.json")
    assert not any(is_time_period(point.period) for point in synthesis.metric_series)

    content = {
        "metric_points": [point.model_dump() for point in synthesis.metric_series]
    }
    assert "chart" not in _candidate_content_types(content)
    assert "bar" in _candidate_content_types(content)


def test_bare_four_digit_years_still_count_as_a_trend():
    from common.content_quality_validator import is_time_period
    from core.layout_generator.generator import _candidate_content_types

    assert is_time_period("2019") is True
    assert is_time_period("20대") is False
    assert is_time_period("30~40대") is False

    content = {
        "metric_points": [
            {"label": "가입자", "period": "2019", "value": 519.0, "unit": "만 명"},
            {"label": "가입자", "period": "2023", "value": 946.0, "unit": "만 명"},
            {"label": "가입자", "period": "2025", "value": 990.0, "unit": "만 명"},
        ]
    }
    assert "chart" in _candidate_content_types(content)


def test_brand_marketing_fills_every_future_business_slot():
    by_id, resolved = _resolve("brand_marketing")

    # An age-bracket comparison is an item ranking, not a movement in time -
    # same renderer, but the block id now says which question it answers.
    assert by_id["market_shift"].block_type == "item_bar"
    assert by_id["capability"].block_type == "table"
    # strengths is empty here, so the SWOT has 3 of 4 quadrants - still enough.
    assert by_id["opportunity"].block_type == "matrix"
    # matrix is claimed above, so 위험 falls to its own narrative bullets.
    assert by_id["risk"].block_type == "narrative_list"
    assert not any(slot.is_last_resort for slot in resolved)


# --- one metric across several subjects is a bar, never a line ----------


def test_three_carriers_are_not_drawn_as_a_trend_line():
    """jungang_group_crisis measures one metric against SK브로드밴드, KT and
    LG유플러스 - three points, none of them a point in time.

    A line asserts a progression between its points, so drawing it here
    claimed that SK브로드밴드 leads to KT leads to LG유플러스.
    """
    from common.content_quality_validator import classify_metric_shape
    from reporting.dashboard_streamlit import components

    synthesis, _, _, _ = load_synthesis_fixture(
        _FIXTURES / "synthesis_jungang_group_crisis.json"
    )

    assert classify_metric_shape(synthesis.metric_series) == "comparison"
    assert components.has_timeseries(synthesis.metric_series) is False
    # Still drawn - as bars, not dropped to prose.
    assert [group[0].label for group in components.bar_metric_groups(synthesis.metric_series)] == [
        "중앙그룹 계열 채널 편성 비중"
    ]


def test_subject_bars_read_largest_first(monkeypatch):
    """Subjects have no inherent order, so value order is the informative one.
    Periods that are real times keep their chronological order instead."""
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    synthesis, _, _, _ = load_synthesis_fixture(
        _FIXTURES / "synthesis_jungang_group_crisis.json"
    )
    components.render_metric_bar(synthesis.metric_series)
    body = "".join(captured)

    assert body.index("KT") < body.index("LG유플러스") < body.index("SK브로드밴드")


def test_unrelated_comparison_axes_do_not_share_a_table():
    """The fixture mixes carrier exposure with 단기 리스크 items, which share
    no criterion - a table of both would pair unrelated cells."""
    from reporting.dashboard_streamlit import components

    synthesis, _, _, _ = load_synthesis_fixture(
        _FIXTURES / "synthesis_jungang_group_crisis.json"
    )
    headers, rows = components.comparison_points_to_table(synthesis.comparison_points)

    assert headers == ["중앙그룹 채널 노출도"]
    assert [row[0] for row in rows] == ["SK브로드밴드", "KT", "LG유플러스"]


def test_jungang_fixture_fills_every_issue_response_slot():
    by_id, resolved = _resolve("jungang_group_crisis")

    assert by_id["impact"].block_type == "item_bar"
    assert by_id["options"].block_type == "table"
    assert by_id["recommendation"].block_type == "action_list"
    assert not any(slot.is_last_resort for slot in resolved)
