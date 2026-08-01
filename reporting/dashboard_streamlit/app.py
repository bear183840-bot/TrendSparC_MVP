"""Design-neutral TrendSparC Streamlit intake and result shell.

Run with: streamlit run reporting/dashboard_streamlit/app.py
"""

from __future__ import annotations

import base64
import sys
import uuid
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from audience.contracts import list_audience_ids, load_audience_profile
from common.contracts import Attachment, UserRequest
from common.errors import StageStatus
from core.request_pipeline.pipeline import run_pipeline
from core.sector_router.router import scan_sectors
from reporting.dashboard_streamlit.renderer import render

SECTORS_DIR = PROJECT_ROOT / "sectors"
AUTO_DETECT_LABEL = "자동 감지 (질문 내용으로 판단)"

st.set_page_config(page_title="TrendSparC_MVP", layout="wide")

if "result" not in st.session_state:
    st.session_state.result = None
if "submitted_question" not in st.session_state:
    st.session_state.submitted_question = None

st.title("TrendSparC_MVP")
st.caption("질문과 선택 정보를 입력하면 분석 결과 블록을 생성합니다. 최종 시각 디자인은 아직 적용하지 않았습니다.")

with st.form("intake_form"):
    question = st.text_area("질문", placeholder="예: SK하이닉스 HBM4 양산 및 고객사 공급 현황은?", height=140)

    uploaded_files = st.file_uploader(
        "첨부자료 (선택)",
        accept_multiple_files=True,
        help="PDF, DOCX, TXT, MD, CSV, JSON, HTML 파일을 질문과 동일한 분석 근거로 사용합니다.",
    )

    audience_ids = list_audience_ids()
    audience_labels = {audience_id: load_audience_profile(audience_id).display_name for audience_id in audience_ids}
    selected_audience = st.selectbox(
        "청중 (선택)",
        options=audience_ids,
        format_func=lambda audience_id: audience_labels.get(audience_id, audience_id),
    ) if audience_ids else None

    sector_profiles = scan_sectors(SECTORS_DIR)
    sector_options = [AUTO_DETECT_LABEL] + sorted(sector_profiles.keys())
    selected_sector_label = st.selectbox("계열사/섹터 (선택)", options=sector_options)
    selected_sector = None if selected_sector_label == AUTO_DETECT_LABEL else selected_sector_label

    dry_run = st.checkbox("구조만 확인 (API 호출 없음)", value=False)
    submitted = st.form_submit_button("분석 시작")

if submitted:
    if not question.strip():
        st.error("질문을 입력해주세요.")
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
        with st.spinner("수집 및 분석 중..."):
            st.session_state.result = run_pipeline(request, dry_run=dry_run, requested_sector_id=selected_sector)
            st.session_state.submitted_question = question

result = st.session_state.result
if result is not None:
    st.divider()
    st.header("분석 결과")
    st.write(st.session_state.submitted_question)

    context = {
        "sector": result.sector_route.sector_id if result.sector_route else None,
        "purpose": result.report_purpose.purpose_id if result.report_purpose else None,
        "audience": result.report_plan.audience_id if result.report_plan else None,
        "documents": result.synthesis.source_count if result.synthesis else 0,
        "unique_sources": result.synthesis.unique_source_count if result.synthesis else 0,
        "generation_mode": result.generated_report.generation_mode if result.generated_report else None,
    }
    st.json(context)

    if result.halted_at_stage:
        failed = [trace for trace in result.trace if trace.status == StageStatus.FAILED]
        reason = failed[0].reason if failed else "알 수 없음"
        st.error(f"'{result.halted_at_stage}' 단계에서 중단되었습니다: {reason}")

    if result.layout is not None and result.layout.blocks:
        render(result.layout)
    elif not result.halted_at_stage:
        st.info("표시할 결과 블록이 없습니다.")

    with st.expander("실행 기록 및 원본 계약"):
        st.json(
            {
                "trace": [trace.model_dump(mode="json") for trace in result.trace],
                "attachments": [item.model_dump(mode="json") for item in result.attachment_extractions],
                "layout": result.layout.model_dump(mode="json") if result.layout else None,
            }
        )
