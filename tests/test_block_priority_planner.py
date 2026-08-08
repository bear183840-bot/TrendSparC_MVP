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


def test_optional_slots_are_excluded_non_optional_slots_are_included():
    plan = plan_block_priorities("req1", "current_status")
    by_id = {slot.slot_id: slot for slot in PURPOSE_SLOTS["current_status"]}
    for target in plan.slots:
        assert target.included == (not by_id[target.slot_id].optional)


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
