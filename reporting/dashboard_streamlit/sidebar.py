"""Compact sidebar navigation and archived-result downloads."""

from __future__ import annotations

import base64
import textwrap
from datetime import datetime
from html import escape
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components

from core.run_archive import list_runs, load_result
from reporting.dashboard_streamlit.logo import wordmark_html
from reporting.export.artifacts import ArtifactKind, ensure_artifact
from reporting.export.report_pdf import pdf_font_available

_DOWNLOAD_LABELS: dict[ArtifactKind, tuple[str, str]] = {
    "dashboard_pdf": ("▤  Dashboard PDF", "Dashboard PDF"),
    "report_pdf": ("▧  Report PDF", "Report PDF"),
    "result_json": ("{ }  Result JSON", "Result JSON"),
}
_RECENT_LIMIT = 7
_DOWNLOAD_RUN_LIMIT = 4


def _short_question(value: str, width: int = 34) -> str:
    return textwrap.shorten(" ".join((value or "(질문 없음)").split()), width=width, placeholder="…")


def _timestamp(value: str | None) -> str:
    if not value:
        return "현재 실행"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:16].replace("T", " ")
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _runs_with_current(current: Any | None, question: str) -> list[dict]:
    runs = list_runs(limit=24)
    if current is not None and not any(run.get("request_id") == current.request_id for run in runs):
        runs.insert(0, {
            "request_id": current.request_id,
            "question": question,
            "sector_id": getattr(getattr(current, "sector_route", None), "sector_id", None),
            "purpose_id": getattr(getattr(current, "report_purpose", None), "purpose_id", None),
            "archived_at": None,
            "reopenable": True,
        })
    return runs


def _result_for(run: dict, current: Any | None) -> Any | None:
    if current is not None and run.get("request_id") == current.request_id:
        return current
    return load_result(run.get("request_id", ""))


def _open_run(run: dict) -> None:
    reopened = load_result(run.get("request_id", ""))
    if reopened is None:
        st.error("저장된 결과를 읽지 못했습니다.")
        return
    st.session_state.result = reopened
    st.session_state.submitted_question = run.get("question") or "분석 결과"
    st.session_state.terminal_log = None
    st.session_state.sidebar_page = "dashboard"
    st.session_state.artifact_preview = None
    st.query_params["run"] = reopened.request_id
    st.rerun()


def _render_download_list(kind: ArtifactKind, runs: list[dict], current: Any | None) -> None:
    _, title = _DOWNLOAD_LABELS[kind]
    st.markdown(f'<div class="ts-side-subtitle">{escape(title)}</div>', unsafe_allow_html=True)
    if kind != "result_json" and not pdf_font_available():
        st.caption("한글 PDF 글꼴이 없어 현재 환경에서는 PDF를 만들 수 없습니다.")
        return
    shown = 0
    for run in runs:
        if shown >= _DOWNLOAD_RUN_LIMIT:
            break
        result = _result_for(run, current)
        if result is None:
            continue
        question = run.get("question") or "분석 결과"
        try:
            path = ensure_artifact(kind, result, question)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"내보내기 실패: {exc}")
            continue
        shown += 1
        st.markdown(
            '<div class="ts-download-record">'
            f'<small>{escape(_timestamp(run.get("archived_at")))}</small>'
            f'<b title="{escape(question)}">{escape(_short_question(question, 31))}</b>'
            f'<span>{escape(run.get("sector_id") or "-")} · '
            f'{escape(run.get("purpose_id") or "-")}</span></div>',
            unsafe_allow_html=True,
        )
        controls = st.columns(2, gap="small") if kind != "result_json" else [None, st.container()]
        if kind != "result_json":
            with controls[0]:
                if st.button("View", key=f"preview_{kind}_{result.request_id}", use_container_width=True):
                    st.session_state.artifact_preview = {
                        "kind": kind, "request_id": result.request_id, "question": question,
                    }
                    st.session_state.sidebar_page = "artifact_preview"
                    st.rerun()
        with controls[-1]:
            st.download_button(
                "Download", path.read_bytes(), file_name=path.name,
                mime="application/pdf" if kind != "result_json" else "application/json",
                key=f"download_{kind}_{result.request_id}", use_container_width=True,
            )
    if shown == 0:
        st.caption("다운로드 가능한 저장 결과가 없습니다.")


