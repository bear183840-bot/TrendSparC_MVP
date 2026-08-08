"""A slot shows what the evidence has, in as many blocks as that takes.

The three failures these tests exist to prevent, all seen on real runs:

* padding - a four-quadrant SWOT filled with "관련 데이터 수집 필요" because the
  block wanted four things and the evidence had two;
* miscategorising - 50대 / 60대 / 70대 이상 rendered under the heading 경쟁사,
  because the slot asked "are there two entities with a shared criterion" and
  age brackets answer yes;
* dropping - a slot showing only its first block and discarding a second,
  entirely different set of figures that answered the same question.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.purpose_slots import PURPOSE_SLOTS, resolve_slots
from common.content_quality_validator import entity_kind, is_demographic
from common.block_shapes import comparison_points_of_kind
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture

_FIXTURES = Path(__file__).parent / "fixtures"


def _resolve(fixture_name: str):
    synthesis, _question, _audience_id, purpose = load_synthesis_fixture(
        _FIXTURES / f"synthesis_{fixture_name}.json"
    )
    resolved = resolve_slots(purpose.purpose_id, synthesis, None)
    return {slot.slot.slot_id: slot for slot in resolved}, synthesis


# --- entity kind decides the slot, not mere presence ---------------------


@pytest.mark.parametrize("entity,expected", [
    ("20대", "age"),
    ("30~40대", "age"),
    ("10-20대", "age"),
    ("50대 이상", "age"),
    ("만 15세", "age"),
    ("전 연령", "age"),
    ("여성", "gender"),
    ("1인 가구", "household"),
    ("KT", "entity"),
    ("B tv", "entity"),
    ("넷플릭스", "entity"),
])
def test_entity_kind_separates_people_from_organisations(entity, expected):
    assert entity_kind(entity) == expected
    assert is_demographic(entity) == (expected != "entity")


def test_age_and_company_comparisons_go_to_different_slots():
    """The fixture mixes both kinds in one comparison_points list."""
    by_id, synthesis = _resolve("mixed_entities")

    assert by_id["competitor"].block_type == "table"
    assert by_id["segments"].block_type == "segment_table"

    companies = comparison_points_of_kind(synthesis.comparison_points, demographic=False)
    people = comparison_points_of_kind(synthesis.comparison_points, demographic=True)
    assert [point.entity for point in companies] == ["SK브로드밴드", "KT", "LG유플러스"]
    # Youngest first: the evidence order is whichever sentence was read first,
    # which is not a fact about the age split.
    assert [point.entity for point in people] == ["20대", "50대", "70대 이상"]


def test_no_demographic_entity_ever_reaches_a_competitor_block():
    for fixture in ("mixed_entities", "revenue_trend", "jungang_group_crisis"):
        _by_id, synthesis = _resolve(fixture)
        for point in comparison_points_of_kind(synthesis.comparison_points, demographic=False):
            assert not is_demographic(point.entity), (fixture, point.entity)


# --- the composition grows and shrinks with the evidence -----------------


def test_a_slot_may_hold_two_blocks_when_they_show_different_facts():
    by_id, _synthesis = _resolve("mixed_entities")

    ranking = by_id["ranking"]
    assert ranking.block_types == ("item_bar", "metric_comparison")
    # The lead is still the single block every non-composition caller reads.
    assert ranking.block_type == "item_bar"


def test_a_companion_never_redraws_the_leads_own_data():
    """Every block in a slot must contribute something the others don't."""
    from common.purpose_slots import _consumption

    consumption = _consumption()
    for fixture in ("mixed_entities", "sparse_evidence", "revenue_trend"):
        by_id, synthesis = _resolve(fixture)
        for slot in by_id.values():
            drawn: set[str] = set()
            for block_type in slot.block_types:
                keys_of = consumption.get(block_type)
                if keys_of is None:
                    continue
                keys = keys_of(synthesis, slot.items)
                assert not (keys and keys <= drawn), (fixture, slot.slot.slot_id, block_type)
                drawn |= keys


