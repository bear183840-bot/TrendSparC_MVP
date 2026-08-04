"""Evidence-safe Issue -> Impact -> Action dashboard composition."""

from __future__ import annotations

from typing import Any

import streamlit as st

from reporting.dashboard_streamlit.components import (
    clean_citation,
    comparison_points_to_table,
    dedupe_clean,
    dedupe_raw,
    has_comparison,
    has_timeseries,
    render_action_list,
    render_comparison_table,
    render_executive_summary,
    render_footer_note,
    render_metric_chart,
    render_page_header,
    render_row_list,
    render_swot,
)
from reporting.dashboard_streamlit.components import evidence_url as _evidence_url


def _points_for_roles(result: Any, roles: set[str], limit: int = 4) -> list[tuple[str, str, str]]:
    by_name = {source.name: source for source in (result.source_plan.planned_sources if result.source_plan else [])}
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
    synthesis = result.synthesis
    report = result.generated_report
    summary = clean_citation((report.executive_summary if report else None) or synthesis.synthesis_text)
    market_rows = _points_for_roles(result, {"market_analysis", "search", "regulatory_official"})
    competitor_rows = _points_for_roles(result, {"competitor_official"})
    risks = dedupe_clean(synthesis.risks, 3)
    opportunities = dedupe_clean(synthesis.opportunities, 3)
    strengths = dedupe_clean(synthesis.strengths, 3)
    weaknesses = dedupe_clean(synthesis.weaknesses, 3)
    actions = dedupe_raw(synthesis.recommended_actions, 4)
    impacts = dedupe_clean(synthesis.business_impacts, 4)
    evidence = dedupe_raw(synthesis.evidence)
    monitoring = dedupe_clean(synthesis.monitoring_indicators, 3)

    render_page_header(question, sector, audience, purpose)
    render_executive_summary(summary, len(risks), len(opportunities))

    columns = st.columns(3)
    with columns[0]:
        with st.container(border=True):
            _card_header("Market Trend")
            if has_timeseries(synthesis.metric_series):
                render_metric_chart(synthesis.metric_series)
            else:
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

    action_rows = []
    for index, raw_action in enumerate(actions, 1):
        url = _evidence_url(raw_action, result) or (_evidence_url(evidence[index - 1], result) if index <= len(evidence) else None)
        impact_note = impacts[index - 1] if index <= len(impacts) else "기대 효과는 추가 검증 필요"
        action_rows.append((clean_citation(raw_action), impact_note, url))
    render_action_list(action_rows)

    render_footer_note(monitoring[0] if monitoring else "새로운 근거가 수집되면 핵심 지표와 경쟁 신호를 갱신합니다.")
