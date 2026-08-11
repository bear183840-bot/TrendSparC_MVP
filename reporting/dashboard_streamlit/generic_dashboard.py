"""Compact, purpose-driven dashboard for non issue-response reports."""

from __future__ import annotations

from html import escape
import re
from typing import Any

import streamlit as st

from audience.presentation import load_audience_presentation, order_slots_for_audience
from common.metric_quality import display_metric_points
from common.action_quality import actions_for_owner, routed_action_owner
from core.question_coverage import (
    assess_question_coverage,
    coverage_safe_summary,
    derive_question_coverage,
    minimum_drawable_periods,
)
from common.block_shapes import (
    comparison_points_of_kind,
    executive_summary_comparison,
    executive_summary_supporting_kpis,
    headline_kpi,
    landscape_parts,
)
from common.block_titles import block_title, slot_title
from common.content_quality_validator import select_chartable_series
from common.content_quality_validator import plotted_chart_series
from common.content_quality_validator import dedupe_across_blocks
from common.content_quality_validator import exclude_non_competitor_comparisons
from common.content_quality_validator import is_chart_trend_restatement
# Importing the package is what registers every block, including the live
# ones - the registry is only "the one table" if nothing can reach the
# dashboard without it being populated.
import reporting.dashboard_streamlit.blocks  # noqa: F401
from reporting.dashboard_streamlit.blocks.base import SlotContext
from reporting.dashboard_streamlit.blocks.registry import slot_renderer
from common.purpose_slots import (
    LAST_RESORT,
    ResolvedSlot,
    Slot,
    bars_evidence_key,
    kpi_evidence_key,
    resolve_slots,
    share_evidence_key,
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
    render_metric_bar,
    render_metric_chart,
    render_metric_insight,
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
_PROPOSAL_SENTENCE_RE = re.compile(
    r"(?:해야\s*한다|할\s*필요가?\s*(?:있다|필요하다)|필요하다|권고한다|제안한다|"
    r"검토해야|대응해야|추진해야|본다면.{0,80}(?:할|해)\s*볼\s*수\s*있다)(?:[.!?]|$)",
    re.IGNORECASE,
)


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
    empty = [slot_title(slot.slot.slot_id, slot.slot.title) for slot in resolved if slot.is_last_resort]
    st.markdown(
        '<div class="ts-card ts-under-evidenced"><h3>이 질문에 필요한 정보가 '
        "충분히 수집되지 않았습니다</h3>"
        f"<p>근거를 찾지 못한 항목: {escape(', '.join(empty))}. "
        "아래 내용은 확보된 근거만으로 구성했습니다.</p></div>",
        unsafe_allow_html=True,
    )


def _render_narrative_list(
    title: str, items: list[str], result: Any, uncorroborated_ids: frozenset[str],
    limit: int = 4,
) -> None:
    rows = "".join(
        _item_markup(value, result, index, uncorroborated_ids)
        for index, value in enumerate(items[:limit], 1)
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
_BLOCK_UNITS = {
    # Compact exact-value blocks: one quarter of the landscape.
    "ranking_list": 1, "item_bar": 1, "bar": 1, "kpi_grid": 1,
    "kpi_single": 1, "keyword_tags": 1, "recurring_terms": 1,
    "factor_list": 1, "status_bar": 1,
    # Comparisons and actions need two readable columns.
    "benchmark_table": 2, "table": 2, "level_matrix": 2,
    "radar": 2, "metric_comparison": 2, "grouped_bar": 2, "entity_attribute_bars": 2,
    "action_list": 2, "narrative_list": 2, "chart": 2, "driver_bars": 2,
    "question_comparison": 2,
    "composition_breakdown": 2, "share_split": 2,
    # Flows keep the full landscape width.
    "cause_map": 4, "cause_tree": 4, "competitor_panels": 4, "matrix": 4,
    # `landscape` (trend + composition, already one card) and `timeline` pack
    # into one row together (3 + 1 = `_GRID_UNITS`) instead of each claiming
    # its own full-width row - live-verified 2026-08-11: on a wide screen a
    # standalone trend chart and a standalone 5-step timeline each left most
    # of their row empty. General to any purpose where both slots resolve
    # next to each other, not specific to any one sector's data.
    "landscape": 3, "timeline": 1,
}
_GRID_UNITS = 4


# What a block would actually put on screen, by block type. `_BLOCK_UNITS`
# above says how wide a block needs to be when it is *full*; this is what
# shrinks it when it is not. A comparison table of two entities and a
# comparison table of nine both took two units, so the page ran to four
# screens with half of it whitespace inside cards.
#
# Deliberately measured, never guessed: a block type absent from this table
# keeps its full width rather than being shrunk on a hunch.
_CONTENT_VOLUME: dict[str, Any] = {
    "narrative_list": lambda synthesis, items: len(items),
    "factor_list": lambda synthesis, items: len(items),
    "action_list": lambda synthesis, items: len(synthesis.recommended_actions or []),
    "chart": lambda synthesis, items: len(
        {point.period for point in select_chartable_series(synthesis.metric_series)}
    ),
    "timeline": lambda synthesis, items: len(synthesis.evidence or []),
    "table": lambda synthesis, items: len(
        {point.entity for point in comparison_points_of_kind(synthesis.comparison_points, False)}
    ),
    "segment_table": lambda synthesis, items: len(
        {point.entity for point in comparison_points_of_kind(synthesis.comparison_points, True)}
    ),
    "benchmark_table": lambda synthesis, items: len(
        {point.entity for point in synthesis.comparison_points}
    ),
    "level_matrix": lambda synthesis, items: len(
        {point.entity for point in synthesis.comparison_points}
    ),
    "competitor_panels": lambda synthesis, items: len(
        {point.entity for point in synthesis.comparison_points}
    ),
    "metric_comparison": lambda synthesis, items: len(synthesis.metric_series),
    "grouped_bar": lambda synthesis, items: len(synthesis.metric_series),
    "cause_map": lambda synthesis, items: len(synthesis.factors or synthesis.risks or []),
}

# Volume -> units. Three things fit a quarter-width card comfortably; past
# nine a block needs its declared width or it starts wrapping mid-row.
_VOLUME_UNITS: tuple[tuple[int, int], ...] = ((3, 1), (9, 2))


def _content_volume(slot: ResolvedSlot, synthesis: Any) -> int | None:
    """How many things this slot's lead block would draw, or None if unknown."""
    measure = _CONTENT_VOLUME.get(slot.block_type)
    if measure is None:
        return None
    try:
        return measure(synthesis, slot.items)
    except AttributeError:
        # A caller passing a partial synthesis stand-in gets the declared
        # width rather than a crash - sizing is presentation, not evidence.
        return None


def _slot_width(
    slot: ResolvedSlot, compact: bool = False, synthesis: Any | None = None,
) -> int:
    """Units this slot occupies - the widest block in its composition wins,
    narrowed to what its content actually fills.

    `synthesis` is optional so a caller measuring the skeleton alone still
    gets the declared widths; only the live page, which has the data, shrinks.
    """
    block_types = slot.block_types[:1] if compact else slot.block_types
    declared = max((_BLOCK_UNITS.get(block_type, 2) for block_type in block_types), default=2)
    if synthesis is None or len(block_types) > 1:
        # A composition draws two blocks stacked in one card; the second one's
        # volume is not measured here, so shrinking on the lead alone would
        # squeeze a card that is in fact full.
        return declared
    volume = _content_volume(slot, synthesis)
    if volume is None:
        return declared
    for threshold, units in _VOLUME_UNITS:
        if volume <= threshold:
            return max(1, min(declared, units))
    return declared


def _grid_rows(
    slots: list[ResolvedSlot], compact: bool = False, synthesis: Any | None = None,
) -> list[list[ResolvedSlot]]:
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
        width = _slot_width(slot, compact=compact, synthesis=synthesis)
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
    presentation: Any,
    question: str = "",
    compact: bool = True,
    complete: bool = False,
) -> None:
    """Draw whichever block the slot resolved to, under the slot's own title."""
    # One table decides every heading - see common/block_titles.py. The
    # slot's own `title` stays as the fallback so a slot added without a
    # registered heading renders under its working name instead of raising.
    title = slot_title(slot.slot.slot_id, slot.slot.title)
    if slot.is_last_resort:
        # Nothing for this slot survived any candidate. Silent: the
        # under-evidenced notice above and the omitted-sections list below
        # already account for it, and an apology card here would be the third
        # copy of the same message.
        return
    if slot.slot.slot_id == "factors":
        # A "factors" item that only narrates the trend the Market Analysis
        # chart already draws (same subjects, direction words, no causal
        # link) adds nothing next to the chart itself - live-verified
        # 2026-08-11: "최근 3년간 추이를 보면 IPTV 가입자는 완만하게
        # 증가한 반면 SO와 위성방송은 감소세가 이어졌다" names the same
        # three series the chart plots and states no "why".
        # `is_chart_trend_restatement` is the general, structural test - a
        # sentence that explains a cause, or names a subject the chart never
        # plotted, is kept regardless of wording. Filtered here, before the
        # block_type branch below, so it also governs whether driver_bars/
        # factor_list (which key on `len(items)`) are eligible at all - a
        # slot whose only content was a restatement should end up with
        # nothing to show, not fall through to a different shape for the
        # same now-empty list.
        chart_subjects = list(dict.fromkeys(
            point.label for point in plotted_chart_series(select_chartable_series(synthesis.metric_series))
        ))
        items = [item for item in items if not is_chart_trend_restatement(item, chart_subjects)]
        if not items:
            return
    if slot.block_type == "narrative_list":
        # A status/finding slot may quote what the source observed, but a
        # source author's proposal is not itself market status. Recommendations
        # have their own owner-validated action slot.
        if slot.slot.slot_id not in {"response", "recommendation", "options"}:
            finding_items = [item for item in items if not _PROPOSAL_SENTENCE_RE.search(item)]
            items = finding_items or items
        # A Korean question must not surface untranslated source prose as the
        # finished dashboard copy. Prefer Korean material already present in
        # the same synthesis; never machine-invent a translation here.
        if any("가" <= char <= "힣" for char in question):
            korean_items = [
                item for item in items
                if any("가" <= char <= "힣" for char in item)
            ]
            if not korean_items:
                korean_items = [
                    item for item in synthesis.key_points
                    if any("가" <= char <= "힣" for char in item)
                ]
            items = korean_items or items
        _render_narrative_list(
            title, items, result, uncorroborated_ids,
            limit=(min(presentation.narrative_limit, 3) if compact else max(len(items), 1)),
        )
        return

    # Decide what every body will be BEFORE opening the card. The title used
    # to be written first, so any block that then emitted nothing - an
    # unrecognised block_type, or a renderer hitting its own internal guard -
    # left a heading with an empty box under it. That is what "필요 역량"
    # looked like: a header, no content, and no explanation either. With a
    # composition the same rule applies per block: a companion that would
    # draw nothing is simply not drawn, and if none of them draw, the card
    # never opens.
    # Compact mode shows one block per card, because a card sharing a row
    # with three others has room for one. A card that already owns the whole
    # row is the exception: its companion has real space to go into rather
    # than space taken from a neighbour, so dropping it there only leaves the
    # row half empty. This is why `resolve_slots` bothered to pick a second
    # block that draws facts the lead does not.
    full_width = _slot_width(slot, compact=True, synthesis=synthesis) >= _GRID_UNITS
    block_types = (
        slot.block_types if complete or not compact or full_width
        else slot.block_types[:1]
    )
    # Each block gets its own card. A slot's lead and companion answer the
    # same question but are not one visualization - the lead's block
    # (`landscape`) already draws its own internal composite (chart+donut)
    # as a single block_type entry, so splitting by block_type here still
    # keeps that pair on one card; only genuinely separate block TYPES
    # (e.g. a `timeline` companion beside `landscape`) get pulled apart.
    # Live-verified 2026-08-11: 요청 - "타임라인은 다른 블록으로 분리" - a
    # timeline sharing landscape's own bordered container read as one card
    # that just kept growing, not two related-but-distinct answers.
    for index, block_type in enumerate(block_types):
        draw = _body_renderer(
            block_type, result, synthesis, risks, opportunities,
            strengths, weaknesses, items,
            presentation,
            compact,
            question,
            slot.drawn_before,
        )
        if draw is None:
            continue
        # `matrix` (the SWOT quadrant grid) is the one block type whose own
        # meaning doesn't track the slot that picked it: `_matrix()` always
        # draws from the full strengths/weaknesses/opportunities/risks
        # pool (see slot_blocks.py), never just the calling slot's own
        # narrow category - live-verified 2026-08-11, the "opportunity"
        # slot (titled "Opportunity") ended up leading with a 3-quadrant
        # SWOT once strengths/weaknesses were also populated, so the card
        # showed Strength+Weakness+Opportunity under a header that named
        # only one of them. Every other block type's meaning doesn't shift
        # under a different slot this way, so this override stays scoped
        # to `matrix` specifically rather than applying to every lead
        # block via `block_title()`.
        card_title = (
            block_title("matrix", "SWOT") if block_type == "matrix"
            else title if index == 0
            else block_title(block_type, title)
        )
        with st.container(border=True):
            st.markdown(f'<div class="ts-card-inner"><h3>{escape(card_title)}</h3></div>', unsafe_allow_html=True)
            draw()
        # AI Insight now sits below the card, not inside it - live-verified
        # 2026-08-11: nested inside `landscape`'s own bordered container, it
        # read as part of the trend chart specifically rather than a comment
        # on the whole card. Recomputed here (not threaded out of `draw()`)
        # so this stays a pure addition after the container closes, rather
        # than changing what every other block's `draw()` returns.
        if block_type == "landscape":
            chartable_points = plotted_chart_series(select_chartable_series(synthesis.metric_series))
            if chartable_points:
                render_metric_insight(chartable_points, synthesis.grounded_claims)


def _body_renderer(
    block_type: str,
    result: Any,
    synthesis: Any,
    risks: list[str],
    opportunities: list[str],
    strengths: list[str],
    weaknesses: list[str],
    items: list[str] | None = None,
    presentation: Any | None = None,
    compact: bool = True,
    question: str = "",
    drawn_before: frozenset[str] = frozenset(),
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
        presentation=presentation,
        question=question,
        compact=compact,
        drawn_before=drawn_before,
    ))


