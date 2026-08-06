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


def test_report_purpose_changes_actual_section_structure():
    """Purpose owns the report's shape - two purposes must not produce the
    same section list. This used to be impossible: every audience carried a
    fixed report_structure that overrode the purpose entirely."""
    synthesis = _synthesis()
    future_plan = plan_report(synthesis, "executive", _purpose("future_business"))
    issue_plan = plan_report(synthesis, "executive", _purpose("issue_response"))

    future = adapt_for_audience(synthesis, future_plan, "executive")
    issue = adapt_for_audience(synthesis, issue_plan, "executive")

    assert set(future.adapted_sections) != set(issue.adapted_sections)
    assert "opportunity" in future_plan.sections and "investment_signal" in future_plan.sections
    assert "issue" in issue_plan.sections and "response_actions" in issue_plan.sections
    assert future.adapted_sections["overview"]["purpose_id"] == "future_business"
    assert issue.adapted_sections["overview"]["purpose_id"] == "issue_response"


def test_every_audience_gets_the_same_structure_for_the_same_purpose():
    """The audience decides tone and depth, never the section list - so the
    same question asked for four different readers is the same report,
    written four different ways."""
    synthesis = _synthesis()
    purpose = _purpose("current_status")

    sections_by_audience = {
        audience: tuple(plan_report(synthesis, audience, purpose).sections)
        for audience in ("practitioner", "executive", "management", "external")
    }

    assert len(set(sections_by_audience.values())) == 1
    # ...and that shared structure is the purpose's own, not a persona's.
    shared = list(next(iter(sections_by_audience.values())))
    assert shared[0] == "overview"
    assert "current_situation" in shared and "near_term_outlook" in shared


def test_no_persona_shape_leaks_into_the_purpose_sections():
    synthesis = _synthesis()
    # None of these section ids belong to current_status; each is the
    # signature of a persona's old fixed structure, so their absence proves
    # no persona shape is being applied any more.
    purpose = _purpose("current_status")

    for audience in ("_default", "executive", "practitioner", "management"):
        plan = plan_report(synthesis, audience, purpose)

        assert "decision_required" not in plan.sections  # executive's old shape
        assert "response_actions" not in plan.sections  # practitioner's old shape
        assert "strategic_recommendation" not in plan.sections  # management's old shape
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
