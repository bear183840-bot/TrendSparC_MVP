"""Evaluate saved PipelineResults without asking an LLM to grade itself."""

from __future__ import annotations

import json
from pathlib import Path

from common.purpose_slots import DEFAULT_PURPOSE_SLOTS, PURPOSE_SLOTS
from core.block_delivery_trace import build_block_delivery_trace
from core.dashboard_evaluation.contracts import (
    DashboardEvaluationCase,
    DashboardEvaluationCheck,
    DashboardEvaluationResult,
)


def load_evaluation_manifest(path: str | Path) -> list[DashboardEvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [DashboardEvaluationCase.model_validate(item) for item in payload["cases"]]


def _check(check_id: str, label: str, status: str, detail: str, score: float | None = None):
    return DashboardEvaluationCheck(
        check_id=check_id, label=label, status=status, detail=detail, score=score,
    )


def _fact_traceability(synthesis) -> tuple[int, int]:
    """(traceable, total) for every structured fact, not one per block."""
    if synthesis is None:
        return 0, 0
    doc_urls = synthesis.doc_url_map or {}
    facts: list[bool] = []
    for point in synthesis.metric_series or []:
        claim_id = point.evidence_synthesis_claim_id or point.evidence_claim_id
        source = point.source_url or (doc_urls.get(point.doc_id) if point.doc_id else None)
        facts.append(bool(claim_id and source))
    for point in synthesis.comparison_points or []:
        claim_id = point.evidence_synthesis_claim_id or point.evidence_claim_id
        source = point.source_url or (doc_urls.get(point.doc_id) if point.doc_id else None)
        facts.append(bool(claim_id and source))
    for claim in synthesis.grounded_claims or []:
        source = claim.source_url or doc_urls.get(claim.doc_id)
        facts.append(bool(claim.synthesis_claim_id and claim.doc_id and source))
    return sum(facts), len(facts)


def evaluate_dashboard_result(result, case: DashboardEvaluationCase) -> DashboardEvaluationResult:
    """Run deterministic checks and leave genuinely visual judgements manual."""
    audience_id = (
        result.generated_report.audience_id
        if result.generated_report is not None else case.audience_id
    )
    trace = result.block_delivery_trace or build_block_delivery_trace(result, audience_id)
    delivered = list(trace.delivered_block_types) if trace else []
    checks: list[DashboardEvaluationCheck] = []

    completed = result.halted_at_stage is None and result.layout is not None and trace is not None
    checks.append(_check(
        "pipeline_completion", "파이프라인 완주",
        "pass" if completed else "fail",
        "layout과 Block Delivery Trace가 생성됨" if completed
        else f"중단 단계: {result.halted_at_stage or 'layout/trace 없음'}",
    ))

    actual_purpose = result.report_purpose.purpose_id if result.report_purpose else ""
    purpose_ok = actual_purpose == case.purpose_id
    actual_slot_ids = [slot.slot_id for slot in trace.slots] if trace else []
    expected_slot_ids = [
        slot.slot_id for slot in PURPOSE_SLOTS.get(case.purpose_id, DEFAULT_PURPOSE_SLOTS)
    ]
    checks.append(_check(
        "purpose_structure", "보고 목적과 논증 골격",
        "pass" if purpose_ok and actual_slot_ids == expected_slot_ids else "fail",
        f"purpose={actual_purpose or '없음'}, slots={actual_slot_ids}",
    ))

    checks.append(_check(
        "audience_assignment", "청중 지정",
        "pass" if audience_id == case.audience_id else "fail",
        f"expected={case.audience_id}, actual={audience_id}",
    ))

    covered_required = 0
    required_total = sum(1 for element in case.expected_elements if element.required)
    for element in case.expected_elements:
        matched = [
            f"{slot.slot_id}:{block_type}"
            for slot in (trace.slots if trace else [])
            if slot.slot_id in element.acceptable_slot_ids
            for block_type in slot.selected_block_types
            if block_type in element.acceptable_block_types
        ]
        status = "pass" if matched else ("fail" if element.required else "not_applicable")
        if element.required and matched:
            covered_required += 1
        checks.append(_check(
            f"expected_element:{element.element_id}",
            f"기대 요소 표현 구조: {element.label}",
            status,
            f"matched={matched}" if matched
            else (f"acceptable_slots={element.acceptable_slot_ids}, "
                  f"acceptable_blocks={element.acceptable_block_types}, delivered={delivered}"),
        ))
    if required_total:
        coverage = round(100 * covered_required / required_total, 1)
        checks.append(_check(
            "expected_element_coverage", "기대 요소 블록 구조 준비도",
            "pass" if covered_required == required_total else "fail",
            f"필수 요소 {covered_required}/{required_total}; 실제 내용 적합성은 별도 검토", coverage,
        ))

    has_analysis_input = any(
        stage.stage == "analysis" and stage.document_count > 0
        for stage in (trace.stages if trace else [])
    )
    if trace and not has_analysis_input:
        checks.append(_check(
            "evidence_traceability", "근거 추적률", "not_applicable",
            "분석 입력이 없는 synthesis fixture/구버전 결과는 provenance 전체를 재현하지 않음",
        ))
    elif trace:
        traceable, total = _fact_traceability(result.synthesis)
        ratio = round(100 * traceable / total, 1) if total else 100.0
        checks.append(_check(
            "evidence_traceability", "근거 추적률",
            "pass" if traceable == total else "fail",
            f"구조화 fact {total}개 중 claim ID와 문서 URL로 추적 가능 {traceable}개", ratio,
        ))

    analysis = next((stage for stage in (trace.stages if trace else []) if stage.stage == "analysis"), None)
    synthesis = next((stage for stage in (trace.stages if trace else []) if stage.stage == "synthesis"), None)
    if not analysis or analysis.metric_point_count == 0:
        checks.append(_check(
            "metric_preservation", "수치 보존률", "not_applicable",
            "분석 단계 metric이 없어 보존률을 계산하지 않음",
        ))
    else:
        ratio = round(100 * min(synthesis.metric_point_count, analysis.metric_point_count)
                      / analysis.metric_point_count, 1)
        checks.append(_check(
            "metric_preservation", "수치 보존률",
            "pass" if synthesis.metric_point_count >= analysis.metric_point_count else "fail",
            f"analysis={analysis.metric_point_count}, synthesis={synthesis.metric_point_count}", ratio,
        ))

    required_empty = [slot.slot_id for slot in (trace.slots if trace else [])
                      if not slot.optional and slot.last_resort]
    checks.append(_check(
        "empty_required_slots", "필수 빈 블록",
        "pass" if not required_empty else "fail",
        "필수 슬롯 모두 실제 블록으로 해석됨" if not required_empty
        else f"last_resort={required_empty}",
    ))

    # These need either a second audience run or rendered-browser inspection.
    # Marking them pass from JSON alone would be a fabricated quality claim.
    checks.extend([
        _check("question_relevance", "질문 적합성", "manual_review",
               "요약·블록이 질문에 직접 답하는지 사람이 확인해야 함"),
        _check("expected_element_content", "기대 요소 내용 충족", "manual_review",
               "준비된 블록 안에 기대 정보가 실제로 들어갔는지 확인해야 함"),
        _check("audience_differentiation", "청중 차별화", "manual_review",
               "동일 synthesis의 다른 청중 결과와 비교해야 함"),
        _check("visual_quality", "디자인 완성도", "manual_review",
               "브라우저에서 정보 위계·가독성·빈 공간·근거 링크를 실측해야 함"),
    ])

    counts = {status: sum(check.status == status for check in checks)
              for status in ("pass", "fail", "manual_review", "not_applicable")}
    return DashboardEvaluationResult(
        case_id=case.case_id,
        request_id=result.request_id,
        question=case.question,
        audience_id=audience_id,
        purpose_id=actual_purpose,
        delivered_block_types=delivered,
        checks=checks,
        passed_count=counts["pass"],
        failed_count=counts["fail"],
        manual_review_count=counts["manual_review"],
        not_applicable_count=counts["not_applicable"],
    )
