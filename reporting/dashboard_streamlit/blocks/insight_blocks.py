"""Dense evidence blocks that extend the delivered design library."""

from __future__ import annotations

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from common.contracts import ComparisonPoint, DashboardBlock, MetricPoint, SynthesisClaim
from reporting.dashboard_streamlit.blocks import _shared
from reporting.dashboard_streamlit.blocks.base import BlockDefinition
from reporting.dashboard_streamlit.blocks.registry import register
from reporting.dashboard_streamlit.components import (
    render_benchmark_table,
    render_composition_breakdown,
    render_ranking_list,
    render_recurring_terms,
)


class InsightBlockContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    metric_points: list[dict] = Field(default_factory=list)
    comparison_points: list[dict] = Field(default_factory=list)
    grounded_claims: list[dict] = Field(default_factory=list)


def _models(data: object, key: str, model: type[BaseModel]) -> list[BaseModel]:
    if not isinstance(data, dict):
        return []
    return [model.model_validate(item) for item in data.get(key, []) if isinstance(item, dict)]


def render_ranking(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    render_ranking_list(_models(data, "metric_points", MetricPoint))


def render_composition(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    render_composition_breakdown(_models(data, "metric_points", MetricPoint))


def render_benchmark(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    render_benchmark_table(
        _models(data, "comparison_points", ComparisonPoint),
        _models(data, "metric_points", MetricPoint),
    )


def render_keywords(block: DashboardBlock) -> None:
    data = _shared.payload(block)
    claims = _models(data, "grounded_claims", SynthesisClaim)
    if claims:
        render_recurring_terms(claims)
    else:
        st.caption("여러 출처에서 반복 확인된 표현이 없습니다.")


for block_type, render, description in (
    ("ranking_list", render_ranking, "4개 이상 항목의 정확한 값과 순위를 압축 표시."),
    ("keyword_tags", render_keywords, "여러 출처의 반복어를 문서 수와 함께 태그로 표시."),
    ("composition_breakdown", render_composition, "명시된 전체의 상세 구성비를 레일과 목록으로 표시."),
    ("benchmark_table", render_benchmark, "기업·국가의 공통 정량/정성 기준을 한 표로 비교."),
):
    register(BlockDefinition(
        block_type=block_type, schema=InsightBlockContent, render=render,
        description=description,
    ))
