"""The summary's corner holds a figure, and every heading comes from one table.

The corner used to hold counters - "확인된 지표 155건 / 주의 신호 3건" - in the
most prominent position on the page. A count of an internal list is not
something a reader can act on. What belongs there is the number the summary
is about, and nothing at all when no single number answers the question.

Headings used to live in three places: a slot's `title`, a hard-coded string
inside a renderer, and a heading assembled in the view.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from common.block_shapes import headline_kpi
from common.block_titles import BLOCK_TITLES, SLOT_TITLES, block_title, slot_title
from common.contracts import MetricPoint
from common.purpose_slots import PURPOSE_SLOTS
from reporting.dashboard_streamlit import components

QUESTION = "IPTV 가입자 수 현황은?"


def _point(label: str, value: float, **kwargs) -> MetricPoint:
    base = dict(label=label, subject=label.split()[0], period="'25년 하반기",
                value=value, unit="단말장치・단자",
                evidence_claim_id="pdf1:det-metric-5", doc_id="pdf1")
    base.update(kwargs)
    return MetricPoint(**base)


# --- which figure, and when none ----------------------------------------


def test_the_figure_is_the_one_the_question_asked_about():
    points = [_point("광고시장 매출", 4_500), _point("IPTV 가입자 수", 21_535_256)]

    assert headline_kpi(points, QUESTION).label == "IPTV 가입자 수"


def test_a_question_no_single_number_answers_leaves_it_empty():
    """Filling it with the largest figure lying around would assert a
    relevance nothing established."""
    points = [_point("광고시장 매출", 4_500)]

    assert headline_kpi(points, "왜 가입자가 줄었나") is None


def test_an_ungrounded_figure_is_never_the_headline():
    points = [_point("IPTV 가입자 수", 21_535_256, evidence_claim_id=None)]

    assert headline_kpi(points, QUESTION) is None


def test_a_figure_with_no_document_to_return_to_is_not_quotable():
    points = [_point("IPTV 가입자 수", 21_535_256, doc_id=None, source_url=None)]

    assert headline_kpi(points, QUESTION) is None


def test_a_grounded_but_unrelated_figure_does_not_get_promoted():
    points = [_point("광고시장 매출", 4_500)]

    assert headline_kpi(points, QUESTION) is None


def test_no_question_means_no_headline():
    assert headline_kpi([_point("IPTV 가입자 수", 1.0)], None) is None
    assert headline_kpi([_point("IPTV 가입자 수", 1.0)], "") is None


def test_a_disputed_figure_never_reaches_the_corner():
    """Two sources disagreeing is exactly the case not to headline."""
    points = [
        _point("IPTV 가입자 수", 21_535_256),
        _point("IPTV 가입자 수", 21_000_000, doc_id="pdf2"),
    ]

    assert headline_kpi(points, QUESTION) is None


# --- what reaches the page ----------------------------------------------


def _summary(**kwargs) -> str:
    captured: list[str] = []
    with patch.object(components.st, "markdown", lambda body, **_: captured.append(body)):
        components.render_executive_summary("요약", **kwargs)
    return "".join(captured)


def test_the_corner_shows_the_figure_at_display_scale():
    body = _summary(headline_point=_point("IPTV 가입자 수", 21_535_256))

    assert "2,154만" in body
    assert "21,535,256" not in body


def test_the_corner_names_the_metric_and_its_period():
    body = _summary(headline_point=_point("IPTV 가입자 수", 21_535_256))
    text = re.sub(r"<[^>]+>", " ", body)

    assert "IPTV 가입자 수" in text
    assert "하반기" in text


def test_no_figure_means_no_empty_corner():
    body = _summary(headline_point=None)

    assert "ts-headline-kpi" not in body
    assert "ts-summary-solo" in body


def test_the_counter_column_is_gone_from_the_default_render():
    assert "건</b>" not in _summary(headline_point=_point("IPTV 가입자 수", 1.0))


# --- headings -----------------------------------------------------------


def test_every_slot_in_every_skeleton_has_a_registered_heading():
    missing = {
        slot.slot_id
        for slots in PURPOSE_SLOTS.values()
        for slot in slots
        if slot.slot_id not in SLOT_TITLES
    }

    assert missing == set()


@pytest.mark.parametrize("purpose_id", sorted(PURPOSE_SLOTS))
def test_headings_are_english(purpose_id):
    for slot in PURPOSE_SLOTS[purpose_id]:
        title = slot_title(slot.slot_id)
        assert not any("가" <= char <= "힣" for char in title), (slot.slot_id, title)


def test_the_same_slot_reads_the_same_in_every_purpose():
    """`segments` appears in two skeletons and means the same thing in both."""
    titles = {
        slot.slot_id: slot_title(slot.slot_id)
        for slots in PURPOSE_SLOTS.values() for slot in slots
    }

    assert titles["segments"] == "Audience Segments"


def test_an_unregistered_slot_renders_under_its_working_name():
    """A heading nobody registered is a slot someone added, not a crash."""
    assert slot_title("brand_new_slot", "새 슬롯") == "새 슬롯"


def test_in_card_headings_come_from_the_same_table():
    assert block_title("cause_tree") == BLOCK_TITLES["cause_tree"]
    assert not any("가" <= char <= "힣" for char in block_title("driver_bars"))
