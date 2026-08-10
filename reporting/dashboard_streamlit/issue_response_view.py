"""Evidence-safe Issue -> Impact -> Action dashboard composition."""

from __future__ import annotations

from typing import Any

import streamlit as st

from audience.presentation import load_audience_presentation
from common.action_quality import actions_for_owner, routed_action_owner
from common.block_shapes import headline_kpi
from common.content_quality_validator import exclude_market_category_entities
from common.purpose_slots import kpi_evidence_key
from reporting.dashboard_streamlit.components import (
    action_impact_lookup,
    headline_stats,
    bar_metric_groups,
    clean_citation,
    comparison_points_to_table,
    dedupe_clean,
    has_comparison,
    has_timeseries,
    prefer_audience_content,
    prefer_audience_content_raw,
    render_action_list,
    render_cause_tree,
    render_importance_bars,
    render_comparison_table,
    render_executive_summary,
    render_footer_note,
    render_kpi_row,
    render_metric_bar,
    render_metric_chart,
    render_page_header,
    render_row_list,
    render_source_list,
    render_swot,
)
from reporting.dashboard_streamlit.components import evidence_url as _evidence_url


def _points_for_roles(result: Any, roles: set[str], limit: int = 4) -> list[tuple[str, str, str]]:
    # registered_sources, not planned_sources: a collector running the AI
    # search harness (sk_broadband) searches the full registry, not just the
    # top-N select_top_sources() trims planned_sources to, so a collected
    # document's source can legitimately sit outside that trimmed list. Using
    # planned_sources here silently dropped such a document from every
    # role-filtered fallback panel below - not "no signal", just unlabelled.
    # registered_sources is always a superset (select_top_sources only narrows
    # planned_sources), so this never changes behaviour for a sector whose
    # collector only ever searches planned_sources in the first place.
    plan = result.source_plan
    sources = (plan.registered_sources or plan.planned_sources) if plan else []
    by_name = {source.name: source for source in sources}
    rows: list[tuple[str, str, str]] = []
    for analysis in result.document_analyses or []:
        source = by_name.get(analysis.source_id)
        if source is None or source.role not in roles:
            continue
        for point in dedupe_clean(analysis.key_points or [analysis.summary], 2):
            rows.append((analysis.source_id or "출처", point, analysis.analysis_confidence or "-"))
    return rows[:limit]


def _card_header(title: str) -> None:
    st.markdown(f'<div class="ts-card-inner"><h3>{title}</h3></div>', unsafe_allow_html=True)


