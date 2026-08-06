"""Bar block ("bar") - new block type, not present in the original renderer.py.

Ordered list of evidence items. Deliberately *not* a bar chart: the only
signal available here is display order, and a bar whose length is computed
from row position reads as a measured quantity while carrying no more
information than the row number beside it. Rank is shown as rank.
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


class BarContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    key_points: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    business_impacts: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = _shared.content_values(data, "key_points", "opportunities", "business_impacts")
    else:
        values = []
    if not values:
        st.caption("표시할 순위 항목이 없습니다.")
        return
    rows = "".join(
        f'<div class="ts-bar-row"><span class="num">{index:02d}</span>'
        f'<span class="label">{escape(clean_citation(str(value)))}</span></div>'
        for index, value in enumerate(values, 1)
    )
    st.markdown(f'<div class="ts-bar-list">{rows}</div>', unsafe_allow_html=True)


register(
    BlockDefinition(
        block_type="bar",
        schema=BarContent,
        render=render,
        description="근거 항목을 순위(등장 순서) 기준 막대 길이로 표현하는 신규 블록.",
    )
)
