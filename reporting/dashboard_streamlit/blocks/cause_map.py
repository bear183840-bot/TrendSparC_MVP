"""Cause Map block ("graph") - problem/cause/impact/improvement 4-column view.

Moved verbatim from renderer.py's old `_render_graph`; only the schema and
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


class CauseMapContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str | None = None
    risks: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    stages = [
        ("문제", _shared.content_values(data, "summary")),
        ("원인", _shared.content_values(data, "risks", "key_points")),
        ("영향", _shared.content_values(data, "evidence")),
        ("개선", _shared.content_values(data, "actions")),
    ]
    columns = st.columns(4)
    for column, (label, values) in zip(columns, stages):
        with column:
            st.caption(label)
            body = "".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values[:3])
            st.markdown(f"<ul>{body}</ul>" if body else '<p class="ts-empty">근거 확인 필요</p>', unsafe_allow_html=True)


register(
    BlockDefinition(
        block_type="graph",
        schema=CauseMapContent,
        render=render,
        description="문제-원인-영향-개선을 4열로 나열하는 원인 구조 블록.",
    )
)
