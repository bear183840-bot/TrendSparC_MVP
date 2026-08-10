"""A composition is drawn once per page, wherever it first appeared.

The live 유료방송 run put the identical donut (IPTV 59.1 / SO 33.4 / 위성 7.5)
in two cards: 시장 변화 drew it inside a `landscape`, and 주요 비교 drew it
again as a `share_split`. Neither block was wrong on its own - they are
different block types, so the claimed-once rule never saw a collision, and
`landscape` reported that it consumed every metric label in the synthesis,
which is both too coarse to collide on a donut and too greedy to let any
other metric block exist.

The rule these tests pin: a block that draws a *set* of compositions draws
only the wholes nothing earlier on the page has drawn, and stops being a
block at all when that leaves nothing.
"""
from __future__ import annotations

from types import SimpleNamespace

from common.block_shapes import share_groups
from common.contracts import MetricPoint
from common.purpose_slots import share_evidence_key
from reporting.dashboard_streamlit.blocks.base import SlotContext
from reporting.dashboard_streamlit.blocks.slot_blocks import (
    _composition_breakdown,
    _share_split,
    _undrawn_share_points,
)

FIRST = "'25년 상반기 가입자 수·점유율"
SECOND = "'25년 하반기 가입자 수·점유율"


def _slice(subject: str, value: float, whole: str, period: str) -> MetricPoint:
    return MetricPoint(
        label=f"{subject} 점유율", subject=subject, period=period, value=value,
        unit="%", share_of=whole, evidence_claim_id=f"c-{subject}-{period}",
        doc_id="d1",
    )


def _points() -> list[MetricPoint]:
    return [
        _slice("IPTV", 59.60, FIRST, "2025년 상반기"),
        _slice("SO", 33.03, FIRST, "2025년 상반기"),
        _slice("위성", 7.37, FIRST, "2025년 상반기"),
        _slice("IPTV", 59.11, SECOND, "2025년 하반기"),
        _slice("SO", 33.38, SECOND, "2025년 하반기"),
        _slice("위성", 7.51, SECOND, "2025년 하반기"),
    ]


def _context(drawn: frozenset[str]) -> SlotContext:
    synthesis = SimpleNamespace(metric_series=_points())
    return SlotContext(
        result=None, synthesis=synthesis, items=[], risks=[], opportunities=[],
        strengths=[], weaknesses=[], drawn_before=drawn,
    )


# --- the key both sides compute -----------------------------------------


def test_the_renderer_and_the_resolver_agree_on_one_key():
    """Two spellings of this rule would stop matching the first time either
    changed, and the symptom would be a silently duplicated card."""
    from common.purpose_slots import _share_keys

    assert _share_keys(share_groups(_points())) == {
        share_evidence_key(FIRST), share_evidence_key(SECOND),
    }


def test_a_whole_written_differently_is_still_the_same_whole():
    assert share_evidence_key(" '25년 상반기  가입자 수·점유율 ") == share_evidence_key(FIRST)


def test_an_absent_whole_does_not_collide_with_a_real_one():
    assert share_evidence_key(None) != share_evidence_key(FIRST)


# --- subtraction --------------------------------------------------------


def test_nothing_drawn_yet_leaves_every_composition_intact():
    assert len(share_groups(_undrawn_share_points(_context(frozenset())))) == 2


def test_a_composition_already_on_the_page_is_dropped():
    remaining = share_groups(_undrawn_share_points(_context(frozenset({share_evidence_key(SECOND)}))))

    assert [whole for whole, _ in remaining] == [FIRST]


def test_the_half_that_is_new_still_gets_drawn():
    """The failure this replaces was all-or-nothing: slot resolution can only
    accept or refuse a block, so a `share_split` holding one drawn and one
    undrawn composition drew both."""
    context = _context(frozenset({share_evidence_key(FIRST)}))

    assert _share_split(context) is not None
    assert [whole for whole, _ in share_groups(_undrawn_share_points(context))] == [SECOND]


def test_a_block_with_nothing_left_to_draw_is_not_a_block():
    drawn = frozenset({share_evidence_key(FIRST), share_evidence_key(SECOND)})

    assert _share_split(_context(drawn)) is None
    assert _composition_breakdown(_context(drawn)) is None


def test_an_unrelated_drawn_key_never_removes_a_composition():
    context = _context(frozenset({"metric:iptv_가입자_수", "timeline"}))

    assert len(share_groups(_undrawn_share_points(context))) == 2


# --- what the landscape card reports it drew -----------------------------


def test_landscape_reports_the_donut_it_actually_draws():
    """It used to report every metric label in the synthesis and no donut at
    all, so the donut looked unclaimed and every KPI looked claimed."""
    from common.purpose_slots import _landscape_keys

    trend = [
        MetricPoint(label="IPTV 가입자 수", subject="IPTV", period=period,
                    value=value, unit="명", evidence_claim_id=f"t-{period}",
                    doc_id="d1")
        for period, value in (("2023년", 20.1), ("2024년", 20.8), ("2025년", 21.5))
    ]
    synthesis = SimpleNamespace(metric_series=[*trend, *_points()])

    keys = _landscape_keys(synthesis)

    assert any("share:" in key for key in keys)
    # Its two halves are two shapes, so they carry two families - a single
    # family for the card would be a lie in one direction or the other.
    assert {key.split("|")[0] for key in keys} == {"trend", "composition"}
    # Not every label in the synthesis - only the two halves of this card.
    assert len(keys) < len({f"metric:{point.label}" for point in synthesis.metric_series})
