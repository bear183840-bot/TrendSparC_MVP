from common.contracts import DocumentAnalysis, GroundedClaim


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
        relevance_level="direct",
        relevance_reason="질문에 직접 답함",
        grounded_claims=[
            GroundedClaim(
                claim_id="c1",
                claim_type="key_point",
                claim="근거가 있는 주장",
                evidence_quote="원문 인용",
                source_url="https://example.com/a",
                confidence="high",
            )
        ],
        covered_information_needs=["현황"],
        missing_information_needs=["전망"],
    )

    assert analysis.risk == "위험"
    assert analysis.opportunity == "기회"
    assert analysis.recommended_actions == ["Review: 내부 검토"]
    assert analysis.grounded_claims[0].confidence == "high"
    assert analysis.missing_information_needs == ["전망"]
