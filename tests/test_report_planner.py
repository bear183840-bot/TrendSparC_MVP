from common.contracts import TrendSynthesis
from core.report_planner.planner import plan_report


def _synthesis() -> TrendSynthesis:
    return TrendSynthesis(request_id="req_test_report_planner", sector_id="sk_hynix")


def test_plan_report_carries_primary_intent_through():
    plan = plan_report(_synthesis(), "practitioner", "future_business")

    assert plan.primary_intent == "future_business"


def test_plan_report_loads_existing_report_structure_template():
    # future_business.md is a real (template-only) file under prompts/report_structures/.
    plan = plan_report(_synthesis(), "practitioner", "future_business")

    assert plan.intent_emphasis is not None
    assert "future_business" in plan.intent_emphasis


def test_plan_report_returns_none_emphasis_for_unrecognized_intent():
    plan = plan_report(_synthesis(), "practitioner", "some_made_up_intent")

    assert plan.intent_emphasis is None
