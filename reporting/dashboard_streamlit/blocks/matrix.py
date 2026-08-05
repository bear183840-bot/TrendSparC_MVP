"""Matrix block ("matrix") - two-column risk/opportunity grid.

Moved verbatim from renderer.py's old `_render_matrix`; only the schema and
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


class MatrixContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    risks = _shared.content_values(data, "risks")
    opportunities = _shared.content_values(data, "opportunities")

    def cell(label: str, values: list, empty: str) -> str:
        body = "".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values) or f"<li class='ts-empty'>{escape(empty)}</li>"
        return f'<div class="ts-duo-cell"><h4>{escape(label)}</h4><ul>{body}</ul></div>'

    markup = (
        '<div class="ts-duo">'
        + cell("주요 위험", risks, "확인된 위험 신호가 없습니다.")
        + cell("기회 신호", opportunities, "확인된 기회 신호가 없습니다.")
        + "</div>"
    )
    st.markdown(markup, unsafe_allow_html=True)


register(
    BlockDefinition(
        block_type="matrix",
        schema=MatrixContent,
        render=render,
        description="위험/기회 신호를 2열 그리드로 나란히 보여주는 블록.",
    )
)
