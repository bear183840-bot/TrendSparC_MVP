"""Design-neutral Streamlit block renderer.

The final component choice belongs to the dashboard design handoff. This
module only provides stable receiving slots and safe fallbacks so the pipeline
can already return arbitrary blocks without the UI crashing or inventing a
chart from non-chart data.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:  # contract/unit tests can run without the optional UI runtime
    st = None  # type: ignore[assignment]

from common.contracts import DashboardBlock, DynamicLayout
from reporting.dashboard_streamlit.components import clean_citation

BlockRenderer = Callable[[DashboardBlock], None]

KNOWN_BLOCK_TYPES = {
    "auto",
    "text",
    "metric",
    "metrics",
    "list",
    "table",
    "chart",
    "timeline",
    "graph",
    "matrix",
    "evidence",
    "custom",
}

_renderer_registry: dict[str, BlockRenderer] = {}

_SECTION_LABELS = {
    "executive_summary": "핵심 요약",
    "overview": "전체 맥락",
    "current_situation": "현재 상황",
    "market_status": "시장 현황",
    "near_term_outlook": "단기 전망",
    "issue": "핵심 이슈",
    "impact": "주요 영향",
    "response_actions": "대응 과제",
    "trend": "변화 신호",
    "opportunity": "사업 기회",
    "investment_signal": "투자 신호",
    "strategic_recommendation": "전략 제안",
    "problem": "문제 정의",
    "root_cause": "원인 구조",
    "improvement_plan": "개선 계획",
    "key_implication": "핵심 시사점",
    "risk_and_opportunity": "위험과 기회",
    "recommended_action": "권고 과제",
}

_BLOCK_LABELS = {
    "text": "SUMMARY",
    "metrics": "KEY SIGNALS",
    "matrix": "PRIORITY VIEW",
    "graph": "CAUSE MAP",
    "chart": "TREND VIEW",
    "timeline": "WATCH POINTS",
    "list": "ACTION LIST",
    "evidence": "EVIDENCE",
}


def _require_streamlit() -> None:
    if st is None:
        raise RuntimeError("Streamlit is required to render the dashboard UI")


def register_renderer(block_type: str, renderer: BlockRenderer) -> None:
    """Allow the finalized design to attach a renderer without changing app.py."""
    _renderer_registry[block_type] = renderer


def normalized_block_type(block: DashboardBlock | dict[str, Any]) -> str:
    value = block.block_type if isinstance(block, DashboardBlock) else block.get("block_type", "auto")
    return value if value in KNOWN_BLOCK_TYPES else "custom"


def _payload(block: DashboardBlock) -> Any:
    return block.data if block.data is not None else block.content


def _render_scalar_or_collection(label: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return
    if isinstance(value, list):
        st.markdown(f"**{label.replace('_', ' ').title()}**")
        for item in value:
            st.write(f"- {item}" if not isinstance(item, (dict, list)) else item)
    elif isinstance(value, dict):
        with st.expander(label.replace("_", " ").title()):
            st.json(value)
    else:
        st.markdown(f"**{label.replace('_', ' ').title()}**")
        st.write(value)


def _render_auto(block: DashboardBlock) -> None:
    """Show structured report fields without selecting a visualization."""
    for key, value in block.content.items():
        if key in {"title", "section_id"}:
            continue
        _render_scalar_or_collection(key, value)
    if block.data is not None:
        _render_scalar_or_collection("data", block.data)


def _bullet_list_html(values: list[Any]) -> str:
    if not values:
        return '<p class="ts-empty">표시할 항목이 없습니다.</p>'
    return "<ul>" + "".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values) + "</ul>"


def _render_text(block: DashboardBlock) -> None:
    payload = _payload(block)
    if not isinstance(payload, dict):
        st.write(payload)
        return
    summary = payload.get("summary")
    if summary:
        st.markdown(f"### {escape(clean_citation(str(summary)))}")
    highlights = payload.get("key_points") or payload.get("highlights") or []
    st.markdown(_bullet_list_html(highlights), unsafe_allow_html=True)
    source_count = payload.get("source_count")
    unique_source_count = payload.get("unique_source_count")
    if source_count is not None or unique_source_count is not None:
        st.markdown(
            '<div class="ts-metric-groups">'
            f'<div class="ts-stat"><small>분석 문서</small><b>{source_count or 0}</b></div>'
            f'<div class="ts-stat"><small>고유 출처</small><b>{unique_source_count or 0}</b></div>'
            "</div>",
            unsafe_allow_html=True,
        )
    limitations = payload.get("limitations") or []
    if limitations:
        with st.expander("분석 한계"):
            st.markdown(_bullet_list_html(limitations), unsafe_allow_html=True)


def _render_list(block: DashboardBlock) -> None:
    payload = _payload(block)
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = payload.get("actions") or payload.get("monitoring_indicators") or payload.get("key_points") or payload.get("items", [])
    else:
        values = []
    if not values:
        st.caption("표시할 실행 항목이 없습니다.")
        return
    rows = "".join(
        f'<li><span class="ts-item-index">{index:02d}</span><span>{escape(clean_citation(str(value)))}</span></li>'
        for index, value in enumerate(values, 1)
    )
    st.markdown(f'<ol class="ts-compact-list">{rows}</ol>', unsafe_allow_html=True)


def _render_metric(block: DashboardBlock) -> None:
    payload = _payload(block)
    if isinstance(payload, dict):
        st.metric(
            label=str(payload.get("label", block.title or block.section)),
            value=payload.get("value", "-"),
            delta=payload.get("delta"),
        )
    else:
        st.metric(label=block.title or block.section, value=payload)


def _render_table(block: DashboardBlock) -> None:
    payload = _payload(block)
    if isinstance(payload, list) and payload and all(isinstance(row, dict) for row in payload):
        columns: list[str] = []
        for row in payload:
            for key in row:
                if key not in columns:
                    columns.append(key)
        head = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(clean_citation(str(row.get(column, ''))))}</td>" for column in columns) + "</tr>"
            for row in payload
        )
        st.markdown(
            f'<div class="ts-table-wrap"><table class="ts-table"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>",
            unsafe_allow_html=True,
        )
        return
    st.dataframe(payload, use_container_width=True)


def _content_values(payload: Any, *keys: str) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    values = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    return values


def _render_metrics(block: DashboardBlock) -> None:
    payload = _payload(block)
    groups = [
        ("핵심 영향", _content_values(payload, "key_points", "business_impacts")),
        ("위험", _content_values(payload, "risks")),
        ("기회", _content_values(payload, "opportunities")),
    ]
    visible = [(label, values) for label, values in groups if values]
    if not visible:
        st.caption("확인된 지표가 없습니다.")
        return
    cards = "".join(
        f'<div class="ts-stat"><small>{escape(label)}</small><b>{len(values)}건</b>'
        f'<ul>{"".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values[:3])}</ul></div>'
        for label, values in visible
    )
    st.markdown(f'<div class="ts-metric-groups">{cards}</div>', unsafe_allow_html=True)


def _render_matrix(block: DashboardBlock) -> None:
    payload = _payload(block)
    risks = _content_values(payload, "risks")
    opportunities = _content_values(payload, "opportunities")

    def cell(label: str, values: list[Any], empty: str) -> str:
        body = "".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values) or f"<li class='ts-empty'>{escape(empty)}</li>"
        return f'<div class="ts-duo-cell"><h4>{escape(label)}</h4><ul>{body}</ul></div>'

    markup = (
        '<div class="ts-duo">'
        + cell("주요 위험", risks, "확인된 위험 신호가 없습니다.")
        + cell("기회 신호", opportunities, "확인된 기회 신호가 없습니다.")
        + "</div>"
    )
    st.markdown(markup, unsafe_allow_html=True)


def _render_graph(block: DashboardBlock) -> None:
    payload = _payload(block)
    stages = [
        ("문제", _content_values(payload, "summary")),
        ("원인", _content_values(payload, "risks", "key_points")),
        ("영향", _content_values(payload, "evidence")),
        ("개선", _content_values(payload, "actions")),
    ]
    columns = st.columns(4)
    for column, (label, values) in zip(columns, stages):
        with column:
            st.caption(label)
            body = "".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values[:3])
            st.markdown(f"<ul>{body}</ul>" if body else '<p class="ts-empty">근거 확인 필요</p>', unsafe_allow_html=True)


def _render_chart(block: DashboardBlock) -> None:
    payload = _payload(block)
    if isinstance(block.data, dict) and isinstance(block.data.get("rows"), list) and block.data["rows"]:
        try:
            import pandas as pd

            x_key = block.config.get("x")
            y_key = block.config.get("y")
            frame = pd.DataFrame(block.data["rows"])
            if x_key in frame.columns and y_key in frame.columns:
                st.area_chart(frame.set_index(x_key)[[y_key]])
                return
        except Exception:
            pass
        st.dataframe(block.data["rows"], use_container_width=True)
        return
    signals = _content_values(payload, "opportunities", "key_points", "monitoring_indicators")
    st.caption("수치·시계열 근거가 없어 차트 대신 확인된 신호를 표시합니다.")
    st.markdown(_bullet_list_html(signals), unsafe_allow_html=True)


def _render_timeline(block: DashboardBlock) -> None:
    values = _content_values(_payload(block), "monitoring_indicators", "opportunities", "key_points")
    if not values:
        st.caption("근거에서 확인된 일정이나 모니터링 시점이 없습니다.")
        return
    markup = '<div class="ts-timeline">' + "".join(
        f'<div class="ts-timeline-step"><b>{index:02d}</b>{escape(clean_citation(str(value)))}</div>'
        for index, value in enumerate(values, 1)
    ) + "</div>"
    st.markdown(markup, unsafe_allow_html=True)


def _render_evidence(block: DashboardBlock) -> None:
    values = _content_values(_payload(block), "evidence")
    if not values:
        st.caption("연결된 근거가 없습니다.")
        return
    rows = "".join(
        f'<li><span class="ts-item-index">↗</span><span>{escape(clean_citation(str(value)))}</span></li>'
        for value in values
    )
    st.markdown(f'<ol class="ts-compact-list">{rows}</ol>', unsafe_allow_html=True)


def _render_unassigned_visual(block: DashboardBlock) -> None:
    st.caption(f"'{block.block_type}' 블록은 임시 표시 방식으로 렌더링됩니다.")
    payload = _payload(block)
    if payload not in (None, {}, []):
        st.json(payload)


register_renderer("auto", _render_auto)
register_renderer("text", _render_text)
register_renderer("list", _render_list)
register_renderer("metric", _render_metric)
register_renderer("metrics", _render_metrics)
register_renderer("table", _render_table)
register_renderer("chart", _render_chart)
register_renderer("timeline", _render_timeline)
register_renderer("graph", _render_graph)
register_renderer("matrix", _render_matrix)
register_renderer("evidence", _render_evidence)
register_renderer("custom", _render_unassigned_visual)


def render_block(block: DashboardBlock | dict[str, Any]) -> None:
    _require_streamlit()
    parsed = block if isinstance(block, DashboardBlock) else DashboardBlock.model_validate(block)
    resolved_type = normalized_block_type(parsed)
    st.caption(_BLOCK_LABELS.get(resolved_type, "INSIGHT BLOCK"))
    st.subheader(_SECTION_LABELS.get(parsed.section, parsed.title or parsed.section.replace("_", " ").title()))
    _renderer_registry.get(resolved_type, _render_unassigned_visual)(parsed)


def render(layout: DynamicLayout) -> None:
    """Render blocks in backend-provided order with no layout/design assumptions."""
    _require_streamlit()
    for block in layout.blocks:
        with st.container(border=True):
            render_block(block)
