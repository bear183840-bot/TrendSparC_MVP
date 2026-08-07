"""Shared, purpose-agnostic HTML component helpers for the dashboard UI.

Every purpose-specific view (issue_response_view, generic_dashboard) and the
generic block renderer (renderer.py) render through these so the visual
language (cards, tables, SWOT, action lists) stays identical no matter which
blocks a given question's report ends up using. Components only ever render
values already present on the result contracts — none of them invent a
number, a comparison, or a business fact that isn't backed by evidence.
"""

from __future__ import annotations

import math
import re
from html import escape
from typing import Any

import streamlit as st

from common.content_quality_validator import (
    classify_metric_shape,
    dated_items,
    filter_shared_comparison_axis,
    group_metric_points_by_label,
    is_duplicate_statement,
    is_time_period,
    period_sort_key,
    rank_by_relevance,
    select_chartable_series,
)
from reporting.dashboard_streamlit.sk_badge import sk_badge_html

_DOC_ID = re.compile(r"\s*\[doc_id=([^\]]+)\]")


def clean_citation(value: str | None) -> str:
    return _DOC_ID.sub("", value or "").strip()


def dedupe_clean(values: list[str] | None, limit: int | None = None) -> list[str]:
    """Dedupe and strip `[doc_id=...]` markers — for display-only lists that
    never need an evidence-url lookup afterward (the marker would be gone)."""
    cleaned = [clean_citation(value) for value in (values or [])]
    unique = list(dict.fromkeys(value for value in cleaned if value))
    return unique[:limit] if limit else unique


def dedupe_raw(values: list[str] | None, limit: int | None = None) -> list[str]:
    """Dedupe while keeping `[doc_id=...]` markers intact, so callers can still
    resolve an evidence url before cleaning the string for display."""
    unique = list(dict.fromkeys(value for value in (values or []) if value))
    return unique[:limit] if limit else unique


def _merged_report_field(report: Any, field_name: str) -> list[str]:
    if report is None or report.generation_mode != "openai":
        return []
    return [value for section in report.sections for value in getattr(section, field_name, [])]


def prefer_audience_content(report: Any, field_name: str, synthesis_values: list[str], limit: int | None = None) -> list[str]:
    """Prefer a `GeneratedReport`'s audience-tailored narrative text over the
    raw, audience-agnostic synthesis list it was built from - only when an
    LLM pass actually wrote it (`generation_mode == "openai"`); a rule-based
    report's fields are copied straight from synthesis anyway (see
    `_fallback_report`), so there's nothing to prefer in that case and this
    silently falls through to `synthesis_values` unchanged. Aggregates
    `field_name` across every section (a report has several, each written
    independently) since callers want one flat list. Every item here already
    passed `_repair_section()`'s citation check, so preferring it introduces
    no fabrication risk - it's the same traceability guarantee synthesis has.
    """
    tailored = dedupe_clean(_merged_report_field(report, field_name), limit)
    return tailored or dedupe_clean(synthesis_values, limit)


def prefer_audience_content_raw(report: Any, field_name: str, synthesis_values: list[str], limit: int | None = None) -> list[str]:
    """Same as `prefer_audience_content`, but keeps `[doc_id=...]` markers
    intact (via `dedupe_raw`) for fields a caller still needs to resolve an
    evidence URL from, like `actions`."""
    tailored = dedupe_raw(_merged_report_field(report, field_name), limit)
    return tailored or dedupe_raw(synthesis_values, limit)


def source_lookup(result: Any) -> dict[str, Any]:
    return {source.name: source for source in (result.source_plan.planned_sources if result.source_plan else [])}


def doc_lookup(result: Any) -> dict[str, Any]:
    return {analysis.doc_id: analysis for analysis in (result.document_analyses or [])}


def evidence_url(value: str, result: Any) -> str | None:
    match = _DOC_ID.search(value or "")
    if not match:
        return None
    analysis = doc_lookup(result).get(match.group(1))
    if analysis is not None and analysis.source_url:
        return analysis.source_url
    source = source_lookup(result).get(analysis.source_id) if analysis else None
    return source.url if source else None


def render_page_header(question: str, sector: str, audience: str, purpose: str) -> None:
    st.markdown(
        '<div class="ts-header-row">'
        f'<div class="ts-top-question"><span class="search">⌕</span>{escape(question)}</div>'
        f"{sk_badge_html()}"
        "</div>"
        f'<div class="ts-context-line"><span><small>Sector</small>{escape(sector)}</span>'
        f'<span><small>Audience</small>{escape(audience)}</span>'
        f'<span><small>Purpose</small>{escape(purpose)}</span></div>',
        unsafe_allow_html=True,
    )


