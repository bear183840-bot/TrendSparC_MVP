"""Table block ("table") - list-of-dicts rendered as an HTML table.

Moved verbatim from renderer.py's old `_render_table`; only the schema and
description are new.
"""

from __future__ import annotations

from html import escape

import streamlit as st
from pydantic import BaseModel, ConfigDict

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.blocks import _shared
from reporting.dashboard_streamlit.blocks.base import BlockDefinition
from reporting.dashboard_streamlit.blocks.registry import register
from reporting.dashboard_streamlit.components import clean_citation


class TableRow(BaseModel):
    """One row of `block.content`/`block.data` - columns are dynamic per
    question, so this stays intentionally open (no fixed field list)."""

    model_config = ConfigDict(extra="allow")


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    if isinstance(data, list) and data and all(isinstance(row, dict) for row in data):
        columns: list[str] = []
        for row in data:
            for key in row:
                if key not in columns:
                    columns.append(key)
        head = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(clean_citation(str(row.get(column, ''))))}</td>" for column in columns) + "</tr>"
            for row in data
        )
        st.markdown(
            f'<div class="ts-table-wrap"><table class="ts-table"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>",
            unsafe_allow_html=True,
        )
        return
    st.dataframe(data, use_container_width=True)


register(
    BlockDefinition(
        block_type="table",
        schema=TableRow,
        render=render,
        description="행(dict) 목록을 컬럼 자동 감지 HTML 표로 렌더링하는 블록.",
    )
)
