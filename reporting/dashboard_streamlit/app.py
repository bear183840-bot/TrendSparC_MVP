"""Design-neutral TrendSparC Streamlit intake and result shell.

Run with: streamlit run reporting/dashboard_streamlit/app.py
"""

from __future__ import annotations

import base64
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
from reporting.dashboard_streamlit.renderer import render

SECTORS_DIR = PROJECT_ROOT / "sectors"
AUTO_DETECT_LABEL = "자동 감지 (질문 내용으로 판단)"
NO_AUDIENCE_LABEL = "선택 없음 (질문자 기준)"
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
    "external": "외부사람",
    "_default": "질문자 기준",
}

st.set_page_config(page_title="TrendSparC_MVP", layout="wide")

APP_STATE_VERSION = 3
if st.session_state.get("app_state_version") != APP_STATE_VERSION:
    st.session_state.result = None
    st.session_state.submitted_question = None
    st.session_state.app_state_version = APP_STATE_VERSION

def _html(markup: str) -> None:
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)


_html(
    """
    <style>
    :root { --ts-navy:#071b35; --ts-blue:#173d67; --ts-red:#ea002c; --ts-orange:#f47725; --ts-ink:#17243b; --ts-muted:#68778c; --ts-line:#dfe6ef; }
    html, body, [class*="css"] { font-family: Pretendard, "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
    [data-testid="stAppViewContainer"] { background:radial-gradient(circle at 92% 2%, rgba(234,0,44,.055), transparent 24rem),#f3f6fa; }
    [data-testid="stHeader"] { background:rgba(243,246,250,.78); backdrop-filter:blur(14px); }
    [data-testid="stToolbar"] { right:1.2rem; }
    .block-container { max-width:1240px; padding:2.2rem 2rem 5rem; }
    .ts-intro { display:flex; flex-direction:column; align-items:center; padding:2.4rem 1rem 2rem; text-align:center; }
    .ts-wordmark { display:flex; align-items:center; gap:1rem; }
    .ts-logo-mark { position:relative; display:grid; place-items:center; width:58px; height:58px; border-radius:17px; background:linear-gradient(135deg,#071b35 0 57%,#ea002c 57% 78%,#f47725 78%); color:white; box-shadow:0 10px 26px rgba(7,27,53,.2); font-size:1rem; font-weight:900; letter-spacing:-.04em; transform:rotate(-4deg); }
    .ts-intro h1 { margin:0; color:var(--ts-navy); font-size:clamp(3rem,7vw,5.15rem); line-height:1; letter-spacing:-.075em; font-weight:900; }
    .ts-tagline { margin:1.4rem 0 0; color:#53657a; font-size:clamp(1rem,2vw,1.3rem); line-height:1.65; letter-spacing:-.025em; }
    .ts-tagline strong { color:var(--ts-navy); font-weight:850; }
    div[data-testid="stForm"] { max-width:900px; margin:0 auto; background:white; border:1px solid rgba(207,218,231,.9); border-radius:22px; padding:1.15rem 1.2rem 1rem; box-shadow:0 18px 50px rgba(23,59,104,.1); }
    div[data-testid="stTextArea"] textarea { min-height:118px; border:1px solid #cbd7e6; border-radius:14px; background:#fbfcfe; padding:1rem 1.1rem; font-size:1.05rem; line-height:1.65; transition:.18s ease; }
    div[data-testid="stTextArea"] textarea:focus { border-color:#315f91; box-shadow:0 0 0 4px rgba(49,95,145,.1); background:white; }
    div[data-testid="stExpander"] { border:1px solid #e2e8f0; border-radius:12px; background:#f8fafc; }
    div[data-testid="stExpander"] summary p { color:#344b65; font-weight:750; }
    div[data-baseweb="select"] > div, [data-testid="stFileUploaderDropzone"] { border-radius:11px; border-color:#d4deea; background:white; }
    div[data-testid="stPopover"] button { width:48px; height:48px; min-height:48px; padding:0; border:1px solid #d5dfe9; border-radius:50%; background:#f4f7fa; color:var(--ts-navy); font-size:1.55rem; line-height:1; box-shadow:none; }
    div[data-testid="stPopover"] button:hover { border-color:#aebdce; background:#eaf0f6; color:var(--ts-red); }
    div[data-testid="stFormSubmitButton"] button { min-height:48px; border:0; border-radius:11px; background:linear-gradient(100deg,#d9002a,#ef334f); box-shadow:0 8px 20px rgba(234,0,44,.2); font-weight:800; letter-spacing:-.01em; transition:.18s ease; }
    div[data-testid="stFormSubmitButton"] button:hover { transform:translateY(-1px); box-shadow:0 11px 25px rgba(234,0,44,.27); }
    .ts-result-head { margin-bottom:1rem; padding:1.55rem 1.7rem; border:1px solid #dfe6ef; border-left:5px solid var(--ts-red); border-radius:16px; background:white; box-shadow:0 8px 28px rgba(23,59,104,.055); }
    .ts-result-label { color:var(--ts-red); font-size:.7rem; font-weight:850; letter-spacing:.12em; }
    .ts-result-head h2 { margin:.42rem 0 0; color:var(--ts-navy); font-size:1.45rem; line-height:1.45; letter-spacing:-.035em; }
    .ts-context { display:flex; flex-wrap:wrap; gap:.5rem; margin:.75rem 0 1.35rem; }
    .ts-chip { border:1px solid #dce5ef; background:#edf3f9; color:#294b70; padding:.4rem .72rem; border-radius:999px; font-size:.76rem; font-weight:700; }
    .ts-chip.auto { border-color:#f5ccd3; background:#fff1f3; color:#b81733; }
    div[data-testid="stVerticalBlockBorderWrapper"] { background:white; border-color:#dfe6ef !important; border-radius:16px; box-shadow:0 7px 24px rgba(23,59,104,.052); transition:.18s ease; }
    div[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color:#cbd8e6 !important; box-shadow:0 11px 30px rgba(23,59,104,.075); }
    div[data-testid="stMetric"] { min-height:104px; padding:.85rem 1rem; border:1px solid #e5ebf2; border-radius:12px; background:linear-gradient(145deg,#f8fafc,#fff); }
    div[data-testid="stMetricLabel"] { color:#69798d; }
    div[data-testid="stMetricValue"] { color:var(--ts-navy); font-weight:800; }
    h2, h3 { color:var(--ts-navy); letter-spacing:-.03em; }
    hr { border-color:#e1e7ef; }
    @media (max-width:720px) { .block-container{padding:1.2rem .9rem 3rem}.ts-intro{padding:1.5rem .4rem}.ts-wordmark{gap:.7rem}.ts-logo-mark{width:44px;height:44px;border-radius:13px}.ts-intro h1{font-size:3rem}div[data-testid="stForm"]{padding:1rem} }
    </style>
    """
)

