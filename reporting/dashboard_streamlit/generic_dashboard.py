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
    render_omitted_sections,
    render_page_header,
    render_source_list,
    render_swot,
)

# Same 2-of-4 threshold layout_generator uses to decide a section is
# SWOT-worthy (core/layout_generator/generator.py:_candidate_content_types) -
# kept in sync so this view and the block-type contract agree on what counts.
_SWOT_QUALIFYING_FIELD_COUNT = 2


# How each planned section is presented: display title, CSS accent, and
# which of the section's own fields carry its narrative items. Keyed on
# section id, so the panels follow whatever report_planner produced for this
# question's purpose rather than a fixed arrangement.
_SECTION_PANELS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "current_situation": ("Current Situation", "snapshot", ("key_points", "evidence")),
    "market_status": ("Market Status", "signal", ("key_points", "evidence")),
    "near_term_outlook": ("Near-term Outlook", "timeline", ("opportunities", "monitoring_indicators")),
    "issue": ("Issue", "problem", ("risks", "key_points")),
    "impact": ("Impact", "signal", ("key_points", "risks")),
    "response_actions": ("Response Actions", "action", ("actions", "monitoring_indicators")),
    "problem": ("Problem Definition", "problem", ("risks", "key_points")),
    "root_cause": ("Cause Map", "cause", ("risks", "key_points")),
    "improvement_plan": ("Improvement Plan", "action", ("actions", "monitoring_indicators")),
    "trend": ("Trend Drivers", "trend", ("key_points", "opportunities")),
    "opportunity": ("Opportunity Map", "opportunity", ("opportunities",)),
    "investment_signal": ("Investment Signals", "signal", ("opportunities", "monitoring_indicators")),
    "strategic_recommendation": ("Strategic Recommendations", "action", ("actions",)),
    "recommended_action": ("Recommended Actions", "action", ("actions",)),
    "decision_required": ("Decision Required", "action", ("actions",)),
    "risk": ("Risk", "problem", ("risks",)),
    "risk_and_opportunity": ("Risk & Opportunity", "signal", ("risks", "opportunities")),
    "key_implication": ("Key Implication", "snapshot", ("key_points",)),
}


def _panel_definitions(report: Any) -> list[tuple[str, str, list[str]]]:
    """One panel per planned section, in the report's own order.

    This used to branch on `purpose_id` and return one of three hardcoded
    triples, which meant the section list report_planner computed for the
    question was never actually rendered - and every purpose without its own
    branch collapsed onto the same three panels. Now the sections drive the
    panels, so a change in the plan is visible on screen.
    """
    if report is None:
        return []
    panels: list[tuple[str, str, list[str]]] = []
    for section in report.sections:
        presentation = _SECTION_PANELS.get(section.section_id)
        if presentation is None:
            continue
        title, accent, fields = presentation
        values: list[str] = []
        for field in fields:
            values.extend(getattr(section, field, []) or [])
        panels.append((title, accent, values))
    return panels


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

    panel_defs = _panel_definitions(report)
    # Neighbouring sections legitimately draw on overlapping evidence, so the
    # same fact often shows up reworded in more than one - keep it in
    # whichever section comes first and drop the restatement from the rest.
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
    if panels:
        st.markdown(
            '<div class="ts-section-grid ts-purpose-grid">' + "".join(panels) + "</div>",
            unsafe_allow_html=True,
        )
    # Sections report_planner dropped for lack of evidence, shown with its
    # recorded reason so a gap in the report is visible rather than silent.
    render_omitted_sections(getattr(result.report_plan, "omitted_sections", None) if result.report_plan else None)

    actions = prefer_audience_content_raw(report, "actions", synthesis.recommended_actions, 4)
    # Expected impact is left empty until an action is genuinely linked to one
    # (see render_action_list). It previously carried the constant string
    # "Evidence-based priority" on every row, which said nothing about the
    # action while occupying the column reserved for a real finding.
    action_rows = [
        (clean_citation(action), "", evidence_url(action, result)) for action in actions
    ]
    render_action_list(action_rows)

    with st.expander("Evidence & Sources"):
        st.markdown(render_source_list(result), unsafe_allow_html=True)

    monitoring = prefer_audience_content(report, "monitoring_indicators", synthesis.monitoring_indicators, 1)
    render_footer_note(monitoring[0] if monitoring else None)
