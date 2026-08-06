from common.contracts import (
    ComparisonPoint,
    MetricPoint,
    SynthesisClaim,
    SynthesisConclusion,
    TrendSynthesis,
)
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


def test_plan_report_uses_actual_evidence_shape_and_routes_internal_ids():
    claim = SynthesisClaim(
        synthesis_claim_id="doc1:risk1",
        claim_id="risk1",
        claim_type="risk",
        claim="해지율 상승 위험",
        evidence_quote="해지율이 상승했다",
        confidence="high",
        doc_id="doc1",
        source_id="source1",
    )
    synthesis = TrendSynthesis(
        request_id="req_evidence_plan",
        sector_id="sk_broadband",
        grounded_claims=[claim],
        conclusions=[
            SynthesisConclusion(
                conclusion_id="ai-conclusion-1",
                conclusion="해지 방어가 필요하다",
                supporting_claim_ids=[claim.synthesis_claim_id],
                confidence="high",
            )
        ],
        metric_series=[
            MetricPoint(
                metric_id="doc1:metric:1",
                label="해지율",
                period="2026년 1분기",
                value=3.2,
                unit="%",
            )
        ],
        comparison_points=[
            ComparisonPoint(
                comparison_id="doc1:comparison:1",
                entity="A사",
                criterion="해지율",
                value="3.2%",
            )
        ],
    )

    plan = plan_report(synthesis, "management", "current_status")

    assert "market_status" in plan.sections
    assert "key_metrics" in plan.sections
    market_refs = plan.section_evidence_map["market_status"]
    assert market_refs.metric_ids == ["doc1:metric:1"]
    assert market_refs.comparison_ids == ["doc1:comparison:1"]
    # current_status has no risk section of its own; the risk claim earns a
    # risk_and_opportunity section via _content_backed_sections.
    risk_refs = plan.section_evidence_map["risk_and_opportunity"]
    assert risk_refs.claim_ids == ["doc1:risk1"]
    assert risk_refs.conclusion_ids == ["ai-conclusion-1"]


def test_plan_report_does_not_add_timeline_without_real_time_series():
    synthesis = TrendSynthesis(
        request_id="req_no_timeline",
        sector_id="sk_broadband",
        metric_series=[
            MetricPoint(
                metric_id="doc1:metric:1",
                label="가입자",
                period="2026년",
                value=100,
                unit="만 명",
            )
        ],
    )

    plan = plan_report(synthesis, "external", "current_status")

    assert "timeline" not in plan.sections
