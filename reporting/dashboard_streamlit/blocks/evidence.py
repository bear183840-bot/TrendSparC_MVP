"""Evidence block ("evidence") - list of source citations backing the report.

Moved verbatim from renderer.py's old `_render_evidence`; only the schema and
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


class EvidenceContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidence: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    values = _shared.content_values(_shared.payload(block), "evidence")
    if not values:
        st.caption("연결된 근거가 없습니다.")
        return
    rows = "".join(
        f'<li><span class="ts-item-index">↗</span><span>{escape(clean_citation(str(value)))}</span></li>'
        for value in values
    )
    st.markdown(f'<ol class="ts-compact-list">{rows}</ol>', unsafe_allow_html=True)


register(
    BlockDefinition(
        block_type="evidence",
        schema=EvidenceContent,
        render=render,
        description="분석에 사용된 근거 인용을 목록으로 보여주는 블록.",
    )
)
