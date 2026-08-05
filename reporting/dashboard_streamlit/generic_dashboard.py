"""Compact, purpose-driven dashboard for non issue-response reports."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from common.content_quality_validator import dedupe_across_blocks
from reporting.dashboard_streamlit.components import (
    bar_metric_groups,
    clean_citation,
    comparison_points_to_table,
    dedupe_clean,
    evidence_url,
    has_comparison,
    has_timeseries,
    prefer_audience_content,
    prefer_audience_content_raw,
    render_action_list,
    render_comparison_table,
    render_executive_summary,
    render_footer_note,
    render_kpi_row,
    render_metric_bar,
    render_metric_chart,
    render_page_header,
    render_source_list,
    render_swot,
)

# Same 2-of-4 threshold layout_generator uses to decide a section is
# SWOT-worthy (core/layout_generator/generator.py:_candidate_content_types) -
# kept in sync so this view and the block-type contract agree on what counts.
_SWOT_QUALIFYING_FIELD_COUNT = 2


def _panel_definitions(purpose_id: str | None, synthesis: Any, report: Any) -> list[tuple[str, str, list[str]]]:
    # `_raw` variant: downstream `_item_markup()` still needs the [doc_id=...]
    # marker intact to resolve an evidence URL, and strips it itself for display.
    key_points = prefer_audience_content_raw(report, "key_points", synthesis.key_points)
    opportunities = prefer_audience_content_raw(report, "opportunities", synthesis.opportunities)
    risks = prefer_audience_content_raw(report, "risks", synthesis.risks)
    actions = prefer_audience_content_raw(report, "actions", synthesis.recommended_actions)
    monitoring = prefer_audience_content_raw(report, "monitoring_indicators", synthesis.monitoring_indicators)
    if purpose_id == "future_business":
        return [
            ("Trend Drivers", "trend", key_points),
            ("Opportunity Map", "opportunity", opportunities),
            ("Investment Signals", "signal", synthesis.business_impacts or monitoring),
        ]
    if purpose_id == "root_cause":
        return [
            ("Problem Definition", "problem", key_points),
            ("Cause Map", "cause", risks),
            ("Improvement Plan", "action", actions),
        ]
    return [
        ("Current Snapshot", "snapshot", key_points),
        ("Market Signals", "signal", synthesis.business_impacts or monitoring),
        ("Near-term Outlook", "timeline", opportunities or monitoring),
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
    risks = prefer_audience_content(report, "risks", synthesis.risks, 3)
    opportunities = prefer_audience_content(report, "opportunities", synthesis.opportunities, 3)
    # strengths/weaknesses are never LLM-rewritten (see issue_response_view.py's
    # identical comment) - facts, not audience-tailored prose.
    strengths = dedupe_clean(synthesis.strengths, 3)
    weaknesses = dedupe_clean(synthesis.weaknesses, 3)

    question_terms = question.split()

    render_page_header(question, sector, audience, purpose)
    render_executive_summary(summary, len(risks), len(opportunities))
    render_kpi_row(synthesis.metric_series, question_terms=question_terms)

    bar_groups = bar_metric_groups(synthesis.metric_series)
    if has_timeseries(synthesis.metric_series) or bar_groups:
        with st.container(border=True):
            if has_timeseries(synthesis.metric_series):
                render_metric_chart(synthesis.metric_series, title="확인된 수치 추이")
            for group in bar_groups:
                render_metric_bar(group)

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

    panel_defs = _panel_definitions(purpose_id, synthesis, report)
    # Cross-block dedup: Current Snapshot/Market Signals/Near-term Outlook (or the
    # future_business/root_cause equivalents) draw from overlapping synthesis fields
    # by design, so the same fact often shows up reworded in 2+ panels - keep it in
    # whichever panel comes first, drop the near-duplicate restatement from the rest.
    deduped_lists = dedupe_across_blocks(
        [list(dict.fromkeys(raw_values or [])) for _, _, raw_values in panel_defs]
    )
    panels = []
    for (title, panel_type, _), unique_raw in zip(panel_defs, deduped_lists):
        unique_raw = unique_raw[:4]
        rows = "".join(_item_markup(value, result, index) for index, value in enumerate(unique_raw, 1))
        if not rows:
            rows = '<li class="ts-empty">검증된 신호가 없습니다.</li>'
        panels.append(
            f'<section class="ts-card ts-purpose-card {panel_type}"><h3>{escape(title)}</h3>'
            f'<ol class="ts-compact-list">{rows}</ol></section>'
        )
    st.markdown('<div class="ts-section-grid ts-purpose-grid">' + "".join(panels) + "</div>", unsafe_allow_html=True)

    actions = prefer_audience_content_raw(report, "actions", synthesis.recommended_actions, 4)
    action_rows = [
        (clean_citation(action), "Evidence-based priority", evidence_url(action, result)) for action in actions
    ]
    render_action_list(action_rows)

    with st.expander("Evidence & Sources"):
        st.markdown(render_source_list(result), unsafe_allow_html=True)

    monitoring = prefer_audience_content(report, "monitoring_indicators", synthesis.monitoring_indicators, 1)
    render_footer_note(monitoring[0] if monitoring else None)