if "result" not in st.session_state:
    st.session_state.result = None
if "submitted_question" not in st.session_state:
    st.session_state.submitted_question = None

result = st.session_state.result

if result is None:
    _html(
        """
        <section class="ts-intro">
          <div class="ts-wordmark">
            <div class="ts-logo-mark">TS</div>
            <h1>TrendSparC</h1>
          </div>
          <p class="ts-tagline"><strong>질문 하나로,</strong> 의사결정에 필요한 흐름을 만듭니다.</p>
        </section>
        """
    )

    with st.form("intake_form"):
        question = st.text_area(
            "질문",
            placeholder="예: 삼성전자와 마이크론의 HBM4 개발 단계와 양산 일정을 비교해줘.",
            height=132,
            label_visibility="collapsed",
        )

        audience_ids = list_audience_ids()
        sector_profiles = scan_sectors(SECTORS_DIR)
        sector_options = [AUTO_DETECT_LABEL] + sorted(sector_profiles.keys())

        action_left, action_right = st.columns([0.075, 0.925], vertical_alignment="center")
        with action_left:
            with st.popover("＋"):
                selected_sector_label = st.selectbox(
                    "계열사 선택",
                    options=sector_options,
                    format_func=lambda sector_id: (
                        sector_profiles[sector_id].display_name
                        if sector_id in sector_profiles
                        else sector_id
                    ),
                )
                audience_options = [NO_AUDIENCE_LABEL] + audience_ids
                selected_audience_label = st.selectbox(
                    "청중 선택",
                    options=audience_options,
                    format_func=lambda audience_id: (
                        NO_AUDIENCE_LABEL if audience_id == NO_AUDIENCE_LABEL
                        else AUDIENCE_LABELS.get(audience_id, audience_id)
                    ),
                )
                selected_audience = None if selected_audience_label == NO_AUDIENCE_LABEL else selected_audience_label
                uploaded_files = st.file_uploader(
                    "파일첨부",
                    accept_multiple_files=True,
                    help="PDF, DOCX, TXT, MD, CSV, JSON, HTML 파일을 질문과 동일한 분석 근거로 사용합니다.",
                )
        with action_right:
            submitted = st.form_submit_button("분석 시작", use_container_width=True)

        selected_sector = None if selected_sector_label == AUTO_DETECT_LABEL else selected_sector_label

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
            with st.spinner("관련 근거를 수집하고 대시보드를 구성하고 있습니다..."):
                st.session_state.result = run_pipeline(
                    request,
                    dry_run=False,
                    requested_sector_id=selected_sector,
                )
                st.session_state.submitted_question = question
            st.rerun()
