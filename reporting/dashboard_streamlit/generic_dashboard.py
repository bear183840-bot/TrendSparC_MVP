"""Compact, purpose-driven dashboard for non issue-response reports."""

from __future__ import annotations

import contextlib

from html import escape
from typing import Any

import streamlit as st

from common.content_quality_validator import dedupe_across_blocks
# Importing the package is what registers every block, including the live
# ones - the registry is only "the one table" if nothing can reach the
# dashboard without it being populated.
import reporting.dashboard_streamlit.blocks  # noqa: F401
from reporting.dashboard_streamlit.blocks.base import SlotContext
from reporting.dashboard_streamlit.blocks.registry import slot_renderer
from common.purpose_slots import (
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
    item_bar_groups,
    metric_comparison_groups,
    time_bar_groups,
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
    render_cause_tree,
    render_factor_list,
    render_importance_bars,
    render_recurring_terms,
    render_share_split,
    render_metric_comparison,
    render_omitted_sections,
    render_radar,
    render_timeline,
    render_page_header,
    render_source_list,
    render_swot,
    item_doc_id,
    uncorroborated_doc_ids,
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


def _item_markup(raw_value: str, result: Any, index: int, uncorroborated_ids: frozenset[str] = frozenset()) -> str:
    url = evidence_url(raw_value, result)
    link = (
        f'<a class="ts-inline-evidence" href="{escape(url)}" target="_blank" title="근거 원문 열기">↗</a>'
        if url
        else ""
    )
    # A single-source claim isn't wrong, just not cross-verified yet - the
    # badge says so next to the exact item it applies to, rather than only
    # in the raw TrendSynthesis.uncorroborated_points list nobody sees.
    badge = (
        '<span class="ts-badge-uncorroborated" title="독립된 출처 1곳에서만 확인된 주장입니다">단일 출처</span>'
        if item_doc_id(raw_value) in uncorroborated_ids
        else ""
    )
    return (
        f'<li><span class="ts-item-index">{index:02d}</span>'
        f"<span>{escape(clean_citation(raw_value))}{badge}</span>{link}</li>"
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


def _render_narrative_list(
    title: str, items: list[str], result: Any, uncorroborated_ids: frozenset[str]
) -> None:
    rows = "".join(
        _item_markup(value, result, index, uncorroborated_ids)
        for index, value in enumerate(items[:4], 1)
    )
    st.markdown(
        f'<section class="ts-card ts-purpose-card"><h3>{escape(title)}</h3>'
        f'<ol class="ts-compact-list">{rows}</ol></section>',
        unsafe_allow_html=True,
    )


# How much horizontal room a block needs to be readable. A laptop screen is
# wider than it is tall, and the report was rendering one full-width card per
# row - so a keyword chip list and a three-bar ranking each took a whole
# 1700px band and the page ran to four screens of scrolling.
#
# Two units per row. A block that carries an axis, a chain, or several series
# takes both; a card that is a list or a short stack of figures takes one and
# sits beside its neighbour.
# Bars and line charts are not on this list. A ranking of three items, or a
# three-point trend, is perfectly readable in half a 1500px screen, and giving
# either the full width bought nothing but a taller page - the whole point of
# the landscape grid. Only blocks that need real horizontal room - a dated
# rail, a branching chain, or several panels side by side - take both units.
_WIDE_BLOCKS = frozenset({
    "landscape", "timeline", "cause_map", "cause_tree",
    "competitor_panels", "matrix",
})
_GRID_UNITS = 2


def _slot_width(slot: ResolvedSlot) -> int:
    """Units this slot occupies - the widest block in its composition wins."""
    if any(block_type in _WIDE_BLOCKS for block_type in slot.block_types):
        return _GRID_UNITS
    return 1


def _grid_rows(slots: list[ResolvedSlot]) -> list[list[ResolvedSlot]]:
    """Greedy left-to-right packing that keeps the skeleton's reading order.

    Deliberately not a masonry re-order: the purpose skeleton is an argument
    (현황 -> 지표 -> 경쟁 -> 대응) and shuffling cards to fill holes would
    scramble it. A narrow card simply waits for the next narrow card; if the
    following slot is wide, the row closes with one card in it.
    """
    rows: list[list[ResolvedSlot]] = []
    current: list[ResolvedSlot] = []
    used = 0
    for slot in slots:
        width = _slot_width(slot)
        if used + width > _GRID_UNITS:
            rows.append(current)
            current, used = [], 0
        current.append(slot)
        used += width
    if current:
        rows.append(current)
    return rows


def _render_slot(
    slot: ResolvedSlot,
    items: list[str],
    result: Any,
    synthesis: Any,
    risks: list[str],
    opportunities: list[str],
    strengths: list[str],
    weaknesses: list[str],
    uncorroborated_ids: frozenset[str],
) -> None:
    """Draw whichever block the slot resolved to, under the slot's own title."""
    title = slot.slot.title
    if slot.is_last_resort:
        # Nothing for this slot survived any candidate. Silent: the
        # under-evidenced notice above and the omitted-sections list below
        # already account for it, and an apology card here would be the third
        # copy of the same message.
        return
    if slot.block_type == "narrative_list":
        _render_narrative_list(title, items, result, uncorroborated_ids)
        return

    # Decide what every body will be BEFORE opening the card. The title used
    # to be written first, so any block that then emitted nothing - an
    # unrecognised block_type, or a renderer hitting its own internal guard -
    # left a heading with an empty box under it. That is what "필요 역량"
    # looked like: a header, no content, and no explanation either. With a
    # composition the same rule applies per block: a companion that would
    # draw nothing is simply not drawn, and if none of them draw, the card
    # never opens.
    draws = [
        draw for draw in (
            _body_renderer(
                block_type, result, synthesis, risks, opportunities,
                strengths, weaknesses, items,
            )
            for block_type in slot.block_types
        ) if draw is not None
    ]
    if not draws:
        return
    with st.container(border=True):
        st.markdown(f'<div class="ts-card-inner"><h3>{escape(title)}</h3></div>', unsafe_allow_html=True)
        for draw in draws:
            draw()


def _body_renderer(
    block_type: str,
    result: Any,
    synthesis: Any,
    risks: list[str],
    opportunities: list[str],
    strengths: list[str],
    weaknesses: list[str],
    items: list[str] | None = None,
):
    """A zero-arg callable that draws this block, or None if it would draw
    nothing. Returning None is what keeps an empty card off the page.

    The mapping itself lives in `blocks/slot_blocks.py`, not here. This used
    to be a long if-chain that duplicated the block registry next door: the
    same block type could be drawn one way through the registry and another
    way through this function, and adding a block meant editing both. Now an
    unregistered block type simply draws nothing, which is also what happens
    to one whose data doesn't support it.
    """
    render = slot_renderer(block_type)
    if render is None:
        return None
    return render(SlotContext(
        result=result,
        synthesis=synthesis,
        items=list(items or []),
        risks=risks,
        opportunities=opportunities,
        strengths=strengths,
        weaknesses=weaknesses,
    ))


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

    uncorroborated_ids = frozenset(uncorroborated_doc_ids(synthesis))

    # No second deduplication pass here. report_generator already gives each
    # section its own material and drops verbatim restatements; running the
    # same rule again over the rendered slots removed items a second time -
    # "시장 변화" showed 1 of its 3 key points because two had been claimed by
    # a neighbouring slot that was drawing from the same section.
    for row in _grid_rows([slot for slot in resolved if not slot.is_last_resort]):
        # A row of one wide card needs no column wrapper - st.columns([1]) adds
        # padding that makes a full-width block narrower than the ones above it.
        columns = st.columns(len(row), gap="small") if len(row) > 1 else [contextlib.nullcontext()]
        for slot, column in zip(row, columns):
            with column:
                _render_slot(
                    slot, list(dict.fromkeys(slot.items)), result, synthesis, risks,
                    opportunities, strengths, weaknesses, uncorroborated_ids,
                )

    # Sections report_planner dropped for lack of evidence, shown with its
    # recorded reason so a gap in the report is visible rather than silent.
    render_omitted_sections(getattr(result.report_plan, "omitted_sections", None) if result.report_plan else None)

    with st.expander("Evidence & Sources"):
        st.markdown(render_source_list(result), unsafe_allow_html=True)

    monitoring = prefer_audience_content(report, "monitoring_indicators", synthesis.monitoring_indicators, 1)
    render_footer_note(monitoring[0] if monitoring else None)