def render_executive_summary(summary: str, risk_count: int, opportunity_count: int) -> None:
    """Executive Summary card with a side stat column.

    Deliberately shows the *actual count* of validated risk/opportunity
    statements rather than a Low/Medium/High severity word — a count is a
    real, evidence-backed number; a synthesized severity label would not be
    (see tests/test_issue_response_view.py's fabrication guard test).
    """
    st.markdown(
        '<div class="ts-summary-grid">'
        '<section class="ts-summary"><h2>Executive Summary</h2>'
        f'<p>{escape(summary or "분석 가능한 근거가 부족합니다.")}</p></section>'
        '<aside class="ts-stat-col">'
        f'<div class="ts-stat risk"><small>Risk Signals</small><b>{risk_count}건</b></div>'
        f'<div class="ts-stat opportunity"><small>Opportunity Signals</small><b>{opportunity_count}건</b></div>'
        "</aside></div>",
        unsafe_allow_html=True,
    )


def render_card(title: str, body_html: str, css_class: str = "") -> str:
    classes = f"ts-card {css_class}".strip()
    return f"<section class=\"{classes}\"><h3>{escape(title)}</h3>{body_html}</section>"


def render_section_rail(label: str) -> None:
    """Stage label (the reference design's PROBLEM / CAUSE / IMPROVEMENT
    spine) marking which stage of the argument the cards that follow belong
    to. Purely a visual grouping cue - it labels blocks that are already
    being rendered, and never adds or implies content of its own, so a stage
    with no evidence simply isn't drawn."""
    st.markdown(
        f'<div class="ts-rail-strip"><span>{escape(label)}</span></div>',
        unsafe_allow_html=True,
    )


# Which stage of the argument each planned section belongs to. Keyed on
# section id (never on sector or audience name), so the grouping follows
# whatever report_planner actually produced for this question - both the
# issue_response shape (issue/impact/response_actions) and the root_cause
# shape (problem/root_cause/improvement_plan) map onto the same three
# stages, and a purpose whose sections don't map to any stage simply
# renders no bands.
_SECTION_STAGES: tuple[tuple[str, frozenset[str]], ...] = (
    ("PROBLEM", frozenset({"issue", "problem", "risk", "current_situation", "market_status"})),
    ("CAUSE", frozenset({"root_cause", "impact", "key_metrics", "risk_and_opportunity"})),
    (
        "IMPROVEMENT",
        frozenset({
            "response_actions", "improvement_plan", "recommended_action",
            "strategic_recommendation", "decision_required", "opportunity",
            "near_term_outlook", "investment_signal", "trend",
        }),
    ),
)


def stages_for_sections(section_ids: list[str] | None) -> list[str]:
    """Stage labels this report actually has sections for, in argument order.
    Empty when the plan is missing or none of its sections map to a stage -
    the caller then renders its cards without bands rather than inventing a
    stage the report doesn't contain."""
    present = set(section_ids or [])
    return [label for label, members in _SECTION_STAGES if present & members]


def render_omitted_sections(omitted: dict[str, str] | None) -> None:
    """Sections report_planner deliberately dropped for lack of evidence,
    shown with the reason it recorded. Surfacing this is the honest
    counterpart to the stage bands: the reader sees not just what the report
    covers but what it couldn't, instead of the gap being invisible."""
    if not omitted:
        return
    items = "".join(
        f"<li><b>{escape(_SECTION_TITLES.get(section_id, section_id))}</b>{escape(reason)}</li>"
        for section_id, reason in omitted.items()
    )
    st.markdown(
        '<div class="ts-omitted"><small>근거가 없어 리포트에서 제외한 항목</small>'
        f"<ul>{items}</ul></div>",
        unsafe_allow_html=True,
    )


# Human-readable names for section ids, for the omitted-sections notice.
_SECTION_TITLES = {
    "key_metrics": "핵심 지표",
    "timeline": "타임라인",
    "market_status": "시장 현황",
    "risk_and_opportunity": "리스크·기회",
    "recommended_action": "권고 과제",
}


def render_row_list(rows: list[tuple[str, str, str]], empty_message: str) -> str:
    """`rows` = (source, point, confidence) triplets already backed by a document analysis."""
    if not rows:
        return f'<p class="ts-empty">{escape(empty_message)}</p>'
    dots = {"high": "high", "medium": "medium", "low": "low"}
    parts = []
    for source, point, confidence in rows:
        dot = dots.get((confidence or "").lower())
        badge = f'<span class="ts-dot {dot}"></span>' if dot else ""
        parts.append(
            f'<div class="ts-source-row"><b>{escape(source)}</b><span>{escape(point)}</span>'
            f"<span>{badge}{escape(confidence)}</span></div>"
        )
    return "".join(parts)


