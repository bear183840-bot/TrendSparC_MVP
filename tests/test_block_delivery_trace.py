from __future__ import annotations

import os
from pathlib import Path

import pytest

from common.contracts import DocumentAnalysis
from common.purpose_slots import PURPOSE_SLOTS, resolve_slots
from core.block_delivery_trace import build_block_delivery_trace
from core.request_pipeline.pipeline import run_pipeline_from_synthesis
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture


_FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("synthesis_*.json"))


def _run(path: Path):
    for variable in ("TRENDSPARC_REPORT_GENERATOR_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(variable, None)
    synthesis, question, audience_id, purpose = load_synthesis_fixture(path)
    result = run_pipeline_from_synthesis(question, synthesis, audience_id, purpose)
    return result, synthesis, purpose


@pytest.mark.parametrize("path", _FIXTURES, ids=lambda path: path.stem)
def test_every_synthesis_fixture_produces_a_complete_delivery_trace(path):
    result, synthesis, purpose = _run(path)
    trace = result.block_delivery_trace

    assert trace is not None
    assert trace.plan_source == "reconstructed_for_diagnostics"
    assert [slot.slot_id for slot in trace.slots] == [
        slot.slot_id for slot in PURPOSE_SLOTS[purpose.purpose_id]
    ]
    expected = {
        item.slot.slot_id: list(item.block_types) if not item.is_last_resort else []
        for item in resolve_slots(purpose.purpose_id, synthesis, result.generated_report)
    }
    assert {slot.slot_id: slot.selected_block_types for slot in trace.slots
            if slot.slot_id in expected} == expected


def test_trace_reports_only_the_shapes_actually_targeted_for_collection():
    result, _, _ = _run(Path(__file__).parent / "fixtures" / "synthesis_brand_marketing.json")
    market = next(slot for slot in result.block_delivery_trace.slots if slot.slot_id == "market_shift")

    assert market.target_block_types == ["landscape", "chart"]
    assert "narrative_list" not in market.target_block_types


def test_reusable_narrative_is_not_reported_as_stolen_by_another_slot():
    result, _, _ = _run(Path(__file__).parent / "fixtures" / "synthesis_brand_marketing.json")
    market = next(slot for slot in result.block_delivery_trace.slots if slot.slot_id == "market_shift")
    narrative = next(candidate for candidate in market.candidates
                     if candidate.block_type == "narrative_list")

    assert "다른 슬롯에서 이미 사용됨" not in narrative.decision_reason


def test_trace_is_part_of_the_pipeline_result_json_contract():
    result, _, _ = _run(Path(__file__).parent / "fixtures" / "synthesis_revenue_trend.json")
    restored = type(result).model_validate_json(result.model_dump_json())

    assert restored.block_delivery_trace is not None
    assert restored.block_delivery_trace.request_id == result.request_id


def test_trace_counts_the_analysis_to_synthesis_handoff_separately():
    result, synthesis, _ = _run(
        Path(__file__).parent / "fixtures" / "synthesis_brand_marketing.json"
    )
    result.document_analyses = [DocumentAnalysis(
        doc_id="d1",
        source_id="s1",
        metric_points=list(synthesis.metric_series[:3]),
        comparison_points=list(synthesis.comparison_points[:2]),
        factors=["요인 A", "요인 B"],
    )]
    result.block_delivery_trace = build_block_delivery_trace(result, "practitioner")
    by_stage = {stage.stage: stage for stage in result.block_delivery_trace.stages}

    assert by_stage["analysis"].metric_point_count == 3
    assert by_stage["analysis"].comparison_point_count == 2
    assert by_stage["analysis"].factor_count == 2
    assert by_stage["synthesis"].metric_point_count == len(synthesis.metric_series)
