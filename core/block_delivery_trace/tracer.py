"""Read-only audit of the evidence-to-dashboard delivery path.

The tracer deliberately calls the same deterministic predicates and
`resolve_slots()` used by the live dashboard. It never supplies data back to
either function, so a diagnostic cannot become a second rendering planner.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from common.contracts import (
    BlockCandidateDeliveryTrace,
    BlockDeliveryStageSnapshot,
    BlockDeliveryTrace,
    SlotDeliveryTrace,
)
from common.purpose_slots import (
    DEFAULT_PURPOSE_SLOTS,
    LAST_RESORT,
    PURPOSE_SLOTS,
    block_data_supported,
    resolve_slots,
    slot_evidence_items,
)
from core.block_priority_planner.planner import (
    _REQUIRED_DATA_HINTS,
    plan_block_priorities,
)


_METRIC_BLOCKS = {
    "chart", "landscape", "bar", "item_bar", "grouped_bar", "share_split",
    "metric_comparison", "kpi_grid", "kpi_single", "timeline",
}
_COMPARISON_BLOCKS = {
    "status_bar", "table", "segment_table", "competitor_panels",
    "level_matrix", "radar",
}
_CLAIM_TYPES_BY_BLOCK = {
    "matrix": {"strength", "weakness", "risk", "opportunity"},
    "cause_map": {"risk", "business_impact", "action"},
    "cause_tree": None,
    "driver_bars": None,
    "factor_list": {"factor"},
    "recurring_terms": None,
    "action_list": {"action"},
    "narrative_list": None,
}


def _unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _stage_snapshots(result: Any) -> list[BlockDeliveryStageSnapshot]:
    documents = list(getattr(result, "collected_source_documents", None) or [])
    analyses = list(getattr(result, "document_analyses", None) or [])
    synthesis = getattr(result, "synthesis", None)
    snapshots = [
        BlockDeliveryStageSnapshot(
            stage="collection",
            document_count=len(documents),
            source_count=len({doc.source_id for doc in documents if doc.source_id}),
            content_character_count=sum(len(doc.content or "") for doc in documents),
        ),
        BlockDeliveryStageSnapshot(
            stage="analysis",
            document_count=len(analyses),
            source_count=len({item.source_id for item in analyses if item.source_id}),
            grounded_claim_count=sum(len(item.grounded_claims) for item in analyses),
            metric_point_count=sum(len(item.metric_points) for item in analyses),
            comparison_point_count=sum(len(item.comparison_points) for item in analyses),
            factor_count=sum(len(item.factors) for item in analyses),
            action_count=sum(len(item.recommended_actions) for item in analyses),
        ),
    ]
    if synthesis is not None:
        snapshots.append(BlockDeliveryStageSnapshot(
            stage="synthesis",
            document_count=synthesis.source_count,
            source_count=synthesis.unique_source_count,
            grounded_claim_count=len(synthesis.grounded_claims),
            metric_point_count=len(synthesis.metric_series),
            comparison_point_count=len(synthesis.comparison_points),
            factor_count=len(synthesis.factors),
            action_count=len(synthesis.recommended_actions),
        ))
    return snapshots


def _candidate_evidence(block_type: str, synthesis: Any) -> tuple[list[str], list[str], list[str]]:
    claims = list(synthesis.grounded_claims or [])
    points: list[Any] = []
    if block_type in _METRIC_BLOCKS:
        points.extend(synthesis.metric_series or [])
    if block_type in _COMPARISON_BLOCKS:
        points.extend(synthesis.comparison_points or [])

    allowed_types = _CLAIM_TYPES_BY_BLOCK.get(block_type, set())
    if block_type in _CLAIM_TYPES_BY_BLOCK:
        if allowed_types is not None:
            claims = [claim for claim in claims if claim.claim_type in allowed_types]
        elif block_type == "cause_tree":
            claims = [claim for claim in claims if claim.parent_synthesis_claim_id]
        elif block_type == "driver_bars":
            claims = [claim for claim in claims if claim.importance is not None and claim.importance_basis]
    else:
        claims = []

    claim_ids = _unique([
        *(getattr(point, "evidence_synthesis_claim_id", None) for point in points),
        *(getattr(point, "evidence_claim_id", None) for point in points),
        *(claim.synthesis_claim_id for claim in claims),
    ])
    doc_ids = _unique([
        *(getattr(point, "doc_id", None) for point in points),
        *(claim.doc_id for claim in claims),
    ])
    urls = _unique([
        *(getattr(point, "source_url", None) for point in points),
        *(claim.source_url for claim in claims),
        *(synthesis.doc_url_map.get(doc_id) for doc_id in doc_ids),
    ])
    return claim_ids, doc_ids, urls


def _decision_reason(
    block_type: str,
    supported: bool,
    selected: list[str],
    selected_elsewhere: dict[str, str],
) -> str:
    if block_type in selected:
        return "대표 블록으로 선택됨" if selected.index(block_type) == 0 else "보완 블록으로 선택됨"
    if not supported:
        hint = _REQUIRED_DATA_HINTS.get(block_type, "필수 데이터 계약")
        return f"데이터 계약 불충족: {hint}"
    if block_type == "narrative_list" and selected:
        return "구조화 블록이 선택되어 산문 폴백은 보완 블록에서 제외됨"
    if block_type != "narrative_list" and block_type in selected_elsewhere:
        return f"다른 슬롯에서 이미 사용됨: {selected_elsewhere[block_type]}"
    if len(selected) >= 2:
        return "슬롯당 최대 2블록에 도달함"
    return "선택된 블록과 같은 데이터를 다시 그리므로 제외됨"


def _targeted_block_types(target: Any) -> list[str]:
    """Only the fresh shapes this slot actually sent to collection.

    `priority_block_types` is the full rendering fallback chain. The planner
    embeds the narrower search targets beside their required-data contracts,
    which is what a delivery audit must report here.
    """
    if target is None or not target.included:
        return []
    return re.findall(r"block_type=([a-z_]+);", target.required_data_hint or "")


def build_block_delivery_trace(result: Any, audience_id: str | None = None) -> BlockDeliveryTrace | None:
    synthesis = getattr(result, "synthesis", None)
    purpose = getattr(result, "report_purpose", None)
    if synthesis is None or purpose is None:
        return None
    purpose_id = purpose.purpose_id
    report = getattr(result, "generated_report", None)
    resolved = resolve_slots(purpose_id, synthesis, report)
    resolved_by_id = {item.slot.slot_id: item for item in resolved}
    selected_elsewhere = {
        block_type: item.slot.slot_id
        for item in resolved
        for block_type in item.block_types
        if block_type != LAST_RESORT
    }

    plan = getattr(result, "block_priority_plan", None)
    plan_source = "pipeline"
    if plan is None:
        plan = plan_block_priorities(result.request_id, purpose_id)
        plan_source = "reconstructed_for_diagnostics"
    targets = {target.slot_id: target for target in plan.slots}

    slots = []
    for slot in PURPOSE_SLOTS.get(purpose_id, DEFAULT_PURPOSE_SLOTS):
        _, items = slot_evidence_items(slot, synthesis, report)
        resolved_slot = resolved_by_id.get(slot.slot_id)
        selected = list(resolved_slot.block_types) if resolved_slot else []
        if selected == [LAST_RESORT]:
            selected = []
        target = targets.get(slot.slot_id)
        candidates = []
        for block_type in slot.candidates:
            supported = block_data_supported(block_type, synthesis, items)
            # Unsupported candidates carry the missing contract, not a bag of
            # unrelated evidence merely because it shares the same broad
            # metric/comparison field. This keeps the trace honest and small.
            claim_ids, doc_ids, urls = (
                _candidate_evidence(block_type, synthesis)
                if supported else ([], [], [])
            )
            role = None
            if block_type in selected:
                role = "lead" if selected.index(block_type) == 0 else "companion"
            candidates.append(BlockCandidateDeliveryTrace(
                block_type=block_type,
                required_data_hint=_REQUIRED_DATA_HINTS.get(block_type, ""),
                data_supported=supported,
                selected_role=role,
                decision_reason=_decision_reason(block_type, supported, selected, selected_elsewhere),
                evidence_claim_ids=claim_ids,
                supporting_doc_ids=doc_ids,
                supporting_source_urls=urls,
            ))
        slots.append(SlotDeliveryTrace(
            slot_id=slot.slot_id,
            title=slot.title,
            intent=slot.intent,
            optional=slot.optional,
            collection_targeted=bool(target and target.included),
            target_block_types=_targeted_block_types(target),
            item_count=len(items),
            selected_block_types=selected,
            last_resort=bool(resolved_slot and resolved_slot.is_last_resort),
            candidates=candidates,
        ))

    return BlockDeliveryTrace(
        request_id=result.request_id,
        purpose_id=purpose_id,
        audience_id=audience_id,
        plan_source=plan_source,
        stages=_stage_snapshots(result),
        slots=slots,
        delivered_block_types=[
            block_type for slot in slots for block_type in slot.selected_block_types
        ],
    )