def render_comparison_table(headers: list[str], rows: list[tuple[str, list[tuple[str, str | None]]]]) -> str:
    """Real HTML table for structured, evidence-backed comparisons.

    `rows` = [(row_label, [(display_value, level), ...]), ...] — one
    (display_value, level) pair per header column, in the same order as
    `headers`. `level` is one of "low"/"medium"/"high" when the source
    document stated an explicit ranking, or None when it only stated a raw
    value (e.g. a price) with no comparative judgement — in that case the
    cell shows the raw value with no colored dot rather than guessing a
    level. Only call this with data that actually came from evidence — when
    no structured comparison exists, use `render_row_list` instead rather
    than inventing table cells.
    """
    if not rows:
        return '<p class="ts-empty">비교 가능한 근거가 없습니다.</p>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = ""
    for label, cells_data in rows:
        cells = "".join(
            (
                f'<td><span class="ts-dot {escape(level.lower())}"></span>{escape(display_value)}</td>'
                if level
                else f"<td>{escape(display_value)}</td>"
            )
            for display_value, level in cells_data
        )
        body += f"<tr><td>{escape(label)}</td>{cells}</tr>"
    return (
        '<div class="ts-table-wrap"><table class="ts-table"><thead><tr><th></th>'
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def comparison_points_to_table(comparison_points: list[Any]) -> tuple[list[str], list[tuple[str, list[tuple[str, str | None]]]]]:
    """Reshape a flat ComparisonPoint list into (headers, rows) for `render_comparison_table`.

    Groups by entity (row) x criterion (column). A cell is left blank when a
    given entity has no evidence for a given criterion — never filled in.
    Only called with `filter_shared_comparison_axis()`'s output (see
    `has_comparison`) so every criterion here is one at least 2 entities
    actually share - a lone unrelated metric (e.g. "국내 월간 이용자 수"
    stated for only one entity) never makes it in as a mostly-blank column.
    """
    comparison_points = filter_shared_comparison_axis(comparison_points)
    entities = list(dict.fromkeys(point.entity for point in comparison_points))
    criteria = list(dict.fromkeys(point.criterion for point in comparison_points))
    by_entity_criterion = {(point.entity, point.criterion): point for point in comparison_points}
    rows = [
        (
            entity,
            [
                ((by_entity_criterion[(entity, criterion)].value, by_entity_criterion[(entity, criterion)].level)
                 if (entity, criterion) in by_entity_criterion else ("-", None))
                for criterion in criteria
            ],
        )
        for entity in entities
    ]
    return criteria, rows


def has_timeseries(metric_points: list[Any]) -> bool:
    """True only when at least one label is genuinely line-chart-shaped (3+
    distinct periods - see `classify_metric_shape`). A label with exactly 2
    periods is a before/after comparison, not a trend - see
    `has_bar_metrics`/`render_metric_bar` for that case instead of forcing
    two dots into a line chart."""
    by_label = group_metric_points_by_label(metric_points)
    return any(classify_metric_shape(points) == "line" for points in by_label.values())


def has_bar_metrics(metric_points: list[Any]) -> bool:
    """True when at least one label has exactly 2 distinct periods - a real
    before/after change worth a bar comparison (`render_metric_bar`), even
    though it's not enough points for a line chart."""
    by_label = group_metric_points_by_label(metric_points)
    return any(classify_metric_shape(points) == "bar" for points in by_label.values())


def bar_metric_groups(metric_points: list[Any]) -> list[list[Any]]:
    """Every label worth drawing as bars, one list per label.

    Covers both bar shapes: a before/after pair over two points in time, and
    one metric measured across several *subjects* ("SK브로드밴드" / "KT" /
    "LG유플러스"), which is an item comparison. The second used to be
    misclassified as a line and drawn as a trend running between companies;
    excluding it outright would have been the opposite mistake, dropping a
    real three-way comparison to prose bullets.
    """
    by_label = group_metric_points_by_label(metric_points)
    return [
        points for points in by_label.values()
        if classify_metric_shape(points) in {"bar", "comparison"}
    ]


def has_comparison(comparison_points: list[Any]) -> bool:
    """True only when 2+ entities share a real common criterion - two
    entities that each only state a *different* metric (no overlap) don't
    make a comparable table, just two unrelated facts side by side."""
    shared = filter_shared_comparison_axis(comparison_points)
    return len({point.entity for point in shared}) >= 2


def render_metric_chart(metric_points: list[Any], title: str = "Market Trend") -> None:
    """Native Streamlit line chart for real, evidence-backed *time series*
    metrics only (3+ distinct periods for a label - see
    `classify_metric_shape`). Only call this when `select_chartable_series()`
    on the same list returns non-empty. Groups by `label` so multiple series
    sharing the same timeline AND the same unit (e.g. IPTV vs. OTT usage,
    both in the same quarters, both in 시간) plot as separate lines - a label
    with a different unit (e.g. 매출 in 억원 next to 가입자 수 in 명) or a
    disjoint timeline is dropped from this chart by `select_chartable_series`
    rather than drawn on an axis it has nothing in common with; overlaying
    incompatible series just looks broken (a flat line crushed by a
    different scale), not like a trend. Dropped labels aren't lost data -
    they still appear in the KPI row or `render_metric_bar`, just not
    squeezed into this shared axis. The x-axis always reads oldest-to-newest
    (chronological, not extraction/insertion order). X-axis labels are the
    evidence-stated `period` text as-is (no invented dates). Height is
    capped so one chart can't push the rest of the dashboard off-screen.
    """
    chartable_points = select_chartable_series(metric_points)
    if not chartable_points:
        return
    st.markdown(_metric_chart_svg(chartable_points, title), unsafe_allow_html=True)


# Chart geometry, in the SVG's own viewBox units (it scales to the container).
_CHART_W, _CHART_H = 356, 150
_CHART_LEFT, _CHART_RIGHT = 46, 344      # plot area, leaving a gutter for y labels
_CHART_TOP, _CHART_BOTTOM = 12, 112      # plot area vertically
_CHART_XLABEL_Y = 136
_CHART_GRID_LINES = 4


def _chart_y_ticks(low: float, high: float) -> list[float]:
    """`_CHART_GRID_LINES` evenly spaced values spanning the real data range,
    top-down. A flat series (every value identical) still gets a readable
    axis rather than a divide-by-zero."""
    if high <= low:
        pad = abs(high) * 0.1 or 1.0
        low, high = high - pad, high + pad
    step = (high - low) / (_CHART_GRID_LINES - 1)
    return [high - step * index for index in range(_CHART_GRID_LINES)]


def _metric_chart_svg(points: list[Any], title: str) -> str:
    """Reference-style area+line chart drawn directly from evidence-stated
    MetricPoints - one polyline per label, x positions in chronological
    `period` order, y scaled to the real min/max of the plotted values.
    Axis labels are the evidence's own period text and real numbers; nothing
    is interpolated or extrapolated, so a gap in the evidence stays a gap.
    """
    by_label = group_metric_points_by_label(points)
    periods = sorted({point.period for point in points}, key=period_sort_key)
    values = [point.value for point in points]
    low, high = min(values), max(values)
    ticks = _chart_y_ticks(low, high)
    tick_low, tick_high = ticks[-1], ticks[0]
    span = (tick_high - tick_low) or 1.0
    unit = next((point.unit for point in points if point.unit), "")

    def x_of(period: str) -> float:
        if len(periods) == 1:
            return (_CHART_LEFT + _CHART_RIGHT) / 2
        step = (_CHART_RIGHT - _CHART_LEFT) / (len(periods) - 1)
        return _CHART_LEFT + step * periods.index(period)

    def y_of(value: float) -> float:
        ratio = (value - tick_low) / span
        return _CHART_BOTTOM - ratio * (_CHART_BOTTOM - _CHART_TOP)

    grid = "".join(
        f'M{_CHART_LEFT - 12} {y_of(tick):.1f}h{_CHART_RIGHT - _CHART_LEFT + 12}' for tick in ticks
    )
    y_labels = "".join(
        f'<text x="2" y="{y_of(tick) + 3:.1f}">{escape(_format_number(tick))}</text>' for tick in ticks
    )
    x_labels = "".join(
        f'<text x="{x_of(period):.1f}" y="{_CHART_XLABEL_Y}">{escape(period)}</text>' for period in periods
    )

    series_markup = ""
    for index, (label, label_points) in enumerate(by_label.items()):
        ordered = sorted(label_points, key=lambda point: period_sort_key(point.period))
        coords = [(x_of(point.period), y_of(point.value)) for point in ordered]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        dots = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4.4 if position == len(coords) - 1 else 3.4}"></circle>'
            for position, (x, y) in enumerate(coords)
        )
        # Only the first series gets the filled area; stacking translucent
        # fills would misread as a stacked chart rather than two independent
        # series sharing one axis.
        area = ""
        if index == 0 and len(coords) > 1:
            area_path = (
                f'M{coords[0][0]:.1f} {coords[0][1]:.1f}'
                + "".join(f'L{x:.1f} {y:.1f}' for x, y in coords[1:])
                + f'L{coords[-1][0]:.1f} {_CHART_BOTTOM}L{coords[0][0]:.1f} {_CHART_BOTTOM}Z'
            )
            area = f'<path d="{area_path}" fill="url(#tsChartFill)"></path>'
        stroke = "var(--ts-accent)" if index == 0 else "var(--ts-teal)"
        series_markup += (
            f'{area}<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="2.2" '
            f'stroke-linejoin="round" stroke-linecap="round"></polyline>'
            f'<g fill="var(--ts-panel)" stroke="{stroke}" stroke-width="2">{dots}</g>'
        )

    legend = "".join(
        f'<span class="ts-chart-key"><i style="background:{"var(--ts-accent)" if index == 0 else "var(--ts-teal)"}"></i>'
        f'{escape(label)}</span>'
        for index, label in enumerate(by_label)
    )
    unit_note = f'<span class="ts-chart-unit">단위: {escape(unit)}</span>' if unit else ""
    return (
        f'<div class="ts-chart"><div class="ts-chart-head"><b>{escape(title)}</b>{unit_note}</div>'
        f'<div class="ts-chart-legend">{legend}</div>'
        f'<svg viewBox="0 0 {_CHART_W} {_CHART_H}" preserveAspectRatio="none" class="ts-chart-svg">'
        '<defs><linearGradient id="tsChartFill" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="var(--ts-accent)" stop-opacity=".22"></stop>'
        '<stop offset="1" stop-color="var(--ts-accent)" stop-opacity="0"></stop></linearGradient></defs>'
        f'<g stroke="var(--ts-soft)" stroke-width="1"><path d="{grid}"></path></g>'
        f'<g class="ts-chart-axis" text-anchor="start">{y_labels}</g>'
        f'{series_markup}'
        f'<g class="ts-chart-axis" text-anchor="middle">{x_labels}</g>'
        "</svg></div>"
    )


