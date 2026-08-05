"""Bar block ("bar") - new block type, not present in the original renderer.py.

Rank-based horizontal bar list: bar width reflects display order (priority),
reusing the same non-fabricated-weight approach as
`components.render_action_list`'s impact bar (`_impact_pct`) - never a score
invented from thin air, just "earlier in the ranked list = wider bar".
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


def _rank_weight_pct(rank: int) -> int:
    """Rank-based visual weight (priority order, not a fabricated score)."""
    return max(38, 92 - (rank - 1) * 16)


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
        f'<span class="label">{escape(clean_citation(str(value)))}</span>'
        f'<div class="ts-impact" style="--impact:{_rank_weight_pct(index)}%"></div></div>'
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
