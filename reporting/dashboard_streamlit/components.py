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
        f'<div class="ts-top-question"><span class="search">⌕</span>{escape(question)}'
        f'<span class="ts-sk">SK</span></div>'
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
    """
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
    return len({point.period for point in metric_points}) >= 2


def has_comparison(comparison_points: list[Any]) -> bool:
    return len({point.entity for point in comparison_points}) >= 2


def render_metric_chart(metric_points: list[Any], title: str = "Market Trend") -> None:
    """Native Streamlit area chart for a real, evidence-backed metric series.

    Only call this when `has_timeseries()` is true. Groups by `label` so
    multiple series (e.g. IPTV vs. OTT) plot as separate lines/areas, x-axis
    is the evidence-stated `period` text as-is (no invented dates).
    """
    import pandas as pd

    frame = pd.DataFrame([point.model_dump() for point in metric_points])
    pivoted = frame.pivot_table(index="period", columns="label", values="value", aggfunc="first")
    st.markdown(f"**{escape(title)}**")
    st.area_chart(pivoted)


def render_swot(strengths: list[str], weaknesses: list[str], opportunities: list[str], threats: list[str]) -> str:
    def cell(label: str, values: list[str], empty: str) -> str:
        body = "".join(f"<p>• {escape(value)}</p>" for value in values) or f'<p class="ts-empty">{escape(empty)}</p>'
        return f"<div class=\"ts-swot-cell\"><h4>{escape(label)}</h4>{body}</div>"

    return (
        '<div class="ts-swot">'
        + cell("Strength", strengths, "근거에서 강점 신호가 확인되지 않았습니다.")
        + cell("Weakness", weaknesses, "근거에서 약점 신호가 확인되지 않았습니다.")
        + cell("Opportunity", opportunities, "확인된 기회 신호가 없습니다.")
        + cell("Threat", threats, "확인된 위협 신호가 없습니다.")
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


def render_footer_note(text: str | None) -> None:
    if not text:
        return
    st.markdown(
        f'<div class="ts-footer-note"><b>AI Monitoring Comment</b><span>{escape(text)}</span></div>',
        unsafe_allow_html=True,
    )
