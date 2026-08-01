"""Design-neutral Streamlit block renderer.

The final component choice belongs to the dashboard design handoff. This
module only provides stable receiving slots and safe fallbacks so the pipeline
can already return arbitrary blocks without the UI crashing or inventing a
chart from non-chart data.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:  # contract/unit tests can run without the optional UI runtime
    st = None  # type: ignore[assignment]

from common.contracts import DashboardBlock, DynamicLayout

BlockRenderer = Callable[[DashboardBlock], None]

KNOWN_BLOCK_TYPES = {
    "auto",
    "text",
    "metric",
    "metrics",
    "list",
    "table",
    "chart",
    "timeline",
    "graph",
    "matrix",
    "evidence",
    "custom",
}

_renderer_registry: dict[str, BlockRenderer] = {}


def _require_streamlit() -> None:
    if st is None:
        raise RuntimeError("Streamlit is required to render the dashboard UI")


def register_renderer(block_type: str, renderer: BlockRenderer) -> None:
    """Allow the finalized design to attach a renderer without changing app.py."""
    _renderer_registry[block_type] = renderer


def normalized_block_type(block: DashboardBlock | dict[str, Any]) -> str:
    value = block.block_type if isinstance(block, DashboardBlock) else block.get("block_type", "auto")
    return value if value in KNOWN_BLOCK_TYPES else "custom"


def _payload(block: DashboardBlock) -> Any:
    return block.data if block.data is not None else block.content


def _render_scalar_or_collection(label: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return
    if isinstance(value, list):
        st.markdown(f"**{label.replace('_', ' ').title()}**")
        for item in value:
            st.write(f"- {item}" if not isinstance(item, (dict, list)) else item)
    elif isinstance(value, dict):
        with st.expander(label.replace("_", " ").title()):
            st.json(value)
    else:
        st.markdown(f"**{label.replace('_', ' ').title()}**")
        st.write(value)


def _render_auto(block: DashboardBlock) -> None:
    """Show structured report fields without selecting a visualization."""
    for key, value in block.content.items():
        if key in {"title", "section_id"}:
            continue
        _render_scalar_or_collection(key, value)
    if block.data is not None:
        _render_scalar_or_collection("data", block.data)


def _render_text(block: DashboardBlock) -> None:
    st.write(_payload(block))


def _render_list(block: DashboardBlock) -> None:
    payload = _payload(block)
    values = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
    for value in values:
        st.write(f"- {value}")


def _render_metric(block: DashboardBlock) -> None:
    payload = _payload(block)
    if isinstance(payload, dict):
        st.metric(
            label=str(payload.get("label", block.title or block.section)),
            value=payload.get("value", "-"),
            delta=payload.get("delta"),
        )
    else:
        st.metric(label=block.title or block.section, value=payload)


def _render_table(block: DashboardBlock) -> None:
    payload = _payload(block)
    st.dataframe(payload, use_container_width=True)


def _render_unassigned_visual(block: DashboardBlock) -> None:
    st.caption(f"'{block.block_type}' 표시 방식은 최종 디자인에서 연결됩니다.")
    payload = _payload(block)
    if payload not in (None, {}, []):
        st.json(payload)


register_renderer("auto", _render_auto)
register_renderer("text", _render_text)
register_renderer("list", _render_list)
register_renderer("metric", _render_metric)
register_renderer("metrics", _render_unassigned_visual)
register_renderer("table", _render_table)
register_renderer("chart", _render_unassigned_visual)
register_renderer("timeline", _render_unassigned_visual)
register_renderer("graph", _render_unassigned_visual)
register_renderer("matrix", _render_unassigned_visual)
register_renderer("evidence", _render_auto)
register_renderer("custom", _render_unassigned_visual)


def render_block(block: DashboardBlock | dict[str, Any]) -> None:
    _require_streamlit()
    parsed = block if isinstance(block, DashboardBlock) else DashboardBlock.model_validate(block)
    resolved_type = normalized_block_type(parsed)
    st.subheader(parsed.title or parsed.section.replace("_", " ").title())
    _renderer_registry.get(resolved_type, _render_unassigned_visual)(parsed)


def render(layout: DynamicLayout) -> None:
    """Render blocks in backend-provided order with no layout/design assumptions."""
    _require_streamlit()
    for block in layout.blocks:
        with st.container(border=True):
            render_block(block)
