"""Radar block ("radar") - capability comparison radar chart.

New 10th block type, added purely to prove the registry is extensible
without touching registry.py or renderer.py: this file is registered by
adding one import line to `blocks/__init__.py` and one entry in
`purpose_templates.py` - nothing else changes.

Reuses the existing `ComparisonPoint` shape (no new contract field): each
axis is a `criterion`, each polygon is an `entity`, and radius comes from the
already-stated ordinal `level` (low/medium/high) mapped to a fixed fraction -
never a fabricated continuous score. Rendered as plain SVG (no charting
dependency, matching `render_metric_chart`'s minimalism), colored exclusively
through the `--ts-*` CSS custom properties from theme.py so the
orange/burgundy accent toggle applies automatically, including to this brand
new block type.
"""

from __future__ import annotations

import math
from html import escape

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.blocks import _shared
from reporting.dashboard_streamlit.blocks.base import BlockDefinition
from reporting.dashboard_streamlit.blocks.registry import register
from reporting.dashboard_streamlit.components import clean_citation

# Shared with common/block_shapes.py so the predicate that decides a radar
# is drawable and the code that draws it can never disagree on the scale.
from common.block_shapes import LEVEL_RADIUS_FRACTION as _LEVEL_RADIUS_FRACTION
_PALETTE = ("var(--ts-accent)", "var(--ts-teal)", "var(--ts-orange)")
_MIN_AXES = 3
_MAX_ENTITIES = 4


class RadarContent(BaseModel):
    """One row of `block.content["comparison_points"]` (or `block.data`) -
    the JSON-serialized shape of a `common.contracts.ComparisonPoint`."""

    model_config = ConfigDict(extra="allow")

    entity: str
    criterion: str
    value: str
    level: str | None = None


def _extract_points(data) -> list[dict]:
    if isinstance(data, dict):
        raw = data.get("comparison_points") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []
    return [point for point in raw if isinstance(point, dict) and point.get("level") in _LEVEL_RADIUS_FRACTION]


def _common_axes(points: list[dict], entities: list[str]) -> list[str]:
    by_entity: dict[str, set[str]] = {}
    for point in points:
        by_entity.setdefault(point["entity"], set()).add(point["criterion"])
    shared = set.intersection(*(by_entity[entity] for entity in entities)) if entities else set()
    ordered = list(dict.fromkeys(point["criterion"] for point in points))
    return [criterion for criterion in ordered if criterion in shared]


def _polygon_points(radii: list[float], center: float, max_radius: float) -> str:
    count = len(radii)
    coords = []
    for index, fraction in enumerate(radii):
        angle = -math.pi / 2 + index * (2 * math.pi / count)
        radius = fraction * max_radius
        coords.append(f"{center + radius * math.cos(angle):.1f},{center + radius * math.sin(angle):.1f}")
    return " ".join(coords)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    points = _extract_points(data)
    entities = list(dict.fromkeys(point["entity"] for point in points))[:_MAX_ENTITIES]
    axes = _common_axes(points, entities)

    if len(axes) < _MIN_AXES or len(entities) < 1:
        st.caption("레이더 차트를 그리기에 충분한 공통 비교 항목(등급 포함)이 없습니다.")
        return

    by_entity_criterion = {(point["entity"], point["criterion"]): point["level"] for point in points}
    center, max_radius = 120, 88

    grid_rings = "".join(
        f'<polygon points="{_polygon_points([fraction] * len(axes), center, max_radius)}" '
        f'fill="none" stroke="var(--ts-line)" stroke-width="1"/>'
        for fraction in (0.4, 0.7, 1.0)
    )
    axis_lines = "".join(
        f'<line x1="{center}" y1="{center}" '
        f'x2="{center + max_radius * math.cos(-math.pi / 2 + i * (2 * math.pi / len(axes))):.1f}" '
        f'y2="{center + max_radius * math.sin(-math.pi / 2 + i * (2 * math.pi / len(axes))):.1f}" '
        f'stroke="var(--ts-line)" stroke-width="1"/>'
        for i in range(len(axes))
    )
    axis_labels = "".join(
        f'<text x="{center + (max_radius + 16) * math.cos(-math.pi / 2 + i * (2 * math.pi / len(axes))):.1f}" '
        f'y="{center + (max_radius + 16) * math.sin(-math.pi / 2 + i * (2 * math.pi / len(axes))):.1f}" '
        f'fill="var(--ts-muted)" font-size="10" text-anchor="middle" dominant-baseline="middle">'
        f"{escape(clean_citation(axis))}</text>"
        for i, axis in enumerate(axes)
    )

    polygons = []
    legend_items = []
    for series_index, entity in enumerate(entities):
        color = _PALETTE[series_index % len(_PALETTE)]
        radii = [_LEVEL_RADIUS_FRACTION[by_entity_criterion[(entity, axis)]] for axis in axes]
        polygons.append(
            f'<polygon points="{_polygon_points(radii, center, max_radius)}" '
            f'fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="2"/>'
        )
        legend_items.append(
            f'<span class="ts-radar-legend-item"><i style="background:{color}"></i>{escape(clean_citation(entity))}</span>'
        )

    svg = (
        '<svg viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg">'
        f"{grid_rings}{axis_lines}{''.join(polygons)}{axis_labels}</svg>"
    )
    st.markdown(
        f'<div class="ts-radar">{svg}<div class="ts-radar-legend">{"".join(legend_items)}</div></div>',
        unsafe_allow_html=True,
    )


register(
    BlockDefinition(
        block_type="radar",
        schema=RadarContent,
        render=render,
        description="ComparisonPoint의 등급(level)을 축별 방사형 차트로 비교하는 역량 비교 블록.",
    )
)