else:
    brand_column, reset_column = st.columns([0.82, 0.18], vertical_alignment="center")
    with brand_column:
        _html('<div class="ts-wordmark"><div class="ts-logo-mark">TS</div><div style="font-size:1.65rem;font-weight:900;letter-spacing:-.05em;color:#071b35">TrendSparC</div></div>')
    with reset_column:
        if st.button("＋ 새 질문", use_container_width=True):
            st.session_state.result = None
            st.session_state.submitted_question = None
            st.rerun()

    _html(
        f"""
        <section class="ts-result-head">
          <div class="ts-result-label">DYNAMIC RESULT</div>
          <h2>{escape(st.session_state.submitted_question or "분석 결과")}</h2>
        </section>
        """
    )

    direct_answer = getattr(result, "direct_answer", None)
    if direct_answer:
        st.chat_message("assistant").write(direct_answer)
        with st.expander("실행 기록"):
            st.json({"trace": [trace.model_dump(mode="json") for trace in result.trace]})
        st.stop()

    context = {
        "sector": (
            result.sector_route.matched_profile.display_name
            if result.sector_route and result.sector_route.matched_profile
            else None
        ),
        "purpose": result.report_purpose.purpose_id if result.report_purpose else None,
        "audience": (
            AUDIENCE_LABELS.get(result.report_plan.audience_id, result.report_plan.audience_id)
            if result.report_plan
            else None
        ),
        "documents": result.synthesis.source_count if result.synthesis else 0,
        "unique_sources": result.synthesis.unique_source_count if result.synthesis else 0,
        "generation_mode": result.generated_report.generation_mode if result.generated_report else None,
    }
    auto_sector = result.sector_route and result.sector_route.reason and "requested" not in result.sector_route.reason.lower()
    auto_purpose = result.report_purpose is not None
    chips = [
        f'<span class="ts-chip{(" auto" if auto_sector else "")}">계열사 · {context["sector"] or "-"}</span>',
        f'<span class="ts-chip">청중 · {context["audience"] or "-"}</span>',
        f'<span class="ts-chip{(" auto" if auto_purpose else "")}">보고 목적 · {PURPOSE_LABELS.get(context["purpose"], context["purpose"] or "-")}</span>',
        f'<span class="ts-chip">출처 · {context["unique_sources"]}</span>',
    ]
    _html('<div class="ts-context">' + "".join(chips) + '</div>')

    if result.halted_at_stage:
        failed = [trace for trace in result.trace if trace.status == StageStatus.FAILED]
        template_only = [trace for trace in result.trace if trace.status == StageStatus.TEMPLATE_ONLY]
        if template_only:
            st.warning(f"질문은 일반 주제로 분류되었습니다. {template_only[0].reason}")
        else:
            reason = failed[0].reason if failed else "알 수 없음"
            st.error(f"'{result.halted_at_stage}' 단계에서 중단되었습니다: {reason}")

    if result.entities and getattr(result.entities, "extraction_method", None) == "rule_fallback":
        st.warning(
            "질문 AI 해석에 실패해 비상 규칙 기반 검색을 사용했습니다. "
            "검색 품질이 낮을 수 있으니 잠시 후 다시 시도해주세요."
        )

    no_evidence = result.synthesis is not None and result.synthesis.source_count == 0
    if no_evidence:
        searched_terms = result.source_plan.question_keywords if result.source_plan else []
        st.error("관련 소스를 수집·검증하지 못해 리포트를 생성하지 않았습니다.")
        if searched_terms:
            st.caption("사용한 검색어: " + " · ".join(searched_terms[:8]))
    elif result.layout is not None and result.layout.blocks:
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
