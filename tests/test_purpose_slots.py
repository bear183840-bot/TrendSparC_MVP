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
        "summary", "market", "metrics", "competitor", "response",
    ]
    assert [slot.slot_id for slot in PURPOSE_SLOTS["issue_response"]] == [
        "problem", "cause", "impact", "options", "recommendation",
    ]
    assert [slot.slot_id for slot in PURPOSE_SLOTS["future_business"]] == [
        "market_shift", "opportunity", "capability", "roadmap", "risk",
    ]
    assert [slot.slot_id for slot in PURPOSE_SLOTS["root_cause"]] == [
        "problem", "cause", "improvement",
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


def test_narrative_list_may_repeat_because_each_slot_holds_different_text():
    _, resolved = _resolve("iptv_competition", _strip_all_structured)
    narratives = [slot for slot in resolved if slot.block_type == "narrative_list"]

    assert len(narratives) > 1
    texts = [tuple(slot.items) for slot in narratives]
    assert len(set(texts)) > 1, "same text repeated under different slot titles"
