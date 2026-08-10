"""The axis says 2,500 만명, not 25,000,000.

A 유료방송 subscriber series put 25,000,000 at every gridline. The numbers
were right and unreadable - the reader has to count digits to tell one tick
from the next, and four ticks of eleven characters each pushed the plot into
a sliver. Only the *label* is divided; nothing rounds a stored value.
"""
from __future__ import annotations

from common.contracts import MetricPoint
from reporting.dashboard_streamlit.components import (
    _metric_chart_svg,
    axis_scale,
)


def _series(label: str, unit: str, values: list[float]) -> list[MetricPoint]:
    return [
        MetricPoint(label=label, subject=label, period=f"202{index}년", value=value,
                    unit=unit, evidence_claim_id=f"c{index}", doc_id="d1")
        for index, value in enumerate(values)
    ]


# --- which magnitude word ------------------------------------------------


def test_tens_of_millions_read_in_man():
    assert axis_scale([25_000_000, 21_500_000], "명") == (1e4, "만")


def test_billions_read_in_eok():
    assert axis_scale([3_000_000_000.0], "원") == (1e8, "억")


def test_a_scale_that_would_leave_less_than_two_digits_is_not_used():
    """0.25억 is harder to read than the number it replaced."""
    divisor, prefix = axis_scale([25_000_000], "명")

    assert divisor == 1e4 and prefix == "만"


def test_small_numbers_are_left_alone():
    assert axis_scale([12.0, 47.5], "명") == (1.0, "")


def test_a_percentage_is_never_scaled():
    """The unit is already the scale; 2.5만% is not a quantity."""
    assert axis_scale([59.1, 33.4, 7.5], "%") == (1.0, "")


def test_a_unitless_series_is_never_scaled():
    assert axis_scale([25_000_000], None) == (1.0, "")


def test_negatives_count_by_magnitude():
    assert axis_scale([-25_000_000.0, -1_000.0], "명") == (1e4, "만")


def test_an_empty_series_does_not_divide_by_anything():
    assert axis_scale([], "명") == (1.0, "")


# --- what reaches the page ----------------------------------------------


def test_the_axis_label_is_divided_and_the_note_says_by_how_much():
    markup = _metric_chart_svg(
        _series("IPTV 가입자 수", "명", [20_100_000, 20_800_000, 21_535_256]), "추세",
    )

    assert "단위: 만명" in markup
    assert "25,000,000" not in markup
    assert "20,100,000" not in markup


def test_an_unscaled_chart_still_names_its_unit():
    markup = _metric_chart_svg(_series("점유율", "%", [59.1, 58.6, 57.9]), "추세")

    assert "단위: %" in markup


def test_the_plot_keeps_its_own_aspect_ratio():
    """`preserveAspectRatio="none"` stretched a three-point line across the
    full card, so its slope stopped meaning anything."""
    markup = _metric_chart_svg(_series("가입자", "명", [1.0, 2.0, 3.0]), "추세")

    assert 'preserveAspectRatio="none"' not in markup
