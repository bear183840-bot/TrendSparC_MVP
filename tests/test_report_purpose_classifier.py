from common.contracts import EntityExtractionResult
from core.report_purpose.classifier import classify_report_purpose


def _entities(primary_intent="current_status", keywords=None):
    return EntityExtractionResult(
        request_id="req_test_report_purpose",
        primary_intent=primary_intent,
        perspective="market_landscape",
        organizations=[],
        technologies=[],
        keywords=keywords or [],
    )


def test_classify_report_purpose_maps_existing_primary_intent():
    result = classify_report_purpose("req_test_report_purpose", _entities("future_business"))

    assert result.purpose_id == "future_business"
    assert result.display_name == "미래사업"
    assert result.confidence == "high"
    assert result.recommended_sections
    assert result.dashboard_block_hints
    assert result.prompt_path == "prompts/report_purposes/future_business.md"


def test_classify_report_purpose_infers_from_terms_when_primary_intent_unknown():
    result = classify_report_purpose(
        "req_test_report_purpose",
        _entities("unknown_intent", keywords=["리스크", "대응", "방안"]),
    )

    assert result.purpose_id == "issue_response"
    assert result.confidence == "high"


def test_classify_report_purpose_falls_back_to_current_status():
    result = classify_report_purpose("req_test_report_purpose", _entities("unknown_intent"))

    assert result.purpose_id == "current_status"
    assert result.confidence == "low"


def test_explicit_risk_response_overrides_broad_root_cause_intent():
    result = classify_report_purpose(
        "req_test_report_purpose",
        _entities("root_cause", keywords=["경쟁 현황", "주요 리스크", "대응 전략"]),
    )

    assert result.purpose_id == "issue_response"
    assert result.confidence == "high"


def test_report_purpose_scores_full_question_across_all_purpose_types():
    cases = [
        ("시장 경쟁 현황과 점유율 추이를 정리해줘", "current_status"),
        ("주요 위험과 고객 영향, 대응 조치를 제안해줘", "issue_response"),
        ("향후 성장 전망과 신사업 투자 기회를 분석해줘", "future_business"),
        ("실적 하락 원인이 무엇인지 근본 이유를 분석해줘", "root_cause"),
    ]

    for question, expected in cases:
        result = classify_report_purpose(
            "req_test_report_purpose",
            _entities("current_status"),
            question=question,
        )
        assert result.purpose_id == expected


def test_compound_status_and_prescriptive_question_gets_secondary_purpose():
    """'현황은 어떻고, 어떻게 늘릴 수 있을까?' asks for both a status readout
    AND a response plan - the single-winner purpose_id must not silently
    drop the second half of the question (problem 6)."""
    result = classify_report_purpose(
        "req_test_report_purpose",
        _entities("current_status", keywords=["가입자 수", "시장"]),
        question="Btv 가입자 수 현황은 어떻고, 어떻게 늘릴 수 있을까?",
    )

    assert result.purpose_id == "current_status"
    assert result.secondary_purpose_id == "future_business"


def test_single_purpose_question_has_no_secondary_purpose():
    result = classify_report_purpose(
        "req_test_report_purpose",
        _entities("current_status", keywords=["시장", "동향"]),
        question="시장 동향이 어떻게 되나요?",
    )

    assert result.purpose_id == "current_status"
    assert result.secondary_purpose_id is None


def test_report_planner_unions_in_secondary_purpose_sections():
    from core.report_planner.planner import plan_report
    from core.synthesis.synthesizer import synthesize

    synthesis = synthesize("req_secondary", "general", [])
    purpose = classify_report_purpose(
        "req_secondary",
        _entities("current_status", keywords=["가입자 수", "시장"]),
        question="Btv 가입자 수 현황은 어떻고, 어떻게 늘릴 수 있을까?",
    )
    assert purpose.secondary_purpose_id == "future_business"

    # "_default" (used when no audience is explicitly selected - see
    # pipeline.py's _DEFAULT_AUDIENCE_ID) is the only profile with no fixed
    # report_structure, so purpose-recommended sections drive the section
    # list directly instead of being suppressed by a fixed page shape (see
    # planner.py's report_structure branch).
    plan = plan_report(synthesis, "_default", purpose)

    assert "opportunity" in plan.sections or "strategic_recommendation" in plan.sections
