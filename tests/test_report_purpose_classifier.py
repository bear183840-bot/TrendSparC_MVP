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
    assert result.confidence == "medium"


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
    assert "explicit" in result.reason
