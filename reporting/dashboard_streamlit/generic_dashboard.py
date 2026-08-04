"""Compact, purpose-driven dashboard for non issue-response reports."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from reporting.dashboard_streamlit.components import (
    clean_citation,
    comparison_points_to_table,
    dedupe_clean,
    dedupe_raw,
    evidence_url,
    has_comparison,
    has_timeseries,
    render_action_list,
    render_comparison_table,
    render_executive_summary,
    render_footer_note,
    render_metric_chart,
    render_page_header,
    render_swot,
)

# Same 2-of-4 threshold layout_generator uses to decide a section is
# SWOT-worthy (core/layout_generator/generator.py:_candidate_content_types) -
# kept in sync so this view and the block-type contract agree on what counts.
_SWOT_QUALIFYING_FIELD_COUNT = 2


def _panel_definitions(purpose_id: str | None, synthesis: Any) -> list[tuple[str, str, list[str]]]:
    if purpose_id == "future_business":
        return [
            ("Trend Drivers", "trend", synthesis.key_points),
            ("Opportunity Map", "opportunity", synthesis.opportunities),
            ("Investment Signals", "signal", synthesis.business_impacts or synthesis.monitoring_indicators),
        ]
    if purpose_id == "root_cause":
        return [
            ("Problem Definition", "problem", synthesis.key_points),
            ("Cause Map", "cause", synthesis.risks),
            ("Improvement Plan", "action", synthesis.recommended_actions),
        ]
    return [
        ("Current Snapshot", "snapshot", synthesis.key_points),
        ("Market Signals", "signal", synthesis.business_impacts or synthesis.monitoring_indicators),
        ("Near-term Outlook", "timeline", synthesis.opportunities or synthesis.monitoring_indicators),
    ]


def _item_markup(raw_value: str, result: Any, index: int) -> str:
    url = evidence_url(raw_value, result)
    link = (
        f'<a class="ts-inline-evidence" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
        if url
        else ""
    )
    return (
        f'<li><span class="ts-item-index">{index:02d}</span>'
        f"<span>{escape(clean_citation(raw_value))}</span>{link}</li>"
    )


def render_generic_dashboard(
    result: Any,
    question: str,
    sector: str,
    audience: str,
    purpose: str,
    purpose_id: str | None,
) -> None:
    synthesis = result.synthesis
    report = result.generated_report
    summary = clean_citation((report.executive_summary if report else None) or synthesis.synthesis_text)
    risks = dedupe_clean(synthesis.risks, 3)
    opportunities = dedupe_clean(synthesis.opportunities, 3)
    strengths = dedupe_clean(synthesis.strengths, 3)
    weaknesses = dedupe_clean(synthesis.weaknesses, 3)

    render_page_header(question, sector, audience, purpose)
    render_executive_summary(summary, len(risks), len(opportunities))

    if has_timeseries(synthesis.metric_series):
        with st.container(border=True):
            render_metric_chart(synthesis.metric_series, title="확인된 수치 추이")

    if has_comparison(synthesis.comparison_points):
        with st.container(border=True):
            st.markdown('<div class="ts-card-inner"><h3>Comparison</h3></div>', unsafe_allow_html=True)
            headers, rows = comparison_points_to_table(synthesis.comparison_points)
            st.markdown(render_comparison_table(headers, rows), unsafe_allow_html=True)

    swot_field_count = sum(1 for field in (strengths, weaknesses, risks, opportunities) if field)
    if swot_field_count >= _SWOT_QUALIFYING_FIELD_COUNT:
        with st.container(border=True):
            st.markdown('<div class="ts-card-inner"><h3>SWOT</h3></div>', unsafe_allow_html=True)
            st.markdown(
                render_swot(strengths=strengths, weaknesses=weaknesses, opportunities=opportunities, threats=risks),
                unsafe_allow_html=True,
            )

    panels = []
    for title, panel_type, raw_values in _panel_definitions(purpose_id, synthesis):
        unique_raw = list(dict.fromkeys(raw_values or []))[:4]
        rows = "".join(_item_markup(value, result, index) for index, value in enumerate(unique_raw, 1))
        if not rows:
            rows = '<li class="ts-empty">검증된 신호가 없습니다.</li>'
        panels.append(
            f'<section class="ts-card ts-purpose-card {panel_type}"><h3>{escape(title)}</h3>'
            f'<ol class="ts-compact-list">{rows}</ol></section>'
        )
    st.markdown('<div class="ts-section-grid ts-purpose-grid">' + "".join(panels) + "</div>", unsafe_allow_html=True)

    actions = dedupe_raw(synthesis.recommended_actions, 4)
    action_rows = [
        (clean_citation(action), "Evidence-based priority", evidence_url(action, result)) for action in actions
    ]
    render_action_list(action_rows)

    monitoring = dedupe_clean(synthesis.monitoring_indicators, 1)
    render_footer_note(monitoring[0] if monitoring else None)
