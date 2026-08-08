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
# Data-shape predicates live in common/block_shapes.py (no Streamlit
# dependency) and are re-exported here so the renderers that use them, and
# every existing caller, keep importing from one place.
from common.section_titles import section_title
from common.block_shapes import (  # noqa: F401
    LEVEL_RADIUS_FRACTION as _LEVEL_RADIUS_FRACTION,
    RADAR_MAX_ENTITIES as _RADAR_MAX_ENTITIES,
    RADAR_MIN_AXES as _RADAR_MIN_AXES,
    _format_number,
    bar_metric_groups,
    item_bar_groups,
    time_bar_groups,
    clean_citation,
    has_bar_metrics,
    has_cause_map,
    has_comparison,
    has_metric_comparison,
    has_radar,
    has_timeline,
    has_timeseries,
    cause_tree,
    has_cause_tree,
    SHARE_SUM_TOLERANCE,
    has_recurring_terms,
    has_share_split,
    recurring_terms,
    share_groups,
    has_importance_ranking,
    importance_ranked,
    metric_axis_labels,
    metric_comparison_groups,
    metric_insight,
    radar_axes,
    timeline_entries,
    timeline_entries_with_status,
    varies_by_subject,
)
from reporting.dashboard_streamlit.sk_badge import sk_badge_html

_DOC_ID = re.compile(r"\s*\[doc_id=([^\]]+)\]")


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
    # registered_sources, not planned_sources: the AI search harness
    # (sk_broadband) searches the full registry, not just the top-N
    # select_top_sources() trims planned_sources to, so a collected
    # document's source can legitimately sit outside that trimmed list.
    # registered_sources is always a superset (select_top_sources only
    # narrows planned_sources), so this is never less complete for a sector
    # whose collector only ever searches planned_sources in the first place.
    plan = result.source_plan
    sources = (plan.registered_sources or plan.planned_sources) if plan else []
    return {source.name: source for source in sources}


def doc_lookup(result: Any) -> dict[str, Any]:
    return {analysis.doc_id: analysis for analysis in (result.document_analyses or [])}


def item_doc_id(value: str) -> str | None:
    """The doc_id a `[doc_id=...]`-tagged item string carries, or None."""
    match = _DOC_ID.search(value or "")
    return match.group(1) if match else None


def evidence_url(value: str, result: Any) -> str | None:
    doc_id = item_doc_id(value)
    if not doc_id:
        return None
    analysis = doc_lookup(result).get(doc_id)
    if analysis is not None and analysis.source_url:
        return analysis.source_url
    source = source_lookup(result).get(analysis.source_id) if analysis else None
    return source.url if source else None


def uncorroborated_doc_ids(synthesis: Any) -> set[str]:
    """doc_ids whose only backed claims are single-source.

    Matching is at the doc_id level - what a rendered item's [doc_id=...] tag
    actually carries - not at the claim-group level, since the AI's grouping
    is topic-level and coarser than one document, and its reworded `claim`
    text won't reliably match what's shown on screen. A doc_id that also
    supports at least one corroborated claim is not flagged: it does have
    cross-verified backing for something, even if not for every claim it
    contributed.
    """
    corroborated_doc_ids = {
        doc_id
        for point in (getattr(synthesis, "corroborated_points", None) or [])
        for doc_id in point.supporting_doc_ids
    }
    single_source_doc_ids = {
        doc_id
        for point in (getattr(synthesis, "uncorroborated_points", None) or [])
        for doc_id in point.supporting_doc_ids
    }
    return single_source_doc_ids - corroborated_doc_ids


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


