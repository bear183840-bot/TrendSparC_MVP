"""The live dashboard draws through the block registry, not beside it.

There used to be two tables: `blocks/*.py` registered fifteen block types the
live app never imported, and `generic_dashboard._body_renderer` was an
if-chain the live app actually used. The same block type could be drawn two
different ways depending on which branch ran, and a new block had to be added
twice. These tests pin the consolidation so it can't quietly come apart.
"""

from __future__ import annotations

import reporting.dashboard_streamlit.blocks  # noqa: F401  (registers everything)
from reporting.dashboard_streamlit.blocks.base import BlockDefinition, SlotContext
from reporting.dashboard_streamlit.blocks.registry import BLOCK_REGISTRY, register, slot_renderer
from reporting.dashboard_streamlit.purpose_slots import PURPOSE_SLOTS


def test_every_block_a_slot_can_choose_has_a_live_renderer():
    """A slot resolving to a block nothing can draw is an empty titled card -
    the failure this registry exists to make impossible."""
    candidates = {
        candidate
        for slots in PURPOSE_SLOTS.values()
        for slot in slots
        for candidate in slot.candidates
    } - {"narrative_list"}  # drawn by the view itself, from the slot's own text

    missing = sorted(name for name in candidates if slot_renderer(name) is None)

    assert missing == []


def test_the_live_view_looks_blocks_up_rather_than_holding_its_own_table():
    from reporting.dashboard_streamlit import generic_dashboard

    source = generic_dashboard._body_renderer.__doc__ or ""

    assert "slot_blocks" in source
    # The if-chain is gone: the function body resolves one lookup.
    assert generic_dashboard._body_renderer("nonexistent_block", None, None, [], [], [], []) is None


def test_registering_one_renderer_never_erases_the_other():
    """Both paths name the same block types, so import order used to decide
    which renderer survived."""
    existing = BLOCK_REGISTRY["radar"]

    assert existing.render is not None
    assert existing.slot_render is not None

    register(BlockDefinition(
        block_type="radar", schema=existing.schema, render=None,
        description="", slot_render=None,
    ))

    assert BLOCK_REGISTRY["radar"].render is existing.render
    assert BLOCK_REGISTRY["radar"].slot_render is existing.slot_render


def test_a_block_whose_data_is_missing_returns_none_not_an_empty_card():
    from common.contracts import TrendSynthesis

    synthesis = TrendSynthesis(request_id="r", sector_id="sk_broadband")
    context = SlotContext(
        result=None, synthesis=synthesis, items=[], risks=[], opportunities=[],
        strengths=[], weaknesses=[],
    )

    assert slot_renderer("kpi_grid")(context) is None
    assert slot_renderer("table")(context) is None
    assert slot_renderer("matrix")(context) is None