def test_thin_evidence_produces_fewer_slots_not_padded_ones():
    thin, _ = _resolve("sparse_evidence")
    dense, _ = _resolve("mixed_entities")

    # Nothing in the thin fixture compares two entities, so both comparison
    # slots are absent or empty rather than filled with something else.
    assert "segments" not in thin
    assert thin["competitor"].is_last_resort
    assert dense["segments"].block_type == "segment_table"
    assert not dense["competitor"].is_last_resort

    # And the dense fixture puts more on screen than the thin one, without
    # either being padded to a fixed shape.
    thin_blocks = sum(len(slot.block_types) for slot in thin.values() if not slot.is_last_resort)
    dense_blocks = sum(len(slot.block_types) for slot in dense.values() if not slot.is_last_resort)
    assert thin_blocks < dense_blocks


def test_composition_never_costs_a_later_slot_its_first_choice():
    """Leads are assigned before any companion, in skeleton order.

    A companion taking a block a later slot needs is how 원인 ended up with
    the ranking bars that 영향 had as its first choice, leaving 영향 in prose.
    """
    for purpose_id, slots in PURPOSE_SLOTS.items():
        for fixture in ("mixed_entities", "sparse_evidence", "jungang_group_crisis",
                        "revenue_trend", "root_cause"):
            synthesis, _q, _a, purpose = load_synthesis_fixture(
                _FIXTURES / f"synthesis_{fixture}.json"
            )
            if purpose.purpose_id != purpose_id:
                continue
            resolved = resolve_slots(purpose_id, synthesis, None)
            leads = {slot.block_type for slot in resolved}
            for slot in resolved:
                for companion in slot.block_types[1:]:
                    assert companion not in leads - {slot.block_type}, (purpose_id, fixture)


# --- partial fills are drawn as themselves -------------------------------


@pytest.mark.parametrize("filled,expected_class", [
    (2, "ts-swot duo"),
    (3, "ts-swot trio"),
    (4, "ts-swot"),
])
def test_swot_grid_follows_the_number_of_quadrants_it_has(filled, expected_class):
    from reporting.dashboard_streamlit.components import render_swot

    quadrants = [["강점"], ["약점"], ["기회"], ["위협"]]
    for index in range(filled, 4):
        quadrants[index] = []
    html = render_swot(*quadrants)
    assert f'class="{expected_class}"' in html
    assert "수집 필요" not in html


def test_one_quadrant_becomes_a_panel_rather_than_disappearing():
    """있는 만큼 쓰기 - the block shrinks to what it has instead of vanishing."""
    from reporting.dashboard_streamlit.components import render_swot

    assert 'class="ts-swot solo"' in render_swot(["강점만 있음"], [], [], [])
    # Nothing at all is still nothing at all.
    assert render_swot([], [], [], []) == ""


def test_kpi_row_draws_as_many_cards_as_there_are_figures():
    """Not four because four looks tidy - however many the evidence gave."""
    from reporting.dashboard_streamlit import components

    class _Point:
        def __init__(self, label, value):
            self.label, self.value, self.unit, self.period = label, value, "%", "2024년"
            self.subject = None
            self.is_forecast = False

    captured: list[str] = []
    original = components.st.markdown
    components.st.markdown = lambda html, **kwargs: captured.append(html)
    try:
        for count in (1, 2, 5, 6):
            captured.clear()
            components.render_kpi_row([_Point(f"지표{n}", float(n)) for n in range(count)])
            html = "".join(captured)
            assert html.count("ts-kpi-card") == count, count
            # One or two figures use the full-width row variant; more fill the
            # card grid. Either way the count is the data's, not the layout's.
            assert ("ts-kpi-row rows" in html) == (count <= 2), count
    finally:
        components.st.markdown = original
