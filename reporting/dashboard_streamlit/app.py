"""TrendSparC intake and purpose-driven dashboard shell.

Run with: python -m streamlit run reporting/dashboard_streamlit/app.py
"""

from __future__ import annotations

import base64
import re
import sys
import textwrap
import uuid
from html import escape
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from audience.contracts import list_audience_ids
from common.contracts import Attachment, UserRequest
from common.errors import StageStatus
from core.request_pipeline.pipeline import run_pipeline
from core.sector_router.router import scan_sectors
from reporting.dashboard_streamlit.collection_progress_view import render_execution_record
from reporting.dashboard_streamlit.generic_dashboard import render_generic_dashboard
from reporting.dashboard_streamlit.issue_response_view import render_issue_response_dashboard
from reporting.dashboard_streamlit.logo import wordmark_html
from reporting.dashboard_streamlit.theme import dashboard_css

SECTORS_DIR = PROJECT_ROOT / "sectors"
_SECTOR_ENGLISH_NAME = re.compile(r"\(([^)]+)\)")


def _sector_english_label(sector_id: str, display_name: str) -> str:
    if sector_id == "general":
        return "General"
    match = _SECTOR_ENGLISH_NAME.search(display_name)
    return match.group(1) if match else display_name
PURPOSE_LABELS = {
    "current_status": "현황 파악",
    "issue_response": "이슈 대응",
    "future_business": "미래사업",
    "root_cause": "문제·원인 분석",
}
AUDIENCE_LABELS = {
    "practitioner": "실무진",
    "executive": "임원",
    "management": "경영진",
    "external": "외부 파트너·고객",
    "_default": "질문자 기준",
}

st.set_page_config(page_title="TrendSparC", page_icon="◼", layout="wide", initial_sidebar_state="expanded")

APP_STATE_VERSION = 4
if st.session_state.get("app_state_version") != APP_STATE_VERSION:
    st.session_state.result = None
    st.session_state.submitted_question = None
    st.session_state.recent_questions = []
    st.session_state.dark_mode = False
    st.session_state.app_state_version = APP_STATE_VERSION


def _html(markup: str) -> None:
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)




def _reset() -> None:
    st.session_state.result = None
    st.session_state.submitted_question = None


result = st.session_state.result

if result is None:
    _html(
        "<style>[data-testid='stSidebar'],[data-testid='collapsedControl']{display:none}"
        ".block-container{max-width:1120px}"
        "[data-testid='stAppViewContainer']{background:#ffffff!important;}"
        "[class*='st-key-landing_toggle']{opacity:.45;transform:scale(.8);transform-origin:top right;}"
        "</style>"
    )
    theme_col, toggle_col = st.columns([0.94, 0.06], vertical_alignment="center")
    with toggle_col, st.container(key="landing_toggle"):
        st.session_state.dark_mode = st.toggle("다크", value=st.session_state.dark_mode, label_visibility="collapsed")
else:
    with st.sidebar:
        _html(wordmark_html())
        if st.button("⌕  New Analysis", use_container_width=True):
            _reset()
            st.rerun()
        _html(
            '<div class="ts-side-nav"><div class="ts-nav active">▦　Dashboard</div>'
            '<div class="ts-nav">▣　Monitoring</div><div class="ts-nav">⚙　Settings</div></div>'
        )
        st.session_state.dark_mode = st.toggle("다크 모드", value=st.session_state.dark_mode)
        recent = st.session_state.recent_questions[-4:]
        recent_html = '<div class="ts-recent"><b>Recent Analyses</b>'
        for index, item in enumerate(reversed(recent)):
            active = " active" if index == 0 else ""
            recent_html += f'<div class="ts-recent-item{active}">{textwrap.shorten(item, width=27, placeholder="…")}</div>'
        _html(recent_html + "</div>")

_html(dashboard_css(st.session_state.dark_mode))