def render_metric_bar(points_for_one_label: list[Any]) -> None:
    """Bars for one label, either before/after over time or across subjects.

    Two points in time don't make a trend worth a line chart, but the real,
    evidence-stated change between them is worth a two-bar comparison. The
    same markup serves one metric measured across several subjects
    ("SK브로드밴드" / "KT" / "LG유플러스"), which is an item comparison.

    Only ever called with one label's points at a time (the caller loops per
    label), since two different labels are two different units/scales and
    don't belong on the same bar pair.
    """
    if len(points_for_one_label) < 2:
        return
    # Time bars read chronologically; subject bars have no inherent order, so
    # they read largest-first, which is what a comparison is asking.
    if all(is_time_period(point.period) for point in points_for_one_label):
        ordered = sorted(points_for_one_label, key=lambda p: period_sort_key(p.period))
    else:
        ordered = sorted(points_for_one_label, key=lambda p: abs(p.value), reverse=True)
    label = ordered[0].label
    unit = ordered[0].unit or ""
    max_value = max(abs(p.value) for p in ordered) or 1
    rows = "".join(
        f'<div class="ts-bar-compare-row"><span class="period">{escape(p.period)}</span>'
        f'<div class="ts-bar-compare-track"><div class="ts-bar-compare-fill" '
        f'style="--pct:{abs(p.value) / max_value * 100:.1f}%"></div></div>'
        f'<span class="value">{escape(_format_number(p.value))}{escape(unit)}</span></div>'
        for p in ordered
    )
    st.markdown(
        f'<div class="ts-bar-compare"><b>{escape(label)}</b>{rows}</div>',
        unsafe_allow_html=True,
    )