# What the summary card's side column counts, per purpose. A 미래사업 report
# showing "RISK SIGNALS 0건" leads with the one number the question never
# asked about; PURPOSE_HEADLINE_STYLE declared this months ago and nothing
# read it, so every purpose got the issue-response treatment.
#
# Every entry is a *count of validated statements*, never a synthesized
# severity word - a count is evidence-backed, "Medium risk" would not be
# (see tests/test_issue_response_view.py's fabrication guard).
_HEADLINE_STATS: dict[str, tuple[tuple[str, str, str], ...]] = {
    # (synthesis field, label, CSS accent)
    "issue_response": (("risks", "Risk Signals", "risk"),
                       ("opportunities", "Opportunity Signals", "opportunity")),
    "root_cause": (("risks", "확인된 원인", "risk"),
                   ("recommended_actions", "개선 과제", "opportunity")),
    "future_business": (("opportunities", "기회 신호", "opportunity"),
                        ("recommended_actions", "실행 과제", "risk")),
    "current_status": (("metric_series", "확인된 지표", "opportunity"),
                       ("risks", "주의 신호", "risk")),
}
_DEFAULT_HEADLINE_STATS = _HEADLINE_STATS["issue_response"]


def headline_stats(synthesis: Any, purpose_id: str | None) -> list[tuple[str, int, str]]:
    """(label, count, accent) for the summary card's side column."""
    spec = _HEADLINE_STATS.get(purpose_id or "", _DEFAULT_HEADLINE_STATS)
    return [
        (label, len(getattr(synthesis, field, None) or []), accent)
        for field, label, accent in spec
    ]


def render_executive_summary(summary: str, stats: list[tuple[str, int, str]]) -> None:
    """Executive Summary card with a purpose-appropriate stat column."""
    cells = "".join(
        f'<div class="ts-stat {accent}"><small>{escape(label)}</small><b>{count}건</b></div>'
        for label, count, accent in stats
    )
    st.markdown(
        '<div class="ts-summary-grid">'
        '<section class="ts-summary"><h2>Executive Summary</h2>'
        f'<p>{escape(summary or "분석 가능한 근거가 부족합니다.")}</p></section>'
        f'<aside class="ts-stat-col">{cells}</aside></div>',
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
        f"<li><b>{escape(section_title(section_id))}</b>{escape(reason)}</li>"
        for section_id, reason in omitted.items()
    )
    st.markdown(
        '<div class="ts-omitted"><small>근거가 없어 리포트에서 제외한 항목</small>'
        f"<ul>{items}</ul></div>",
        unsafe_allow_html=True,
    )


# Human-readable names for section ids, for the omitted-sections notice.


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










def render_metric_insight(points: list[Any], grounded_claims: list[Any] | None) -> None:
    """The evidence sentence a plotted series was read out of, under the chart.

    Deliberately not a generated interpretation: the text is a verified claim
    already carried by the metric, so an unlinked series simply gets nothing.
    """
    insight = metric_insight(points, grounded_claims or [])
    if not insight:
        return
    text, url = insight
    link = f' <a href="{escape(url)}" target="_blank">출처</a>' if url else ""
    st.markdown(
        f'<div class="ts-metric-insight"><span class="ts-metric-insight-tag">근거</span>'
        f'{escape(clean_citation(text))}{link}</div>',
        unsafe_allow_html=True,
    )


