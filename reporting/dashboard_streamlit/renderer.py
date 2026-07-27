"""Streamlit dashboard renderer stub. No real Streamlit app is built yet."""

from __future__ import annotations

from common.contracts import DynamicLayout


def render(layout: DynamicLayout) -> str:
    return (
        f"template_only: dashboard_streamlit renderer not implemented "
        f"(request_id={layout.request_id}, {len(layout.blocks)} block(s) pending)"
    )
