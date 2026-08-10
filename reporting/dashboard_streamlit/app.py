"""TrendSparC intake and purpose-driven dashboard shell.

Run with: python -m streamlit run reporting/dashboard_streamlit/app.py
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import textwrap
import threading
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
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
from core.request_pipeline.pipeline import PipelineResult, run_pipeline
from core.synthesis.synthesizer import repair_dropped_comparison_points
from core.run_archive import load_result
from core.sector_router.router import scan_sectors
from reporting.dashboard_streamlit.collection_progress_view import _STATUS_LABELS, render_execution_record
from reporting.dashboard_streamlit.generic_dashboard import render_generic_dashboard
from reporting.dashboard_streamlit.logo import wordmark_html
from reporting.dashboard_streamlit.build_stamp import build_stamp_html
from reporting.dashboard_streamlit.theme import dashboard_css
from reporting.dashboard_streamlit.sidebar import (
    render_artifact_preview,
    render_settings_placeholder,
    render_sidebar,
)

SECTORS_DIR = PROJECT_ROOT / "sectors"
_SECTOR_ENGLISH_NAME = re.compile(r"\(([^)]+)\)")
_INTERNAL_PROVENANCE_KEYS = {"grounded_claims", "conclusions"}


def _without_internal_provenance(value):
    """Remove audit-only claim graphs from user-visible debug JSON."""
    if isinstance(value, dict):
        return {
            key: _without_internal_provenance(item)
            for key, item in value.items()
            if key not in _INTERNAL_PROVENANCE_KEYS
        }
    if isinstance(value, list):
        return [_without_internal_provenance(item) for item in value]
    return value


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

APP_STATE_VERSION = 9  # 9: compact sidebar navigation and artifact center
if st.session_state.get("app_state_version") != APP_STATE_VERSION:
    st.session_state.result = None
    st.session_state.submitted_question = None
    st.session_state.recent_questions = []
    st.session_state.dark_mode = False
    # Orange is the product's own accent - it is what the delivered design is
    # drawn in and what every block's tokens are tuned against. Burgundy is
    # the alternate, reachable from the toggle.
    st.session_state.accent_theme = "orange"
    st.session_state.terminal_log = None
    st.session_state.sidebar_page = "dashboard"
    st.session_state.sidebar_download_kind = None
    st.session_state.sidebar_show_all = False
    st.session_state.artifact_preview = None
    st.session_state.app_state_version = APP_STATE_VERSION



def _archived_question(result: "PipelineResult") -> str:
    """The question a saved run was asked, read back from its archive record.

    New results carry the question themselves.  Older full-result files can
    still recover it from their source plan, then from the small archive.
    """
    if result.question:
        return result.question
    search_context = getattr(getattr(result, "source_plan", None), "search_context", None)
    if search_context is not None and search_context.question:
        return search_context.question
    record = Path("storage/requests") / f"{result.request_id}.json"
    if record.exists():
        try:
            return json.loads(record.read_text(encoding="utf-8")).get("question") or "분석 결과"
        except (OSError, ValueError):
            pass
    return "분석 결과"



def _diagnostics(result: "PipelineResult") -> dict:
    """Where a run lost what it lost, in the order it lost it.

    Reading a full PipelineResult to find out why a report came out thin
    means holding several counts in your head at once - documents collected
    vs. validated vs. analysed vs. actually used, which needs went unmet,
    which figures survived verification, which blocks the data could support.
    This assembles exactly those, in pipeline order, so the first line that
    looks wrong is the stage to open.
    """
    synthesis = result.synthesis
    analyses = result.document_analyses or []
    dropped = [
        {
            "doc_id": analysis.doc_id,
            "reason": ("관련 없음" if analysis.relevant_to_question is False
                       else f"근거 검증 status={analysis.analysis_validation_status}"),
        }
        for analysis in analyses
        if analysis.relevant_to_question is False or analysis.analysis_validation_status == "failed"
    ]
    failed_stages = [
        {"stage": trace.stage, "status": trace.status.value, "reason": trace.reason}
        for trace in result.trace
        if trace.status.value not in {"ok", "skipped"}
    ]
    metrics = list(getattr(synthesis, "metric_series", []) or [])
    comparisons = list(getattr(synthesis, "comparison_points", []) or [])
    delivery = getattr(result, "block_delivery_trace", None)
    return {
        "중단된 단계": result.halted_at_stage,
        "문제 있는 단계": failed_stages or "없음",
        "수집": {
            "수집 문서": len(result.collected_source_documents or []),
            "분석 완료": len(analyses),
            "분석에서 제외": dropped or "없음",
            "수집 이벤트": len(result.collection_events or []),
        },
        "정보 요구": {
            "요청": (result.source_plan.information_needs if result.source_plan else []),
            "충족": sorted({
                need for analysis in analyses for need in (analysis.covered_information_needs or [])
            }),
        },
        "구조화 결과": {
            "metric_points": len(metrics),
            "그중 전망": sum(1 for point in metrics if getattr(point, "is_forecast", False)),
            "주체(subject) 있는 수치": sum(1 for point in metrics if getattr(point, "subject", None)),
            "comparison_points": len(comparisons),
            "등급이 매겨진 비교": sum(1 for point in comparisons if point.level),
            "grounded_claims": len(getattr(synthesis, "grounded_claims", []) or []),
            "인과 연결된 claim": sum(
                1 for claim in (getattr(synthesis, "grounded_claims", []) or [])
                if getattr(claim, "parent_synthesis_claim_id", None)
            ),
            "교차검증됨 / 단일출처": (
                f"{len(getattr(synthesis, 'corroborated_points', []) or [])} / "
                f"{len(getattr(synthesis, 'uncorroborated_points', []) or [])}"
            ),
        },
        "그릴 수 있는 블록": _drawable_blocks(synthesis),
        "블록 전달 추적": (
            {
                "계획 출처": delivery.plan_source,
                "단계별 보존": [stage.model_dump(mode="json") for stage in delivery.stages],
                "슬롯": [
                    {
                        "slot_id": slot.slot_id,
                        "수집 목표": slot.target_block_types,
                        "최종 블록": slot.selected_block_types,
                        "필수 폴백": slot.last_resort,
                        "후보 판정": {
                            candidate.block_type: candidate.decision_reason
                            for candidate in slot.candidates
                        },
                    }
                    for slot in delivery.slots
                ],
            }
            if delivery else "없음"
        ),
        "리포트": {
            "섹션": [section.section_id for section in result.generated_report.sections]
            if result.generated_report else [],
            "생략된 섹션": (result.report_plan.omitted_sections if result.report_plan else []),
            "한계 고지": (result.generated_report.limitations if result.generated_report else []),
        },
    }


def _drawable_blocks(synthesis) -> list[str]:
    """Which block shapes this evidence could support - the answer to "why is
    it all text?" without having to guess at thresholds."""
    if synthesis is None:
        return []
    from common import block_shapes

    metrics = synthesis.metric_series
    comparisons = synthesis.comparison_points
    claims = getattr(synthesis, "grounded_claims", []) or []
    checks = {
        "chart(3시점+)": block_shapes.has_timeseries(metrics),
        "bar(전후)": bool(block_shapes.time_bar_groups(metrics)),
        "item_bar(항목비교)": bool(block_shapes.item_bar_groups(metrics)),
        "grouped_bar(3축)": block_shapes.has_grouped_bars(metrics),
        "share_split(도넛)": block_shapes.has_share_split(metrics),
        "landscape": block_shapes.has_landscape(metrics),
        "table(비교표)": block_shapes.has_comparison(comparisons),
        "status_bar(등급)": block_shapes.has_status_levels(comparisons),
        "competitor_panels": block_shapes.has_competitor_panels(comparisons, metrics),
        "radar": block_shapes.has_radar(comparisons),
        "cause_tree(인과)": block_shapes.has_cause_tree(claims),
        "driver_bars(중요도)": block_shapes.has_importance_ranking(claims),
        "recurring_terms(키워드)": block_shapes.has_recurring_terms(claims),
        "timeline": block_shapes.has_timeline(synthesis.evidence, metrics),
    }
    return [name for name, drawable in checks.items() if drawable] or ["없음 (서술형만 가능)"]


