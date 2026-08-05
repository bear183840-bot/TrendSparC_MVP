"""Action List block ("list") - numbered list of recommended actions or items.

Moved verbatim from renderer.py's old `_render_list`; only the schema and
description are new.
"""

from __future__ import annotations

from html import escape

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.blocks import _shared
from reporting.dashboard_streamlit.blocks.base import BlockDefinition
from reporting.dashboard_streamlit.blocks.registry import register
from reporting.dashboard_streamlit.components import clean_citation


class ActionListContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    actions: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = data.get("actions") or data.get("monitoring_indicators") or data.get("key_points") or data.get("items", [])
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


register(
    BlockDefinition(
        block_type="list",
        schema=ActionListContent,
        render=render,
        description="실행 과제나 모니터링 항목을 번호가 매겨진 목록으로 보여주는 블록.",
    )
)
