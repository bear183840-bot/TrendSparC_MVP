"""KPI Card block ("metrics") - grouped counts of key signals as stat cards.

Moved verbatim from renderer.py's old `_render_metrics`; only the schema and
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


class KpiCardContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    key_points: list[str] = Field(default_factory=list)
    business_impacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    groups = [
        ("핵심 영향", _shared.content_values(data, "key_points", "business_impacts")),
        ("위험", _shared.content_values(data, "risks")),
        ("기회", _shared.content_values(data, "opportunities")),
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


register(
    BlockDefinition(
        block_type="metrics",
        schema=KpiCardContent,
        render=render,
        description="핵심 영향/위험/기회 신호 건수를 카드로 요약하는 KPI 블록.",
    )
)