def render_metric_chart(
    metric_points: list[Any],
    title: str = "Market Trend",
    grounded_claims: list[Any] | None = None,
) -> None:
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
    render_metric_insight(chartable_points, grounded_claims)


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
        # A projection is not history. The observed part of the series is a
        # solid line; the segment that runs into a forecast point is dashed,
        # so the reader can see where the evidence stops and the source's
        # expectation begins instead of reading one continuous measurement.
        first_forecast = next(
            (index for index, point in enumerate(ordered) if getattr(point, "is_forecast", False)),
            None,
        )
        if first_forecast is None:
            solid_coords, forecast_coords = coords, []
        else:
            solid_coords = coords[:first_forecast]
            forecast_coords = coords[max(first_forecast - 1, 0):]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in solid_coords)
        forecast_line = " ".join(f"{x:.1f},{y:.1f}" for x, y in forecast_coords)
        dots = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4.4 if position == len(coords) - 1 else 3.4}"></circle>'
            for position, (x, y) in enumerate(coords)
        )
        # Only the first series gets the filled area; stacking translucent
        # fills would misread as a stacked chart rather than two independent
        # series sharing one axis.
        area = ""
        if index == 0 and len(solid_coords) > 1:
            area_path = (
                f'M{solid_coords[0][0]:.1f} {solid_coords[0][1]:.1f}'
                + "".join(f'L{x:.1f} {y:.1f}' for x, y in solid_coords[1:])
                + f'L{solid_coords[-1][0]:.1f} {_CHART_BOTTOM}L{solid_coords[0][0]:.1f} {_CHART_BOTTOM}Z'
            )
            area = f'<path d="{area_path}" fill="url(#tsChartFill)"></path>'
        stroke = "var(--ts-accent)" if index == 0 else "var(--ts-teal)"
        forecast_markup = (
            f'<polyline points="{forecast_line}" fill="none" stroke="{stroke}" stroke-width="2.2" '
            f'stroke-dasharray="5 4" stroke-linejoin="round" stroke-linecap="round" '
            f'opacity="0.75"></polyline>'
            if len(forecast_coords) > 1 else ""
        )
        series_markup += (
            f'{area}<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="2.2" '
            f'stroke-linejoin="round" stroke-linecap="round"></polyline>{forecast_markup}'
            f'<g fill="var(--ts-panel)" stroke="{stroke}" stroke-width="2">{dots}</g>'
        )

    legend = "".join(
        f'<span class="ts-chart-key"><i style="background:{"var(--ts-accent)" if index == 0 else "var(--ts-teal)"}"></i>'
        f'{escape(label)}</span>'
        for index, label in enumerate(by_label)
    )
    unit_note = f'<span class="ts-chart-unit">단위: {escape(unit)}</span>' if unit else ""
    if any(getattr(point, "is_forecast", False) for point in points):
        legend += '<span class="ts-chart-key ts-chart-key-forecast"><i></i>전망(출처 제시)</span>'
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


def render_metric_bar(
    points_for_one_label: list[Any],
    grounded_claims: list[Any] | None = None,
) -> None:
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
    if varies_by_subject(points_for_one_label):
        ordered = sorted(points_for_one_label, key=lambda p: abs(p.value), reverse=True)
    elif all(is_time_period(point.period) for point in points_for_one_label):
        ordered = sorted(points_for_one_label, key=lambda p: period_sort_key(p.period))
    else:
        ordered = sorted(points_for_one_label, key=lambda p: abs(p.value), reverse=True)
    label = ordered[0].label
    unit = ordered[0].unit or ""
    max_value = max(abs(p.value) for p in ordered) or 1
    rows = "".join(
        f'<div class="ts-bar-compare-row"><span class="period">{escape(axis_label)}</span>'
        f'<div class="ts-bar-compare-track"><div class="ts-bar-compare-fill" '
        f'style="--pct:{abs(p.value) / max_value * 100:.1f}%"></div></div>'
        f'<span class="value">{escape(_format_number(p.value))}{escape(unit)}</span></div>'
        for p, axis_label in zip(ordered, metric_axis_labels(ordered))
    )
    st.markdown(
        f'<div class="ts-bar-compare"><b>{escape(label)}</b>{rows}</div>',
        unsafe_allow_html=True,
    )
    render_metric_insight(ordered, grounded_claims)


