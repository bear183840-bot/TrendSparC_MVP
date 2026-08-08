"""Decide, before any collection happens, which block shapes are worth
searching for.

This sits between report_purpose and source_planner. It answers a narrower
question than `purpose_slots.resolve_slots()` does at render time: not "what
can we draw with what we have" (resolve_slots, unchanged, still the final
arbiter) but "what would be worth having, given only the purpose we already
know". The two intentionally share one table (`common.purpose_slots.
PURPOSE_SLOTS`) rather than each keeping their own - see that module's
docstring for why a second, independently-authored priority table is exactly
the kind of drift this project has already been bitten by once.

The plan produced here is advisory, never enforced: `included=False` just
means source_planner/collector should not spend a supplementary search round
chasing that slot, not that the slot is forbidden from appearing later if the
data shows up anyway (resolve_slots doesn't consult this plan at all).
"""

from __future__ import annotations

from common.contracts import BlockPriorityPlan, SlotTarget
from common.purpose_slots import DEFAULT_PURPOSE_SLOTS, PURPOSE_SLOTS

# Plain-language restatement of each block_type's block_shapes predicate -
# never a new judgement, just what common/block_shapes.py already requires,
# said in words a search/extraction prompt can act on. Every block_type that
# appears in any Slot.candidates across common/purpose_slots.py must have an
# entry here (see tests/test_block_priority_planner.py).
_REQUIRED_DATA_HINTS: dict[str, str] = {
    "chart": "같은 라벨로 서로 다른 시점 3개 이상의 수치 (추이)",
    "bar": "같은 라벨로 서로 다른 시점 정확히 2개의 수치 (전후 비교)",
    "item_bar": "같은 라벨을 2개 이상 주체(기업·연령대 등)에 대해 측정한 수치 (항목 비교)",
    "share_split": "하나의 전체(share_of)에 대한 비중(%) 2개 이상, 합계 100 이하",
    "metric_comparison": "같은 시점·같은 단위를 공유하는 서로 다른 라벨의 수치 2개 이상",
    "kpi_grid": "확인된 수치(metric) 2개 이상",
    "kpi_single": "확인된 수치(metric) 1개 이상",
    "timeline": "날짜가 명시된 근거 문장 또는 시점이 있는 수치",
    "table": "공통 평가축(criterion)을 공유하는 엔티티 2개 이상",
    "radar": "등급(level)이 매겨진 공통 기준 3개 이상, 엔티티 2개 이상",
    "matrix": "강점/약점/기회/위험 중 2개 이상 항목에 근거",
    "cause_tree": "원인-결과로 연결된(parent_claim_id) claim",
    "cause_map": "위험/영향/대응 중 2개 이상 열에 근거",
    "driver_bars": "중요도 점수와 그 근거(importance + importance_basis)가 모두 있는 claim 2개 이상",
    "action_list": "권고 조치(recommended_actions)",
    "factor_list": "요인·페인포인트 항목 3개 이상",
    "recurring_terms": "서로 다른 문서 2개 이상에서 반복된 표현",
    "narrative_list": "질문과 관련된 서술형 근거 문장",
}


def _hint_for(block_type: str) -> str:
    return _REQUIRED_DATA_HINTS.get(block_type, "")


def plan_block_priorities(request_id: str, purpose_id: str) -> BlockPriorityPlan:
    """Read purpose_slots' fixed skeleton for `purpose_id` and restate each
    slot's top-priority block as a search/extraction target.

    Pure lookup - no API call, no question text read. `purpose_id` is already
    resolved by the time this runs (report_purpose classified it); this stage
    never re-derives it.
    """
    slots = PURPOSE_SLOTS.get(purpose_id, DEFAULT_PURPOSE_SLOTS)
    return BlockPriorityPlan(
        request_id=request_id,
        purpose_id=purpose_id,
        slots=[
            SlotTarget(
                slot_id=slot.slot_id,
                title=slot.title,
                priority_block_types=list(slot.candidates),
                required_data_hint=_hint_for(slot.candidates[0]) if slot.candidates else "",
                # v1: reuses the slot's own optional flag (data-driven) rather
                # than a new question-intent judgement - see this package's
                # module docstring and the plan this stage was built from.
                included=not slot.optional,
            )
            for slot in slots
        ],
    )


def target_block_shapes(plan: BlockPriorityPlan | None) -> list[str]:
    """Flatten an included plan into the string hints WebSearchContext and
    the analyzer consume - the one formatting rule shared by every caller
    (source_planner and the analyzer invocation in pipeline.py) so it is
    written once, not copy-pasted at each call site."""
    if plan is None:
        return []
    return [
        f"{slot.title}: {slot.required_data_hint}"
        for slot in plan.slots
        if slot.included and slot.required_data_hint
    ]
