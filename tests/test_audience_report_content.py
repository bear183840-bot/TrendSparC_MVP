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

    expected = {"overview", "key_metrics", "timeline", "decision_required", "risk", "sources"}
    assert set(future.adapted_sections) == expected
    assert set(issue.adapted_sections) == expected
    assert future.adapted_sections["overview"]["purpose_id"] == "future_business"
    assert issue.adapted_sections["overview"]["purpose_id"] == "issue_response"


def test_practitioner_management_external_each_have_their_own_fixed_structure():
    synthesis = _synthesis()
    purpose = _purpose("current_status")

    practitioner_sections = plan_report(synthesis, "practitioner", purpose).sections
    management_sections = plan_report(synthesis, "management", purpose).sections
    external_sections = plan_report(synthesis, "external", purpose).sections

    assert practitioner_sections == ["overview", "key_metrics", "timeline", "response_actions", "risk", "sources"]
    assert management_sections == ["overview", "opportunity", "risk", "strategic_recommendation", "sources"]
    assert external_sections == ["overview", "market_status", "opportunity", "sources"]
    # each audience's fixed structure differs from the others' and from executive's
    assert len({tuple(practitioner_sections), tuple(management_sections), tuple(external_sections)}) == 3


def test_no_audience_selected_falls_back_to_dynamic_purpose_sections():
    synthesis = _synthesis()
    # current_status's own recommended_sections (current_situation/market_status/
    # near_term_outlook) don't overlap with any of the 4 personas' fixed section
    # names, so this cleanly proves no fixed persona shape leaked in.
    purpose = _purpose("current_status")

    plan = plan_report(synthesis, "_default", purpose)

    assert "decision_required" not in plan.sections  # executive's fixed shape
    assert "response_actions" not in plan.sections  # practitioner's fixed shape
    assert "strategic_recommendation" not in plan.sections  # management's fixed shape
    assert plan.sections[0] == "overview"


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
