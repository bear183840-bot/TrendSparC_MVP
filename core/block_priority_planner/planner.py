"""Restate the configured purpose/answer narrative for diagnostics.

Collection must not consult this plan. The question's answer/evidence
requirements drive source search; `resolve_slots()` later chooses only blocks
whose evidence contracts pass. This module keeps one inspectable view of the
reader flow and candidate order without owning either decision.
"""

from __future__ import annotations

from common.contracts import BlockPriorityPlan, SlotTarget
from common.purpose_slots import (
    DEFAULT_PURPOSE_SLOTS,
    PURPOSE_SLOTS,
    narrative_configuration_issues,
    slots_for,
)

# Plain-language restatement of each block_type's block_shapes predicate -
# never a new judgement, just what common/block_shapes.py already requires,
# exposed for audit and UI diagnostics. Every block_type that
# appears in any Slot.candidates across common/purpose_slots.py must have an
# entry here (see tests/test_block_priority_planner.py).
_REQUIRED_DATA_HINTS: dict[str, str] = {
    "chart": "같은 semantic metric·비교 가능한 단위로 실제 시점 3개 이상의 수치 (비연속 시점 허용, actual/estimate/forecast/target 구분)",
    "landscape": "핵심 시장 추이/스냅샷 1개와 구성비·현재 KPI·주요 주체 비교 중 보완 구조 1개",
    "grouped_bar": "같은 semantic metric·단위로 2개 이상 주체 × 2개 이상 공통 항목에 대해 측정한 수치",
    "status_bar": "근거가 등급(High/Medium/Low)을 매긴 항목 2개 이상",
    "bar": "같은 semantic metric·단위의 정확히 두 시점 또는 명시적 current/target·before/after 상태",
    "item_bar": "같은 semantic metric·시점/맥락을 2개 이상 주체(기업·연령대 등)에 대해 측정한 수치",
    "ranking_list": "같은 라벨을 4개 이상 항목에 대해 측정한 수치 (긴 순위 목록)",
    "share_split": "하나의 전체(share_of)에 대한 비중(%) 2개 이상, 합계 100 이하",
    "composition_breakdown": "하나의 전체(share_of)에 대한 비중(%) 4개 이상 (상세 구성)",
    "metric_comparison": "같은 시점·맥락을 설명하는 서로 다른 핵심 수치 2개 이상(단위가 다르면 공통 막대축 금지, 개별 단위 유지)",
    "kpi_grid": "확인된 수치(metric) 2개 이상",
    "kpi_single": "확인된 수치(metric) 1개 이상",
    "timeline": "날짜가 명시된 근거 문장 또는 시점이 있는 수치",
    "table": "공통 평가축(criterion)을 공유하는 기업·브랜드 2개 이상",
    "segment_table": "같은 기준으로 비교된 연령대·성별 등 이용자 집단 2개 이상",
    "level_matrix": "2개 이상 기업·브랜드를 2개 이상 공통 기준으로 high/medium/low 등급 평가",
    "competitor_panels": "경쟁사별로 등급·수치·구성비 중 2가지 이상이 확인되는 자료",
    "benchmark_table": "기업·국가·기술 2개 이상을 공통 정량/정성 기준 2개 이상으로 비교한 자료",
    "radar": "등급(level)이 매겨진 공통 기준 3개 이상, 엔티티 2개 이상",
    "matrix": "근거가 있는 SWOT 항목 또는 후보 2개 이상에 대해 실제 수치/명시 level이 존재하는 공통 판단축 2개",
    "cause_tree": "원문이 명시한 원인-결과를 별도 claim과 parent_claim_id로 연결한 구조(동시 발생만으로 연결 금지)",
    "cause_map": "위험/영향/대응 중 2개 이상 열에 근거",
    "driver_bars": "중요도 점수와 그 근거(importance + importance_basis)가 모두 있는 claim 2개 이상",
    "action_list": "권고 조치(recommended_actions)",
    "factor_list": "요인·페인포인트 항목 3개 이상",
    "recurring_terms": "서로 다른 문서 2개 이상에서 반복된 표현",
    "keyword_tags": "서로 다른 문서 2개 이상에서 반복된 표현",
    "narrative_list": "질문과 관련된 서술형 근거 문장",
}


def _hint_for(block_type: str) -> str:
    return _REQUIRED_DATA_HINTS.get(block_type, "")


def plan_block_priorities(
    request_id: str, purpose_id: str, question_answer_type: str | None = None,
) -> BlockPriorityPlan:
    """Read purpose_slots' narrative and restate each candidate contract.

    Pure lookup - no API call, no question text read. `purpose_id` is already
    resolved by the time this runs (report_purpose classified it); this stage
    never re-derives it.
    """
    slots = slots_for(purpose_id, question_answer_type)
    if question_answer_type:
        issues = narrative_configuration_issues(slots)
        if issues:
            raise ValueError("invalid narrative slot configuration: " + "; ".join(issues))
    targets: list[SlotTarget] = []
    for slot in slots:
        # included now describes the baseline reader flow, not a search
        # budget. Optional slots remain eligible later but are not required
        # to occupy dashboard space when their evidence is absent.
        included = not slot.optional
        targets.append(
            SlotTarget(
                slot_id=slot.slot_id,
                title=slot.title,
                priority_block_types=list(slot.candidates),
                # Keep the slot's two leading alternatives inspectable without
                # turning a long fallback chain into a second priority table;
                # source search and analyzer inputs never consume this field.
                required_data_hint=" / ".join(
                    f"block_type={block_type}; required_data={_hint_for(block_type)}"
                    for block_type in slot.candidates[:2]
                ),
                included=included,
                role=slot.role if slot.role in {"answer", "evidence", "analysis", "decision", "action", "support"} else "support",
                question_answered=slot.question_answered,
                why_here=slot.why_here,
            )
        )
    return BlockPriorityPlan(request_id=request_id, purpose_id=purpose_id, slots=targets)


def target_block_shapes(plan: BlockPriorityPlan | None) -> list[str]:
    """Deprecated compatibility hook.

    Runtime collection intentionally receives no block targets. Returning an
    empty list makes accidental old callers evidence-first as well.
    """
    return []
