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
    "landscape": "추이용 시계열 수치와 함께, 하나의 전체에 대한 구성비(%)까지",
    "grouped_bar": "같은 라벨을 2개 이상 주체 × 2개 이상 공통 항목에 대해 측정한 수치",
    "status_bar": "근거가 등급(High/Medium/Low)을 매긴 항목 2개 이상",
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


# Shapes a search round can actually go looking for. The rest are real
# blocks, just not *search targets*: narrative prose and recommended actions
# come out of whatever documents arrive, `recurring_terms` is measured across
# whatever was collected, and a single KPI needs no shape a query could ask
# for. Spending one of the harness's three follow-up queries on "서술형 근거
# 문장" would displace a query for a shape that genuinely depends on finding
# the right document.
_SEARCHABLE_BLOCK_TYPES = frozenset({
    "chart", "landscape", "bar", "item_bar", "grouped_bar", "share_split",
    "metric_comparison", "kpi_grid", "timeline", "table", "radar", "matrix",
    "cause_tree", "driver_bars", "factor_list",
    # `status_bar` is deliberately absent: a grade is something an analyzer
    # assigns while reading, not a document shape a query can go and find.
})

# How many block-shape targets one plan may carry. The harness proposes at
# most three follow-up queries per round, so a longer list doesn't buy more
# searching - it just makes the tail of the list silently unreachable while
# looking like it was requested.
_MAX_TARGETS = 5


def _searchable_candidates(slot) -> list[str]:
    """The slot's own candidates, in its own order, minus the ones no query
    can target. Two are taken rather than one: a slot's first choice is its
    most demanding shape (현황파악's 순위 slot leads with `share_split`, which
    needs a source that framed its figures as parts of one whole), and
    searching only for that misses the far more findable second choice
    (`item_bar`) that answers the same slot."""
    searchable: list[str] = []
    for block_type in slot.candidates:
        # Stop at the first candidate no query can target, rather than
        # skipping past it. A slot whose own first choice is prose or a list
        # of recommendations is not asking for a document of a particular
        # shape; reaching further down its list would target 원인분석's
        # 개선 slot at a comparison table, which is not what that slot is for.
        if block_type not in _SEARCHABLE_BLOCK_TYPES:
            break
        searchable.append(block_type)
    return searchable[:2]


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
    targets: list[SlotTarget] = []
    claimed_shapes: set[str] = set()
    included_count = 0
    for slot in slots:
        searchable = _searchable_candidates(slot)
        # Never target the same shape twice. 문제대응's 문제 and 선택지 slots
        # both lead with `matrix`, so the plan used to spend two of three
        # follow-up queries hunting the same SWOT material. Once is right -
        # the purpose skeleton put a SWOT-shaped slot there because the
        # question type calls for one - but the second is pure waste.
        fresh = [block_type for block_type in searchable if block_type not in claimed_shapes]
        # `optional` is a *rendering* flag ("hide this card when the data
        # isn't there"), not a statement that the data isn't worth looking
        # for. Reading it as the latter excluded exactly the slots added for
        # list-shaped questions - 순위, 요인, 반복 언급 - so a question about
        # a ranking never searched for one. Inclusion is decided here by
        # whether a query could plausibly find the shape, and by the budget.
        included = bool(fresh) and included_count < _MAX_TARGETS
        if included:
            claimed_shapes.update(fresh)
            included_count += 1
        targets.append(
            SlotTarget(
                slot_id=slot.slot_id,
                title=slot.title,
                priority_block_types=list(slot.candidates),
                required_data_hint=" / ".join(_hint_for(b) for b in fresh) if included else "",
                included=included,
            )
        )
    return BlockPriorityPlan(request_id=request_id, purpose_id=purpose_id, slots=targets)


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
