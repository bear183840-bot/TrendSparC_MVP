"""Compact, purpose-driven dashboard for non issue-response reports."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from common.content_quality_validator import dedupe_across_blocks
from reporting.dashboard_streamlit.purpose_slots import (
    LAST_RESORT,
    ResolvedSlot,
    resolve_slots,
    under_evidenced,
)
from reporting.dashboard_streamlit.components import (
    bar_metric_groups,
    clean_citation,
    comparison_points_to_table,
    action_impact_lookup,
    dedupe_clean,
    dedupe_raw,
    evidence_url,
    headline_stats,
    metric_comparison_groups,
    prefer_audience_content,
    reference_year,
    render_action_list,
    render_comparison_table,
    render_executive_summary,
    render_footer_note,
    render_kpi_row,
    render_metric_bar,
    render_metric_chart,
    render_cause_map,
    render_metric_comparison,
    render_omitted_sections,
    render_radar,
    render_timeline,
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


def _render_under_evidenced_notice(resolved: list[ResolvedSlot]) -> None:
    """Say it once at the top, rather than leaving the reader to infer it.

    Half the slots coming up empty means collection failed, not that the
    layout picked badly - and that is a different message from any single
    empty card.
    """
    empty = [slot.slot.title for slot in resolved if slot.is_last_resort]
    st.markdown(
        '<div class="ts-card ts-under-evidenced"><h3>이 질문에 필요한 정보가 '
        "충분히 수집되지 않았습니다</h3>"
        f"<p>근거를 찾지 못한 항목: {escape(', '.join(empty))}. "
        "아래 내용은 확보된 근거만으로 구성했습니다.</p></div>",
        unsafe_allow_html=True,
    )


def _render_narrative_list(title: str, items: list[str], result: Any) -> None:
    rows = "".join(_item_markup(value, result, index) for index, value in enumerate(items[:4], 1))
    st.markdown(
        f'<section class="ts-card ts-purpose-card"><h3>{escape(title)}</h3>'
        f'<ol class="ts-compact-list">{rows}</ol></section>',
        unsafe_allow_html=True,
    )


def _render_slot(
    slot: ResolvedSlot,
    items: list[str],
    result: Any,
    synthesis: Any,
    risks: list[str],
    opportunities: list[str],
    strengths: list[str],
    weaknesses: list[str],
) -> None:
    """Draw whichever block the slot resolved to, under the slot's own title."""
    title, block_type = slot.slot.title, slot.block_type
    if block_type == LAST_RESORT:
        # Nothing for this slot survived any candidate. Silent: the
        # under-evidenced notice above and the omitted-sections list below
        # already account for it, and an apology card here would be the third
        # copy of the same message.
        return
    if block_type == "narrative_list":
        _render_narrative_list(title, items, result)
        return

    # Decide what the body will be BEFORE opening the card. The title used to
    # be written first, so any block that then emitted nothing - an
    # unrecognised block_type, or a renderer hitting its own internal guard -
    # left a heading with an empty box under it. That is what "필요 역량"
    # looked like: a header, no content, and no explanation either.
    draw = _body_renderer(
        block_type, result, synthesis, risks, opportunities, strengths, weaknesses
    )
    if draw is None:
        return
    with st.container(border=True):
        st.markdown(f'<div class="ts-card-inner"><h3>{escape(title)}</h3></div>', unsafe_allow_html=True)
        draw()


def _body_renderer(
    block_type: str,
    result: Any,
    synthesis: Any,
    risks: list[str],
    opportunities: list[str],
    strengths: list[str],
    weaknesses: list[str],
):
    """A zero-arg callable that draws this block, or None if it would draw
    nothing. Returning None is what keeps an empty card off the page."""
    if block_type == "chart":
        return lambda: render_metric_chart(synthesis.metric_series, title="확인된 수치 추이",
                                        grounded_claims=synthesis.grounded_claims)
    if block_type == "bar":
        groups = bar_metric_groups(synthesis.metric_series)
        return (lambda: [render_metric_bar(group, synthesis.grounded_claims) for group in groups]) if groups else None
    if block_type == "metric_comparison":
        groups = metric_comparison_groups(synthesis.metric_series)
        return (
            lambda: [render_metric_comparison(period, points) for period, points in groups]
        ) if groups else None
    if block_type in {"kpi_grid", "kpi_single"}:
        return (lambda: render_kpi_row(synthesis.metric_series)) if synthesis.metric_series else None
    if block_type == "timeline":
        return lambda: render_timeline(
            synthesis.evidence, synthesis.metric_series, reference_year(synthesis)
        )
    if block_type == "table":
        headers, rows = comparison_points_to_table(synthesis.comparison_points)
        return (
            lambda: st.markdown(render_comparison_table(headers, rows), unsafe_allow_html=True)
        ) if rows else None
    if block_type == "radar":
        return lambda: render_radar(synthesis.comparison_points)
    if block_type == "matrix":
        # render_swot returns "" when fewer than two quadrants have evidence -
        # a one-cell "matrix" is not a matrix.
        markup = render_swot(
            strengths=strengths, weaknesses=weaknesses,
            opportunities=opportunities, threats=risks,
        )
        return (lambda: st.markdown(markup, unsafe_allow_html=True)) if markup else None
    if block_type == "cause_map":
        return lambda: render_cause_map(
            risks,
            dedupe_clean(synthesis.business_impacts, 3),
            dedupe_clean(synthesis.recommended_actions, 3),
        )
    if block_type == "action_list":
        actions = dedupe_raw(synthesis.recommended_actions, 4)
        # Expected Impact is filled only where a source actually stated what
        # the action would achieve (GeneratedReport.action_impacts); the rest
        # stay empty rather than borrowing a neighbouring finding.
        impacts = action_impact_lookup(result.generated_report)
        rows = [
            (clean_citation(action), impacts.get(clean_citation(action)), evidence_url(action, result))
            for action in actions
        ]
        return (lambda: render_action_list(rows)) if rows else None
    # An unrecognised block_type draws nothing rather than an empty titled box.
    return None


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
    render_executive_summary(summary, headline_stats(synthesis, purpose_id))
    render_kpi_row(synthesis.metric_series, question_terms=question_terms)

    # The purpose's slot skeleton drives the page: fixed order, but each slot
    # takes the first block type its data can honestly support. See
    # purpose_slots.py - a slot only reaches "정보 없음" after every candidate
    # for its intent has been tried.
    resolved = resolve_slots(purpose_id, synthesis, report)
    if under_evidenced(resolved):
        _render_under_evidenced_notice(resolved)

    # No second deduplication pass here. report_generator already gives each
    # section its own material and drops verbatim restatements; running the
    # same rule again over the rendered slots removed items a second time -
    # "시장 변화" showed 1 of its 3 key points because two had been claimed by
    # a neighbouring slot that was drawing from the same section.
    for slot in resolved:
        items = list(dict.fromkeys(slot.items))
        _render_slot(slot, items, result, synthesis, risks, opportunities, strengths, weaknesses)

    # Sections report_planner dropped for lack of evidence, shown with its
    # recorded reason so a gap in the report is visible rather than silent.
    render_omitted_sections(getattr(result.report_plan, "omitted_sections", None) if result.report_plan else None)

    with st.expander("Evidence & Sources"):
        st.markdown(render_source_list(result), unsafe_allow_html=True)

    monitoring = prefer_audience_content(report, "monitoring_indicators", synthesis.monitoring_indicators, 1)
    render_footer_note(monitoring[0] if monitoring else None)
