"""Internal plumbing shared by multiple block files - not part of the public registry API."""

from __future__ import annotations

from html import escape
from typing import Any

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.components import clean_citation


def payload(block: DashboardBlock) -> Any:
    return block.data if block.data is not None else block.content


def content_values(data: Any, *keys: str) -> list[Any]:
    if not isinstance(data, dict):
        return []
    values: list[Any] = []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    return values


def bullet_list_html(values: list[Any]) -> str:
    if not values:
        return '<p class="ts-empty">표시할 항목이 없습니다.</p>'
    return "<ul>" + "".join(f"<li>{escape(clean_citation(str(value)))}</li>" for value in values) + "</ul>"
