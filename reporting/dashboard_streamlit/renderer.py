"""Design-neutral Streamlit block renderer.

Thin compat layer over `reporting.dashboard_streamlit.blocks` (the actual
block registry). This module keeps the stable public surface
(`render`, `render_block`, `register_renderer`, `normalized_block_type`) used
by app.py and existing tests, while every block's schema/render/description
lives in its own file under `blocks/`.

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
from reporting.dashboard_streamlit import blocks as _blocks  # noqa: F401  (populates the registry)
from reporting.dashboard_streamlit.blocks import registry as _registry
from reporting.dashboard_streamlit.blocks.base import BlockDefinition

BlockRenderer = Callable[[DashboardBlock], None]

_SECTION_LABELS = {
    "executive_summary": "핵심 요약",
    "overview": "전체 맥락",
    "current_situation": "현재 상황",
    "market_status": "시장 현황",
    "near_term_outlook": "단기 전망",
    "issue": "핵심 이슈",
    "impact": "주요 영향",
    "response_actions": "대응 과제",
    "trend": "변화 신호",
    "opportunity": "사업 기회",
    "investment_signal": "투자 신호",
    "strategic_recommendation": "전략 제안",
    "problem": "문제 정의",
    "root_cause": "원인 구조",
    "improvement_plan": "개선 계획",
    "key_implication": "핵심 시사점",
    "risk_and_opportunity": "위험과 기회",
    "recommended_action": "권고 과제",
}

_BLOCK_LABELS = {
    "text": "SUMMARY",
    "metrics": "KEY SIGNALS",
    "matrix": "PRIORITY VIEW",
    "graph": "CAUSE MAP",
    "chart": "TREND VIEW",
    "bar": "RANKED VIEW",
    "timeline": "WATCH POINTS",
    "list": "ACTION LIST",
    "evidence": "EVIDENCE",
}


def _require_streamlit() -> None:
    if st is None:
        raise RuntimeError("Streamlit is required to render the dashboard UI")


def register_renderer(block_type: str, renderer: BlockRenderer) -> None:
    """Backward-compat shim: registers a bare render function with an open schema."""
    from pydantic import BaseModel, ConfigDict

    class _OpenContent(BaseModel):
        model_config = ConfigDict(extra="allow")

    _registry.register(BlockDefinition(block_type=block_type, schema=_OpenContent, render=renderer, description=""))


def normalized_block_type(block: DashboardBlock | dict[str, Any]) -> str:
    value = block.block_type if isinstance(block, DashboardBlock) else block.get("block_type", "auto")
    return value if value in _registry.known_types() else "custom"


def render_block(block: DashboardBlock | dict[str, Any]) -> None:
    _require_streamlit()
    parsed = block if isinstance(block, DashboardBlock) else DashboardBlock.model_validate(block)
    resolved_type = normalized_block_type(parsed)
    st.caption(_BLOCK_LABELS.get(resolved_type, "INSIGHT BLOCK"))
    st.subheader(_SECTION_LABELS.get(parsed.section, parsed.title or parsed.section.replace("_", " ").title()))
    definition = _registry.get(resolved_type) or _registry.get("custom")
    definition.render(parsed)


def render(layout: DynamicLayout) -> None:
    """Render blocks in backend-provided order with no layout/design assumptions."""
    _require_streamlit()
    for block in layout.blocks:
        with st.container(border=True):
            render_block(block)