def render_swot(strengths: list[str], weaknesses: list[str], opportunities: list[str], threats: list[str]) -> str:
    """Only the quadrants that have evidence.

    Every quadrant used to be drawn, with "관련 데이터 수집 필요" filling the
    empty ones - so a question about which ad channels suit which age bracket,
    which has no weaknesses or threats to state, showed two apologies beside
    two findings. An absent quadrant is a fact about the question, not a gap
    to be papered over; the agreed principle is that a multi-quadrant block is
    only used when the data genuinely fills it.

    Returns "" when fewer than two quadrants have content, so the caller can
    drop the block rather than render a one-cell "matrix".
    """
    quadrants = [
        ("Strength", strengths, "positive"),
        ("Weakness", weaknesses, "negative"),
        ("Opportunity", opportunities, "positive"),
        ("Threat", threats, "negative"),
    ]
    filled = [(label, values, tone) for label, values, tone in quadrants if values]
    if len(filled) < 2:
        return ""
    cells = "".join(
        f'<div class="ts-swot-cell {tone}"><h4>{escape(label)}</h4>'
        + "".join(f"<p>• {escape(value)}</p>" for value in values)
        + "</div>"
        for label, values, tone in filled
    )
    # Two quadrants read better side by side than in a 2x2 with two holes.
    layout_class = "ts-swot duo" if len(filled) == 2 else "ts-swot"
    return f'<div class="{layout_class}">{cells}</div>'


def reference_year(synthesis: Any) -> int | None:
    """The year relative dates in this run's evidence are relative to."""
    as_of = getattr(synthesis, "as_of_date", None)
    try:
        return int(str(as_of)[:4]) if as_of else None
    except ValueError:
        return None


