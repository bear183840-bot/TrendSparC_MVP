from common.contracts import DocumentAnalysis


def test_document_analysis_strategy_fields_are_optional_and_structured():
    analysis = DocumentAnalysis(
        doc_id="doc1",
        summary="요약",
        key_points=["핵심"],
        business_impact="매출 영향",
        risk="위험",
        opportunity="기회",
        recommended_actions=["Review: 내부 검토"],
        monitoring_indicators=["가입자 변화"],
        evidence=["문서 근거"],
        action_level="Review",
        analysis_confidence="medium",
        relevant_to_question=True,
    )

    assert analysis.risk == "위험"
    assert analysis.opportunity == "기회"
    assert analysis.recommended_actions == ["Review: 내부 검토"]