def render_swot(strengths: list[str], weaknesses: list[str], opportunities: list[str], threats: list[str]) -> str:
    def cell(label: str, values: list[str], empty: str, tone: str) -> str:
        body = "".join(f"<p>• {escape(value)}</p>" for value in values) or f'<p class="ts-empty">{escape(empty)}</p>'
        return f'<div class="ts-swot-cell {tone}"><h4>{escape(label)}</h4>{body}</div>'

    return (
        '<div class="ts-swot">'
        + cell("Strength", strengths, "관련 데이터 수집 필요 (강점 근거 미확인)", "positive")
        + cell("Weakness", weaknesses, "관련 데이터 수집 필요 (약점 근거 미확인)", "negative")
        + cell("Opportunity", opportunities, "관련 데이터 수집 필요 (기회 근거 미확인)", "positive")
        + cell("Threat", threats, "관련 데이터 수집 필요 (위협 근거 미확인)", "negative")
        + "</div>"
    )


def render_action_list(rows: list[tuple[str, str, str | None]]) -> None:
    """`rows` = (title, expected_impact, evidence_url) already resolved by the caller.

    `expected_impact` must be an impact this specific action is actually
    linked to; pass "" when no such link exists. It used to be filled by
    pairing the Nth action with the Nth business_impact, which looked like a
    finding but was just two independent lists lined up by position - so an
    unlinked action now shows an empty cell instead of a borrowed one.

    The old rank-derived bar (92%/76%/60%… computed purely from row order)
    is gone for the same reason: it rendered as a measured quantity while
    carrying no information beyond "this row is above that row", which the
    row numbers already say.
    """
    # No actions means no Recommended Actions block at all. A card whose only
    # content is "근거에 연결된 권고 과제가 없습니다" occupies the space that
    # the sections which do have evidence could use, and says nothing the
    # omitted-sections note below the report doesn't already say.
    if not rows:
        return
    body_parts = []
    for index, (title, expected_impact, url) in enumerate(rows, 1):
        link = (
            f'<a class="ts-evidence-link" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
            if url
            else "<span></span>"
        )
        impact_cell = (
            f'<span class="impact" title="{escape(expected_impact)}">{escape(expected_impact)}</span>'
            if expected_impact
            else '<span class="impact ts-empty">연결된 기대효과 없음</span>'
        )
        body_parts.append(
            f'<div class="ts-action-row"><span class="num">{index:02d}</span>'
            f'<span class="action">{escape(title)}</span>'
            f"{impact_cell}{link}</div>"
        )
    st.markdown(
        '<section class="ts-actions"><h3>Recommended Actions</h3>'
        '<div class="ts-actions-head"><span></span><span></span><span>Expected Impact</span><span>Evidence</span></div>'
        + "".join(body_parts)
        + "</section>",
        unsafe_allow_html=True,
    )


