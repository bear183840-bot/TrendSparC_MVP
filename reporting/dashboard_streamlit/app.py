"""Request-intake Streamlit app — the first real user-facing surface.

One page, two states (session-state driven): an intake form (question,
attachments, audience, sector) and, once submitted, the pipeline result
rendered structurally. This intentionally does not attempt polished
per-audience/per-intent visual design yet — that is later content work
once a team member finalizes the dashboard design (Figma) and someone
implements reporting/dashboard_streamlit/renderer.py for real. Until then,
this app renders whatever DynamicLayout the pipeline produces as plain
section blocks, so the actual data flow can be exercised and iterated on
now.

Run with: streamlit run reporting/dashboard_streamlit/app.py
"""

from __future__ import annotations

import sys
import textwrap
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

SECTORS_DIR = PROJECT_ROOT / "sectors"
AUTO_DETECT_LABEL = "자동 감지 (질문 내용으로 판단)"

# SK 그룹 공통 브랜드 톤(오렌지->레드 그라데이션). 정확한 공식 브랜드 컬러 코드는
# 아니며, 나중에 실제 가이드라인 색상으로 교체하면 됨.
SK_ORANGE = "#F7941D"
SK_RED = "#EE1C25"

# 실제 회사 로고(이미지/벡터)를 복제하지 않고, 섹터별로 구분되는 워드마크 배지만
# 우리가 직접 만든 추상 마크 + 텍스트 스타일로 표시함 (상표/저작권 있는 로고
# 그래픽을 그대로 가져다 쓰지 않기 위함 — SK 계열사들이 실제로 공유하는 CI처럼
# "같은 마크 + 다른 사업부명" 패턴만 흉내냄).
SECTOR_BADGES = {
    "sk_hynix": "SK hynix",
    "sk_broadband": "SK broadband",
    "sk_planet": "SK플래닛",
}

_MARK_SVG = f"""
<svg width="{{size}}" height="{{size}}" viewBox="0 0 40 40" style="vertical-align:middle;">
  <defs>
    <linearGradient id="skGrad{{uid}}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{SK_ORANGE}"/>
      <stop offset="100%" stop-color="{SK_RED}"/>
    </linearGradient>
  </defs>
  <path d="M6 28 C 6 16, 16 6, 28 6 C 22 10, 18 16, 18 22 C 18 16, 24 10, 32 8 C 26 14, 22 20, 22 28 C 22 20, 30 14, 36 12 C 28 22, 18 30, 6 28 Z" fill="url(#skGrad{{uid}})"/>
</svg>
"""


def _mark(size: int = 30, uid: str = "a") -> str:
    return _MARK_SVG.format(size=size, uid=uid)


def _html(markup: str) -> None:
    # textwrap.dedent + strip: st.markdown's underlying Markdown parser treats any
    # line indented 4+ spaces as a code block, which would silently break HTML
    # rendering (everything after gets escaped as literal text) if this string
    # were emitted with the source code's own indentation intact.
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)


st.set_page_config(page_title="TrendSparC_MVP", layout="wide")

if "result" not in st.session_state:
    st.session_state.result = None

_html(f"""
<style>
div.stButton > button[kind="primaryFormSubmit"],
div.stFormSubmitButton > button {{
    background-color: {SK_RED};
    color: white;
    border: none;
}}
div.stFormSubmitButton > button:hover {{
    background-color: #C4141B;
    color: white;
}}
.tsp-hero {{
    background: linear-gradient(135deg, #0B1F3A 0%, #142B52 100%);
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 18px;
}}
.tsp-hero-title {{
    font-size: 1.9rem;
    font-weight: 800;
    color: white;
    margin: 0;
}}
.tsp-hero-caption {{
    color: #C7D3E8;
    font-size: 0.95rem;
    margin-top: 6px;
}}
</style>
""")