if result is None:
    _html(
        '<section class="ts-landing">' + wordmark_html(large=True) +
        '<h1 class="ts-question-title">What should we work on?</h1></section>'
    )
    with st.form("intake_form"):
        question = st.text_area(
            "질문",
            placeholder="분석이 필요한 시장·기술·사업 이슈를 질문해 주세요.",
            height=180,
            label_visibility="collapsed",
        )
        audience_ids = list_audience_ids()
        sector_profiles = scan_sectors(SECTORS_DIR)

        with st.container(key="intake_meta_row"):
            meta_row = st.columns([0.11, 0.14, 0.14, 0.61], vertical_alignment="center")
            with meta_row[0]:
                with st.popover("＋　첨부", use_container_width=True):
                    uploaded_files = st.file_uploader(
                        "파일첨부",
                        accept_multiple_files=True,
                        label_visibility="collapsed",
                        help="PDF, DOCX, TXT, MD, CSV, JSON, HTML 파일을 질문과 함께 근거로 사용합니다.",
                    )
            with meta_row[1]:
                selected_audience = st.selectbox(
                    "청중",
                    options=audience_ids,
                    index=None,
                    placeholder="청중",
                    format_func=lambda audience_id: AUDIENCE_LABELS.get(audience_id, audience_id),
                    label_visibility="collapsed",
                )
            with meta_row[2]:
                selected_sector = st.selectbox(
                    "계열사",
                    options=sorted(sector_profiles.keys()),
                    index=None,
                    placeholder="계열사",
                    format_func=lambda sector_id: _sector_english_label(sector_id, sector_profiles[sector_id].display_name),
                    label_visibility="collapsed",
                )

        _, submit_col = st.columns([0.78, 0.22])
        with submit_col:
            submitted = st.form_submit_button("Start  →", use_container_width=True)

    if submitted:
        if not question.strip():
            st.error("질문을 입력해 주세요.")
        else:
            attachments = [
                Attachment(
                    attachment_id=str(uuid.uuid4()),
                    filename=file.name,
                    content_type=file.type,
                    size_bytes=file.size,
                    content_base64=base64.b64encode(file.getvalue()).decode("ascii"),
                )
                for file in (uploaded_files or [])
            ]
            request = UserRequest(
                request_id=f"req_ui_{uuid.uuid4().hex[:8]}",
                question=question,
                target_audience=selected_audience,
                requested_sector_id=selected_sector,
                attachments=attachments,
            )
            with st.spinner("관련 근거를 수집하고 의사결정 흐름을 구성하고 있습니다..."):
                st.session_state.result = run_pipeline(request, dry_run=False, requested_sector_id=selected_sector)
                st.session_state.submitted_question = question
                st.session_state.recent_questions.append(question)
            st.rerun()
    st.stop()

question = st.session_state.submitted_question or "분석 결과"
direct_answer = getattr(result, "direct_answer", None)
if direct_answer:
    _html(f'<div class="ts-top-question"><span class="search">⌕</span>{escape(question)}<span class="ts-sk">SK</span></div>')
    st.chat_message("assistant").write(direct_answer)
    st.stop()

sector = result.sector_route.matched_profile.display_name if result.sector_route and result.sector_route.matched_profile else "일반"
purpose_id = result.report_purpose.purpose_id if result.report_purpose else None
purpose = PURPOSE_LABELS.get(purpose_id, purpose_id or "분석")
audience_id = result.report_plan.audience_id if result.report_plan else "_default"
audience = AUDIENCE_LABELS.get(audience_id, audience_id)

if result.halted_at_stage:
    failed = [trace for trace in result.trace if trace.status == StageStatus.FAILED]
    reason = failed[0].reason if failed else "분석 파이프라인이 완료되지 않았습니다."
    st.error(f"{result.halted_at_stage} 단계에서 중단되었습니다: {reason}")

no_evidence = result.synthesis is not None and result.synthesis.source_count == 0
if no_evidence:
    _html(f'<div class="ts-top-question"><span class="search">⌕</span>{escape(question)}<span class="ts-sk">SK</span></div>')
    st.error("관련 소스를 수집·검증하지 못해 리포트를 생성하지 않았습니다.")
elif purpose_id == "issue_response" and result.synthesis is not None:
    render_issue_response_dashboard(result, question, sector, audience, purpose)
elif result.layout is not None and result.layout.blocks:
    render_generic_dashboard(result, question, sector, audience, purpose, purpose_id)
else:
    st.info("표시할 결과 블록이 없습니다.")

with st.expander("실행 기록 및 원본 계약"):
    render_execution_record(result.collection_events, result.trace)
    st.markdown("#### 원본 계약")
    st.json({
        "trace": [trace.model_dump(mode="json") for trace in result.trace],
        "attachments": [item.model_dump(mode="json") for item in result.attachment_extractions],
        "layout": result.layout.model_dump(mode="json") if result.layout else None,
    })
