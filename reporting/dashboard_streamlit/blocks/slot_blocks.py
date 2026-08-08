"""Live dashboard renderers, registered against the same block registry.

This file is the swap point for the design block library. Every block the
live dashboard can draw is one entry here, mapping a `block_type` — the same
id `purpose_slots.py` chooses between and `DESIGN_LIBRARY_BLOCKS` maps to a
design component — onto the function that draws it. Replacing a block with
its design-library counterpart is editing one entry.

It exists because the two rendering paths had drifted apart: `blocks/*.py`
held a registry of fifteen block types that the live app never imported, and
`generic_dashboard.py` held a parallel if-chain that the live app used. The
same block type could be drawn two different ways depending on which branch
ran, and adding a block meant remembering both. The registry is now the one
table; `generic_dashboard` looks blocks up in it.

The two entry points stay distinct on purpose. `render` (in the sibling
modules) draws a `DashboardBlock` the layout generator trimmed;
`slot_render` here draws a slot resolved against the full synthesis, which
is what the live dashboard has. Merging them would mean giving one of the
two paths data it was deliberately not given.
"""

from __future__ import annotations

from typing import Any

import streamlit as st
from pydantic import BaseModel

from reporting.dashboard_streamlit.blocks.base import BlockDefinition, SlotContext
from reporting.dashboard_streamlit.blocks.registry import register
from common.block_shapes import (
    has_competitor_panels,
    has_grouped_bars,
    has_landscape,
    has_status_levels,
)
from reporting.dashboard_streamlit.components import (
    action_impact_lookup,
    clean_citation,
    comparison_points_to_table,
    dedupe_clean,
    dedupe_raw,
    evidence_url,
    item_bar_groups,
    metric_comparison_groups,
    reference_year,
    render_action_list,
    render_cause_map,
    render_competitor_panels,
    render_cause_tree,
    render_comparison_table,
    render_factor_list,
    render_grouped_bars,
    render_importance_bars,
    render_kpi_row,
    render_landscape,
    render_metric_bar,
    render_metric_chart,
    render_metric_comparison,
    render_radar,
    render_recurring_terms,
    render_share_split,
    render_status_bar,
    render_swot,
    render_timeline,
    time_bar_groups,
)


class _SynthesisContent(BaseModel):
    """These blocks read the synthesis, not a block payload — the schema
    exists only so every registry entry has one."""


def _chart(context: SlotContext):
    synthesis = context.synthesis
    return lambda: render_metric_chart(
        synthesis.metric_series, title="확인된 수치 추이",
        grounded_claims=synthesis.grounded_claims,
    )


def _bars(groups_of):
    def build(context: SlotContext):
        synthesis = context.synthesis
        groups = groups_of(synthesis.metric_series)
        if not groups:
            return None
        return lambda: [render_metric_bar(group, synthesis.grounded_claims) for group in groups]
    return build


def _competitor_panels(context: SlotContext):
    synthesis = context.synthesis
    if not has_competitor_panels(synthesis.comparison_points, synthesis.metric_series):
        return None
    return lambda: render_competitor_panels(synthesis.comparison_points, synthesis.metric_series)


def _landscape(context: SlotContext):
    synthesis = context.synthesis
    if not has_landscape(synthesis.metric_series):
        return None
    return lambda: render_landscape(synthesis.metric_series, synthesis.grounded_claims)


def _grouped_bars(context: SlotContext):
    points = context.synthesis.metric_series
    return (lambda: render_grouped_bars(points)) if has_grouped_bars(points) else None


def _status_bar(context: SlotContext):
    points = context.synthesis.comparison_points
    return (lambda: render_status_bar(points)) if has_status_levels(points) else None


def _metric_comparison(context: SlotContext):
    groups = metric_comparison_groups(context.synthesis.metric_series)
    if not groups:
        return None
    return lambda: [render_metric_comparison(period, points) for period, points in groups]


def _kpi(context: SlotContext):
    points = context.synthesis.metric_series
    return (lambda: render_kpi_row(points)) if points else None


def _timeline(context: SlotContext):
    synthesis = context.synthesis
    return lambda: render_timeline(
        synthesis.evidence, synthesis.metric_series, reference_year(synthesis),
        as_of_date=getattr(synthesis, "as_of_date", None),
    )


def _table(context: SlotContext):
    headers, rows = comparison_points_to_table(context.synthesis.comparison_points)
    if not rows:
        return None
    return lambda: st.markdown(render_comparison_table(headers, rows), unsafe_allow_html=True)


