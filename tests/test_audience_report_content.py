from common.contracts import EntityExtractionResult, TrendSynthesis
from core.report_purpose.classifier import classify_report_purpose
from core.report_planner.planner import plan_report
from audience.adapter import adapt_for_audience


def _synthesis():
    return TrendSynthesis(
        request_id="req_audience_content",
        sector_id="sk_telecom",
        synthesis_text="통신 AI 경쟁이 투자 우선순위를 바꾸고 있다.",
        highlights=["근거 1", "근거 2", "근거 3", "근거 4", "근거 5"],
        source_count=6,
    )


def _purpose(purpose_id):
    entities = EntityExtractionResult(
        request_id="req_audience_content",
        primary_intent=purpose_id,
        perspective="market_landscape",
        organizations=[],
        technologies=[],
        keywords=[],
    )
    return classify_report_purpose("req_audience_content", entities)


def test_report_purpose_changes_actual_section_content():
    synthesis = _synthesis()
    future_plan = plan_report(synthesis, "executive", _purpose("future_business"))
    issue_plan = plan_report(synthesis, "executive", _purpose("issue_response"))

    future = adapt_for_audience(synthesis, future_plan, "executive")
    issue = adapt_for_audience(synthesis, issue_plan, "executive")

    assert "opportunity" in future.adapted_sections
    assert "response_actions" in issue.adapted_sections
    assert future.adapted_sections["opportunity"]["section_goal"] != issue.adapted_sections["response_actions"]["section_goal"]
    assert future.adapted_sections["opportunity"]["purpose_id"] == "future_business"
    assert issue.adapted_sections["response_actions"]["purpose_id"] == "issue_response"


def test_audience_profile_changes_visible_depth_tone_and_focus():
    synthesis = _synthesis()
    purpose = _purpose("future_business")
    executive_plan = plan_report(synthesis, "executive", purpose)
    practitioner_plan = plan_report(synthesis, "practitioner", purpose)

    executive = adapt_for_audience(synthesis, executive_plan, "executive").adapted_sections["overview"]
    practitioner = adapt_for_audience(synthesis, practitioner_plan, "practitioner").adapted_sections["overview"]

    assert len(executive["highlights"]) == 3
    assert len(practitioner["highlights"]) == 5
    assert executive["tone"] != practitioner["tone"]
    assert executive["audience_focus"] != practitioner["audience_focus"]
    assert executive["audience_guidance"] != practitioner["audience_guidance"]
