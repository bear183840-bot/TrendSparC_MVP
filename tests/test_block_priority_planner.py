"""block_priority_planner reads purpose_slots' fixed skeleton before any
collection happens, and restates it as a search/extraction target - never a
second, independently-authored priority table (see the module docstring in
core/block_priority_planner/planner.py for why not)."""

from __future__ import annotations

from common.purpose_slots import PURPOSE_SLOTS
from core.block_priority_planner.planner import (
    _REQUIRED_DATA_HINTS,
    plan_block_priorities,
    target_block_shapes,
)


def test_every_purpose_produces_a_slot_target_per_slot():
    for purpose_id, slots in PURPOSE_SLOTS.items():
        plan = plan_block_priorities("req1", purpose_id)
        assert plan.purpose_id == purpose_id
        assert [target.slot_id for target in plan.slots] == [slot.slot_id for slot in slots]


def test_priority_block_types_are_copied_verbatim_from_the_slot():
    plan = plan_block_priorities("req1", "current_status")
    by_id = {slot.slot_id: slot for slot in PURPOSE_SLOTS["current_status"]}
    for target in plan.slots:
        assert target.priority_block_types == list(by_id[target.slot_id].candidates)


def test_a_slot_is_targeted_when_a_query_could_plausibly_find_its_shape():
    """`optional` is a rendering flag - "hide this card when the data isn't
    there" - and reading it as "don't look for the data" excluded exactly the
    slots that answer list-shaped questions."""
    plan = plan_block_priorities("req1", "current_status")
    targeted = {target.slot_id for target in plan.slots if target.included}

    assert {"ranking", "factors"} <= targeted
    # Prose and recommendations aren't document shapes a query can ask for;
    # spending one of three follow-up queries on them displaces a shape that
    # genuinely depends on finding the right document.
    assert "summary" not in targeted
    assert "response" not in targeted


def test_a_slot_whose_own_first_choice_is_prose_is_not_a_search_target():
    """원인분석's 개선 slot leads with action_list; reaching past it down the
    candidate list would target it at a comparison table instead."""
    plan = plan_block_priorities("req1", "root_cause")
    targeted = {target.slot_id for target in plan.slots if target.included}

    assert "improvement" not in targeted


def test_the_same_shape_is_never_targeted_twice():
    """문제대응's 문제 and 선택지 both lead with `matrix`. Searching for SWOT
    material once is right - the skeleton put a SWOT-shaped slot there because
    the question type calls for one - but twice spends two of the harness's
    three follow-up queries on one thing."""
    plan = plan_block_priorities("req1", "issue_response")
    swot_hint = _REQUIRED_DATA_HINTS["matrix"]
    shapes = target_block_shapes(plan)

    assert sum(1 for shape in shapes if swot_hint in shape) == 1


def test_a_slot_is_targeted_at_its_second_choice_too_not_only_its_first():
    """현황파악's 순위 slot leads with `share_split`, which needs a source that
    framed its figures as parts of one whole. Searching only for that misses
    `item_bar`, which answers the same slot and is far more findable."""
    plan = plan_block_priorities("req1", "current_status")
    ranking = next(target for target in plan.slots if target.slot_id == "ranking")

    assert _REQUIRED_DATA_HINTS["share_split"] in ranking.required_data_hint
    assert _REQUIRED_DATA_HINTS["grouped_bar"] in ranking.required_data_hint


def test_targets_stay_within_the_harness_query_budget():
    """The harness proposes at most three follow-up queries per round, so a
    longer list doesn't buy more searching - the tail just goes unreachable
    while looking like it was requested."""
    for purpose_id in PURPOSE_SLOTS:
        plan = plan_block_priorities("req1", purpose_id)
        assert len(target_block_shapes(plan)) <= 5, purpose_id


def test_required_data_hint_covers_every_candidate_block_type_in_every_purpose():
    """A missing entry would silently produce an empty hint string, which
    then becomes a useless search/extraction target - this is the guard
    against that, not a narrow "did I remember this one" check."""
    all_types = {
        block_type
        for slots in PURPOSE_SLOTS.values()
        for slot in slots
        for block_type in slot.candidates
    }
    missing = all_types - set(_REQUIRED_DATA_HINTS)
    assert missing == set()
    assert all(hint.strip() for hint in _REQUIRED_DATA_HINTS.values())


def test_unknown_purpose_falls_back_to_current_status_default():
    plan = plan_block_priorities("req1", "not_a_real_purpose")
    assert [target.slot_id for target in plan.slots] == [
        slot.slot_id for slot in PURPOSE_SLOTS["current_status"]
    ]


def test_target_block_shapes_flattens_only_included_slots_with_a_hint():
    plan = plan_block_priorities("req1", "current_status")
    shapes = target_block_shapes(plan)
    included_slot_ids = {target.slot_id for target in plan.slots if target.included}
    assert len(shapes) == len(included_slot_ids)
    for target in plan.slots:
        if target.included:
            assert any(target.title in shape for shape in shapes)


def test_target_block_shapes_handles_none_plan():
    assert target_block_shapes(None) == []
