"""Timeline block ("timeline") - ordered watch-point / monitoring steps.

Moved verbatim from renderer.py's old `_render_timeline`; only the schema and
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


class TimelineContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    monitoring_indicators: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    values = _shared.content_values(_shared.payload(block), "monitoring_indicators", "opportunities", "key_points")
    if not values:
        st.caption("근거에서 확인된 일정이나 모니터링 시점이 없습니다.")
        return
    markup = '<div class="ts-timeline">' + "".join(
        f'<div class="ts-timeline-step"><b>{index:02d}</b>{escape(clean_citation(str(value)))}</div>'
        for index, value in enumerate(values, 1)
    ) + "</div>"
    st.markdown(markup, unsafe_allow_html=True)


register(
    BlockDefinition(
        block_type="timeline",
        schema=TimelineContent,
        render=render,
        description="모니터링 지표나 향후 확인 시점을 순서대로 나열하는 블록.",
    )
)