def _format_number(value: float) -> str:
    """Comma-grouped, human-readable number - never scientific notation.

    Python's `:g` format switches to "1.1498e+06" past ~1e6, which is not
    how a Korean financial figure (e.g. "1,149,800백만 원") is ever written.
    """
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def render_kpi_row(metric_points: list[Any], limit: int = 4, question_terms: list[str] | None = None) -> None:
    """Key KPI badge row - up to `limit` distinct metrics as stat cards.

    When two points share the same label (e.g. two different periods of the
    same metric), shows the latest value with a delta computed by actual
    subtraction between two evidence-stated numbers - never an estimate. A
    label with only one point shows that value alone with a small "as of
    <period>" caption instead of a delta - a bare number with no time
    reference is ambiguous (as of when?), but there's nothing to subtract
    from, so no comparison is fabricated.

    `question_terms` (the question's extracted keywords/entities, when
    available) reorders labels so ones actually about the question come
    first - a metric with real evidence never disappears just because it
    scored low, it just sinks toward the back of the `limit` cutoff instead
    of a channel-ranking number crowding out the actual "가입자 수" the
    question asked about.
    """
    if not metric_points:
        return
    by_label = group_metric_points_by_label(metric_points)
    ordered_labels = rank_by_relevance(list(by_label.keys()), question_terms or [])
    cards = []
    for label in ordered_labels[:limit]:
        points = by_label[label]
        latest = points[-1]
        value_text = f"{_format_number(latest.value)}{latest.unit}"
        if len(points) >= 2:
            delta = latest.value - points[0].value
            sign = "+" if delta >= 0 else ""
            caption_text = f"{sign}{_format_number(delta)}{latest.unit} ({escape(points[0].period)}→{escape(latest.period)})"
        else:
            caption_text = f"{escape(latest.period)} 기준"
        # Label on the left, figure + its caption right-aligned as one unit -
        # the reference design's KPI row shape. The delta is deliberately left
        # in a neutral colour rather than red/green: whether a rise is good or
        # bad is metric-specific (subscribers up is good, churn up is not) and
        # nothing in the evidence tells us which this is, so colouring it would
        # be asserting a judgement the data doesn't support.
        cards.append(
            f'<div class="ts-kpi-card"><small>{escape(label)}</small>'
            f'<div class="ts-kpi-figure"><b>{escape(value_text)}</b>'
            f'<small class="ts-kpi-delta">{caption_text}</small></div></div>'
        )
    st.markdown(f'<div class="ts-kpi-row">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_source_list(result: Any) -> str:
    """Evidence & Sources panel - registered sources actually cited in this
    result's document analyses, each linking to the source's registered URL."""
    sources = source_lookup(result)
    used_ids = list(dict.fromkeys(
        analysis.source_id for analysis in (result.document_analyses or []) if analysis.source_id
    ))
    rows = []
    for source_id in used_ids:
        source = sources.get(source_id)
        label = source.name if source else source_id
        url = source.url if source else None
        link = f'<a href="{escape(url)}" target="_blank">Link ↗</a>' if url else '<span class="ts-empty">링크 없음</span>'
        rows.append(f'<li><span>{escape(label)}</span>{link}</li>')
    if not rows:
        return '<p class="ts-empty">등록된 출처가 없습니다.</p>'
    return f'<ul class="ts-source-list">{"".join(rows)}</ul>'


def render_footer_note(text: str | None) -> None:
    if not text:
        return
    st.markdown(
        f'<div class="ts-footer-note"><b>AI Monitoring Comment</b><span>{escape(text)}</span></div>',
        unsafe_allow_html=True,
    )


# --- Block types ported from the registry into the live path ---------------
#
# The block registry (reporting/dashboard_streamlit/blocks/) was never
# reachable from the live dashboard, and its chart block asked for
# `block.data["rows"]`, a field no pipeline stage has ever written. What was
# worth keeping is the *range of block types* it set out to offer. These
# functions rebuild the ones the live path was missing, each driven by a
# contract the pipeline actually populates - never by a field that is always
# empty.

_LEVEL_RADIUS_FRACTION = {"low": 0.4, "medium": 0.7, "high": 1.0}
_RADAR_PALETTE = ("var(--ts-accent)", "var(--ts-teal)", "var(--ts-orange)")
_RADAR_MIN_AXES = 3
_RADAR_MAX_ENTITIES = 3


def radar_axes(comparison_points: list[Any]) -> list[str]:
    """Criteria every compared entity has a stated `level` for. A radar with
    a missing vertex misreads as a zero, so an axis only counts when all
    plotted entities actually have a value on it."""
    leveled = [point for point in comparison_points if point.level in _LEVEL_RADIUS_FRACTION]
    entities = list(dict.fromkeys(point.entity for point in leveled))[:_RADAR_MAX_ENTITIES]
    if not entities:
        return []
    criteria_by_entity = {
        entity: {point.criterion for point in leveled if point.entity == entity}
        for entity in entities
    }
    shared = set.intersection(*criteria_by_entity.values()) if criteria_by_entity else set()
    return [
        criterion
        for criterion in dict.fromkeys(point.criterion for point in leveled)
        if criterion in shared
    ]


def has_radar(comparison_points: list[Any]) -> bool:
    return len(radar_axes(comparison_points)) >= _RADAR_MIN_AXES


def _radar_polygon(fractions: list[float], center: float, max_radius: float) -> str:
    step = 2 * math.pi / len(fractions)
    return " ".join(
        f"{center + max_radius * fraction * math.cos(-math.pi / 2 + index * step):.1f},"
        f"{center + max_radius * fraction * math.sin(-math.pi / 2 + index * step):.1f}"
        for index, fraction in enumerate(fractions)
    )


def render_radar(comparison_points: list[Any]) -> None:
    """Capability radar over ComparisonPoints that carry an explicit `level`.

    Radius comes from the document-stated low/medium/high ordinal, never from
    an invented continuous score - a point whose source didn't state a level
    is left out rather than guessed at.
    """
    axes = radar_axes(comparison_points)
    if len(axes) < _RADAR_MIN_AXES:
        return
    leveled = [point for point in comparison_points if point.level in _LEVEL_RADIUS_FRACTION]
    entities = list(dict.fromkeys(point.entity for point in leveled))[:_RADAR_MAX_ENTITIES]
    level_by_key = {(point.entity, point.criterion): point.level for point in leveled}
    center, max_radius = 120.0, 84.0

    rings = "".join(
        f'<polygon points="{_radar_polygon([fraction] * len(axes), center, max_radius)}" '
        f'fill="none" stroke="var(--ts-line)" stroke-width="1" opacity=".5"/>'
        for fraction in (0.4, 0.7, 1.0)
    )
    step = 2 * math.pi / len(axes)
    spokes = "".join(
        f'<line x1="{center}" y1="{center}" '
        f'x2="{center + max_radius * math.cos(-math.pi / 2 + i * step):.1f}" '
        f'y2="{center + max_radius * math.sin(-math.pi / 2 + i * step):.1f}" '
        f'stroke="var(--ts-line)" stroke-width="1" opacity=".5"/>'
        for i in range(len(axes))
    )
    labels = "".join(
        f'<text x="{center + (max_radius + 18) * math.cos(-math.pi / 2 + i * step):.1f}" '
        f'y="{center + (max_radius + 18) * math.sin(-math.pi / 2 + i * step):.1f}" '
        f'fill="var(--ts-muted)" font-size="9.5" text-anchor="middle" dominant-baseline="middle">'
        f"{escape(clean_citation(axis))}</text>"
        for i, axis in enumerate(axes)
    )
    shapes = ""
    for index, entity in enumerate(entities):
        colour = _RADAR_PALETTE[index % len(_RADAR_PALETTE)]
        fractions = [_LEVEL_RADIUS_FRACTION[level_by_key[(entity, axis)]] for axis in axes]
        shapes += (
            f'<polygon points="{_radar_polygon(fractions, center, max_radius)}" '
            f'fill="{colour}" fill-opacity=".16" stroke="{colour}" stroke-width="2"/>'
        )
    legend = "".join(
        f'<span class="ts-radar-legend-item">'
        f'<i style="background:{_RADAR_PALETTE[index % len(_RADAR_PALETTE)]}"></i>{escape(entity)}</span>'
        for index, entity in enumerate(entities)
    )
    st.markdown(
        f'<div class="ts-radar"><svg viewBox="0 0 240 240">{rings}{spokes}{shapes}{labels}</svg>'
        f'<div class="ts-radar-legend">{legend}</div></div>',
        unsafe_allow_html=True,
    )


def metric_comparison_groups(metric_points: list[Any]) -> list[tuple[str, list[Any]]]:
    """Periods where two or more differently-labelled metrics share a unit -
    a genuine like-for-like item comparison, as opposed to the same metric
    tracked over time (which is `bar_metric_groups`/`render_metric_chart`).
    """
    by_period: dict[str, list[Any]] = {}
    for point in metric_points:
        by_period.setdefault(point.period, []).append(point)
    groups: list[tuple[str, list[Any]]] = []
    for period, points in by_period.items():
        by_unit: dict[str, list[Any]] = {}
        for point in points:
            by_unit.setdefault(point.unit or "", []).append(point)
        for unit_points in by_unit.values():
            if len({point.label for point in unit_points}) >= 2:
                groups.append((period, unit_points))
    return groups


def has_metric_comparison(metric_points: list[Any]) -> bool:
    return bool(metric_comparison_groups(metric_points))


def render_metric_comparison(period: str, points: list[Any]) -> None:
    """Horizontal bars comparing several metrics measured in the same unit at
    the same point in time. Bar length is the real value against the largest
    in the group - not a rank-derived width."""
    if len(points) < 2:
        return
    ordered = sorted(points, key=lambda point: point.value, reverse=True)
    unit = ordered[0].unit or ""
    largest = max(abs(point.value) for point in ordered) or 1
    rows = "".join(
        f'<div class="ts-compare-row"><span class="label">{escape(point.label)}</span>'
        f'<div class="ts-compare-track"><div class="ts-compare-fill" '
        f'style="--pct:{abs(point.value) / largest * 100:.1f}%"></div></div>'
        f'<span class="value">{escape(_format_number(point.value))}{escape(unit)}</span></div>'
        for point in ordered
    )
    st.markdown(
        f'<div class="ts-compare"><b>{escape(period)}</b>{rows}</div>',
        unsafe_allow_html=True,
    )


# A full year+quarter/month label, a bare year, and an apostrophe year
# ("'24년" - standard in Korean financial copy) all pin a point in time.
_FULL_PERIOD_RE = re.compile(r"(?:20\d{2}|'\d{2})\s*년(?:\s*(?:[1-4]\s*분기|\d{1,2}\s*월))?")
_BARE_QUARTER_RE = re.compile(r"[1-4]\s*분기")


def _timeline_period(sentence: str) -> str | None:
    """The period label for a timeline row, or None if the year is unknown.

    A quarter with no year ("2분기 매출액을 1조1522억원으로 예상") is only
    usable when the sentence names a year somewhere else, in which case the
    two are combined. Otherwise there is nothing to sort it by and it is left
    out - an undated row silently placed among dated ones is worse than a
    missing row.
    """
    full = _FULL_PERIOD_RE.search(sentence or "")
    if full:
        label = re.sub(r"\s+", " ", full.group(0)).strip()
        if label.startswith("'"):
            label = "20" + label[1:]
        if _BARE_QUARTER_RE.search(label):
            return label
        quarter = _BARE_QUARTER_RE.search(sentence)
        if quarter and "월" not in label:
            return f"{label} {re.sub(r'\\s+', '', quarter.group(0))}"
        return label
    return None


def timeline_entries(evidence: list[str], metric_points: list[Any]) -> list[tuple[str, str]]:
    """(period, text) pairs in chronological order, from evidence sentences
    that actually carry a date and from metric points that state a period.
    Undated prose is left out - a numbered list of undated statements is not
    a timeline, which is all the old registry block produced."""
    entries: list[tuple[str, str]] = []
    for point in metric_points:
        # `period` is free text and is not always a time. An app-churn
        # analysis used it for the compared subject ("B tv+ 앱"), which put
        # "B tv+ 앱 — 30일 이탈률 42%" on a timeline as though it were a date.
        if is_time_period(point.period):
            entries.append((point.period, f"{point.label} {_format_number(point.value)}{point.unit or ''}"))
    for sentence in dated_items(evidence):
        period = _timeline_period(sentence)
        # A bare "2분기" with no year anywhere in the sentence can't be placed
        # on an axis, and guessing the year would be fabrication - so the
        # entry is skipped rather than shown out of order. This is why the
        # observed timeline had "3분기 '24년 …" sitting after 2026 entries.
        if period:
            entries.append((period, clean_citation(sentence)))
    deduped = list(dict.fromkeys(entries))
    # Two sentences can state the same fact in different words ("2026년 1분기
    # 영업이익 5,376억원" and "1분기 영업이익이 5376억원을 기록"). Keyed on the
    # figures they cite, so the restatement drops out.
    unique: list[tuple[str, str]] = []
    for period, text in deduped:
        if any(
            existing_period == period and is_duplicate_statement(existing_text, text)
            for existing_period, existing_text in unique
        ):
            continue
        unique.append((period, text))
    return sorted(unique, key=lambda entry: period_sort_key(entry[0]))


def has_timeline(evidence: list[str], metric_points: list[Any]) -> bool:
    return bool(timeline_entries(evidence, metric_points))


def render_timeline(evidence: list[str], metric_points: list[Any], limit: int = 6) -> None:
    entries = timeline_entries(evidence, metric_points)[:limit]
    if not entries:
        return
    steps = "".join(
        f'<div class="ts-timeline-step"><b>{escape(period)}</b>{escape(text)}</div>'
        for period, text in entries
    )
    st.markdown(f'<div class="ts-timeline">{steps}</div>', unsafe_allow_html=True)


def has_cause_map(risks: list[str], impacts: list[str], actions: list[str]) -> bool:
    return sum(1 for column in (risks, impacts, actions) if column) >= 2


def render_cause_map(risks: list[str], impacts: list[str], actions: list[str], limit: int = 3) -> None:
    """Cause -> effect -> response, laid out as three ordered columns.

    Each column is filled from its own synthesis field. No arrow is drawn
    between individual items, because nothing in the data says which cause
    produced which impact - drawing that edge would assert a link the
    evidence does not contain. The columns show the flow; the items stay
    honestly unpaired.
    """
    columns = (("원인", "cause", risks), ("영향", "impact", impacts), ("대응", "action", actions))
    cells = ""
    for label, accent, values in columns:
        items = "".join(
            f"<li>{escape(clean_citation(str(value)))}</li>" for value in values[:limit]
        ) or '<li class="ts-empty">확인된 근거 없음</li>'
        cells += (
            f'<div class="ts-cause-col {accent}"><h4>{escape(label)}</h4>'
            f"<ol>{items}</ol></div>"
        )
    st.markdown(f'<div class="ts-cause-map">{cells}</div>', unsafe_allow_html=True)
