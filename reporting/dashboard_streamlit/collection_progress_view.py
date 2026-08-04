"""Human-readable collection and pipeline audit trail for the dashboard."""

from __future__ import annotations

from html import escape

import streamlit as st

from common.contracts import SourceCollectionEvent
from common.errors import StageTrace


_STATUS_LABELS = {
    "started": ("◌", "수집 중", "running"),
    "completed": ("✓", "수집 완료", "completed"),
    "failed": ("!", "수집 실패", "failed"),
    "skipped": ("–", "건너뜀", "skipped"),
}


def latest_collection_events(events: list[SourceCollectionEvent]) -> list[SourceCollectionEvent]:
    """Collapse start/end events into one final row per source, in plan order."""

    latest: dict[tuple[int, str], SourceCollectionEvent] = {}
    for event in events:
        latest[(event.source_index, event.source_name)] = event
    return [latest[key] for key in sorted(latest)]


def render_execution_record(
    collection_events: list[SourceCollectionEvent],
    traces: list[StageTrace],
) -> None:
    st.markdown("#### 출처별 수집 기록")
    rows = latest_collection_events(collection_events)
    if not rows:
        st.caption("기록된 출처별 수집 내역이 없습니다.")
    for event in rows:
        icon, label, css_class = _STATUS_LABELS[event.status]
        count = f" · {event.document_count}건" if event.status == "completed" else ""
        st.markdown(
            (
                f'<div class="ts-collection-row {css_class}">'
                f'<span class="ts-collection-icon">{icon}</span>'
                f'<span class="ts-collection-order">{event.source_index}/{event.source_total}</span>'
                f'<strong>{escape(event.source_name)}</strong>'
                f'<span class="ts-collection-state">{label}{count}</span>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        if event.status == "failed" and event.detail:
            st.caption(event.detail)

    st.markdown("#### 전체 파이프라인")
    for trace in traces:
        status = trace.status.value
        icon = {"ok": "✓", "failed": "!", "skipped": "–", "template_only": "○"}.get(status, "·")
        reason = f" · {trace.reason}" if trace.reason else ""
        st.markdown(f"`{icon}` **{trace.stage}** — {status}{reason}")