def _partition_dashboard_slots(
    slots: list[ResolvedSlot], primary_limit: int,
) -> tuple[list[ResolvedSlot], list[ResolvedSlot]]:
    """Split the decision surface from the complete supporting analysis.

    Summary and KPI-only slots are already represented by the dedicated
    summary/KPI bands above the grid, so repeating them is duplication rather
    than preservation.  The next audience-ordered slots become the first
    screen; every other supported slot remains available in detail.
    """
    supported = [slot for slot in slots if not slot.is_last_resort]
    candidates: list[ResolvedSlot] = []
    complete: list[ResolvedSlot] = []
    for slot in supported:
        if slot.slot.slot_id == "summary":
            continue
        complete.append(slot)
        if set(slot.block_types) <= {"kpi_grid"}:
            continue
        if len(candidates) < primary_limit:
            candidates.append(slot)
    return candidates, complete


def _detail_slot_order(slots: list[ResolvedSlot]) -> list[ResolvedSlot]:
    """Keep compact keyword frequency in the bottom-right supporting cell."""
    keywords = [
        slot for slot in slots
        if any(kind in {"keyword_tags", "recurring_terms"} for kind in slot.block_types)
    ]
    others = [slot for slot in slots if slot not in keywords]
    return [*others, *keywords]


def _question_structure_order(
    slots: list[ResolvedSlot], coverage_requirement: Any,
    metric_points: list[Any] | None = None,
) -> list[ResolvedSlot]:
    """Put the question's requested evidence shape first, without topics.

    An N-period trend question leads with the slot that resolved to a real
    time-series chart.  An A-vs-B question leads with a supported comparison
    when no time-series requirement outranks it.  This is intentionally about
    structural contracts, not OTT, chips, telecoms, brands, or any example.
    """
    ordered = list(slots)
    requested_periods = getattr(coverage_requirement, "minimum_distinct_periods", 0)
    chartable = select_chartable_series(metric_points or [])
    drawable_periods = max(
        (
            len({point.period for point in chartable if point.label == label})
            for label in {point.label for point in chartable}
        ),
        default=0,
    )
    if (
        requested_periods >= 3
        and drawable_periods >= minimum_drawable_periods(requested_periods)
    ):
        for index, slot in enumerate(ordered):
            if slot.block_type == "chart":
                return [slot, *ordered[:index], *ordered[index + 1:]]
    if len(getattr(coverage_requirement, "comparison_anchors", ()) or ()) >= 2:
        for index, slot in enumerate(ordered):
            if slot.block_type == "question_comparison":
                return [slot, *ordered[:index], *ordered[index + 1:]]
        comparison_types = {
            "grouped_bar", "benchmark_table", "table", "level_matrix",
            "metric_comparison", "ranking_list", "item_bar", "share_split",
            "question_comparison",
        }
        for index, slot in enumerate(ordered):
            if slot.block_type in comparison_types:
                return [slot, *ordered[:index], *ordered[index + 1:]]
    return ordered


