"""Three or more items get three or more colours, from one ramp.

Colour used to be assigned by *axis* on the line chart and not at all on the
bars: IPTV and SO shared the left axis and were drawn as the same orange
line, and a five-slice donut used five tints of one hue, the last of which
was barely distinguishable from the empty track. Telling items apart by
position alone is what the colour is for.

The ramp is the design guide's two colours plus mixes between them, so
nothing here introduces a hue the brand does not use.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from common.contracts import ComparisonPoint, MetricPoint
from reporting.dashboard_streamlit import components
from reporting.dashboard_streamlit.components import (
    SERIES_PALETTE,
    SERIES_PALETTE_MIN_ITEMS,
    series_color,
)


def _rendered(render, *args, **kwargs) -> str:
    captured: list[str] = []
    with patch.object(components.st, "markdown", lambda body, **_: captured.append(body)):
        render(*args, **kwargs)
    return "".join(captured)


def _fills(markup: str) -> set[str]:
    return set(re.findall(r"background:([^\";]+)", markup))


# --- the ramp itself -----------------------------------------------------


def test_the_ramp_starts_at_the_two_guide_colours():
    assert SERIES_PALETTE[0] == "var(--ts-accent)"
    assert SERIES_PALETTE[1] == "var(--ts-navy)"


def test_the_third_colour_is_the_midpoint_of_the_first_two():
    """Computed, not a third hex, so it stays correct if either end moves."""
    assert SERIES_PALETTE[2] == "color-mix(in srgb,var(--ts-accent) 50%,var(--ts-navy))"


def test_every_colour_is_built_from_the_guide_variables():
    for colour in SERIES_PALETTE:
        assert "--ts-accent" in colour or "--ts-navy" in colour


def test_the_ramp_has_no_repeats():
    assert len(set(SERIES_PALETTE)) == len(SERIES_PALETTE)


@pytest.mark.parametrize("count", [1, 2])
def test_below_three_items_one_accent_is_the_whole_ramp(count):
    """Two bars are not a set to tell apart; colouring them differently
    implies a distinction the data does not make."""
    assert {series_color(index, count) for index in range(count)} == {SERIES_PALETTE[0]}


@pytest.mark.parametrize("count", [3, 4, 5, 6])
def test_at_three_and_above_every_item_differs(count):
    assert len({series_color(index, count) for index in range(count)}) == count


def test_more_items_than_colours_wraps_rather_than_failing():
    assert series_color(len(SERIES_PALETTE), 99) == SERIES_PALETTE[0]


def test_the_threshold_is_three():
    assert SERIES_PALETTE_MIN_ITEMS == 3


# --- and the blocks use it ----------------------------------------------


def _metrics(count: int, unit: str = "명") -> list[MetricPoint]:
    return [
        MetricPoint(label="가입자 수", subject=f"사업자{index}", period="2025년",
                    value=(count - index) * 1000.0, unit=unit,
                    evidence_claim_id=f"c{index}", doc_id="d1")
        for index in range(count)
    ]


def test_a_three_item_bar_block_uses_three_colours():
    markup = _rendered(components.render_metric_bar, _metrics(3), show_insight=False)

    assert len(_fills(markup)) == 3


def test_a_two_item_bar_block_stays_on_one_accent():
    markup = _rendered(components.render_metric_bar, _metrics(2), show_insight=False)

    assert _fills(markup) <= {SERIES_PALETTE[0]}


def test_a_donut_uses_the_same_ramp_as_the_chart():
    slices = [
        MetricPoint(label=f"{name} 점유율", subject=name, period="2025년 하반기",
                    value=value, unit="%", share_of="유료방송 가입자",
                    evidence_claim_id=f"c-{name}", doc_id="d1")
        for name, value in (("IPTV", 59.1), ("SO", 33.4), ("위성", 7.5))
    ]

    markup = _rendered(components.render_share_split, slices)
    used = set(re.findall(r'stroke="(var\(--ts-[a-z]+\)|color-mix[^"]*)"', markup))

    assert len(used & set(SERIES_PALETTE)) >= 3


def test_a_ranked_comparison_list_colours_its_rows():
    points = [
        # `ranking_comparison_groups` only claims criteria that name a
        # ranking - anything else belongs to a comparison table.
        ComparisonPoint(entity=f"사업자{index}", criterion="가입자 순위",
                        value=f"{30 - index}%", evidence_claim_id=f"c{index}", doc_id="d1")
        for index in range(4)
    ]

    markup = _rendered(
        components.render_ranking_list, [], comparison_points=points,
    )

    assert len(_fills(markup)) >= SERIES_PALETTE_MIN_ITEMS


def test_the_line_chart_colours_by_series_not_by_axis():
    """Two lines sharing an axis were the same orange."""
    points = [
        MetricPoint(label=label, subject=label, period=period, value=value, unit="명",
                    evidence_claim_id=f"c-{label}-{period}", doc_id="d1")
        for label, values in (
            ("IPTV", (21.4, 21.5, 21.6)),
            ("SO", (12.1, 12.0, 11.9)),
            ("위성", (2.7, 2.7, 2.6)),
        )
        for period, value in zip(("2023년", "2024년", "2025년"), values)
    ]

    markup = components._metric_chart_svg(points, "Trend")
    swatches = re.findall(r'ts-chart-key"><i style="background:([^"]+)"', markup)

    assert len(set(swatches)) == 3
