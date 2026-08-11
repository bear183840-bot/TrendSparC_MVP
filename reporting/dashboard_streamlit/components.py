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
    group_metric_points_by_series,
    classify_metric_shape,
    dated_items,
    filter_shared_comparison_axis,
    group_metric_points_by_label,
    is_duplicate_statement,
    is_time_period,
    period_sort_key,
    rank_by_relevance,
    select_chartable_series,
    plotted_chart_series,
)
# Data-shape predicates live in common/block_shapes.py (no Streamlit
# dependency) and are re-exported here so the renderers that use them, and
# every existing caller, keep importing from one place.
from common.metric_identity import metric_identity
from common.number_format import (
    display_value,
    scaled_number,
    joined_value,
    scale_for,
    scale_prefixed_unit,
    unit_needs_space,
)
from common.section_titles import section_title
from common.block_titles import block_title
from common.block_shapes import (  # noqa: F401
    LEVEL_RADIUS_FRACTION as _LEVEL_RADIUS_FRACTION,
    RADAR_MAX_ENTITIES as _RADAR_MAX_ENTITIES,
    RADAR_MIN_AXES as _RADAR_MIN_AXES,
    _format_number,
    bar_metric_groups,
    item_bar_groups,
    ranking_comparison_groups,
    ranking_list_groups,
    time_bar_groups,
    clean_citation,
    has_bar_metrics,
    has_cause_map,
    has_comparison,
    has_metric_comparison,
    has_radar,
    has_timeline,
    has_timeseries,
    cause_forest,
    cause_tree,
    has_cause_tree,
    SHARE_SUM_TOLERANCE,
    grouped_bar_series,
    competitor_panels,
    benchmark_grid,
    has_competitor_panels,
    has_grouped_bars,
    has_landscape,
    landscape_parts,
    has_recurring_terms,
    has_share_split,
    level_matrix,
    split_aggregate,
    has_status_levels,
    status_levels,
    recurring_terms,
    share_groups,
    has_importance_ranking,
    importance_ranked,
    metric_axis_labels,
    metric_comparison_groups,
    decision_matrix,
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


def _distinct_measurements(points: list[Any]) -> int:
    """How many different things were measured, not how many readings landed.

    A live run put "확인된 지표 226건" beside a page showing perhaps a dozen
    figures, because the list counts every reading: the same 가입자 수 in two
    documents, at two periods, restated in a table and in the sentence above
    it. As a headline that number answers no question a reader has - it is
    the size of an intermediate array. Counting identities makes it the
    claim it looked like all along, and readings that disagree still collapse
    to the one measurement they disagree about.
    """
    return len({metric_identity(point) for point in points})


# Fields whose length is not the number the label promises.
_HEADLINE_COUNTERS = {"metric_series": _distinct_measurements}


def headline_stats(synthesis: Any, purpose_id: str | None) -> list[tuple[str, int, str]]:
    """(label, count, accent) for the summary card's side column."""
    spec = _HEADLINE_STATS.get(purpose_id or "", _DEFAULT_HEADLINE_STATS)
    return [
        (label, _HEADLINE_COUNTERS.get(field, len)(getattr(synthesis, field, None) or []), accent)
        for field, label, accent in spec
    ]


def render_headline_kpi(point: Any) -> str:
    """The one figure the summary is about, as the corner card's markup."""
    number, unit = display_value(point.value, point.unit)
    period = getattr(point, "period", None) or ""
    return (
        '<div class="ts-headline-kpi">'
        f'<small>{escape(clean_citation(point.label))}</small>'
        f'<b>{escape(number)}</b>'
        + (f'<span class="ts-headline-unit">{escape(unit)}</span>' if unit else "")
        + (f'<em>{escape(period)}</em>' if period else "")
        + "</div>"
    )


def render_executive_summary(
    summary: str,
    stats: list[tuple[str, int, str]] | None = None,
    heading: str = "Executive Summary",
    headline_point: Any | None = None,
    supporting_points: list[Any] | None = None,
    comparison: tuple[str, str, list[Any]] | None = None,
) -> None:
    """Executive Summary as a summary *composition*, not a text container.

    The core message stays a short paragraph, but numbers already drawable
    as cards - a few more KPIs beside the headline figure, one comparison or
    composition visualization when the evidence is shaped for either - are
    shown as blocks instead of being spelled out in a longer paragraph. Both
    additions are optional and independent: a question with no comparable
    figures gets narrative alone, exactly as before.

    `supporting_points` (`common.block_shapes.executive_summary_supporting_kpis`)
    and `comparison` (`common.block_shapes.executive_summary_comparison`) are
    computed by the caller, not here - this function only decides how to
    lay out what it is handed, the same selection/render split every other
    block in this module follows.

    The corner aside used to hold counters - "확인된 지표 155건 / 주의 신호
    3건". A count of an internal list is not something a reader can act on,
    and it sat in the most prominent position on the page. What belongs
    there is the number the summary is about, chosen by `headline_kpi` using
    the ranking the KPI grid already uses; when no single figure answers the
    question the corner is simply empty, on the same rule as every other
    block here. `stats` is still accepted so existing callers keep working,
    and is used only when there is no headline figure to show instead.
    """
    if headline_point is not None:
        aside = render_headline_kpi(headline_point)
    elif stats:
        aside = "".join(
            f'<div class="ts-stat {accent}"><small>{escape(label)}</small><b>{count}건</b></div>'
            for label, count, accent in stats
        )
    else:
        aside = ""
    st.markdown(
        f'<div class="ts-summary-grid{"" if aside else " ts-summary-solo"}">'
        f'<section class="ts-summary"><h2>{escape(heading)}</h2>'
        f'<p>{escape(summary or "분석 가능한 근거가 부족합니다.")}</p></section>'
        + (f'<aside class="ts-stat-col">{aside}</aside>' if aside else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if supporting_points:
        render_kpi_row(supporting_points, limit=len(supporting_points))
    # `comparison` is already None here when the Landscape card below will
    # pair this same composition with its trend chart - the caller
    # (`generic_dashboard.py`) checks that before calling in, so the
    # identical donut does not appear once here and once beside its trend.
    # When Landscape has no chartable trend to pair it with, the composition
    # still gets its Executive Summary visualization here as before.
    if comparison is not None:
        kind, subject, points = comparison
        if kind == "share":
            render_share_split(points)
        else:
            render_metric_comparison(subject, points)


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


def render_question_axis_comparison(
    groups: list[tuple[str, list[tuple[str, str | None]]]],
) -> None:
    """Evidence columns for the two sides of an explicit A-vs-B question.

    This is the honest fallback when both sides are evidenced but their units
    cannot share a numeric axis.  It preserves comparison without pretending
    unlike quantities are mathematically comparable.
    """
    if len(groups) != 2:
        return
    columns = []
    for label, items in groups:
        if items:
            rows = "".join(
                '<li>'
                f'<span>{escape(clean_citation(text))}</span>'
                + (
                    f'<a class="ts-inline-evidence" href="{escape(url)}" target="_blank">↗</a>'
                    if url else ""
                )
                + '</li>'
                for text, url in items[:2]
            )
        else:
            rows = '<li class="ts-empty">비교 가능한 근거가 아직 확보되지 않았습니다.</li>'
        columns.append(
            f'<section class="ts-axis-side"><h4>{escape(label)}</h4><ul>{rows}</ul></section>'
        )
    st.markdown(
        '<div class="ts-axis-comparison">' + ''.join(columns) + '</div>'
        '<p class="ts-axis-note">같은 단위의 공통 축이 없어 각 측에서 확인된 근거를 나란히 제시합니다.</p>',
        unsafe_allow_html=True,
    )


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
    """The evidence sentence a plotted series was read out of.

    The artwork puts this behind a small bordered "AI Insight" control beside
    the chart rather than printing it underneath, which is also the honest
    shape: the sentence is context for the chart, not a caption the chart
    can't be read without. Opened, it shows the verified claim and its source.

    Deliberately not a generated interpretation - the text is a claim already
    carried by the metric, so an unlinked series gets no control at all rather
    than a written one.
    """
    insight = metric_insight(points, grounded_claims or [])
    if not insight:
        return
    text, url = insight
    with st.expander("AI Insight"):
        link = f' <a href="{escape(url)}" target="_blank">출처 원문</a>' if url else ""
        # The chip says what the sentence is before the reader starts reading
        # it: a quoted claim, not the dashboard's own commentary. Without it
        # the panel behind "AI Insight" reads as something the model wrote.
        st.markdown(
            '<div class="ts-metric-insight">'
            '<span class="ts-metric-insight-tag">근거</span>'
            f'{escape(clean_citation(text))}{link}</div>',
            unsafe_allow_html=True,
        )


def render_metric_chart(
    metric_points: list[Any],
    title: str = "Market Trend",
    grounded_claims: list[Any] | None = None,
    show_insight: bool = True,
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
    chartable_points = _plottable_series(select_chartable_series(metric_points))
    if not chartable_points:
        return
    st.markdown(_metric_chart_svg(chartable_points, title), unsafe_allow_html=True)
    if show_insight:
        render_metric_insight(chartable_points, grounded_claims)


# Moved to common/block_shapes.py so slot resolution, which must not import
# Streamlit, can ask the same question this renderer answers.
_plottable_series = plotted_chart_series


# Chart geometry, in the SVG's own viewBox units (it scales to the container).
# Kept in step with `.ts-chart-svg { aspect-ratio: 356/150 }` in theme.py -
# the CSS holds the ratio because the browser needs it before the SVG loads.
_CHART_W, _CHART_H = 356, 150
_CHART_LEFT, _CHART_RIGHT = 46, 344      # plot area, leaving a gutter for y labels
_CHART_TOP, _CHART_BOTTOM = 12, 112      # plot area vertically
_CHART_XLABEL_Y = 136
_CHART_GRID_LINES = 4


# A second series whose numbers are this much smaller than the first gets its
# own axis. Below the threshold one shared axis is easier to read - the whole
# point of a single axis is that two lines can be compared directly, and
# splitting them at 2x throws that away for no gain. Above it the smaller
# series is pressed flat against the floor and stops being a line at all:
# 영업이익 (900~3,700억원) drawn against 매출액 (44,000~46,900억원) rendered as
# a straight rule along the bottom of the plot.
_DUAL_AXIS_RATIO = 4.0

# One colour per series, not per axis. Colouring by axis meant two series
# sharing the left axis were drawn identically - IPTV and SO were the same
# orange line, and the legend could not tell the reader which was which.
#
# The ramp is the design guide's own two colours plus the midpoint between
# them, so three series separate cleanly without introducing a hue the brand
# does not use. `color-mix` computes the middle rather than hard-coding a
# third hex, which keeps it correct if either end is retuned.
SERIES_PALETTE = (
    "var(--ts-accent)",
    "var(--ts-navy)",
    "color-mix(in srgb,var(--ts-accent) 50%,var(--ts-navy))",
    "color-mix(in srgb,var(--ts-accent) 75%,var(--ts-navy))",
    "color-mix(in srgb,var(--ts-accent) 25%,var(--ts-navy))",
    "color-mix(in srgb,var(--ts-accent) 62%,var(--ts-panel))",
)

# Below three items a single accent reads as "these are all the same kind of
# thing", which is true and calmer. At three and above the reader is being
# asked to tell items apart, and one colour makes them do it by position
# alone.
SERIES_PALETTE_MIN_ITEMS = 3


def series_color(index: int, count: int = SERIES_PALETTE_MIN_ITEMS) -> str:
    """The colour for one item of `count`, from the shared ramp."""
    if count < SERIES_PALETTE_MIN_ITEMS:
        return SERIES_PALETTE[0]
    return SERIES_PALETTE[index % len(SERIES_PALETTE)]


# The line chart's own alias, kept because it colours by series unconditionally
# - a chart never plots fewer than two lines' worth of meaning per line.
_LINE_SERIES_COLORS = SERIES_PALETTE

_NICE_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def _nice_step(rough: float) -> float:
    """The next round number at or above `rough` - 1, 2, 2.5 or 5 x 10^n.

    Axis ticks were the raw data range divided into four, which is how an
    axis came to read 46,900 / 31,583.7 / 16,267.3 / 951. Those numbers are
    accurate and unreadable; nobody holds 16,267.3 in their head to judge
    where a point sits.
    """
    if rough <= 0:
        return 1.0
    magnitude = 10.0 ** math.floor(math.log10(rough))
    for step in _NICE_STEPS:
        if rough <= step * magnitude + 1e-9:
            return step * magnitude
    return 10.0 * magnitude


def _chart_y_ticks(low: float, high: float) -> list[float]:
    """`_CHART_GRID_LINES` round values covering the data range, top-down.

    The range is widened outward to the nearest round step rather than
    starting exactly at the data, so every plotted point sits inside the
    axis and the labels are numbers a reader can use. A flat series (every
    value identical) still gets a readable axis rather than a divide-by-zero.
    """
    if high <= low:
        pad = abs(high) * 0.1 or 1.0
        low, high = high - pad, high + pad
    step = _nice_step((high - low) / (_CHART_GRID_LINES - 1))
    # Series that never go negative keep a zero floor where that is close by:
    # a revenue axis starting at 44,000 exaggerates a 6% rise into a doubling.
    base = 0.0 if low >= 0 and low <= step else math.floor(low / step) * step
    top = base + step * (_CHART_GRID_LINES - 1)
    while top < high:
        step = _nice_step(step * 1.5)
        base = 0.0 if low >= 0 and low <= step else math.floor(low / step) * step
        top = base + step * (_CHART_GRID_LINES - 1)
    return [top - step * index for index in range(_CHART_GRID_LINES)]


def axis_scale(values: list[float], unit: str | None) -> tuple[float, str]:
    """The chart axis's share of one project-wide rule.

    Kept as a name because the axis is where scaling first appeared, but the
    rule itself lives in `common/number_format.py` so a KPI card, a bar
    label and this axis all write the same figure the same way.
    """
    return scale_for(values, unit)


def _axis_groups(by_label: dict) -> list[list[str]]:
    """Which labels share an axis - one group, or two when the scales differ.

    Split on magnitude, not on label, because nothing in the evidence says
    which metric is "the main one"; the biggest series anchors the left axis
    and anything an order of magnitude below it moves right.
    """
    peaks = {
        label: max(abs(point.value) for point in points)
        for label, points in by_label.items() if points
    }
    if len(peaks) < 2:
        return [list(by_label)]
    ordered = sorted(peaks, key=lambda label: peaks[label], reverse=True)
    largest = peaks[ordered[0]]
    small = [label for label in ordered if peaks[label] * _DUAL_AXIS_RATIO <= largest]
    if not small:
        return [ordered]
    return [[label for label in ordered if label not in small], small]


_BAR_AXIS_MAX_INTERVALS = 4


def _bar_axis(peak: float) -> tuple[float, list[float]]:
    """(axis top, ticks bottom-up) for a bar chart, which starts at zero.

    A different question from the line chart's axis, which frames a range that
    may sit far from zero. Bars are read as lengths from a zero baseline, so
    this axis always starts at 0 and its top sits just above the tallest bar.
    Reusing the line-chart ticks put the top gridline at 150 for a 93.2% peak,
    leaving every bar in the bottom two thirds of the plot for no reason.
    """
    if peak <= 0:
        return 1.0, [0.0, 1.0]
    best: tuple[float, float] | None = None
    for exponent in range(-4, 13):
        for mantissa in _NICE_STEPS:
            step = mantissa * (10.0 ** exponent)
            intervals = math.ceil(peak / step - 1e-9)
            if not 2 <= intervals <= _BAR_AXIS_MAX_INTERVALS:
                continue
            top = step * intervals
            if best is None or top < best[0] - 1e-9:
                best = (top, step)
    if best is None:
        return peak, [0.0, peak]
    top, step = best
    return top, [step * index for index in range(int(round(top / step)) + 1)]


def _metric_chart_svg(points: list[Any], title: str) -> str:
    """Reference-style area+line chart drawn directly from evidence-stated
    MetricPoints - one polyline per label, x positions in chronological
    `period` order, y scaled to the real min/max of the plotted values.
    Axis labels are the evidence's own period text and real numbers; nothing
    is interpolated or extrapolated, so a gap in the evidence stays a gap.
    """
    by_label = group_metric_points_by_series(points)
    periods = sorted({point.period for point in points}, key=period_sort_key)
    unit = next((point.unit for point in points if point.unit), "")

    groups = _axis_groups(by_label)
    ticks_by_group = []
    scale_by_group: list[tuple[float, str]] = []
    for group in groups:
        group_values = [point.value for label in group for point in by_label[label]]
        ticks_by_group.append(_chart_y_ticks(min(group_values), max(group_values)))
        group_unit = next(
            (point.unit for label in group for point in by_label[label] if point.unit), ""
        )
        scale_by_group.append(axis_scale(group_values, group_unit))
    axis_of_label = {label: index for index, group in enumerate(groups) for label in group}

    def tick_label(axis: int, tick: float) -> str:
        divisor, _prefix = scale_by_group[axis]
        return _format_number(tick / divisor)

    def x_of(period: str) -> float:
        if len(periods) == 1:
            return (_CHART_LEFT + _CHART_RIGHT) / 2
        step = (_CHART_RIGHT - _CHART_LEFT) / (len(periods) - 1)
        return _CHART_LEFT + step * periods.index(period)

    def y_on(axis: int, value: float) -> float:
        ticks = ticks_by_group[axis]
        tick_low, tick_high = ticks[-1], ticks[0]
        ratio = (value - tick_low) / ((tick_high - tick_low) or 1.0)
        return _CHART_BOTTOM - ratio * (_CHART_BOTTOM - _CHART_TOP)

    # Gridlines follow the left axis only. Two sets of horizontal rules at
    # different heights would read as a grid that means nothing.
    grid = "".join(
        f'M{_CHART_LEFT - 12} {y_on(0, tick):.1f}h{_CHART_RIGHT - _CHART_LEFT + 12}'
        for tick in ticks_by_group[0]
    )
    y_labels = "".join(
        f'<text x="2" y="{y_on(0, tick) + 3:.1f}">{escape(tick_label(0, tick))}</text>'
        for tick in ticks_by_group[0]
    )
    # The right-hand axis is tinted with its series' colour, because on a dual
    # axis "which line does this number belong to" is the question the reader
    # has to answer before anything else.
    right_labels = ""
    if len(groups) > 1:
        # Tinted with its series' colour only when it carries exactly one -
        # "which line does this number belong to" is the first question a
        # dual axis raises, and with two lines on it any single tint would
        # answer it wrongly. Then the legend's 좌축/우축 labels are the cue.
        right_series = [label for label in by_label if axis_of_label[label] == 1]
        axis_tint = (
            _LINE_SERIES_COLORS[list(by_label).index(right_series[0]) % len(_LINE_SERIES_COLORS)]
            if len(right_series) == 1 else "var(--ts-muted)"
        )
        right_labels = (
            f'<g class="ts-chart-axis" text-anchor="end" fill="{axis_tint}">'
            + "".join(
                f'<text x="{_CHART_W - 2}" y="{y_on(1, tick) + 3:.1f}">'
                f'{escape(tick_label(1, tick))}</text>'
                for tick in ticks_by_group[1]
            )
            + "</g>"
        )
    x_labels = "".join(
        f'<text x="{x_of(period):.1f}" y="{_CHART_XLABEL_Y}">{escape(period)}</text>' for period in periods
    )

    series_markup = ""
    for index, (label, label_points) in enumerate(by_label.items()):
        ordered = sorted(label_points, key=lambda point: period_sort_key(point.period))
        axis = axis_of_label[label]
        coords = [(x_of(point.period), y_on(axis, point.value)) for point in ordered]
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
        if index == 0 and axis == 0 and len(solid_coords) > 1:
            area_path = (
                f'M{solid_coords[0][0]:.1f} {solid_coords[0][1]:.1f}'
                + "".join(f'L{x:.1f} {y:.1f}' for x, y in solid_coords[1:])
                + f'L{solid_coords[-1][0]:.1f} {_CHART_BOTTOM}L{solid_coords[0][0]:.1f} {_CHART_BOTTOM}Z'
            )
            area = f'<path d="{area_path}" fill="url(#tsChartFill)"></path>'
        stroke = _LINE_SERIES_COLORS[index % len(_LINE_SERIES_COLORS)]
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

    # The legend has to say which axis a line is read against, or a dual-axis
    # chart silently invites the reader to compare two different scales.
    legend = "".join(
        f'<span class="ts-chart-key">'
        f'<i style="background:{_LINE_SERIES_COLORS[index % len(_LINE_SERIES_COLORS)]}"></i>'
        f'{escape(label)}'
        + (f'<small>{"우축" if axis_of_label[label] else "좌축"}</small>' if len(groups) > 1 else "")
        + "</span>"
        for index, label in enumerate(by_label)
    )
    # The axis divides its labels, so the note is where the reader is told by
    # how much. Without it the chart would understate every figure by four
    # orders of magnitude and say nothing about having done so.
    left_unit = scale_prefixed_unit(unit, scale_by_group[0][1])
    note_parts = [f"단위: {left_unit}"] if left_unit else []
    if len(groups) > 1:
        right_raw = next(
            (point.unit for label in groups[1] for point in by_label[label] if point.unit), ""
        )
        right_unit = scale_prefixed_unit(right_raw, scale_by_group[1][1])
        if right_unit and right_unit != left_unit:
            note_parts.append(f"우축 {right_unit}")
    unit_note = (
        f'<span class="ts-chart-unit">{escape(" · ".join(note_parts))}</span>'
        if note_parts else ""
    )
    if any(getattr(point, "is_forecast", False) for point in points):
        projected_types = list(dict.fromkeys(
            _VALUE_TYPE_LABELS.get(getattr(point, "value_type", "forecast"), "전망")
            for point in points if getattr(point, "is_forecast", False)
        ))
        legend += (
            '<span class="ts-chart-key ts-chart-key-forecast"><i></i>'
            f'{escape("·".join(projected_types))}(출처 제시)</span>'
        )
    return (
        f'<div class="ts-chart"><div class="ts-chart-head"><b>{escape(title)}</b>{unit_note}</div>'
        f'<div class="ts-chart-legend">{legend}</div>'
        f'<svg viewBox="0 0 {_CHART_W} {_CHART_H}" class="ts-chart-svg">'
        '<defs><linearGradient id="tsChartFill" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="var(--ts-accent)" stop-opacity=".22"></stop>'
        '<stop offset="1" stop-color="var(--ts-accent)" stop-opacity="0"></stop></linearGradient></defs>'
        f'<g stroke="var(--ts-soft)" stroke-width="1"><path d="{grid}"></path></g>'
        f'<g class="ts-chart-axis" text-anchor="start">{y_labels}</g>'
        f'{right_labels}'
        f'{series_markup}'
        f'<g class="ts-chart-axis" text-anchor="middle">{x_labels}</g>'
        "</svg></div>"
    )


def render_metric_bar(
    points_for_one_label: list[Any],
    grounded_claims: list[Any] | None = None,
    show_insight: bool = True,
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
    # Three or more items compared read better as columns - the artwork's
    # vertical bar card - than as a stack of rows; two are a before/after and
    # stay horizontal, where the pair reads as one change.
    if (
        varies_by_subject(points_for_one_label)
        and len(split_aggregate(points_for_one_label)[0]) >= _COLUMN_BAR_MIN_ITEMS
    ):
        render_metric_columns(points_for_one_label)
        if show_insight:
            render_metric_insight(points_for_one_label, grounded_claims)
        return
    if varies_by_subject(points_for_one_label):
        ordered = sorted(points_for_one_label, key=lambda p: abs(p.value), reverse=True)
    elif all(is_time_period(point.period) for point in points_for_one_label):
        ordered = sorted(points_for_one_label, key=lambda p: period_sort_key(p.period))
    else:
        ordered = sorted(points_for_one_label, key=lambda p: abs(p.value), reverse=True)
    label = ordered[0].label
    unit = ordered[0].unit or ""
    max_value = max(abs(p.value) for p in ordered) or 1
    # One scale across the group: bars are read as lengths against each
    # other, so writing one row in 만 and another raw breaks the comparison
    # the block exists to make.
    bar_scale = scale_for([p.value for p in ordered], unit)
    rows = "".join(
        f'<div class="ts-bar-compare-row"><span class="period">{escape(axis_label)}</span>'
        f'<div class="ts-bar-compare-track"><div class="ts-bar-compare-fill" '
        f'style="--pct:{abs(p.value) / max_value * 100:.1f}%;'
        f'background:{series_color(position, len(ordered))}"></div></div>'
        f'<span class="value">{escape(joined_value(p.value, unit, bar_scale))}</span></div>'
        for position, (p, axis_label) in enumerate(zip(ordered, metric_axis_labels(ordered)))
    )
    st.markdown(
        f'<div class="ts-bar-compare"><b>{escape(label)}</b>{rows}</div>',
        unsafe_allow_html=True,
    )
    if show_insight:
        render_metric_insight(ordered, grounded_claims)


def render_swot(strengths: list[str], weaknesses: list[str], opportunities: list[str], threats: list[str]) -> str:
    """Only the quadrants that have evidence.

    Every quadrant used to be drawn, with "관련 데이터 수집 필요" filling the
    empty ones - so a question about which ad channels suit which age bracket,
    which has no weaknesses or threats to state, showed two apologies beside
    two findings. An absent quadrant is a fact about the question, not a gap
    to be papered over; the agreed principle is that a multi-quadrant block is
    only used when the data genuinely fills it.

    One quadrant is drawn too, as the artwork's single accent panel rather
    than as a one-cell grid pretending to be a matrix. Dropping it sent the
    only thing the question had to say - "기회" on a brand question with no
    stated risks - back to plain bullets, which is the opposite of using what
    is there. Returns "" only when every quadrant is empty.
    """
    quadrants = [
        ("Strength", strengths, "positive"),
        ("Weakness", weaknesses, "negative"),
        ("Opportunity", opportunities, "positive"),
        ("Threat", threats, "negative"),
    ]
    filled = [(label, values, tone) for label, values, tone in quadrants if values]
    if not filled:
        return ""
    # The artwork's quadrant head is one big initial with a soft colour disc
    # sitting behind it, and the items hang off a hairline rule with small ring
    # dots - no filled cell, no pill. Splitting the initial out lets the disc
    # be positioned behind just that letter rather than the whole heading.
    cells = "".join(
        f'<div class="ts-swot-cell {tone}">'
        f'<h4><span class="ts-swot-initial">{escape(label[0])}</span>{escape(label[1:])}</h4>'
        + '<ul>' + "".join(f"<li>{escape(value)}</li>" for value in values) + '</ul>'
        + "</div>"
        for label, values, tone in filled
    )
    # The grid follows the count instead of the count being padded to fit the
    # grid: two quadrants read better side by side than in a 2x2 with two
    # holes, and three across beats a 2x2 with one. Only four fill the square.
    layout_class = {1: "ts-swot solo", 2: "ts-swot duo", 3: "ts-swot trio"}.get(
        len(filled), "ts-swot"
    )
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


def render_action_list(
    rows: list[tuple[str, str, str | None]], owner: str | None = None,
    ai_judgements: dict[str, str] | None = None,
) -> None:
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
    ai_judgements = ai_judgements or {}
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
            impact_display = joined_value(impact_value, unit)
            bar = (
                f'<span class="ts-impact-bar" title="{escape(impact_display)}">'
                f'<i style="width:{abs(impact_value) / max_impact * 100:.1f}%"></i>'
                f'<b>{escape(impact_display)}</b></span>'
            )
        judgement_basis = ai_judgements.get(title)
        impact_cell = (
            f'<span class="impact"><b>판단 근거</b> {escape(judgement_basis)}</span>'
            if judgement_basis else
            f'<span class="impact" title="{escape(impact_text)}">{escape(impact_text)}{bar}</span>'
            if impact_text else '<span class="impact ts-empty">연결된 기대효과 없음</span>'
        )
        badge = '<span class="ts-ai-badge">AI 판단</span>' if judgement_basis else ""
        body_parts.append(
            f'<div class="ts-action-row"><span class="num">{index:02d}</span>'
            f'<span class="action">{escape(title)}{badge}</span>'
            f"{impact_cell}{link}</div>"
        )
    # A small subtitle, not a big <h3>, repeating "실행 제안" - the card's own
    # header (e.g. "Recommended Actions", set by the slot renderer one level
    # up) already says that at full size; live-verified 2026-08-11, a second
    # big title reading "SK브로드밴드 실행 제안" right under it read as the
    # same claim twice. The words stay (a reader still sees what this list
    # is), just no longer competing with the card header for size/attention.
    owner_note = (
        f'<span class="ts-actions-owner">실행 제안 ({escape(owner)})</span>'
        if owner else '<span class="ts-actions-owner">실행 제안</span>'
    )
    st.markdown(
        f'<section class="ts-actions">{owner_note}'
        '<div class="ts-actions-head"><span></span><span></span><span>기대 효과</span><span>근거</span></div>'
        + "".join(body_parts)
        + "</section>",
        unsafe_allow_html=True,
    )




# One hue stepped down in strength, as the artwork does it: a share of a whole
# is still the same quantity, so five unrelated colours would read as five
# unrelated things. Slices arrive largest-first, so strength tracks size.
# Slices of one whole are items to tell apart, same as lines on a chart, so
# they use the shared ramp rather than five tints of one hue - at 7.5% a
# 20%-opacity orange wedge was barely distinguishable from the empty track.
_DONUT_COLORS = SERIES_PALETTE


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
            f'{escape(point.subject or point.label)}'
            f'<b style="color:{_DONUT_COLORS[index % len(_DONUT_COLORS)]}">'
            f'{_format_number(point.value)}%</b></span>'
            for index, point in enumerate(slices)
        )
        remainder = 100 - total
        note = (
            f'<p class="ts-factor-note">근거가 밝힌 항목의 합은 {_format_number(total)}%이며, '
            f'나머지 {_format_number(remainder)}%는 출처에 명시되지 않았습니다.</p>'
            if remainder > SHARE_SUM_TOLERANCE else ""
        )
        # Title lives in its own compact header above the donut, the same
        # `.ts-*-head` pattern render_metric_chart uses for `.ts-chart-head` -
        # not a flex sibling beside the circle, which used to claim a whole
        # extra column to the donut's left and split it visually from a
        # companion chart placed beside this card (see render_landscape).
        st.markdown(
            f'<div class="ts-donut-card"><div class="ts-donut-head"><b>{escape(whole)}</b></div>'
            f'<div class="ts-donut-body">'
            f'<svg viewBox="0 0 42 42" class="ts-donut">'
            f'<circle r="15.9155" cx="21" cy="21" fill="none" stroke="var(--ts-soft)" '
            f'stroke-width="7"></circle>{segments}</svg>'
            f'<div class="ts-donut-legend">{legend}</div></div></div>{note}',
            unsafe_allow_html=True,
        )


def render_composition_breakdown(metric_points: list[Any], limit: int = 8) -> None:
    """A dense part-to-whole view for cost, channel, product, or any mix.

    The source must already have named the whole through ``share_of``.  This
    renderer changes only presentation: one stacked rail plus an exact-value
    list.  It never guesses an "other" slice when the stated parts fall short.
    """
    for whole, slices in share_groups(metric_points):
        ordered = sorted(slices, key=lambda point: point.value, reverse=True)[:limit]
        total = sum(point.value for point in ordered)
        segments = "".join(
            f'<i style="width:{point.value:.2f}%;background:{_DONUT_COLORS[index % len(_DONUT_COLORS)]}" '
            f'title="{escape(point.subject or point.label)} {_format_number(point.value)}%"></i>'
            for index, point in enumerate(ordered)
        )
        rows = "".join(
            f'<div class="ts-composition-row"><span class="num">{index:02d}</span>'
            f'<span class="label"><i style="background:{_DONUT_COLORS[(index - 1) % len(_DONUT_COLORS)]}"></i>'
            f'{escape(point.subject or point.label)}</span>'
            f'<b>{escape(_format_number(point.value))}%</b></div>'
            for index, point in enumerate(ordered, 1)
        )
        remainder = 100 - total
        note = (
            f'<p class="ts-factor-note">명시 항목 합계 {_format_number(total)}% · '
            f'미명시 {_format_number(remainder)}%</p>' if remainder > SHARE_SUM_TOLERANCE else ""
        )
        st.markdown(
            f'<section class="ts-composition"><div class="ts-block-title">{escape(whole)}</div>'
            f'<div class="ts-composition-rail">{segments}</div>{rows}{note}</section>',
            unsafe_allow_html=True,
        )


def render_ranking_list(
    metric_points: list[Any], grounded_claims: list[Any] | None = None,
    comparison_points: list[Any] | None = None, limit: int = 7,
    group_limit: int | None = None,
    show_insight: bool = True,
    question: str = "",
    preferred_entities: list[str] | None = None,
) -> None:
    """Compact exact-value ranking for long categorical comparisons."""
    # A long list earns this compact block. Once earned, keep the other
    # categorical series from the same evidence pool in the same card too:
    # e.g. five platforms plus three content genres. Splitting the shorter
    # companion into a second bar card repeats context and loses the source's
    # own relationship between the two comparisons.
    metric_triggers = ranking_list_groups(metric_points)
    comparison_groups = ranking_comparison_groups(comparison_points or [])
    if not metric_triggers and not comparison_groups:
        return
    def normalized(value: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]+", "", (value or "").casefold())

    question_tokens = {
        normalized(token) for token in re.findall(r"[A-Za-z0-9가-힣]+", question)
        if len(normalized(token)) >= 2
    }
    preferred = {normalized(value) for value in (preferred_entities or []) if normalized(value)}

    def group_score(group: list[Any]) -> tuple[int, int, int, int]:
        items, _ = split_aggregate(group)
        label = normalized(group[0].label if group else "")
        subjects = [normalized(getattr(point, "subject", "") or point.period) for point in items]
        entity_hits = sum(
            1 for subject in subjects
            if any(entity in subject or subject in entity for entity in preferred)
        )
        question_hits = sum(1 for token in question_tokens if token and token in label)
        item_count = len(items)
        fit = 2 if 3 <= item_count <= 5 else 1 if item_count >= 2 else 0
        dated = sum(1 for point in items if is_time_period(point.period))
        return entity_hits, question_hits, fit, dated

    metric_groups = sorted(item_bar_groups(metric_points), key=group_score, reverse=True)
    rendered_entity_sets: list[set[str]] = []
    rendered_groups = 0
    for group in metric_groups:
        if group_limit is not None and rendered_groups >= group_limit:
            break
        items, total = split_aggregate(group)
        if len(items) < 3:
            continue
        rendered_entity_sets.append({point.subject for point in items if point.subject})
        ordered = sorted(items, key=lambda point: point.value, reverse=True)[:limit]
        if len(ordered) < 2:
            continue
        peak = max(abs(point.value) for point in ordered) or 1
        unit = ordered[0].unit or ""
        # The total is written at the ranking's own scale so "전체" and the
        # rows it totals are the same kind of number.
        rank_scale = scale_for(
            [point.value for point in ordered] + ([total.value] if total else []), unit,
        )
        rows = "".join(
            f'<div class="ts-ranking-row"><span class="rank">{index:02d}</span>'
            f'<span class="label">{escape(point.subject or point.period)}</span>'
            f'<span class="track"><i style="width:{abs(point.value) / peak * 100:.1f}%;'
            f'background:{series_color(index - 1, len(ordered))}"></i></span>'
            f'<b>{escape(joined_value(point.value, unit, rank_scale))}</b></div>'
            for index, point in enumerate(ordered, 1)
        )
        total_note = (
            '<span class="ts-chart-unit">전체 '
            f'{escape(joined_value(total.value, total.unit or unit, rank_scale))}</span>'
            if total else ""
        )
        st.markdown(
            f'<section class="ts-ranking"><div class="ts-chart-head"><b>{escape(ordered[0].label)}</b>'
            f'{total_note}</div>{rows}</section>', unsafe_allow_html=True,
        )
        if show_insight:
            render_metric_insight(ordered, grounded_claims)
        rendered_groups += 1

    for group in comparison_groups:
        if group_limit is not None and rendered_groups >= group_limit:
            break
        entity_set = {point.entity for point in group}
        if any(entity_set <= rendered for rendered in rendered_entity_sets):
            continue

        def numeric_value(point: Any) -> float | None:
            match = re.search(r"-?\d+(?:\.\d+)?", point.value or "")
            return float(match.group()) if match else None

        values = [(point, numeric_value(point)) for point in group]
        ordered = sorted(
            values,
            key=lambda row: row[1] if row[1] is not None else float("-inf"),
            reverse=True,
        )[:limit]
        peak = max((abs(value) for _, value in ordered if value is not None), default=1) or 1
        rows = "".join(
            f'<div class="ts-ranking-row"><span class="rank">{index:02d}</span>'
            f'<span class="label">{escape(point.entity)}</span>'
            f'<span class="track"><i style="width:{abs(value) / peak * 100:.1f}%;'
            f'background:{series_color(index - 1, len(ordered))}"></i></span>'
            f'<b>{escape(point.value)}</b></div>'
            if value is not None else
            f'<div class="ts-ranking-row"><span class="rank">{index:02d}</span>'
            f'<span class="label">{escape(point.entity)}</span><span class="track"></span>'
            f'<b>{escape(point.value)}</b></div>'
            for index, (point, value) in enumerate(ordered, 1)
        )
        st.markdown(
            f'<section class="ts-ranking"><div class="ts-chart-head">'
            f'<b>{escape(group[0].criterion)}</b></div>{rows}</section>',
            unsafe_allow_html=True,
        )
        rendered_groups += 1


def render_benchmark_table(comparison_points: list[Any], metric_points: list[Any]) -> None:
    """Shared qualitative and numeric dimensions across countries/companies."""
    entities, dimensions, cells = benchmark_grid(comparison_points, metric_points)
    if len(entities) < 2 or len(dimensions) < 2:
        return
    header = "".join(f'<th>{escape(dimension)}</th>' for dimension in dimensions)
    rows = "".join(
        f'<tr><th>{escape(entity)}</th>' + "".join(
            f'<td>{escape(cells.get((dimension, entity), "—"))}</td>' for dimension in dimensions
        ) + '</tr>'
        for entity in entities
    )
    st.markdown(
        f'<div class="ts-benchmark-wrap"><table class="ts-benchmark"><thead><tr><th>경쟁사</th>'
        f'{header}</tr></thead><tbody>{rows}</tbody></table></div>', unsafe_allow_html=True,
    )


_SERIES_COLORS = SERIES_PALETTE
_GROUPED_BAR_HEIGHT = 132


_COLUMN_BAR_MIN_ITEMS = 3


def render_metric_columns(points_for_one_label: list[Any]) -> None:
    """One metric across three or more items, drawn as columns.

    Same data the row layout takes; the difference is only that a wide set of
    items is easier to compare against a shared baseline than down a column of
    tracks. Scaled against the largest item, and the stated whole - where the
    evidence gave one - is a caption rather than a fourth bar.
    """
    items, total = split_aggregate(points_for_one_label)
    ordered = sorted(items, key=lambda point: abs(point.value), reverse=True)
    unit = ordered[0].unit or ""
    # Where the evidence stated a whole, the bars are drawn against it and it
    # becomes a marked ceiling on the plot. Scaling to the tallest item
    # instead makes the leader touch the top of the chart whatever it is
    # worth - 78.8% out of a stated 93.2% looked identical to 78.8% out of
    # 100%, and the stated whole survived only as a line of caption text.
    ceiling = abs(total.value) if total and abs(total.value) >= max(
        abs(point.value) for point in ordered
    ) else 0.0
    peak = ceiling or max(abs(point.value) for point in ordered) or 1
    # Bars, the stated whole, and the gridlines all read against one scale.
    axis_top, ticks = _bar_axis(peak)
    labels = metric_axis_labels(ordered)
    # Bars, the stated whole and the axis ticks share one scale, so the unit
    # is stated once in the caption and the bar labels carry only the number
    # plus its magnitude word.
    column_scale = scale_for([*(point.value for point in ordered), axis_top], unit)
    columns = "".join(
        f'<div class="ts-gbar-col"><div class="ts-gbar-stack">'
        f'<i style="height:{abs(point.value) / axis_top * 100:.1f}%;'
        f'background:{series_color(position, len(ordered))}" '
        f'title="{escape(joined_value(point.value, unit, column_scale))}"></i>'
        f'<b class="ts-gbar-value">{escape(scaled_number(point.value, column_scale))}</b></div>'
        f'<span>{escape(label)}</span></div>'
        for position, (point, label) in enumerate(zip(ordered, labels))
    )
    ceiling_markup = (
        f'<div class="ts-gbar-ceiling" style="bottom:{ceiling / axis_top * 100:.1f}%">'
        f'<span>전체 {escape(joined_value(total.value, total.unit or unit, column_scale))}'
        '</span></div>' if ceiling else ""
    )
    # The artwork's bars stand on a dashed grid with a labelled axis, which is
    # what lets a reader read a bar's value off the chart instead of only
    # comparing it to its neighbours. The ticks are the same round numbers the
    # line chart uses, so the two blocks agree on what a scale looks like.
    axis = "".join(
        f'<span style="bottom:{tick / axis_top * 100:.1f}%">'
        f'{escape(scaled_number(tick, column_scale))}</span>'
        for tick in ticks
    )
    grid = f'<div class="ts-gbar-axis">{axis}</div>' if axis else ""
    # The period belongs in the caption line, never on the axis: it is the
    # same for every bar here, so repeating it under each one says nothing
    # while competing with the labels that do.
    notes = " · ".join(
        part for part in (
            f"단위: {escape(column_scale[1])}{escape(unit)}" if unit else "",
            f"{escape(ordered[0].period)} 기준" if ordered[0].period else "",
            # Drawn as a ceiling instead when the bars are scaled to it.
            f"전체 {escape(joined_value(total.value, total.unit or '', column_scale))}"
            if total and not ceiling else "",
        ) if part
    )
    unit_note = f'<span class="ts-chart-unit">{notes}</span>' if notes else ""
    st.markdown(
        f'<div class="ts-chart"><div class="ts-chart-head"><b>{escape(ordered[0].label)}</b>'
        f'{unit_note}</div>'
        f'<div class="ts-gbar single has-axis" style="height:{_GROUPED_BAR_HEIGHT}px">'
        f'{grid}{ceiling_markup}{columns}</div></div>',
        unsafe_allow_html=True,
    )


def render_grouped_bars(metric_points: list[Any]) -> None:
    """Two or more subjects compared across the same categories.

    The third axis the data has carried since `subject` was added, and the
    only block that can show it: one metric, several subjects, several
    categories. Bars are scaled against the largest value in the group, and a
    category no one measured everyone on never reaches here (`grouped_bar_series`).
    """
    for label, categories, by_subject in grouped_bar_series(metric_points):
        subjects = list(by_subject)[:len(_SERIES_COLORS)]
        all_values = [
            point.value for subject in subjects for point in by_subject[subject]
        ]
        peak = max(abs(value) for value in all_values) or 1
        unit = next(
            (point.unit for subject in subjects for point in by_subject[subject] if point.unit), ""
        )
        scale = scale_for(all_values, unit)
        legend = "".join(
            f'<span class="ts-chart-key"><i style="background:{_SERIES_COLORS[index]}"></i>'
            f'{escape(subject)}</span>'
            for index, subject in enumerate(subjects)
        )
        columns = ""
        for position, category in enumerate(categories):
            bars = "".join(
                f'<i style="height:{abs(by_subject[subject][position].value) / peak * 100:.1f}%;'
                f'background:{_SERIES_COLORS[index]}" '
                f'title="{escape(subject)} '
                f'{escape(joined_value(by_subject[subject][position].value, unit, scale))}"></i>'
                for index, subject in enumerate(subjects)
            )
            columns += (
                f'<div class="ts-gbar-col"><div class="ts-gbar-stack">{bars}</div>'
                f'<span>{escape(category)}</span></div>'
            )
        unit_note = (
            f'<span class="ts-chart-unit">단위: {escape(scale_prefixed_unit(unit, scale[1]))}</span>'
            if unit else ""
        )
        st.markdown(
            f'<div class="ts-chart"><div class="ts-chart-head"><b>{escape(label)}</b>{unit_note}</div>'
            f'<div class="ts-chart-legend">{legend}</div>'
            f'<div class="ts-gbar" style="height:{_GROUPED_BAR_HEIGHT}px">{columns}</div></div>',
            unsafe_allow_html=True,
        )


def render_entity_attribute_bars(groups: list[tuple[str, list[Any]]]) -> None:
    """Two or more subjects, each its own small bar panel of its own
    distinct attributes - "롱폼 콘텐츠: 깊이감 71.1%, 전문지식 68.4%" beside
    "숏폼 콘텐츠: 가성비 구독 64.7%, 광고 요금제 34.8%".

    `entity_attribute_groups` only groups subjects whose attributes don't
    overlap at all, so there is no shared category axis for a crosstab -
    unlike `render_grouped_bars`, each subject gets its own panel, placed
    side by side rather than merged into one chart. Reuses `.ts-bar-compare`'s
    row markup, the same one `render_metric_bar` draws a single subject's
    bars with, so a reader sees the same bar language everywhere on the page.
    """
    if not groups:
        return
    columns = st.columns(len(groups), gap="small")
    for column, (subject, points) in zip(columns, groups):
        with column:
            ordered = sorted(points, key=lambda point: abs(point.value), reverse=True)
            unit = ordered[0].unit or ""
            max_value = max(abs(point.value) for point in ordered) or 1
            bar_scale = scale_for([point.value for point in ordered], unit)
            rows = "".join(
                f'<div class="ts-bar-compare-row"><span class="period">{escape(point.label)}</span>'
                f'<div class="ts-bar-compare-track"><div class="ts-bar-compare-fill" '
                f'style="--pct:{abs(point.value) / max_value * 100:.1f}%;'
                f'background:{series_color(index, len(ordered))}"></div></div>'
                f'<span class="value">{escape(joined_value(point.value, unit, bar_scale))}</span></div>'
                for index, point in enumerate(ordered)
            )
            st.markdown(
                f'<div class="ts-bar-compare"><b>{escape(subject)}</b>{rows}</div>',
                unsafe_allow_html=True,
            )


_STATUS_TONE = {"high": "high", "medium": "medium", "low": "low"}
_KPI_ROW_LAYOUT_MAX = 2


def render_level_matrix(comparison_points: list[Any]) -> None:
    """The artwork's Competitor Analysis grid: criteria down, entities across.

    Each cell is a coloured dot *and* the grade word - the colour is a second
    channel, never the only one carrying the value, same rule the status band
    follows. A criterion an entity was never graded on stays blank rather than
    being filled with a middle grade.
    """
    entities, criteria, cells = level_matrix(comparison_points or [])
    if len(entities) < 2 or len(criteria) < 2:
        return
    header = "".join(f"<th>{escape(entity)}</th>" for entity in entities)
    rows = ""
    for criterion in criteria:
        body = ""
        for entity in entities:
            cell = cells.get((criterion, entity))
            if cell is None:
                body += '<td class="ts-level-empty">-</td>'
                continue
            level, value = cell
            body += (
                f'<td class="{_STATUS_TONE[level]}" title="{escape(value)}">'
                f'<i></i>{escape(level.capitalize())}</td>'
            )
        rows += f"<tr><th>{escape(criterion)}</th>{body}</tr>"
    st.markdown(
        f'<table class="ts-level-grid"><thead><tr><th></th>{header}</tr></thead>'
        f"<tbody>{rows}</tbody></table>",
        unsafe_allow_html=True,
    )


def render_status_bar(comparison_points: list[Any]) -> None:
    """Graded standings across one row, the qualitative twin of the KPI row.

    Shows only what a document actually graded. The grade word is always
    printed beside its colour - the colour is a second channel, never the
    only one carrying the value.
    """
    rows = status_levels(comparison_points or [])
    if len(rows) < 2:
        return
    cells = "".join(
        f'<div class="ts-status-cell {_STATUS_TONE[level]}">'
        f'<small>{escape(criterion)}</small>'
        f'<b>{escape(detail)}</b>'
        f'<span class="ts-status-level">{escape(level.upper())}</span></div>'
        for criterion, detail, level in rows
    )
    st.markdown(f'<div class="ts-status-bar">{cells}</div>', unsafe_allow_html=True)


def render_competitor_panels(
    comparison_points: list[Any], metric_points: list[Any]
) -> None:
    """One panel per named competitor, built only from what is attributable
    to that competitor.

    Three sections where the evidence has them - the criteria a document
    graded, figures whose `subject` is this entity, and this entity's slice of
    a stated whole - and nothing where it doesn't. The artwork's per-company
    process rail is absent on purpose: nothing dates a claim to a competitor,
    and building one from the report's own chronology would hand this
    company's milestones to a rival.
    """
    panels = competitor_panels(comparison_points or [], metric_points or [])
    if not panels:
        return
    columns = st.columns(len(panels))
    for column, (entity, graded, figures, share) in zip(columns, panels):
        with column:
            rows = "".join(
                f'<div class="ts-panel-row"><span>{escape(criterion)}</span>'
                + (f'<b class="ts-dot {level}"></b>' if level else "")
                + f'<span class="ts-panel-value">{escape(value)}</span></div>'
                for criterion, value, level in graded
            )
            figure_rows = "".join(
                f'<div class="ts-panel-figure"><small>{escape(point.label)}</small>'
                f'<b>{escape(joined_value(point.value, point.unit))}</b></div>'
                for point in figures
            )
            share_row = (
                f'<div class="ts-panel-share"><small>{escape(share.share_of or "구성비")}</small>'
                f'<b>{escape(joined_value(share.value, "%"))}</b></div>'
                if share else ""
            )
            st.markdown(
                f'<div class="ts-panel"><div class="ts-panel-name">{escape(entity)}</div>'
                f'{rows}{figure_rows}{share_row}</div>',
                unsafe_allow_html=True,
            )


def render_landscape(
    metric_points: list[Any],
    grounded_claims: list[Any] | None = None,
    title: str | None = None,
) -> None:
    """The artwork's Landscape: the trend on the left, what the total is made
    of on the right.

    Two blocks that already stand alone, placed in one card because a reader
    comparing "which way is it going" against "what is it made of" should not
    have to hold one in their head while scrolling to the other. Neither half
    is derived from the other, and if either stops qualifying the card falls
    back to whichever half still does.
    """
    parts = landscape_parts(metric_points)
    if parts is None:
        return
    core_kind, core_points, complement_kind, complement_points = parts
    st.markdown(
        '<div class="ts-landscape-head ts-landscape">'
        f'<b>{escape(title or block_title("landscape"))}</b></div>',
        unsafe_allow_html=True,
    )
    if complement_kind == "kpi":
        # A bare KPI reading is not a composition of the trend beside it -
        # live-verified 2026-08-11: `landscape_parts` falls back to this when
        # no real share/comparison data qualifies, and squeezing 3 KPI cards
        # into the composite's companion column read as "KPI cards trapped
        # inside the trend chart's card" rather than the trend+composition
        # pairing this block exists for. Those same points are still in
        # `synthesis.metric_series` and undrawn, so the Key Metrics slot
        # picks them up on its own - this just stops double-homing them here.
        if core_kind == "trend":
            render_metric_chart(
                core_points, title=block_title("chart"), grounded_claims=grounded_claims,
                show_insight=False,
            )
        else:
            render_kpi_row(core_points, limit=4)
        return
    # One card, so one gap. The default column gap put a full gutter between
    # the trend and the composition of that same trend, and the two halves
    # read as two cards that happened to be adjacent - which is the opposite
    # of why they were put together.
    # 2:1 rather than the earlier 1.35:1 - live-verified 2026-08-11, the
    # donut+legend column was reading wider than the ring/labels inside it
    # actually needed once the card itself narrowed (see `_BLOCK_UNITS`),
    # leaving the trend chart cramped for no reason.
    trend, split = st.columns([2, 1], gap="small")
    with trend:
        if core_kind == "trend":
            render_metric_chart(
                core_points, title=block_title("chart"), grounded_claims=grounded_claims,
                show_insight=False,
            )
        else:
            render_kpi_row(core_points, limit=4)
    with split:
        if complement_kind == "share":
            render_share_split(complement_points)
        else:
            render_metric_bar(complement_points, grounded_claims, show_insight=False)


def render_decision_matrix(comparison_points: list[Any]) -> None:
    """Two-axis placement using only stated numeric values or stated levels."""
    matrix = decision_matrix(comparison_points)
    if matrix is None:
        return
    entities, x_axis, y_axis, cells = matrix
    dots = "".join(
        f'<div class="ts-decision-dot" style="left:{8 + x * 84:.1f}%;bottom:{8 + y * 78:.1f}%" '
        f'title="{escape(entity)} · {escape(x_axis)} {escape(x_text)} · '
        f'{escape(y_axis)} {escape(y_text)}"><i></i><span>{escape(entity)}</span></div>'
        for entity, (x, y, x_text, y_text) in cells.items()
    )
    legend = "".join(
        f'<li><b>{escape(entity)}</b><span>{escape(x_axis)} {escape(cells[entity][2])} · '
        f'{escape(y_axis)} {escape(cells[entity][3])}</span></li>'
        for entity in entities
    )
    st.markdown(
        '<div class="ts-decision-matrix">'
        f'<div class="ts-decision-y">{escape(y_axis)}</div>'
        f'<div class="ts-decision-plane">{dots}</div>'
        f'<div class="ts-decision-x">{escape(x_axis)}</div>'
        f'<ul class="ts-decision-legend">{legend}</ul></div>',
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


def render_recurring_terms(grounded_claims: list[Any], limit: int = 8) -> None:
    """Words several separate documents used, with how many used each.

    A count of the evidence, not a reading of it. The number beside a term is
    the number of distinct documents it appeared in, and clicking through
    lands on a real claim containing it - so a reader can check the word
    rather than take the list on faith. No weighting, no sentiment, no
    inference about why a word recurs.
    """
    terms = recurring_terms(grounded_claims or [], limit=limit)
    if not terms:
        return
    # How the count was arrived at is a caveat, not a finding, and it was
    # taking three lines of body text under a block whose whole content is a
    # word count. It belongs where a reader goes looking for it - on the
    # chip - not in the reading flow ahead of the analysis.
    method = "이 표현이 등장한 서로 다른 출처 문서의 수. 빈도만 센 것이며 중요도 판단이 아닙니다."
    chips = "".join(
        f'<span class="ts-term" title="{escape(clean_citation(claim.claim))}">'
        f'{escape(term)}<b title="{escape(method)}">{count}</b></span>'
        for term, count, claim in terms
    )
    st.markdown(
        f'<div class="ts-terms ts-terms-quiet" title="{escape(method)}">{chips}</div>',
        unsafe_allow_html=True,
    )


def _claim_link(claim: Any) -> str:
    """A small inline arrow, not the 27px round `ts-evidence-link` badge -
    inside a cause-tree pill that badge is nearly as tall as the pill itself
    and pushes the label out of it."""
    url = getattr(claim, "source_url", None)
    return (
        f'<a class="ts-inline-evidence" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
        if url else ""
    )


def _cause_node_markup(node: dict, depth: int) -> str:
    """One outlined pill plus whatever the evidence says followed from it.

    Recursive so a document that stated a three-link chain shows three links;
    the depth cut lives in `cause_forest`, not here.
    """
    claim = node["claim"]
    children = "".join(_cause_node_markup(child, depth + 1) for child in node["children"])
    nested = f'<div class="ts-cause-sub">{children}</div>' if children else ""
    return (
        f'<div class="ts-cause-item">'
        f'<span class="ts-cause-pill">{escape(clean_citation(claim.claim))}{_claim_link(claim)}</span>'
        f'{nested}</div>'
    )


def render_cause_tree(grounded_claims: list[Any]) -> None:
    """Root cause, what it drove, and what that drove - as the artwork lays it
    out: one filled pill on top, its branches side by side beneath a shared
    rule, and each branch's own consequences stacked under it.

    The branch row is a wrapping grid rather than a fixed three columns, so
    two causes don't leave a hole and six don't run off the card - which is
    the whole reason this is CSS and not a copy of the SVG's geometry.

    Drawn only from `parent_synthesis_claim_id` links that survived the
    analyzer's verification; a document that never stated a causal chain
    produces no tree, and the flat claim list stays the honest rendering.
    """
    forest = cause_forest(grounded_claims or [])
    if not forest:
        return
    trees = ""
    for root in forest:
        branches = "".join(_cause_node_markup(branch, 2) for branch in root["children"])
        trees += (
            f'<div class="ts-cause-tree-root">'
            f'<span class="ts-cause-root">'
            f'{escape(clean_citation(root["claim"].claim))}{_claim_link(root["claim"])}</span>'
            f'<div class="ts-cause-branches">{branches}</div></div>'
        )
    st.markdown(
        f'<section class="ts-cause-tree"><div class="ts-block-title">{escape(block_title("cause_tree"))}</div>'
        f'{trees}</section>',
        unsafe_allow_html=True,
    )


def render_importance_bars(
    grounded_claims: list[Any], impact_target: str | None = None, limit: int = 5,
    compact: bool = False,
) -> None:
    """Claims ranked by the model's stated importance.

    Every bar carries an "AI 판단" badge and the reason the score was given,
    because the number is a judgement and not a measurement - a score with no
    reason attached never reaches this function (the analyzer discards it).
    Bars are scaled against 100, not against the top row, so a set of claims
    the model thought were all middling doesn't render as one dominant driver.
    """
    ranked = importance_ranked(grounded_claims or [], limit=limit)
    # Two bars of equal length are not a ranking, and a card headed 영향도
    # whose every row reads 100 tells the reader only that the model declined
    # to choose. `has_importance_ranking` refuses these at slot resolution;
    # this is the same rule where the drawing happens.
    if len(ranked) < 2 or len({claim.importance for claim in ranked}) < 2:
        return
    # The reason is printed, not hidden behind a tooltip. A score the reader
    # can see and a justification they have to hover to find is exactly the
    # arrangement that lets a judgement read as a measurement - and on a touch
    # screen the hover never happens at all.
    rows = "".join(
        f'<div class="ts-driver-row">'
        f'<span class="label" title="{escape(clean_citation(claim.claim))}">'
        f'{escape(clean_citation(claim.claim))}</span>'
        f'<span class="ts-driver-track"><i style="width:{claim.importance}%"></i></span>'
        f'<span class="value">{claim.importance}</span>{_claim_link(claim)}</div>'
        + (
            f'<div class="ts-action-basis" title="{escape(clean_citation(claim.importance_basis))}">'
            f'{escape(clean_citation(claim.importance_basis))}</div>'
            if claim.importance_basis and not compact else ""
        )
        for claim in ranked
    )
    target = (
        f'<p class="ts-driver-target"><span class="ts-ai-badge">AI 판단</span> '
        f'<b>영향 기준</b> {escape(impact_target)}</p>'
        if impact_target else '<p class="ts-driver-target"><span class="ts-ai-badge">AI 판단</span></p>'
    )
    note = (
        '<p class="ts-drivers-note">AI가 근거 문서 안에서 매긴 상대적 중요도이며 측정값이 아닙니다.</p>'
        if compact else
        '<p class="ts-drivers-note">근거 문서가 제시한 수치가 아니라 모델이 매긴 상대적 중요도입니다. '
        '각 항목 아래에 그렇게 본 이유를 함께 적었습니다.</p>'
    )
    st.markdown(
        # No repeated ".ts-block-title" line here anymore - live-verified
        # 2026-08-11: whenever this block renders as a slot's *companion*
        # (not its lead), the outer card header already reads
        # block_title("driver_bars") ("Ranked by Relevance") via
        # generic_dashboard.py's `_render_slot`, so printing that exact
        # string again inside the card body was a plain duplicate. The
        # AI-judgement badge and the basis line are what actually add
        # information, not a second copy of the card's own name.
        '<section class="ts-drivers">' + target +
        note + rows + "</section>",
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
    # The artwork fills under the line with a fading wash of the line's own
    # colour. It carries no extra claim - the shape is the same shape - but it
    # is what makes a 26px sparkline read as a trend rather than as a scratch.
    # The tint follows direction only, never good/bad: whether a rise is
    # welcome is metric-specific and the evidence never says which.
    gradient_id = f"tsSpark{abs(hash(tuple(values))) % 100000}"
    area = (
        f'<polygon points="0,30 {coords} 100,30" fill="url(#{gradient_id})"/>'
        if len(values) > 2 else ""
    )
    return (
        f'<svg class="ts-kpi-spark" viewBox="0 0 100 30" preserveAspectRatio="none">'
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{stroke}" stop-opacity=".28"/>'
        f'<stop offset="1" stop-color="{stroke}" stop-opacity="0"/></linearGradient></defs>'
        f'{area}<polyline points="{coords}" fill="none" stroke="{stroke}" stroke-width="2" '
        f'vector-effect="non-scaling-stroke"/></svg>'
    )


# The grid is auto-fill, so the count decides the shape rather than the shape
# deciding how many figures get shown: one or two become full-width rows,
# three to six fill the card grid at whatever width fits. The cap exists only
# so a run that extracted thirty figures doesn't turn the report into a wall
# of numbers - it is not a target to pad up to.
_KPI_MAX_CARDS = 6
_VALUE_TYPE_LABELS = {
    "estimate": "추정", "forecast": "전망", "target": "목표", "guidance": "가이던스",
}


def render_kpi_row(
    metric_points: list[Any],
    limit: int = _KPI_MAX_CARDS,
    question_terms: list[str] | None = None,
    compact: bool = False,
) -> None:
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
        value_type = getattr(latest, "value_type", "forecast" if getattr(latest, "is_forecast", False) else "actual")
        type_label = _VALUE_TYPE_LABELS.get(value_type)
        forecast_tag = (
            f'<span class="ts-kpi-forecast">{escape(type_label)}</span>' if type_label else ""
        )
        # One scale for the headline and its delta, or a card would say
        # 2,154만 above +12만 above -  two magnitudes of the same series.
        # The unit becomes its own element: `21,535,256단말장치・단자` ran the
        # digits straight into a word, and gluing 만 onto it would have made
        # that worse ("2,154만단말장치・단자" reads as a unit named 만단말장치).
        card_scale = scale_for(
            [point.value for point in points], latest.unit,
        )
        value_number, value_unit = display_value(latest.value, latest.unit, card_scale)
        value_text = (
            f'{escape(value_number)}'
            + (
                f'<span class="ts-kpi-unit">{escape(value_unit)}</span>'
                if unit_needs_space(value_unit)
                else escape(value_unit)
            )
        )
        if is_chronological and len(observed) >= 2:
            delta = latest.value - observed[0].value
            sign = "+" if delta >= 0 else ""
            delta_text = joined_value(delta, latest.unit, card_scale)
            caption_text = (
                f"{sign}{escape(delta_text)} "
                f"({escape(observed[0].period)}→{escape(latest.period)})"
            )
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
            f'<div class="ts-kpi-figure"><b>{value_text}{forecast_tag}</b>'
            f'<small class="ts-kpi-delta">{caption_text}</small></div>{spark}</div>'
        )
    # The artwork ships the KPI block in several densities, and which one fits
    # is a question about how much data arrived: one or two figures in a
    # four-up grid leave two empty tracks, which reads as missing data rather
    # than as a short list. Two or fewer switch to the artwork's row variant -
    # full-width tinted rows, label left, figure right - and three or more
    # keep the card grid.
    layout = (
        "ts-kpi-row compact" if compact
        else "ts-kpi-row rows" if len(cards) <= _KPI_ROW_LAYOUT_MAX
        else "ts-kpi-row"
    )
    st.markdown(f'<div class="{layout}">{"".join(cards)}</div>', unsafe_allow_html=True)


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






def render_metric_comparison(
    period: str, points: list[Any], limit: int | None = None,
) -> None:
    """Horizontal bars comparing several metrics measured in the same unit at
    the same point in time. Bar length is the real value against the largest
    in the group - not a rank-derived width."""
    if len(points) < 2:
        return
    ordered = sorted(points, key=lambda point: point.value, reverse=True)
    if limit is not None:
        ordered = ordered[:limit]
    units = {(point.unit or "").strip() for point in ordered}
    if len(units) > 1:
        # Each row is its own metric here (different units can't share a
        # scale), so every row picks its own scale via display_value/
        # joined_value's default rather than the group-wide `scale` param.
        rows = "".join(
            f'<div class="ts-metric-snapshot-row"><span>{escape(point.label)}</span>'
            f'<b>{escape(joined_value(point.value, point.unit))}</b></div>'
            for point in ordered
        )
        st.markdown(
            f'<div class="ts-metric-snapshot"><b>{escape(period)}</b>{rows}</div>',
            unsafe_allow_html=True,
        )
        return
    unit = ordered[0].unit or ""
    scale = scale_for([point.value for point in ordered], unit)
    largest = max(abs(point.value) for point in ordered) or 1
    rows = "".join(
        f'<div class="ts-compare-row"><span class="label">{escape(point.label)}</span>'
        f'<div class="ts-compare-track"><div class="ts-compare-fill" '
        f'style="--pct:{abs(point.value) / largest * 100:.1f}%"></div></div>'
        f'<span class="value">{escape(joined_value(point.value, unit, scale))}</span></div>'
        for point in ordered
    )
    st.markdown(
        f'<div class="ts-compare"><b>{escape(period)}</b>{rows}</div>',
        unsafe_allow_html=True,
    )


# A full year+quarter/month label, a bare year, and an apostrophe year
# ("'24년" - standard in Korean financial copy) all pin a point in time.






_STATUS_LABELS = {"done": "완료", "active": "진행", "todo": "예정"}
_HORIZONTAL_TIMELINE_MAX_STEPS = 5
_HORIZONTAL_TIMELINE_MAX_CHARS = 22
_TIMELINE_METHOD_RE = re.compile(
    r"표본|조사\s*대상|응답자|대면\s*면접|실시한.{0,20}조사|"
    r"조사.{0,50}(?:국민|명)|sample|respondents?|surveyed",
    re.IGNORECASE,
)


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
    # A timeline gets one axis. Prefer one metric definition observed at
    # several dates; if none exists, show dated evidence events only. Mixing
    # one-off KPIs into an event rail is what produced a sequence of survey
    # size -> viewing hours -> usage rate with no common meaning.
    dated_by_label = {
        label: [point for point in points if is_time_period(point.period)]
        for label, points in group_metric_points_by_label(metric_points).items()
    }
    series = max(
        (points for points in dated_by_label.values() if len({p.period for p in points}) >= 2),
        key=lambda points: len({p.period for p in points}),
        default=None,
    )
    if series:
        basis = series[0].label
        raw_entries = timeline_entries_with_status([], series, reference_year, as_of_date)
    else:
        basis = "출처에 날짜가 명시된 주요 사건"
        raw_entries = timeline_entries_with_status(evidence, [], reference_year, as_of_date)
    entries = [entry for entry in raw_entries if not _TIMELINE_METHOD_RE.search(entry[1])]
    deduped: list[tuple[str, str, str]] = []
    seen_timeline: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry[0], re.sub(r"\W+", "", entry[1]).casefold()[:60])
        if key in seen_timeline:
            continue
        seen_timeline.add(key)
        deduped.append(entry)
    entries = deduped[:limit]
    if not entries:
        return
    st.markdown(
        f'<div class="ts-chart-unit">기준 · {escape(basis)}</div>',
        unsafe_allow_html=True,
    )
    # The artwork has both a horizontal rail and a vertical one, and which
    # fits is a property of the data: five short stage labels read across the
    # page, but a row of full evidence sentences does not. Long text or many
    # steps take the vertical rail, which can give each row a full line.
    if len(entries) <= _HORIZONTAL_TIMELINE_MAX_STEPS and all(
        len(text) <= _HORIZONTAL_TIMELINE_MAX_CHARS for _, text, _ in entries
    ):
        nodes = "".join(
            f'<div class="ts-htimeline-step {status}">'
            f'<span class="ts-htimeline-node"></span>'
            f'<b>{escape(period)}</b>'
            f'<span class="ts-htimeline-state">{_STATUS_LABELS[status]}</span>'
            f'<span class="ts-htimeline-text">{escape(text)}</span></div>'
            for period, text, status in entries
        )
        st.markdown(f'<div class="ts-htimeline">{nodes}</div>', unsafe_allow_html=True)
        return
    steps = "".join(
        f'<div class="ts-timeline-step {status}">'
        f'<b>{escape(period)}<span class="ts-step-state">{_STATUS_LABELS[status]}</span></b>'
        f'<span>{escape(text)}</span></div>'
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
