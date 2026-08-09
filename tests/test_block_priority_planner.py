"""Planner exposes reader flow without controlling collection."""

from __future__ import annotations

from common.purpose_slots import PURPOSE_SLOTS, slots_for
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


def test_included_describes_required_reader_flow_not_search_targets():
    plan = plan_block_priorities("req1", "current_status")
    targeted = {target.slot_id for target in plan.slots if target.included}

    assert "summary" in targeted
    assert "ranking" not in targeted
    assert "factors" not in targeted


def test_non_optional_action_slot_remains_in_reader_flow():
    plan = plan_block_priorities("req1", "root_cause")
    targeted = {target.slot_id for target in plan.slots if target.included}

    assert "improvement" in targeted


def test_planner_never_exports_block_shapes_to_collection():
    assert target_block_shapes(plan_block_priorities("req1", "issue_response")) == []


def test_a_slot_documents_all_candidate_contracts_not_only_its_first():
    plan = plan_block_priorities("req1", "current_status")
    ranking = next(target for target in plan.slots if target.slot_id == "ranking")

    assert _REQUIRED_DATA_HINTS["share_split"] in ranking.required_data_hint
    assert _REQUIRED_DATA_HINTS["grouped_bar"] in ranking.required_data_hint


def test_no_purpose_exports_collection_targets():
    for purpose_id in PURPOSE_SLOTS:
        plan = plan_block_priorities("req1", purpose_id)
        assert len(target_block_shapes(plan)) <= 5, purpose_id


def test_required_data_hint_covers_every_candidate_block_type_in_every_purpose():
    """Every renderer candidate keeps an auditable evidence contract."""
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


def test_required_candidate_contracts_stay_diagnostic_only():
    plan = plan_block_priorities("req1", "current_status")
    assert any(target.required_data_hint for target in plan.slots)
    assert target_block_shapes(plan) == []


def test_recommendation_is_required_and_execution_is_optional():
    plan = plan_block_priorities("req1", "current_status", "recommend")
    included = {slot.slot_id for slot in plan.slots if slot.included}
    assert "recommendation" in included
    assert "execution" not in included


def test_target_block_shapes_handles_none_plan():
    assert target_block_shapes(None) == []


def test_answer_type_plan_carries_narrative_metadata_for_reader_flow():
    plan = plan_block_priorities("req_recommend", "current_status", "recommend")

    assert [slot.slot_id for slot in plan.slots][:3] == ["target", "candidates", "comparison"]
    assert all(slot.question_answered and slot.why_here and slot.role for slot in plan.slots)


def test_every_question_first_candidate_has_a_data_contract_and_exports_no_targets():
    variants = (
        ("current_status", "status"),
        ("current_status", "compare"),
        ("current_status", "trend"),
        ("current_status", "recommend"),
        ("root_cause", "cause"),
        ("issue_response", "issue_response"),
        ("future_business", "strategy"),
    )
    for purpose_id, answer_type in variants:
        candidates = {
            block_type
            for slot in slots_for(purpose_id, answer_type)
            for block_type in slot.candidates
        }
        assert candidates <= set(_REQUIRED_DATA_HINTS)
        assert len(target_block_shapes(
            plan_block_priorities("req", purpose_id, answer_type)
        )) <= 5