def _axis_match_score(text: str, anchor: str) -> int:
    lowered = text.casefold()
    return 1 if anchor.casefold() in lowered else 0


def _report_comparison_sentences(
    result: Any, synthesis: Any, question: str, safe_summary: str | None = None,
) -> list[str]:
    values: list[str] = []
    report = getattr(result, "generated_report", None)
    if report:
        values.append(safe_summary if safe_summary is not None else (report.executive_summary or ""))
        for section in report.sections:
            for field in (
                "key_points", "evidence", "risks", "opportunities",
                "monitoring_indicators",
            ):
                values.extend(getattr(section, field, None) or [])
    values.extend([*synthesis.key_points, *synthesis.evidence])
    sentences: list[str] = []
    korean_question = any("가" <= char <= "힣" for char in question)
    for value in values:
        for sentence in re.split(r"(?<=[.!?])\s+", clean_citation(value)):
            sentence = sentence.strip()
            if not sentence or (korean_question and not any("가" <= char <= "힣" for char in sentence)):
                continue
            if _PROPOSAL_SENTENCE_RE.search(sentence):
                continue
            if sentence not in sentences:
                sentences.append(sentence)
    return sentences


def _question_comparison_slot(
    result: Any, synthesis: Any, question: str, anchors: list[str],
    safe_summary: str | None = None,
) -> ResolvedSlot | None:
    """Fallback comparison block when the two sides lack a shared axis."""
    if len(anchors) != 2:
        return None
    grouped: dict[str, list[str]] = {anchor: [] for anchor in anchors}
    for sentence in _report_comparison_sentences(
        result, synthesis, question, safe_summary=safe_summary
    ):
        scores = [_axis_match_score(sentence, anchor) for anchor in anchors]
        best = max(scores)
        if best <= 0 or scores.count(best) != 1:
            continue
        anchor = anchors[scores.index(best)]
        if len(grouped[anchor]) < 2:
            grouped[anchor].append(sentence)
    # The block is still required when one side is missing: an explicit empty
    # side is more truthful than silently answering only half the comparison.
    if not any(grouped.values()):
        return None
    encoded: list[str] = []
    for anchor in anchors:
        payload = "\x1e".join(
            f"{sentence}\x1d{evidence_url(sentence, result) or ''}"
            for sentence in grouped[anchor]
        )
        encoded.append(f"{anchor}\x1f{payload}")
    slot = Slot(
        "question_comparison", f"{anchors[0]} vs {anchors[1]} 비교",
        "질문에 명시된 두 축은 어떻게 다른가",
        ("question_comparison",), optional=False,
    )
    return ResolvedSlot(slot, ("question_comparison",), None, encoded)