def render_sidebar(current: Any | None, question: str, reset: Callable[[], None]) -> None:
    """Render navigation without changing any analysis or dashboard contract."""
    runs = _runs_with_current(current, question)
    with st.sidebar:
        st.markdown(wordmark_html(), unsafe_allow_html=True)
        if st.button("✦  New Trend Report                         ›", key="sidebar_new_report",
                     use_container_width=True):
            reset()
            st.query_params.clear()
            st.rerun()

        active = st.session_state.get("sidebar_page", "dashboard")
        if st.button("▦  Dashboard", key=f"sidebar_nav_dashboard_{active == 'dashboard'}",
                     use_container_width=True):
            st.session_state.sidebar_page = "dashboard"
            st.session_state.artifact_preview = None
            st.rerun()
        if st.button("⚙  Settings", key=f"sidebar_nav_settings_{active == 'settings'}",
                     use_container_width=True):
            st.session_state.sidebar_page = "settings"
            st.session_state.artifact_preview = None
            st.rerun()

        st.markdown('<div class="ts-side-divider"></div><div class="ts-side-heading">Download</div>',
                    unsafe_allow_html=True)
        selected = st.session_state.get("sidebar_download_kind")
        for kind, (label, _) in _DOWNLOAD_LABELS.items():
            if st.button(label + "  ›", key=f"sidebar_download_{kind}_{selected == kind}",
                         use_container_width=True):
                st.session_state.sidebar_download_kind = None if selected == kind else kind
                st.rerun()
        selected = st.session_state.get("sidebar_download_kind")
        if selected in _DOWNLOAD_LABELS:
            _render_download_list(selected, runs, current)

        st.markdown('<div class="ts-side-divider"></div><div class="ts-side-heading">Recent Questions</div>',
                    unsafe_allow_html=True)
        show_all = bool(st.session_state.get("sidebar_show_all"))
        visible_runs = runs[:24 if show_all else _RECENT_LIMIT]
        for run in visible_runs:
            question_text = run.get("question") or "(질문 없음)"
            disabled = not run.get("reopenable") and (
                current is None or run.get("request_id") != current.request_id
            )
            if st.button(
                _short_question(question_text), key=f"sidebar_recent_{run.get('request_id')}",
                help=question_text, disabled=disabled, use_container_width=True,
            ):
                if current is not None and run.get("request_id") == current.request_id:
                    st.session_state.sidebar_page = "dashboard"
                    st.session_state.artifact_preview = None
                    st.rerun()
                _open_run(run)
        if len(runs) > _RECENT_LIMIT:
            if st.button("Show less" if show_all else "View all", key="sidebar_recent_toggle"):
                st.session_state.sidebar_show_all = not show_all
                st.rerun()

        st.markdown(
            '<div class="ts-side-divider"></div><div class="ts-side-heading">Additional Features</div>',
            unsafe_allow_html=True,
        )
        for key, label in (
            ("favorites", "☆  Favorites"), ("compare", "⇄  Compare"),
            ("share", "↗  Share"), ("search", "⌕  Search"),
        ):
            st.button(label, key=f"sidebar_feature_{key}", disabled=True, use_container_width=True)
        st.markdown('<div class="ts-coming-soon">Coming Soon</div>', unsafe_allow_html=True)


def render_settings_placeholder() -> None:
    st.markdown('<div class="ts-settings-page"><h1>Settings</h1>', unsafe_allow_html=True)
    cards = (
        ("Language", "언어 및 표시 언어 설정", "한국어 · English"),
        ("Default Report Settings", "기본 분석 설정", "Company · Audience · Report Purpose"),
        ("API Usage & Credits", "외부 API 사용량 및 잔여 크레딧", "Usage dashboard · Coming Soon"),
    )
    for title, description, detail in cards:
        st.markdown(
            '<section class="ts-settings-card">'
            f'<div><h3>{escape(title)}</h3><p>{escape(description)}</p><small>{escape(detail)}</small></div>'
            '<span>Coming Soon&nbsp;&nbsp;›</span></section>', unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)


def render_artifact_preview(current: Any | None) -> bool:
    preview = st.session_state.get("artifact_preview")
    if not preview:
        return False
    result = current if current is not None and current.request_id == preview["request_id"] \
        else load_result(preview["request_id"])
    if result is None:
        st.error("미리 볼 저장 결과를 찾지 못했습니다.")
        return True
    path = ensure_artifact(preview["kind"], result, preview["question"])
    data = path.read_bytes()
    st.markdown(f"## {_DOWNLOAD_LABELS[preview['kind']][1]}")
    st.caption(f"{preview['question']} · {result.request_id}")
    st.download_button("Download", data, file_name=path.name, mime="application/pdf")
    encoded = base64.b64encode(data).decode("ascii")
    components.html(
        f'<embed src="data:application/pdf;base64,{encoded}" type="application/pdf" '
        'width="100%" height="860px" style="border:0;border-radius:12px">',
        height=880,
    )
    return True