def action_impact_lookup(report: Any) -> dict[str, Any]:
    """Cleaned action text -> the whole `ActionImpact` a source stated for it.

    Keyed on the cleaned text because the same action reaches the renderer
    with and without its `[doc_id=...]` marker depending on the path. The
    link object rather than just its sentence, because an impact that came
    with a stated size can be drawn as well as read.
    """
    return {
        clean_citation(link.action): link
        for link in (getattr(report, "action_impacts", None) or [])
    }


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
    stated_sizes = [
        abs(size) for _, impact, _ in rows
        if (size := getattr(impact, "impact_value", None)) is not None
    ]
    max_impact = max(stated_sizes) if stated_sizes else 0
    body_parts = []
    for index, (title, expected_impact, url) in enumerate(rows, 1):
        link = (
            f'<a class="ts-evidence-link" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
            if url
            else "<span></span>"
        )
        impact_text = getattr(expected_impact, "expected_impact", expected_impact) or ""
        impact_value = getattr(expected_impact, "impact_value", None)
        # A bar only where the source stated a size, and scaled against the
        # largest size stated in this same list - never against a rank. Rows
        # whose impact is prose keep the sentence and get no bar, which is the
        # difference between "we don't know how big" and "it is small".
        bar = ""
        if impact_value is not None and max_impact:
            unit = getattr(expected_impact, "impact_unit", None) or ""
            bar = (
                f'<span class="ts-impact-bar" title="{escape(_format_number(impact_value))}{escape(unit)}">'
                f'<i style="width:{abs(impact_value) / max_impact * 100:.1f}%"></i>'
                f'<b>{escape(_format_number(impact_value))}{escape(unit)}</b></span>'
            )
        impact_cell = (
            f'<span class="impact" title="{escape(impact_text)}">{escape(impact_text)}{bar}</span>'
            if impact_text
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




_DONUT_COLORS = ("var(--ts-accent)", "var(--ts-teal)", "var(--ts-muted)", "var(--ts-soft)")


def render_share_split(metric_points: list[Any]) -> None:
    """Composition of one stated whole, as a donut per whole.

    Only drawn for figures the source framed as parts of a named population
    and whose sum stays within 100 (`share_groups`). Where the named slices
    fall short, the gap is left visibly unfilled and labelled as
    unaccounted-for rather than closed with an invented "기타" - a source that
    named the top three is not a source that said the rest is one thing.
    """
    groups = share_groups(metric_points)
    if not groups:
        return
    for whole, slices in groups:
        total = sum(point.value for point in slices)
        offset = 0.0
        segments = ""
        for index, point in enumerate(slices):
            color = _DONUT_COLORS[index % len(_DONUT_COLORS)]
            segments += (
                f'<circle class="ts-donut-seg" r="15.9155" cx="21" cy="21" fill="none" '
                f'stroke="{color}" stroke-width="7" '
                f'stroke-dasharray="{point.value:.1f} {100 - point.value:.1f}" '
                f'stroke-dashoffset="{(25 - offset) % 100:.1f}"></circle>'
            )
            offset += point.value
        legend = "".join(
            f'<span class="ts-donut-key">'
            f'<i style="background:{_DONUT_COLORS[index % len(_DONUT_COLORS)]}"></i>'
            f'{escape(point.subject or point.label)} {_format_number(point.value)}%</span>'
            for index, point in enumerate(slices)
        )
        remainder = 100 - total
        note = (
            f'<p class="ts-factor-note">근거가 밝힌 항목의 합은 {_format_number(total)}%이며, '
            f'나머지 {_format_number(remainder)}%는 출처에 명시되지 않았습니다.</p>'
            if remainder > SHARE_SUM_TOLERANCE else ""
        )
        st.markdown(
            f'<div class="ts-donut-card"><b>{escape(whole)}</b>'
            f'<svg viewBox="0 0 42 42" class="ts-donut">'
            f'<circle r="15.9155" cx="21" cy="21" fill="none" stroke="var(--ts-soft)" '
            f'stroke-width="7"></circle>{segments}</svg>'
            f'<div class="ts-donut-legend">{legend}</div></div>{note}',
            unsafe_allow_html=True,
        )


def render_factor_list(items: list[tuple[str, str | None]]) -> None:
    """A list of factors, as a list - `items` = (text, evidence_url).

    Separate from the narrative fallback for one reason: that card shows the
    first four bullets of whatever a section happens to hold, because it is a
    summary. A question that asks *which factors* is asking for the set, so
    truncating it to four answers a different question. Nothing is ranked -
    the evidence stated these, not an order between them; where the analyzer
    did score them, `driver_bars` is picked ahead of this block instead.
    """
    if not items:
        return
    rows = "".join(
        f'<li><span>{escape(clean_citation(text))}</span>'
        + (
            f'<a class="ts-inline-evidence" href="{escape(url)}" target="_blank" '
            f'title="근거 원문 열기">↗</a>' if url else ""
        )
        + "</li>"
        for text, url in items
    )
    st.markdown(
        f'<ul class="ts-factor-list">{rows}</ul>'
        f'<p class="ts-factor-note">근거에서 확인된 {len(items)}개 항목이며, 순서는 우열이 아닙니다.</p>',
        unsafe_allow_html=True,
    )


def render_recurring_terms(grounded_claims: list[Any]) -> None:
    """Words several separate documents used, with how many used each.

    A count of the evidence, not a reading of it. The number beside a term is
    the number of distinct documents it appeared in, and clicking through
    lands on a real claim containing it - so a reader can check the word
    rather than take the list on faith. No weighting, no sentiment, no
    inference about why a word recurs.
    """
    terms = recurring_terms(grounded_claims or [])
    if not terms:
        return
    chips = "".join(
        f'<span class="ts-term" title="{escape(clean_citation(claim.claim))}">'
        f'{escape(term)}<b>{count}</b></span>'
        for term, count, claim in terms
    )
    st.markdown(
        f'<div class="ts-terms">{chips}</div>'
        '<p class="ts-factor-note">숫자는 그 표현이 등장한 <b>서로 다른 출처 문서의 수</b>입니다. '
        '빈도만 센 것이며 중요도 판단이 아닙니다.</p>',
        unsafe_allow_html=True,
    )


def _claim_link(claim: Any) -> str:
    url = getattr(claim, "source_url", None)
    return (
        f'<a class="ts-evidence-link" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
        if url else ""
    )


def render_cause_tree(grounded_claims: list[Any]) -> None:
    """Root causes with what the evidence says follows from them.

    Drawn only from `parent_synthesis_claim_id` links that survived the
    analyzer's verification - a document that never stated a causal chain
    produces no tree, and the flat claim list stays the honest rendering.
    """
    roots = cause_tree(grounded_claims or [])
    if not roots:
        return
    branches = ""
    for root, children in roots:
        child_rows = "".join(
            f'<li>{escape(clean_citation(child.claim))}{_claim_link(child)}</li>'
            for child in children
        )
        branches += (
            f'<div class="ts-cause-branch">'
            f'<div class="ts-cause-root">{escape(clean_citation(root.claim))}{_claim_link(root)}</div>'
            f'<ul class="ts-cause-children">{child_rows}</ul></div>'
        )
    st.markdown(
        f'<section class="ts-cause-tree"><h3>원인 구조</h3>{branches}</section>',
        unsafe_allow_html=True,
    )


def render_importance_bars(grounded_claims: list[Any]) -> None:
    """Claims ranked by the model's stated importance.

    Every bar carries an "AI 판단" badge and the reason the score was given,
    because the number is a judgement and not a measurement - a score with no
    reason attached never reaches this function (the analyzer discards it).
    Bars are scaled against 100, not against the top row, so a set of claims
    the model thought were all middling doesn't render as one dominant driver.
    """
    ranked = importance_ranked(grounded_claims or [])
    if len(ranked) < 2:
        return
    rows = "".join(
        f'<div class="ts-driver-row" title="{escape(claim.importance_basis or "")}">'
        f'<span class="label">{escape(clean_citation(claim.claim))}</span>'
        f'<span class="ts-driver-track"><i style="width:{claim.importance}%"></i></span>'
        f'<span class="value">{claim.importance}</span>{_claim_link(claim)}</div>'
        for claim in ranked
    )
    st.markdown(
        '<section class="ts-drivers"><h3>영향도 <span class="ts-ai-badge">AI 판단</span></h3>'
        '<p class="ts-drivers-note">근거 문서가 제시한 수치가 아니라 모델이 매긴 상대적 중요도입니다. '
        '각 항목에 마우스를 올리면 그렇게 본 이유가 표시됩니다.</p>'
        + rows + "</section>",
        unsafe_allow_html=True,
    )


def _sparkline_svg(points: list[Any]) -> str:
    """A bare shape of where this metric has been - no axes, no labels.

    Only drawn for three or more points in time. Two points are already fully
    described by the delta beside the figure, and a line between two dots
    implies a path the evidence never described.
    """
    values = [point.value for point in points]
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = 100 / (len(values) - 1)
    coords = " ".join(
        f"{index * step:.1f},{28 - (value - low) / span * 24:.1f}"
        for index, value in enumerate(values)
    )
    rising = values[-1] >= values[0]
    stroke = "var(--ts-teal)" if rising else "var(--ts-accent)"
    return (
        f'<svg class="ts-kpi-spark" viewBox="0 0 100 30" preserveAspectRatio="none">'
        f'<polyline points="{coords}" fill="none" stroke="{stroke}" stroke-width="2" '
        f'vector-effect="non-scaling-stroke"/></svg>'
    )


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
        # Sort before calling anything "latest": grouping preserves input
        # order, so points[-1] was whichever the analyzer happened to emit
        # last, not the most recent period. Non-time axes (age brackets,
        # companies) have no chronology, so they keep their given order and
        # get no delta - a "change" between two age groups is meaningless.
        points = by_label[label]
        # A metric measured for several subjects is never chronological, even
        # when every one of its periods is a real date - "KT 2024 vs SKB 2024"
        # sorted by period would call one of them "latest" and print a delta
        # between two different companies.
        is_chronological = (
            not varies_by_subject(points)
            and all(is_time_period(point.period) for point in points)
        )
        if is_chronological:
            points = sorted(points, key=lambda point: period_sort_key(point.period))
        # The headline number is the latest figure the evidence *observed*. A
        # series ending in a forecast would otherwise show a projection as the
        # current value, and subtract from it to report a change that has not
        # happened. The forecast still reaches the reader - it is drawn on the
        # chart as a dashed segment and tagged here - it just isn't presented
        # as fact.
        observed = [point for point in points if not getattr(point, "is_forecast", False)]
        latest = (observed or points)[-1]
        forecast_tag = ' <span class="ts-kpi-forecast">전망</span>' if getattr(latest, "is_forecast", False) else ""
        value_text = f"{_format_number(latest.value)}{latest.unit}{forecast_tag}"
        if is_chronological and len(observed) >= 2:
            delta = latest.value - observed[0].value
            sign = "+" if delta >= 0 else ""
            caption_text = f"{sign}{_format_number(delta)}{latest.unit} ({escape(observed[0].period)}→{escape(latest.period)})"
        elif len(points) >= 2:
            caption_text = f"{escape(latest.period)} 기준 · {len(points)}개 대상 비교"
        elif latest.subject:
            caption_text = f"{escape(latest.subject)} · {escape(latest.period)} 기준"
        else:
            caption_text = f"{escape(latest.period)} 기준"
        spark = _sparkline_svg(observed) if is_chronological and len(observed) >= 3 else ""
        # Label on the left, figure + its caption right-aligned as one unit -
        # the reference design's KPI row shape. The delta is deliberately left
        # in a neutral colour rather than red/green: whether a rise is good or
        # bad is metric-specific (subscribers up is good, churn up is not) and
        # nothing in the evidence tells us which this is, so colouring it would
        # be asserting a judgement the data doesn't support.
        cards.append(
            f'<div class="ts-kpi-card"><small>{escape(label)}</small>'
            f'<div class="ts-kpi-figure"><b>{escape(value_text)}</b>'
            f'<small class="ts-kpi-delta">{caption_text}</small></div>{spark}</div>'
        )
    st.markdown(f'<div class="ts-kpi-row">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_source_list(result: Any) -> str:
    """Evidence & Sources panel, linking to the document actually cited.

    This used to look each analysis's `source_id` up in the registered source
    plan by name and use that source's homepage. Documents found by the AI
    search harness carry a bare domain ("www.ajupress.com") as source_id,
    which matches no registered source name, so every row fell through to
    "링크 없음" - while `analysis.source_url`, the real article URL, sat
    unused on the same object. Prefer that; fall back to the registered
    source's URL only when the analysis has none.
    """
    sources = source_lookup(result)
    rows = []
    seen: set[str] = set()
    for analysis in result.document_analyses or []:
        source_id = analysis.source_id
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        registered = sources.get(source_id)
        label = registered.name if registered else source_id
        url = analysis.source_url or (registered.url if registered else None)
        title = clean_citation(getattr(analysis, "source_title", None) or "")
        if title and title != label:
            label = f"{label} · {title}"
        link = (
            f'<a href="{escape(url)}" target="_blank">Link ↗</a>'
            if url
            else '<span class="ts-empty">링크 없음</span>'
        )
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

# Shape thresholds come from common/block_shapes.py so the predicate and the
# renderer can never disagree about what counts as radar-able; only the colours
# belong to the rendering layer.
_RADAR_PALETTE = ("var(--ts-accent)", "var(--ts-teal)", "var(--ts-orange)")






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






_STATUS_LABELS = {"done": "완료", "active": "진행", "todo": "예정"}


def render_timeline(
    evidence: list[str],
    metric_points: list[Any],
    reference_year: int | None = None,
    limit: int = 6,
    as_of_date: str | None = None,
) -> None:
    """Dated evidence in order, each row marked with where it stands.

    The state comes from words the document wrote ("추진 중", "출시 예정",
    "완료") and, only where it wrote none, from whether the period is before
    or after this report's as-of date. A row with neither stays 진행 - a
    dated statement with no completion word is something that was reported,
    and calling it finished is the one reading nothing supports.
    """
    entries = timeline_entries_with_status(
        evidence, metric_points, reference_year, as_of_date
    )[:limit]
    if not entries:
        return
    steps = "".join(
        f'<div class="ts-timeline-step {status}">'
        f'<b>{escape(period)}<span class="ts-step-state">{_STATUS_LABELS[status]}</span></b>'
        f'{escape(text)}</div>'
        for period, text, status in entries
    )
    st.markdown(f'<div class="ts-timeline">{steps}</div>', unsafe_allow_html=True)




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