_html(f"""
<div class="tsp-hero">
{_mark(34, "hero")}
<span class="tsp-hero-title">&nbsp;TrendSparC</span>
<div class="tsp-hero-caption">SK 계열사 트렌드 인텔리전스 — 질문을 입력하면 트렌드 대시보드가 생성됩니다.</div>
</div>
""")

with st.form("intake_form"):
    question = st.text_area("질문", placeholder="예: SK하이닉스 HBM4 양산 및 고객사 공급 현황은?", height=100)

    with st.popover("＋ 첨부 · 청중 · 계열사"):
        uploaded_files = st.file_uploader(
            "파일/이미지 첨부 (선택)",
            accept_multiple_files=True,
            help="첨부된 파일은 이름/형식/용량만 요청에 기록됩니다. 내용 분석은 아직 구현되지 않았습니다.",
        )

        audience_ids = list_audience_ids()
        audience_labels = {aid: load_audience_profile(aid).display_name for aid in audience_ids}
        selected_audience = st.selectbox(
            "청중 (보고서를 볼 대상)",
            options=audience_ids,
            format_func=lambda aid: audience_labels.get(aid, aid),
        ) if audience_ids else None

        sector_profiles = scan_sectors(SECTORS_DIR)
        sector_options = [AUTO_DETECT_LABEL] + sorted(sector_profiles.keys())
        selected_sector_label = st.selectbox("계열사 (섹터)", options=sector_options)
        selected_sector = None if selected_sector_label == AUTO_DETECT_LABEL else selected_sector_label

        dry_run = st.checkbox("dry-run (실제 API 호출 없이 구조만 확인)", value=False)

    submitted = st.form_submit_button("분석 시작")

if submitted:
    if not question.strip():
        st.error("질문을 입력해주세요.")
    else:
        attachments = [
            Attachment(
                attachment_id=str(uuid.uuid4()),
                filename=f.name,
                content_type=f.type,
                size_bytes=f.size,
            )
            for f in (uploaded_files or [])
        ]
        request = UserRequest(
            request_id=f"req_ui_{uuid.uuid4().hex[:8]}",
            question=question,
            target_audience=selected_audience,
            requested_sector_id=selected_sector,
            attachments=attachments,
        )
        with st.spinner("파이프라인 실행 중..."):
            st.session_state.result = run_pipeline(request, dry_run=dry_run, requested_sector_id=selected_sector)

result = st.session_state.result
if result is not None:
    st.divider()

    routed_sector_id = result.sector_route.sector_id if result.sector_route else None
    badge_label = SECTOR_BADGES.get(routed_sector_id)
    header_col, badge_col = st.columns([5, 1])
    with header_col:
        st.subheader("분석 결과")
    if badge_label is not None:
        with badge_col:
            _html(f"""
<div style="text-align:right; white-space:nowrap;">
{_mark(24, "badge")}
<span style="font-weight:800; font-size:1.05rem; background: linear-gradient(135deg, {SK_ORANGE}, {SK_RED}); -webkit-background-clip: text; background-clip: text; color: transparent;">
&nbsp;{badge_label}
</span>
</div>
""")

    if result.halted_at_stage:
        failed = [t for t in result.trace if t.status == StageStatus.FAILED]
        reason = failed[0].reason if failed else "알 수 없음"
        st.error(f"파이프라인이 '{result.halted_at_stage}' 단계에서 중단되었습니다: {reason}")

    with st.expander("단계별 실행 기록 (StageTrace)"):
        for t in result.trace:
            st.text(f"{t.stage}: {t.status.value}" + (f" — {t.reason}" if t.reason else ""))

    if result.layout is not None and result.layout.blocks:
        st.caption(f"포맷: {result.layout.format}")
        for block in result.layout.blocks:
            st.markdown(f"**{block['section']}**")
            st.json(block["content"])
    elif not result.halted_at_stage:
        st.info("파이프라인은 정상 완료됐지만 표시할 결과 블록이 없습니다 (dry-run이거나 문서가 수집되지 않았을 수 있습니다).")
