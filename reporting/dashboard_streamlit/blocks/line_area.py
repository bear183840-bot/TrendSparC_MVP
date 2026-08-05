"""Line/Area block ("chart") - real time-series when data.rows qualifies,
otherwise an honest text fallback (never a fabricated chart).

Moved verbatim from renderer.py's old `_render_chart`; only the schema and
description are new.
"""

from __future__ import annotations

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.blocks import _shared
from reporting.dashboard_streamlit.blocks.base import BlockDefinition
from reporting.dashboard_streamlit.blocks.registry import register


class LineAreaContent(BaseModel):
    """Describes `block.content`; the actual series lives in `block.data.rows`
    (a list of row dicts) with the x/y column names in `block.config`."""

    model_config = ConfigDict(extra="allow")

    opportunities: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)


def render(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    if isinstance(block.data, dict) and isinstance(block.data.get("rows"), list) and block.data["rows"]:
        try:
            import pandas as pd

            x_key = block.config.get("x")
            y_key = block.config.get("y")
            frame = pd.DataFrame(block.data["rows"])
            if x_key in frame.columns and y_key in frame.columns:
                st.area_chart(frame.set_index(x_key)[[y_key]])
                return
        except Exception:
            pass
        st.dataframe(block.data["rows"], use_container_width=True)
        return
    signals = _shared.content_values(data, "opportunities", "key_points", "monitoring_indicators")
    st.caption("수치·시계열 근거가 없어 차트 대신 확인된 신호를 표시합니다.")
    st.markdown(_shared.bullet_list_html(signals), unsafe_allow_html=True)


register(
    BlockDefinition(
        block_type="chart",
        schema=LineAreaContent,
        render=render,
        description="시계열 근거(data.rows)가 있으면 area chart, 없으면 확인된 신호 목록으로 대체.",
    )
)
