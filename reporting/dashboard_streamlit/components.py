"""Shared, purpose-agnostic HTML component helpers for the dashboard UI.

Every purpose-specific view (issue_response_view, generic_dashboard) and the
generic block renderer (renderer.py) render through these so the visual
language (cards, tables, SWOT, action lists) stays identical no matter which
blocks a given question's report ends up using. Components only ever render
values already present on the result contracts — none of them invent a
number, a comparison, or a business fact that isn't backed by evidence.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

import streamlit as st

from common.content_quality_validator import (
    classify_metric_shape,
    filter_shared_comparison_axis,
    group_metric_points_by_label,
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
    """Every label's points where `classify_metric_shape` == "bar", one
    list per label, ready to pass individually to `render_metric_bar`."""
    by_label = group_metric_points_by_label(metric_points)
    return [points for points in by_label.values() if classify_metric_shape(points) == "bar"]


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
    import pandas as pd

    chartable_points = select_chartable_series(metric_points)
    if not chartable_points:
        return

    frame = pd.DataFrame([point.model_dump() for point in chartable_points])
    period_order = sorted(frame["period"].unique(), key=period_sort_key)
    pivoted = frame.pivot_table(index="period", columns="label", values="value", aggfunc="first")
    pivoted = pivoted.reindex(period_order)
    st.markdown(f"**{escape(title)}**")
    st.line_chart(pivoted, height=170)


def render_metric_bar(points_for_one_label: list[Any]) -> None:
    """Before/after comparison bar for a label with exactly 2 distinct
    periods (`classify_metric_shape` == "bar") - two points don't make a
    trend worth a line chart, but the real, evidence-stated change between
    them is still worth showing as a simple two-bar comparison. Only ever
    called with one label's points at a time (the caller loops per label),
    since two different labels are two different units/scales and don't
    belong on the same bar pair.
    """
    if len(points_for_one_label) < 2:
        return
    ordered = sorted(points_for_one_label, key=lambda p: period_sort_key(p.period))
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


def _impact_pct(rank: int) -> int:
    """Rank-based visual weight for the impact bar (priority order, not a fabricated score)."""
    return max(38, 92 - (rank - 1) * 16)


def render_action_list(rows: list[tuple[str, str, str | None]]) -> None:
    """`rows` = (title, impact_note, evidence_url) already resolved by the caller."""
    if not rows:
        st.markdown(
            '<section class="ts-actions"><h3>Recommended Actions</h3>'
            '<p class="ts-empty">근거에 연결된 권고 과제가 없습니다.</p></section>',
            unsafe_allow_html=True,
        )
        return
    body_parts = []
    for index, (title, impact_note, url) in enumerate(rows, 1):
        link = (
            f'<a class="ts-evidence-link" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
            if url
            else "<span></span>"
        )
        body_parts.append(
            f'<div class="ts-action-row"><span class="num">{index:02d}</span>'
            f'<span class="action">{escape(title)}</span>'
            f'<span title="{escape(impact_note)}"><small>{escape(impact_note)}</small>'
            f'<div class="ts-impact" style="--impact:{_impact_pct(index)}%"></div></span>{link}</div>'
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
        delta_html = f'<small class="ts-kpi-delta">{caption_text}</small>'
        cards.append(
            f'<div class="ts-kpi-card"><small>{escape(label)}</small><b>{escape(value_text)}</b>{delta_html}</div>'
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
