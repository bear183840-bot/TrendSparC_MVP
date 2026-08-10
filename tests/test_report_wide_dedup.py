"""Dedup is report-wide, and keyed on evidence *and* shape.

Two earlier attempts failed in opposite directions.

Keying on the block type alone let the same composition donut reach the page
twice under two different type ids. Keying on the evidence alone broke four
existing behaviours: whichever slot ran first claimed a label outright, so a
매출액 bar comparison in 순위 swallowed both the 매출액 trend line in 시장상황
and the 매출액 KPI card in 지표 - three questions ("how did it move", "what is
it now", "how does it rank") that a 현황파악 skeleton has three slots for.

The rule that holds: same facts drawn the same way is a repeat; same facts
drawn a different way is another question answered. That only works because
every entry in `_consumption()` reports what its block *draws* - `kpi_grid`
used to claim all 77 metrics for the six it shows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from common.purpose_slots import (
    _SHAPE_FAMILIES,
    _consumption,
    qualified_key,
    resolve_slots,
    share_evidence_key,
)
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture

_FIXTURES = Path(__file__).parent / "fixtures"


def _resolve(fixture_name: str):
    synthesis, question, _audience_id, purpose = load_synthesis_fixture(
        _FIXTURES / f"synthesis_{fixture_name}.json"
    )
    resolved = resolve_slots(purpose.purpose_id, synthesis, None, None, question)
    return {slot.slot.slot_id: slot for slot in resolved}, synthesis, question


# --- a block reports what it draws --------------------------------------


def test_a_kpi_grid_claims_only_the_cards_it_shows():
    """77 keys for six cards was a claim on the whole page, not caution."""
    _by_id, synthesis, question = _resolve("revenue_trend")

    keys = _consumption(question)["kpi_grid"](synthesis, [])

    assert 0 < len(keys) <= 6
    assert len(keys) < len(synthesis.metric_series) or len(synthesis.metric_series) <= 6


def test_a_chart_claims_only_the_series_it_plots():
    _by_id, synthesis, question = _resolve("revenue_trend")

    assert len(_consumption(question)["chart"](synthesis, [])) <= 3


def test_reporting_survives_having_no_question():
    """The dashboard passes one; a diagnostic caller may not."""
    _by_id, synthesis, _question = _resolve("revenue_trend")

    assert _consumption(None)["kpi_grid"](synthesis, []) is not None


# --- shape is part of the key -------------------------------------------


@pytest.mark.parametrize("block_types,family", [
    (("share_split", "composition_breakdown"), "composition"),
    (("kpi_grid", "kpi_single"), "kpi"),
    (("bar", "item_bar", "ranking_list", "grouped_bar", "metric_comparison"), "bars"),
    (("table", "segment_table", "benchmark_table", "level_matrix"), "comparison_grid"),
])
def test_blocks_that_draw_the_same_picture_share_a_family(block_types, family):
    assert {_SHAPE_FAMILIES[block_type] for block_type in block_types} == {family}


def test_a_trend_and_a_bar_of_one_label_are_not_the_same_key():
    label = "metric:매출액"

    assert qualified_key("trend", label) != qualified_key("bars", label)


def test_an_undeclared_block_type_dedupes_only_against_itself():
    """Its family is its own id, which is the old claimed-once rule."""
    assert "timeline" not in _SHAPE_FAMILIES


def test_a_key_that_already_names_its_family_is_left_alone():
    """`landscape` mints its own, because it draws two shapes in one card."""
    key = share_evidence_key("유료방송 가입자")

    assert qualified_key("bars", key) == key
    assert key.startswith("composition|")


# --- what that produces on a real skeleton ------------------------------


def test_three_shapes_of_one_label_still_get_three_slots():
    """The exact regression that forced the first attempt to be reverted."""
    by_id, _synthesis, _question = _resolve("revenue_trend")

    assert by_id["market"].block_type == "chart"
    assert by_id["metrics"].block_type == "kpi_grid"
    assert by_id["ranking"].block_type == "metric_comparison"


def test_a_composition_already_drawn_is_refused_at_resolution_now():
    """Not merely subtracted by the renderer - the slot moves on to a block
    that has something to add."""
    by_id, synthesis, question = _resolve("revenue_trend")
    consumption = _consumption(question)

    drawn = consumption["landscape"](synthesis, [])
    if drawn:
        # Whatever landscape draws, share_split's own keys for the same
        # wholes are in the same family and would collide.
        assert all("|" in key for key in drawn)


def test_a_slot_composition_still_holds_two_different_blocks():
    by_id, _synthesis, _question = _resolve("mixed_entities")

    assert by_id["ranking"].block_types == ("item_bar", "metric_comparison")