def render_issue_response_dashboard(result: Any, question: str, sector: str, audience: str, purpose: str) -> None:
    market_keywords = getattr(
        getattr(getattr(result, "sector_route", None), "matched_profile", None),
        "market_keywords", None,
    )
    # A market/category label ("IPTV") sitting in comparison_points beside
    # real competitors ("KT"/"SKB"/"LGU+") reads as a competitor to the
    # comparison table below - filtered once here against the sector's own
    # registered market_keywords, same fix as generic_dashboard.py's.
    synthesis = result.synthesis.model_copy(update={
        "comparison_points": exclude_market_category_entities(
            result.synthesis.comparison_points, market_keywords,
        ),
    })
    report = result.generated_report
    summary = clean_citation((report.executive_summary if report else None) or synthesis.synthesis_text)
    market_rows = _points_for_roles(result, {"market_analysis", "search", "regulatory_official"})
    competitor_rows = _points_for_roles(result, {"competitor_official"})
    audience_id = (
        result.report_plan.audience_id if getattr(result, "report_plan", None) else "_default"
    )
    presentation = load_audience_presentation(audience_id)
    risks = prefer_audience_content(
        report, "risks", synthesis.risks, presentation.narrative_limit
    )
    opportunities = prefer_audience_content(
        report, "opportunities", synthesis.opportunities, presentation.narrative_limit
    )
    # strengths/weaknesses are never LLM-rewritten (report_generator._repair_section
    # always takes them from the rule-based fallback, i.e. straight from synthesis) -
    # they're facts, not audience-tailored prose, so there's nothing to prefer here.
    strengths = dedupe_clean(synthesis.strengths, 3)
    weaknesses = dedupe_clean(synthesis.weaknesses, 3)
    action_owner = routed_action_owner(getattr(result, "sector_route", None))
    actions = actions_for_owner(
        prefer_audience_content_raw(
            report, "actions", synthesis.recommended_actions, presentation.narrative_limit
        ),
        action_owner,
    )
    monitoring = prefer_audience_content(
        report, "monitoring_indicators", synthesis.monitoring_indicators,
        presentation.narrative_limit,
    )

    question_terms = question.split()

    render_page_header(question, sector, audience, purpose)
    # This view only ever renders issue_response reports.
    headline_point = headline_kpi(synthesis.metric_series, question)
    render_executive_summary(
        summary, heading=presentation.summary_label, headline_point=headline_point,
    )
    # Without this filter, Key Metrics repeats the exact figure the summary
    # just showed: headline_kpi and render_kpi_row's own ranking share one
    # selection (rank_kpi_candidates), so the top pick is the same for both -
    # see generic_dashboard.py's identical fix via resolve_slots'
    # `initial_drawn` for the purpose-skeleton dashboard.
    kpi_points = synthesis.metric_series
    if headline_point is not None:
        headline_key = kpi_evidence_key(headline_point)
        kpi_points = [
            point for point in kpi_points if kpi_evidence_key(point) != headline_key
        ]
    render_kpi_row(
        kpi_points, limit=presentation.kpi_limit,
        question_terms=question_terms,
    )

    columns = st.columns(3)
    with columns[0]:
        with st.container(border=True):
            _card_header("Market Trend")
            bar_groups = bar_metric_groups(synthesis.metric_series)
            shown_anything = False
            if has_timeseries(synthesis.metric_series):
                render_metric_chart(synthesis.metric_series,
                                    grounded_claims=synthesis.grounded_claims)
                shown_anything = True
            for group in bar_groups:
                render_metric_bar(group, synthesis.grounded_claims)
                shown_anything = True
            if not shown_anything:
                st.markdown(
                    render_row_list(market_rows, "시장 추이를 그릴 수치 시계열이 없어 확인된 신호만 표시합니다."),
                    unsafe_allow_html=True,
                )
    with columns[1]:
        with st.container(border=True):
            _card_header("Competitor Analysis")
            if has_comparison(synthesis.comparison_points):
                headers, rows = comparison_points_to_table(synthesis.comparison_points)
                st.markdown(render_comparison_table(headers, rows), unsafe_allow_html=True)
            else:
                st.markdown(
                    render_row_list(competitor_rows, "검증을 통과한 경쟁사 자료가 없습니다."),
                    unsafe_allow_html=True,
                )
    with columns[2]:
        with st.container(border=True):
            _card_header("SWOT")
            st.markdown(
                render_swot(strengths=strengths, weaknesses=weaknesses, opportunities=opportunities, threats=risks),
                unsafe_allow_html=True,
            )

    # Only this action's own [doc_id=...] resolves its evidence link, and the
    # expected-impact cell stays empty unless a real link exists. Both used to
    # be filled positionally (action N borrowed evidence N / business_impact N),
    # which produced a citation arrow pointing at an unrelated document and an
    # impact phrase with nothing tying it to the action.
    # Expected Impact is filled only where a source actually stated what the
    # action would achieve (GeneratedReport.action_impacts, verified against
    # the evidence); the rest stay empty rather than borrowing a neighbour's.
    impacts = action_impact_lookup(result.generated_report)
    action_rows = [
        (
            clean_citation(raw_action),
            impacts.get(clean_citation(raw_action)),
            _evidence_url(raw_action, result),
        )
        for raw_action in actions
    ]
    # Drawn only when the analyzer verified a causal chain / scored the
    # claims; both are no-ops otherwise, so a report without them looks
    # exactly as it did before rather than showing an empty frame.
    render_cause_tree(synthesis.grounded_claims)
    render_importance_bars(synthesis.grounded_claims)

    render_action_list(action_rows, owner=action_owner)

    with st.expander("Evidence & Sources"):
        st.markdown(render_source_list(result), unsafe_allow_html=True)

    render_footer_note(monitoring[0] if monitoring else "새로운 근거가 수집되면 핵심 지표와 경쟁 신호를 갱신합니다.")
