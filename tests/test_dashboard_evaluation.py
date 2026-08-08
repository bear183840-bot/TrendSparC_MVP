from __future__ import annotations

import os
from pathlib import Path

from common.purpose_slots import DESIGN_LIBRARY_BLOCKS, PURPOSE_SLOTS
from core.dashboard_evaluation import evaluate_dashboard_result, load_evaluation_manifest
from core.dashboard_evaluation.contracts import DashboardEvaluationCase, ExpectedDashboardElement
from core.request_pipeline.pipeline import run_pipeline_from_synthesis
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture


ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "evals" / "sk_broadband_mentor_questions.json"


def _run_fixture(name: str):
    for variable in ("TRENDSPARC_REPORT_GENERATOR_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(variable, None)
    synthesis, question, audience_id, purpose = load_synthesis_fixture(
        ROOT / "tests" / "fixtures" / name
    )
    return run_pipeline_from_synthesis(question, synthesis, audience_id, purpose)


def test_mentor_manifest_contains_the_nine_reference_questions_only():
    cases = load_evaluation_manifest(MANIFEST)

    assert len(cases) == 9
    assert len({case.case_id for case in cases}) == 9
    assert {case.audience_id for case in cases} == {
        "practitioner", "executive", "management", "external"
    }
    assert {case.purpose_id for case in cases} == set(PURPOSE_SLOTS)


def test_every_expected_element_names_a_real_deterministic_block_type():
    known = {block for blocks in DESIGN_LIBRARY_BLOCKS.values() for block in blocks}
    known |= {candidate for slots in PURPOSE_SLOTS.values() for slot in slots
              for candidate in slot.candidates}

    for case in load_evaluation_manifest(MANIFEST):
        for element in case.expected_elements:
            assert element.acceptable_slot_ids
            assert set(element.acceptable_slot_ids) <= {
                slot.slot_id for slot in PURPOSE_SLOTS[case.purpose_id]
            }
            assert element.acceptable_block_types
            assert set(element.acceptable_block_types) <= known


def test_evaluator_separates_automatic_checks_from_human_visual_review():
    result = _run_fixture("synthesis_revenue_trend.json")
    case = DashboardEvaluationCase(
        case_id="fixture_revenue",
        question="매출 추이는?",
        audience_id="management",
        purpose_id="current_status",
        expected_elements=[ExpectedDashboardElement(
            element_id="trend", label="추이", acceptable_slot_ids=["market"],
            acceptable_block_types=["chart"],
        )],
    )

    evaluation = evaluate_dashboard_result(result, case)
    by_id = {check.check_id: check for check in evaluation.checks}

    assert by_id["pipeline_completion"].status == "pass"
    assert by_id["expected_element:trend"].status == "pass"
    assert by_id["evidence_traceability"].status == "not_applicable"
    assert by_id["question_relevance"].status == "manual_review"
    assert by_id["expected_element_content"].status == "manual_review"
    assert by_id["visual_quality"].status == "manual_review"


def test_live_run_traceability_fails_when_structured_facts_lack_provenance():
    result = _run_fixture("synthesis_revenue_trend.json")
    result.block_delivery_trace.plan_source = "pipeline"
    result.block_delivery_trace.stages[1].document_count = 1
    case = DashboardEvaluationCase(
        case_id="fixture_revenue",
        question="매출 추이는?",
        audience_id="management",
        purpose_id="current_status",
    )

    evaluation = evaluate_dashboard_result(result, case)
    evidence = next(check for check in evaluation.checks
                    if check.check_id == "evidence_traceability")

    assert evidence.status == "fail"
    assert evidence.score < 100


def test_evaluator_rebuilds_trace_for_an_older_saved_result():
    result = _run_fixture("synthesis_revenue_trend.json")
    result.block_delivery_trace = None
    case = DashboardEvaluationCase(
        case_id="fixture_revenue",
        question="매출 추이는?",
        audience_id="management",
        purpose_id="current_status",
    )

    evaluation = evaluate_dashboard_result(result, case)

    assert evaluation.delivered_block_types
    assert next(check for check in evaluation.checks
                if check.check_id == "pipeline_completion").status == "pass"