def _has_shared_axis_for_anchors(synthesis: Any, anchors: list[str]) -> bool:
    """Whether structured data already compares both requested sides."""
    by_label: dict[tuple[str, str], list[Any]] = {}
    for point in synthesis.metric_series:
        by_label.setdefault((point.label, point.unit), []).append(point)
    for points in by_label.values():
        subjects = [point.subject or "" for point in points]
        if all(any(_axis_match_score(subject, anchor) for subject in subjects) for anchor in anchors):
            return True
    by_criterion: dict[str, list[str]] = {}
    for point in synthesis.comparison_points:
        by_criterion.setdefault(point.criterion, []).append(point.entity)
    return any(
        all(any(_axis_match_score(entity, anchor) for entity in entities) for anchor in anchors)
        for entities in by_criterion.values()
    )


def render_generic_dashboard(
    result: Any,
    question: str,
    sector: str,
    audience: str,
    purpose: str,
    purpose_id: str | None,
) -> None:
    action_owner = routed_action_owner(getattr(result, "sector_route", None))
    market_keywords = getattr(
        getattr(getattr(result, "sector_route", None), "matched_profile", None),
        "market_keywords", None,
    )
    synthesis = result.synthesis.model_copy(update={
        "metric_series": display_metric_points(result.synthesis.metric_series),
        "recommended_actions": actions_for_owner(
            result.synthesis.recommended_actions, action_owner
        ),
        # A market/category label ("IPTV") sitting in comparison_points beside
        # real competitors ("KT"/"SKB"/"LGU+") reads as a competitor to every
        # block downstream - filtered once here, against the sector's own
        # registered market_keywords, so no renderer has to remember to do it.
        "comparison_points": exclude_non_competitor_comparisons(
            result.synthesis.comparison_points, market_keywords,
        ),
    })
    report = result.generated_report
    summary = clean_citation((report.executive_summary if report else None) or synthesis.synthesis_text)
    coverage_requirement = (
        getattr(result, "question_coverage", None) or derive_question_coverage(question)
    )
    coverage_gaps = (
        list(getattr(result, "question_coverage_gaps", None) or [])
        or assess_question_coverage(result.document_analyses, coverage_requirement)
    )
    summary = coverage_safe_summary(summary, coverage_requirement, coverage_gaps)
    risks = prefer_audience_content(report, "risks", synthesis.risks, 3)
    opportunities = prefer_audience_content(report, "opportunities", synthesis.opportunities, 3)
    # strengths/weaknesses are never LLM-rewritten (see issue_response_view.py's
    # identical comment) - facts, not audience-tailored prose.
    strengths = dedupe_clean(synthesis.strengths, 3)
    weaknesses = dedupe_clean(synthesis.weaknesses, 3)
    audience_id = (
        result.report_plan.audience_id if getattr(result, "report_plan", None) else "_default"
    )
    presentation = load_audience_presentation(audience_id)

    render_page_header(question, sector, audience, purpose)
    # Organizations only, not technologies: a technology entity like "배터리"
    # or "ESS" is the sector's own topic vocabulary - true of a company's own
    # figures and of an unrelated industry-wide statistic alike, so it can't
    # tell them apart. An organization name is what actually distinguishes
    # "about the company this question asks about" from "about the market
    # generally" - see `executive_summary_supporting_kpis`'s docstring.
    entities = getattr(result, "entities", None)
    core_entities = list(getattr(entities, "organizations", None) or [])
    headline_point = headline_kpi(synthesis.metric_series, question, core_entities)
    supporting_points = executive_summary_supporting_kpis(
        synthesis.metric_series, question, headline_point, core_entities=core_entities,
    )
    comparison = executive_summary_comparison(synthesis.metric_series)
    # If Landscape will pair this same composition with its trend chart
    # below, Executive Summary skips drawing it a second time as its own
    # donut - see `render_executive_summary`'s docstring. Checked by subject
    # (the "whole" being split), not just kind=="share", so a question with
    # a *different* composition than the one Landscape claims still gets its
    # Executive Summary visualization as before.
    landscape_parts_here = landscape_parts(synthesis.metric_series)
    landscape_owns_this_share = (
        comparison is not None
        and comparison[0] == "share"
        and landscape_parts_here is not None
        and landscape_parts_here[2] == "share"
        and landscape_parts_here[0] == "trend"
        and comparison[1] == landscape_parts_here[3][0].share_of
    )
    render_executive_summary(
        summary, heading=presentation.summary_label, headline_point=headline_point,
        supporting_points=supporting_points,
        comparison=None if landscape_owns_this_share else comparison,
    )
    # The purpose's slot skeleton drives the page: fixed order, but each slot
    # takes the first block type its data can honestly support. See
    # purpose_slots.py - a slot only reaches "정보 없음" after every candidate
    # for its intent has been tried.
    #
    # `initial_drawn` seeds the dedup state with every fact the Executive
    # Summary just rendered above (headline figure, supporting KPIs, its own
    # bar-shaped comparison): without it, Key Metrics' own ranking would pick
    # the same top metrics all over again, since headline_kpi/
    # executive_summary_supporting_kpis and rank_kpi_candidates share one
    # ranking and neither knew about the other's pick.
    #
    # A "share" composition is seeded here only when Executive Summary
    # actually drew it (i.e. Landscape does not own it - see above). When
    # Landscape owns it, Executive Summary skipped rendering it, so nothing
    # is drawn to seed and Landscape must still see it as available.
    # Live-verified 2026-08-11: seeding it unconditionally used to make
    # Landscape lose its own donut whenever Executive Summary claimed the
    # same composition first, splitting the trend chart and its composition
    # into two separate cards instead of the one paired card they belong in.
    # Seeded in *both* the kpi and bars namespaces for every point drawn here,
    # not just whichever shape Executive Summary happened to use. Live-verified
    # 2026-08-11: "Global semiconductor market growth: 975 billion" drawn here
    # as a bars comparison still showed up again under Key Metrics, because
    # `_undrawn_kpi_points` only checks the kpi-shaped key and this seed had
    # only recorded the bars-shaped one for the same point - two different
    # spellings of "already shown" for a fact the reader has already seen once,
    # on the one section that always renders first and is never itself subject
    # to dedup. The multi-shape-family allowance in `resolve_slots()` is for
    # slots choosing between shapes for their *own* undrawn facts; it was never
    # meant to let a slot re-draw what the fixed cover section already shows.
    exec_summary_drawn: set[str] = set()
    if headline_point is not None:
        exec_summary_drawn.add(kpi_evidence_key(headline_point))
        exec_summary_drawn.add(bars_evidence_key(headline_point))
    for point in supporting_points:
        exec_summary_drawn.add(kpi_evidence_key(point))
        exec_summary_drawn.add(bars_evidence_key(point))
    if comparison is not None:
        kind, subject, points = comparison
        if kind == "share":
            if not landscape_owns_this_share:
                exec_summary_drawn.add(share_evidence_key(subject))
        else:
            for point in points:
                exec_summary_drawn.add(bars_evidence_key(point))
                exec_summary_drawn.add(kpi_evidence_key(point))
    resolved = order_slots_for_audience(
        resolve_slots(
            purpose_id, synthesis, report,
            getattr(getattr(result, "report_purpose", None), "question_answer_type", None),
            question,
            initial_drawn=frozenset(exec_summary_drawn),
        ), presentation,
    )
    if under_evidenced(resolved):
        _render_under_evidenced_notice(resolved)

    uncorroborated_ids = frozenset(uncorroborated_doc_ids(synthesis))

    # No second deduplication pass here. report_generator already gives each
    # section its own material and drops verbatim restatements; running the
    # same rule again over the rendered slots removed items a second time -
    # "시장 변화" showed 1 of its 3 key points because two had been claimed by
    # a neighbouring slot that was drawing from the same section.
    # A "factors" slot whose only items are chart restatements (see
    # `_render_slot`, which applies the same `is_chart_trend_restatement`
    # filter) draws nothing - excluded here too, before `_grid_rows` sizes
    # the row, so a blank reserved column doesn't sit next to Key
    # Comparisons squeezing it to a width its bar labels can't fit in.
    # Live-verified 2026-08-11: an empty grid column (Key Drivers' old spot)
    # left Key Comparisons at 186px with overlapping axis text next to it.
    chart_subjects_for_factors = list(dict.fromkeys(
        point.label for point in plotted_chart_series(select_chartable_series(synthesis.metric_series))
    ))
    dashboard_slots = _detail_slot_order([
        slot for slot in resolved
        if not slot.is_last_resort and slot.slot.slot_id != "summary"
        and not (
            slot.slot.slot_id in {"response", "recommendation"}
            and not (
                synthesis.recommended_actions
                or getattr(synthesis, "ai_recommended_actions", None)
            )
        )
        and not (
            slot.slot.slot_id == "factors"
            and slot.items
            and all(
                is_chart_trend_restatement(item, chart_subjects_for_factors)
                for item in slot.items
            )
        )
    ])
    anchors = list(coverage_requirement.comparison_anchors)
    if len(anchors) == 2 and not _has_shared_axis_for_anchors(synthesis, anchors):
        comparison_slot = _question_comparison_slot(
            result, synthesis, question, anchors, safe_summary=summary
        )
        if comparison_slot is not None:
            market_index = next(
                (
                    index for index, slot in enumerate(dashboard_slots)
                    if slot.slot.slot_id == "market" and slot.block_type == "narrative_list"
                ),
                len(dashboard_slots),
            )
            dashboard_slots = [
                slot for slot in dashboard_slots
                if not (slot.slot.slot_id == "market" and slot.block_type == "narrative_list")
            ]
            dashboard_slots.insert(min(market_index, len(dashboard_slots)), comparison_slot)
    dashboard_slots = _question_structure_order(
        dashboard_slots, coverage_requirement, synthesis.metric_series
    )
    for row in _grid_rows(dashboard_slots, compact=True, synthesis=synthesis):
        widths = [_slot_width(slot, compact=True, synthesis=synthesis) for slot in row]
        remainder = _GRID_UNITS - sum(widths)
        keyword_last = any(
            kind in {"keyword_tags", "recurring_terms"} for kind in row[-1].block_types
        )
        if remainder and keyword_last:
            ratios = [*widths[:-1], remainder, widths[-1]]
            all_columns = st.columns(ratios, gap="small")
            columns = [*all_columns[:len(widths) - 1], all_columns[-1]]
        elif remainder:
            # No blank trailing column here: `_grid_rows` already packed
            # every slot that fits into this row (greedy, order-preserving -
            # a slot too wide for `remainder` genuinely cannot join without
            # reordering), so a leftover unit that stays unfilled is just
            # dead space at the row's right edge. Live-verified 2026-08-11.
            # Stretching the row's own cards over the full row instead of
            # reserving that space for nothing keeps the same *relative*
            # proportions between cards in this row, at the cost of their
            # absolute width no longer matching same-width cards in another
            # row - a smaller inconsistency than a visible empty gap.
            columns = st.columns(widths, gap="small")
        else:
            columns = st.columns(widths, gap="small")
        for slot, column in zip(row, columns):
            with column:
                _render_slot(
                    slot, list(dict.fromkeys(slot.items)), result, synthesis, risks,
                    opportunities, strengths, weaknesses, uncorroborated_ids,
                    presentation,
                    question,
                    compact=True,
                )

    # Sections report_planner dropped for lack of evidence, shown with its
    # recorded reason so a gap in the report is visible rather than silent.
    render_omitted_sections(getattr(result.report_plan, "omitted_sections", None) if result.report_plan else None)

    with st.expander("Evidence & Sources"):
        st.markdown(render_source_list(result), unsafe_allow_html=True)

    monitoring = prefer_audience_content(report, "monitoring_indicators", synthesis.monitoring_indicators, 1)
    render_footer_note(monitoring[0] if monitoring else None)