def _radar(context: SlotContext):
    return lambda: render_radar(context.synthesis.comparison_points)


def _matrix(context: SlotContext):
    # render_swot returns "" when fewer than two quadrants have evidence -
    # a one-cell "matrix" is not a matrix.
    markup = render_swot(
        strengths=context.strengths, weaknesses=context.weaknesses,
        opportunities=context.opportunities, threats=context.risks,
    )
    return (lambda: st.markdown(markup, unsafe_allow_html=True)) if markup else None


def _share_split(context: SlotContext):
    return lambda: render_share_split(context.synthesis.metric_series)


def _factor_list(context: SlotContext):
    # Keep the complete grounded set.  Source/analyzer/synthesis all preserve
    # these factors, so imposing a new display-layer cap here would silently
    # discard information precisely while building the final block.
    rows = [(value, evidence_url(value, context.result)) for value in context.items]
    return (lambda: render_factor_list(rows)) if rows else None


def _recurring_terms(context: SlotContext):
    return lambda: render_recurring_terms(context.synthesis.grounded_claims)


def _cause_tree(context: SlotContext):
    return lambda: render_cause_tree(context.synthesis.grounded_claims)


def _driver_bars(context: SlotContext):
    return lambda: render_importance_bars(context.synthesis.grounded_claims)


def _cause_map(context: SlotContext):
    synthesis = context.synthesis
    return lambda: render_cause_map(
        context.risks,
        dedupe_clean(synthesis.business_impacts, 3),
        dedupe_clean(synthesis.recommended_actions, 3),
    )


def _action_list(context: SlotContext):
    actions = dedupe_raw(context.synthesis.recommended_actions, 4)
    # Expected Impact is filled only where a source actually stated what the
    # action would achieve; the rest stay empty rather than borrowing a
    # neighbouring finding.
    impacts = action_impact_lookup(getattr(context.result, "generated_report", None))
    rows = [
        (clean_citation(action), impacts.get(clean_citation(action)), evidence_url(action, context.result))
        for action in actions
    ]
    return (lambda: render_action_list(rows)) if rows else None


_LIVE_BLOCKS: tuple[tuple[str, Any, str], ...] = (
    ("landscape", _landscape, "추세선과 구성비 도넛을 한 카드에 나란히."),
    ("chart", _chart, "시점이 3개 이상인 지표의 추이선."),
    ("bar", _bars(time_bar_groups), "두 시점 사이의 변화를 막대 두 개로."),
    ("item_bar", _bars(item_bar_groups), "항목 간 순위 비교 막대."),
    ("grouped_bar", _grouped_bars, "한 지표를 여러 주체 × 여러 항목으로 비교하는 묶음 막대."),
    ("status_bar", _status_bar, "근거가 등급을 매긴 항목들의 정성 상태 한 줄."),
    ("metric_comparison", _metric_comparison, "같은 시점·같은 단위 지표들의 항목 비교."),
    ("kpi_grid", _kpi, "확인된 수치 카드 묶음."),
    ("kpi_single", _kpi, "확인된 수치 카드 하나."),
    ("timeline", _timeline, "날짜가 있는 근거를 순서대로, 진행 상태와 함께."),
    ("competitor_panels", _competitor_panels, "경쟁사별 등급·수치·구성비를 한 패널로."),
    ("table", _table, "공통 기준을 가진 주체 간 정성 비교표."),
    ("radar", _radar, "등급이 매겨진 기준들의 레이더."),
    ("matrix", _matrix, "SWOT 사분면(2개 이상 채워졌을 때만)."),
    ("share_split", _share_split, "한 전체의 구성비 도넛."),
    ("factor_list", _factor_list, "요인·페인포인트 목록 전체."),
    ("recurring_terms", _recurring_terms, "여러 출처가 공통으로 쓴 표현."),
    ("cause_tree", _cause_tree, "근거가 서술한 인과 구조."),
    ("driver_bars", _driver_bars, "AI가 매긴 상대적 영향도 막대."),
    ("cause_map", _cause_map, "원인→영향→대응 3열."),
    ("action_list", _action_list, "권고 조치와 근거가 밝힌 기대효과."),
)

for _block_type, _render, _description in _LIVE_BLOCKS:
    register(
        BlockDefinition(
            block_type=_block_type,
            schema=_SynthesisContent,
            render=None,
            description=_description,
            slot_render=_render,
        )
    )
