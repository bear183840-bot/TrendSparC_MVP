"""Non-core block types kept for backward compatibility: "auto" (structural
fallback that dumps whatever fields exist), "text" (summary + highlights),
"metric" (single st.metric), and "custom" (unrecognized block_type).

None of these are part of the user-facing "9 blocks" set, but renderer.py
supported them before this package existed, so they move here unchanged
rather than being dropped.
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st
from pydantic import BaseModel, ConfigDict

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.blocks import _shared
from reporting.dashboard_streamlit.blocks.base import BlockDefinition
from reporting.dashboard_streamlit.blocks.registry import register
from reporting.dashboard_streamlit.components import clean_citation


class AutoContent(BaseModel):
    """Structural fallback - shape varies per section, kept open on purpose."""

    model_config = ConfigDict(extra="allow")


class TextContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str | None = None
    key_points: list[str] = []
    highlights: list[str] = []
    source_count: int | None = None
    unique_source_count: int | None = None
    limitations: list[str] = []


class MetricContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str | None = None
    value: Any = None
    delta: Any = None


class CustomContent(BaseModel):
    model_config = ConfigDict(extra="allow")


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


def render_auto(block: DashboardBlock) -> None:
    for key, value in block.content.items():
        if key in {"title", "section_id"}:
            continue
        _render_scalar_or_collection(key, value)
    if block.data is not None:
        _render_scalar_or_collection("data", block.data)


def render_text(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    if not isinstance(data, dict):
        st.write(data)
        return
    summary = data.get("summary")
    if summary:
        st.markdown(f"### {escape(clean_citation(str(summary)))}")
    highlights = data.get("key_points") or data.get("highlights") or []
    st.markdown(_shared.bullet_list_html(highlights), unsafe_allow_html=True)
    source_count = data.get("source_count")
    unique_source_count = data.get("unique_source_count")
    if source_count is not None or unique_source_count is not None:
        st.markdown(
            '<div class="ts-metric-groups">'
            f'<div class="ts-stat"><small>분석 문서</small><b>{source_count or 0}</b></div>'
            f'<div class="ts-stat"><small>고유 출처</small><b>{unique_source_count or 0}</b></div>'
            "</div>",
            unsafe_allow_html=True,
        )
    limitations = data.get("limitations") or []
    if limitations:
        with st.expander("분석 한계"):
            st.markdown(_shared.bullet_list_html(limitations), unsafe_allow_html=True)


def render_metric(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    if isinstance(data, dict):
        st.metric(
            label=str(data.get("label", block.title or block.section)),
            value=data.get("value", "-"),
            delta=data.get("delta"),
        )
    else:
        st.metric(label=block.title or block.section, value=data)


def render_custom(block: DashboardBlock) -> None:
    st.caption(f"'{block.block_type}' 블록은 임시 표시 방식으로 렌더링됩니다.")
    data = _shared.payload(block)
    if data not in (None, {}, []):
        st.json(data)


register(BlockDefinition(block_type="auto", schema=AutoContent, render=render_auto, description="블록 타입 미지정 시 필드를 그대로 나열하는 구조적 폴백."))
register(BlockDefinition(block_type="text", schema=TextContent, render=render_text, description="요약문 + 핵심 포인트 불릿을 보여주는 기본 텍스트 블록."))
register(BlockDefinition(block_type="metric", schema=MetricContent, render=render_metric, description="단일 지표 값을 st.metric으로 보여주는 블록."))
register(BlockDefinition(block_type="custom", schema=CustomContent, render=render_custom, description="등록되지 않은 block_type에 대한 안전한 폴백 렌더러."))