def _html(markup: str) -> None:
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)


class _TeeStream:
    """Writes to every wrapped stream - lets run_pipeline's stderr/stdout
    prints keep reaching the real console while a copy is also captured for
    display/download in the app itself."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self._streams:
            stream.flush()


def _reset() -> None:
    st.session_state.result = None
    st.session_state.submitted_question = None
    st.session_state.terminal_log = None
    st.session_state.sidebar_page = "dashboard"
    st.session_state.sidebar_download_kind = None
    st.session_state.artifact_preview = None
    for key in ("intake_question", "intake_audience", "intake_sector"):
        st.session_state.pop(key, None)


# ?run=<request_id> opens an archived run directly. A past question is then a
# link someone can send - "the answer we based this on" survives the session
# it was produced in, which is the whole point of storing full results.
_requested_run = st.query_params.get("run")
if _requested_run and getattr(st.session_state.result, "request_id", None) != _requested_run:
    _reopened = load_result(_requested_run)
    if _reopened is not None:
        st.session_state.result = _reopened
        st.session_state.submitted_question = _archived_question(_reopened)

result = st.session_state.result

if result is None:
    _html(
        "<style>[data-testid='stSidebar'],[data-testid='collapsedControl']{display:none}"
        ".block-container{max-width:1120px}"
        "[data-testid='stAppViewContainer']{background:#ffffff!important;}"
        "[class*='st-key-landing_toggle_']{opacity:.45;transform:scale(.8);transform-origin:top right;}"
        "</style>"
    )
    theme_col, accent_col, dark_col = st.columns([0.88, 0.06, 0.06], vertical_alignment="center")
    with accent_col, st.container(key="landing_toggle_accent"):
        is_burgundy = st.toggle(
            "버건디", value=(st.session_state.accent_theme == "burgundy"), label_visibility="collapsed"
        )
        st.session_state.accent_theme = "burgundy" if is_burgundy else "orange"
    with dark_col, st.container(key="landing_toggle_dark"):
        st.session_state.dark_mode = st.toggle("다크", value=st.session_state.dark_mode, label_visibility="collapsed")
else:
    render_sidebar(
        result,
        st.session_state.get("submitted_question") or _archived_question(result),
        _reset,
    )

_html(dashboard_css(st.session_state.dark_mode, st.session_state.accent_theme))
# Streamlit Cloud redeploys on push, so this answers "is my fix live yet?"
# without leaving the page. Rendered once, outside the result branches, so it
# shows on the landing screen too.
_html(build_stamp_html())

if result is not None and st.session_state.get("sidebar_page") == "settings":
    render_settings_placeholder()
    st.stop()

if result is not None and st.session_state.get("sidebar_page") == "artifact_preview":
    if render_artifact_preview(result):
        st.stop()

if result is None:
    _html(
        '<section class="ts-landing">' + wordmark_html(large=True) +
        '<h1 class="ts-question-title">What Trend should we Spark?</h1></section>'
    )
    with st.form("intake_form"):
        # Explicit `key=` binds each widget to st.session_state so its value
        # survives a rerun triggered by something outside the form (e.g. the
        # dark-mode/accent toggles above) instead of only living in transient
        # frontend state until the form is submitted.
        question = st.text_area(
            "질문",
            placeholder="분석이 필요한 시장·기술·사업 이슈를 질문해 주세요.",
            height=180,
            label_visibility="collapsed",
            key="intake_question",
        )
        audience_ids = list_audience_ids()
        sector_profiles = scan_sectors(SECTORS_DIR)

        with st.container(key="intake_meta_row"):
            meta_row = st.columns([0.10, 0.16, 0.16, 0.58], vertical_alignment="center")
            with meta_row[0]:
                with st.popover("첨부", use_container_width=True):
                    uploaded_files = st.file_uploader(
                        "파일첨부",
                        accept_multiple_files=True,
                        label_visibility="collapsed",
                        help="PDF, DOCX, TXT, MD, CSV, JSON, HTML 파일을 질문과 함께 근거로 사용합니다.",
                        key="intake_attachments",
                    )
            with meta_row[1]:
                selected_audience = st.selectbox(
                    "청중",
                    options=audience_ids,
                    index=None,
                    placeholder="청중",
                    format_func=lambda audience_id: AUDIENCE_LABELS.get(audience_id, audience_id),
                    label_visibility="collapsed",
                    key="intake_audience",
                )
            with meta_row[2]:
                selected_sector = st.selectbox(
                    "계열사",
                    options=sorted(sector_profiles.keys()),
                    index=None,
                    placeholder="계열사",
                    format_func=lambda sector_id: _sector_english_label(sector_id, sector_profiles[sector_id].display_name),
                    label_visibility="collapsed",
                    key="intake_sector",
                )

        _, submit_col = st.columns([0.78, 0.22])
        with submit_col:
            submitted = st.form_submit_button("Start!", use_container_width=True)

    # Open a run that was executed elsewhere (main.py --save-result). The
    # archive under storage/requests/ keeps only a summary of each run, which
    # is enough to answer "what happened across many runs" but not enough to
    # redraw one - so a full PipelineResult JSON is what this takes. It means
    # a live run can be executed once, on the command line where its stderr
    # is readable, and still be reviewed here in its finished form.
    with st.expander("저장된 실행 결과 열기"):
        uploaded_result = st.file_uploader(
            "PipelineResult JSON", type="json", key="result_upload",
            label_visibility="collapsed",
        )
        if uploaded_result is not None:
            try:
                # A saved result is replayed, not re-synthesised, so a run
                # archived under an older rule keeps that rule's losses. This
                # re-applies today's grounding rule to points the run already
                # verified and stored; it derives nothing new.
                loaded = repair_dropped_comparison_points(
                    PipelineResult.model_validate_json(uploaded_result.getvalue())
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"이 파일은 실행 결과로 읽히지 않습니다: {exc}")
            else:
                st.session_state.result = loaded
                st.session_state.submitted_question = _archived_question(loaded)
                st.rerun()

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
            log_buffer = io.StringIO()
            tee_out = _TeeStream(sys.stdout, log_buffer)
            tee_err = _TeeStream(sys.stderr, log_buffer)
            progress_events: list = []
            run_outcome: dict = {}

            def _run_pipeline_in_background() -> None:
                try:
                    with redirect_stdout(tee_out), redirect_stderr(tee_err):
                        run_outcome["result"] = run_pipeline(
                            request,
                            dry_run=False,
                            requested_sector_id=selected_sector,
                            progress_sink=progress_events,
                        )
                except Exception as exc:  # noqa: BLE001
                    run_outcome["error"] = exc

            worker = threading.Thread(target=_run_pipeline_in_background, daemon=True)
            worker.start()

            with st.status("관련 근거를 수집하고 의사결정 흐름을 구성하고 있습니다...", expanded=True) as status:
                shown = 0
                while worker.is_alive():
                    pending = progress_events[shown:]
                    for event in pending:
                        icon, label, _ = _STATUS_LABELS.get(event.status, ("·", event.status, ""))
                        detail = f" · {event.document_count}건" if event.status == "completed" else ""
                        status.update(
                            label=f"[{event.source_index}/{event.source_total}] {event.source_name} — {label}{detail}"
                        )
                        st.write(f"{icon} [{event.source_index}/{event.source_total}] {event.source_name} — {label}{detail}")
                    shown = len(progress_events)
                    time.sleep(0.4)
                worker.join()
                if run_outcome.get("error") is not None:
                    status.update(label="오류가 발생했습니다.", state="error", expanded=True)
                else:
                    status.update(label="수집·분석이 끝났습니다.", state="complete", expanded=False)

            if run_outcome.get("error") is not None:
                st.session_state.terminal_log = log_buffer.getvalue()
                raise run_outcome["error"]

            st.session_state.result = run_outcome["result"]
            st.session_state.terminal_log = log_buffer.getvalue()
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
elif result.synthesis is not None:
    # Gated on the synthesis the view actually reads. It used to be gated on
    # `result.layout.blocks`, which this view never touches (layout.blocks is
    # debug-only) - so a run with real evidence could still fall through to
    # "표시할 결과 블록이 없습니다" purely because layout generation came back empty.
    render_generic_dashboard(result, question, sector, audience, purpose, purpose_id)
else:
    st.info("표시할 결과 블록이 없습니다.")

with st.expander("실행 기록 및 원본 계약"):
    render_execution_record(result.collection_events, result.trace)
    st.markdown("#### 진단 요약")
    st.caption(
        "파이프라인 순서대로: 어디서 멈췄는지 → 문서가 몇 건 걸러졌고 왜인지 → "
        "구조화가 얼마나 됐는지 → 그 결과 어떤 블록을 그릴 수 있는지. "
        "위에서부터 읽어 처음 이상한 줄이 열어볼 단계입니다."
    )
    st.json(_diagnostics(result), expanded=False)
    terminal_log = st.session_state.get("terminal_log")
    if terminal_log:
        st.markdown("#### 터미널 실행 로그")
        st.caption("수집·분석 단계에서 콘솔에 출력된 원본 로그입니다 (제외된 문서, AI 보정 실패 등 상세 사유 포함).")
        st.code(terminal_log, language=None)
        st.download_button(
            "로그 다운로드 (.txt)",
            terminal_log,
            file_name=f"{result.request_id}_terminal_log.txt",
            mime="text/plain",
        )
    st.markdown("#### 원본 계약")
    st.json({
        "trace": [trace.model_dump(mode="json") for trace in result.trace],
        "attachments": [item.model_dump(mode="json") for item in result.attachment_extractions],
        "layout": (
            _without_internal_provenance(result.layout.model_dump(mode="json"))
            if result.layout
            else None
        ),
        "block_delivery_trace": (
            result.block_delivery_trace.model_dump(mode="json")
            if result.block_delivery_trace else None
        ),
    })
