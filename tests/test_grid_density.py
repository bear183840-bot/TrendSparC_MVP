"""Card width follows content volume; reading order never follows width.

Every block took the width its type declared, so a comparison table of two
entities and one of nine were both half the landscape and the page ran to
four screens with most of it whitespace inside cards. Width is now what the
block would actually fill.

The constraint that matters more than density: the purpose skeleton is an
argument (현황 -> 지표 -> 경쟁 -> 대응) read top-to-bottom, left-to-right.
Packing is greedy in that order and never reshuffles to close a gap.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from common.contracts import ComparisonPoint
from common.purpose_slots import ResolvedSlot, Slot
from reporting.dashboard_streamlit.generic_dashboard import (
    _GRID_UNITS,
    _grid_rows,
    _slot_width,
)


def _slot(slot_id: str, block_type: str, items: list[str] | None = None) -> ResolvedSlot:
    return ResolvedSlot(
        slot=Slot(slot_id, slot_id, "", (block_type,), ()),
        block_types=(block_type,), section_id=None, items=list(items or []),
    )


def _synthesis(**kwargs) -> SimpleNamespace:
    base = dict(
        metric_series=[], comparison_points=[], evidence=[], recommended_actions=[],
        factors=[], risks=[],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _comparisons(count: int) -> list[ComparisonPoint]:
    return [
        ComparisonPoint(entity=f"사업자{index}", criterion="점유율", value=f"{index}%",
                        evidence_claim_id=f"c{index}", doc_id="d1")
        for index in range(count)
    ]


# --- volume decides the width -------------------------------------------


def test_a_two_row_table_takes_a_quarter_not_a_half():
    slot = _slot("competitor", "table")

    assert _slot_width(slot, synthesis=_synthesis(comparison_points=_comparisons(2))) == 1


def test_a_nine_row_table_keeps_its_declared_width():
    slot = _slot("competitor", "table")

    assert _slot_width(slot, synthesis=_synthesis(comparison_points=_comparisons(12))) == 2


def test_a_short_prose_card_shrinks():
    assert _slot_width(_slot("market", "narrative_list", ["한 줄"]), synthesis=_synthesis()) == 1


def test_a_long_prose_card_does_not():
    items = [f"항목 {index}" for index in range(12)]

    assert _slot_width(_slot("market", "narrative_list", items), synthesis=_synthesis()) == 2


def test_width_never_grows_past_what_the_block_type_declared():
    """Density narrows a card. It never widens one - a block that says it
    needs one unit is not given two because it happens to have a lot."""
    slot = _slot("keywords", "keyword_tags", [f"항목 {i}" for i in range(40)])

    assert _slot_width(slot, synthesis=_synthesis()) == 1


# --- and the cases where it must not guess ------------------------------


def test_an_unmeasured_block_type_keeps_its_declared_width():
    assert _slot_width(_slot("market", "landscape"), synthesis=_synthesis()) == 4


def test_without_a_synthesis_nothing_shrinks():
    slot = _slot("competitor", "table")

    assert _slot_width(slot) == 2


def test_a_composition_is_measured_by_neither_of_its_blocks():
    """Two stacked blocks fill a card the lead's volume knows nothing about."""
    slot = ResolvedSlot(
        slot=Slot("comparison", "비교", "", ("table",), ()),
        block_types=("table", "item_bar"), section_id=None, items=[],
    )

    assert _slot_width(slot, synthesis=_synthesis(comparison_points=_comparisons(2))) == 2


def test_a_partial_synthesis_does_not_crash_the_page():
    slot = _slot("competitor", "table")

    assert _slot_width(slot, synthesis=SimpleNamespace()) == 2


# --- reading order survives packing -------------------------------------


@pytest.mark.parametrize("compact", [True, False])
def test_packing_preserves_the_skeleton_order(compact):
    slots = [
        _slot("summary", "narrative_list", ["한 줄"]),
        _slot("market", "landscape"),
        _slot("competitor", "table"),
        _slot("keywords", "keyword_tags"),
    ]
    synthesis = _synthesis(comparison_points=_comparisons(2))

    flattened = [
        slot for row in _grid_rows(slots, compact=compact, synthesis=synthesis) for slot in row
    ]

    assert [slot.slot.slot_id for slot in flattened] == [
        "summary", "market", "competitor", "keywords",
    ]


def test_no_row_is_packed_past_the_landscape_width():
    slots = [_slot(f"s{index}", "narrative_list", ["한 줄"]) for index in range(7)]
    synthesis = _synthesis()

    for row in _grid_rows(slots, compact=True, synthesis=synthesis):
        assert sum(_slot_width(slot, compact=True, synthesis=synthesis) for slot in row) <= _GRID_UNITS


def test_shrinking_puts_more_cards_on_one_row():
    """The whole point: four one-line cards share a row instead of taking four."""
    slots = [_slot(f"s{index}", "narrative_list", ["한 줄"]) for index in range(4)]

    dense = _grid_rows(slots, compact=True, synthesis=_synthesis())
    unsized = _grid_rows(slots, compact=True)

    assert len(dense) < len(unsized)
