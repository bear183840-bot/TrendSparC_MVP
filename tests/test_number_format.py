"""One rule for writing a measured number, wherever it is drawn.

The scaling rule started life private to the line chart's y axis, so the
chart said 2,500 만명 while the KPI card beside it said
`21,535,256단말장치・단자` - the same series at two magnitudes, with eleven
digits run straight into a four-syllable word. These tests pin the rule and
the fact that every render point shares it.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from common.contracts import MetricPoint
from common.number_format import (
    display_value,
    format_number,
    joined_value,
    scale_for,
    scaled_number,
    unit_needs_space,
)
from reporting.dashboard_streamlit import components


# --- choosing a scale ----------------------------------------------------


@pytest.mark.parametrize("values,unit,expected", [
    ([25_000_000, 21_500_000], "명", (1e4, "만")),
    ([3_000_000_000.0], "원", (1e8, "억")),
    ([4.5e13], "원", (1e12, "조")),
    ([12.0, 47.5], "명", (1.0, "")),
])
def test_the_magnitude_word_follows_the_numbers(values, unit, expected):
    assert scale_for(values, unit) == expected


def test_a_scale_leaving_under_two_digits_is_not_used():
    """0.25억 is harder to read than the number it would replace."""
    assert scale_for([25_000_000], "명") == (1e4, "만")


@pytest.mark.parametrize("unit", ["%", "%p", "배", "점", "위", "건", "개", None, ""])
def test_units_that_are_already_a_scale_are_never_scaled(unit):
    assert scale_for([25_000_000], unit) == (1.0, "")


def test_the_peak_decides_for_the_whole_group():
    """Bars are read as lengths against each other, so one scale or none."""
    assert scale_for([25_000_000, 3.0], "명") == (1e4, "만")


def test_negatives_count_by_magnitude():
    assert scale_for([-25_000_000.0, -1_000.0], "명") == (1e4, "만")


def test_an_empty_group_divides_by_nothing():
    assert scale_for([], "명") == (1.0, "")


# --- writing one number --------------------------------------------------


def test_a_fraction_of_a_magnitude_is_dropped_once_it_is_noise():
    assert scaled_number(21_535_256, (1e4, "만")) == "2,154만"


def test_a_small_scaled_figure_keeps_its_decimal():
    assert scaled_number(125_000, (1e4, "만")) == "12.5만"


def test_an_unscaled_number_is_never_rounded():
    assert scaled_number(21_535_256, (1.0, "")) == "21,535,256"
    assert format_number(59.11) == "59.1"


def test_the_unit_comes_back_separately():
    assert display_value(21_535_256, "단말장치・단자") == ("2,154만", "단말장치・단자")


def test_a_word_unit_is_spaced_off_the_digits():
    assert joined_value(21_535_256, "명") == "2,154만 명"


def test_a_sign_unit_stays_tight():
    assert joined_value(59.11, "%") == "59.1%"


@pytest.mark.parametrize("unit,spaced", [
    ("명", True), ("단말장치・단자", True), ("억원", True),
    ("%", False), ("%p", False), ("", False), (None, False),
])
def test_which_units_need_air(unit, spaced):
    assert unit_needs_space(unit) is spaced


def test_a_shared_scale_is_honoured_rather_than_recomputed():
    """A card's headline and its delta must not land at two magnitudes."""
    scale = (1e4, "만")

    assert joined_value(21_535_256, "명", scale) == "2,154만 명"
    assert joined_value(120_735, "명", scale) == "12.1만 명"


# --- and the render points actually call it ------------------------------


def _rendered(render, *args, **kwargs) -> str:
    captured: list[str] = []
    with patch.object(components.st, "markdown", lambda body, **_: captured.append(body)):
        render(*args, **kwargs)
    return "".join(captured)


def _series(unit: str, values: list[float]) -> list[MetricPoint]:
    return [
        MetricPoint(label="가입자 수", subject="IPTV", period=f"202{index}년",
                    value=value, unit=unit, evidence_claim_id=f"c{index}", doc_id="d1")
        for index, value in enumerate(values, 1)
    ]


def test_the_kpi_card_no_longer_prints_eight_raw_digits():
    body = _rendered(components.render_kpi_row, _series("단말장치・단자", [21_414_521, 21_535_256]))

    assert "21,535,256" not in body
    assert "2,154만" in body


def test_the_kpi_card_puts_a_word_unit_in_its_own_element():
    body = _rendered(components.render_kpi_row, _series("단말장치・단자", [21_535_256]))

    assert 'class="ts-kpi-unit">단말장치・단자<' in body
    assert not re.search(r"\d단말장치", re.sub(r"<[^>]+>", "", body))


def test_the_chart_axis_and_the_kpi_card_agree():
    points = _series("명", [20_100_000, 20_800_000, 21_535_256])

    assert "만" in components._metric_chart_svg(points, "추세")
    assert "만" in _rendered(components.render_kpi_row, points)


def test_a_percentage_card_is_untouched():
    body = _rendered(components.render_kpi_row, _series("%", [59.11, 59.57]))

    assert "59.6%" in body
    assert "만" not in body
