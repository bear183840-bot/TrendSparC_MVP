from common.contracts import EvidenceRequirement, QuestionBrief, QuestionContext, SynthesisClaim, TrendSynthesis
from core.question_brief import (
    _REFINEMENT_PROMPT,
    _schema,
    build_fulfillment,
    build_rule_based_question_brief,
    classify_question_shape,
    classify_question_shapes,
    legacy_requirement_lists,
    validate_question_brief,
)


def test_rule_based_brief_keeps_question_as_the_explicit_answer():
    brief = build_rule_based_question_brief(
        "req_brief", "연령층별 광고 매체 및 모델 추천"
    )

    assert brief.refinement_mode == "rule_based"
    assert [answer.subject for answer in brief.requested_answers] == ["광고 매체", "광고 모델"]
    assert all(answer.dimensions == ["연령층"] for answer in brief.requested_answers)
    assert brief.requested_answers[0].origin == "user_explicit"
    assert {item.for_answer_id for item in brief.evidence_requirements} == {"answer_1", "answer_2"}
    assert any(item.kind == "comparison" and item.common_basis_required for item in brief.evidence_requirements)


def test_rule_based_brief_keeps_selection_criterion_separate_from_requested_answers():
    brief = build_rule_based_question_brief(
        "req_brand", "SK브로드밴드 브랜드 이미지 개선에 맞는 연령층별 광고 매체 및 모델 추천"
    )

    assert [answer.subject for answer in brief.requested_answers] == ["광고 매체", "광고 모델"]
    assert all(answer.selection_criteria == ["SK브로드밴드 브랜드 이미지 개선"] for answer in brief.requested_answers)
    assert all("브랜드 이미지 개선" not in answer.subject for answer in brief.requested_answers)


def test_question_context_does_not_duplicate_entity_extraction():
    """QuestionBrief preserves question scope; entity identity stays in the
    entity/sector contracts so an extraction error cannot become a second
    source of truth inside the brief."""
    assert "organizations" not in QuestionContext.model_fields
    assert "technologies" not in QuestionContext.model_fields


def test_validator_rejects_a_derived_requirement_without_rationale():
    draft = build_rule_based_question_brief("req_brief", "가격 비교")
    invalid = draft.model_copy(update={
        "evidence_requirements": [*draft.evidence_requirements, EvidenceRequirement(
            requirement_id="evidence_derived",
            for_answer_id="answer_1",
            kind="comparison",
            semantic_target="가격 적합성",
            comparison_dimension="제품",
            common_basis_required=True,
            derivation_type="semantic_inference",
            origin="derived",
        )]
    })

    try:
        validate_question_brief(invalid, draft)
    except ValueError as exc:
        assert "rationale" in str(exc)
    else:
        raise AssertionError("validator accepted a derived requirement without rationale")


def test_validator_accepts_an_anchored_split_of_a_compound_explicit_request():
    draft = build_rule_based_question_brief(
        "req_brief", "연령층별 광고 매체 및 모델 추천"
    )
    candidate = QuestionBrief.model_validate({
        **draft.model_dump(),
        "requested_answers": [
            {
                "answer_id": "answer_media", "question_anchor": "연령층별 광고 매체",
                "answer_type": "recommend", "subject": "광고 매체", "origin": "ai_refined",
                "rationale": "매체와 모델은 독립적으로 답할 수 있는 사용자 요청입니다.",
            },
            {
                "answer_id": "answer_model", "question_anchor": "모델 추천",
                "answer_type": "recommend", "subject": "광고 모델", "origin": "ai_refined",
                "rationale": "매체 추천과 모델 추천을 분리해 누락을 방지합니다.",
            },
        ],
        "evidence_requirements": [],
    })

    assert validate_question_brief(candidate, draft).refinement_mode == "ai_refined"


def test_validator_rejects_precollection_fulfillment():
    draft = build_rule_based_question_brief("req_brief", "시장 현황")
    invalid = QuestionBrief.model_validate({
        **draft.model_dump(),
        "fulfillment": [{
            "for_answer_id": "answer_1", "status": "fulfilled",
        }],
    })

    try:
        validate_question_brief(invalid, draft)
    except ValueError as exc:
        assert "fulfillment" in str(exc)
    else:
        raise AssertionError("validator accepted precollection fulfillment")


def test_validator_allows_barrier_as_evidence_not_a_bar_chart_instruction():
    draft = build_rule_based_question_brief(
        "req_pain", "2030 1인 가구의 유선 인터넷 가입 고려 요인 및 페인 포인트"
    )

    assert validate_question_brief(draft, draft).refinement_mode == "ai_refined"


def test_fulfillment_uses_only_existing_synthesis_contracts():
    brief = build_rule_based_question_brief("req_brief", "시장 현황")
    fulfilled = build_fulfillment(
        brief,
        TrendSynthesis(
            request_id="req_brief", sector_id="test", source_ids=["source_1"],
            doc_source_map={"doc_1": "source_1"},
        ),
    )

    assert fulfilled.fulfillment[0].status == "unmet"
    assert fulfilled.fulfillment[0].document_ids == []


def test_fulfillment_keeps_evidence_scoped_to_each_separated_answer():
    brief = build_rule_based_question_brief(
        "req_chip", "칩플레이션이 셋톱박스 업계에 미치는 영향과 IPTV사의 중장기 대응 전략"
    )
    synthesis = TrendSynthesis(
        request_id="req_chip", sector_id="test",
        grounded_claims=[
            SynthesisClaim(
                synthesis_claim_id="claim_factor", claim_id="factor", claim_type="factor",
                claim="Chip costs increase device costs.", evidence_quote="source states the link",
                confidence="high", parent_synthesis_claim_id="claim_impact", doc_id="doc_impact", source_id="source_impact",
            ),
            SynthesisClaim(
                synthesis_claim_id="claim_impact", claim_id="impact", claim_type="business_impact",
                claim="Set-top-box operations are affected.", evidence_quote="source states the impact",
                confidence="high", doc_id="doc_impact", source_id="source_impact",
            ),
            SynthesisClaim(
                synthesis_claim_id="claim_action", claim_id="action", claim_type="action",
                claim="Operator response option.", evidence_quote="source states the option",
                confidence="high", doc_id="doc_strategy", source_id="source_strategy",
            ),
        ],
    )

    fulfilled = build_fulfillment(brief, synthesis).fulfillment
    impact, strategy = fulfilled

    assert impact.status == "fulfilled"
    assert impact.claim_ids == ["claim_factor", "claim_impact"]
    assert impact.document_ids == ["doc_impact"]
    assert strategy.status == "partial"
    assert strategy.claim_ids == ["claim_impact", "claim_action"]
    assert strategy.document_ids == ["doc_impact", "doc_strategy"]


def test_legacy_lists_are_derived_from_the_brief_not_renderer_terms():
    brief = build_rule_based_question_brief("req_brief", "가격 비교")
    answers, evidence = legacy_requirement_lists(brief)

    assert answers == ["가격 비교"]
    assert all("KPI" not in value and "BAR" not in value for value in evidence)


def test_question_shape_reads_only_the_question_not_report_purpose_or_entities():
    assert classify_question_shape("연령층별 광고 매체 추천") == "recommend"
    assert classify_question_shape("지난 3년 매출 변화") == "trend"


def test_compound_trend_and_comparison_question_preserves_both_evidence_shapes():
    question = "지난 5년간 OTT 생태계의 변화 추이 (국내 vs 글로벌 비교)"
    brief = build_rule_based_question_brief("req_ott", question)

    assert classify_question_shapes(question) == ["trend", "compare"]
    assert brief.question_context.question_answer_type == "trend"
    assert brief.question_context.required_answer_shapes == ["trend", "compare"]
    assert brief.question_context.time_scope == "지난 5년"
    assert brief.question_context.geography_scope == "국내 vs 글로벌"
    assert {item.kind for item in brief.evidence_requirements} == {"trend", "comparison"}


def test_question_brief_handles_explicit_impact_and_strategy_as_separate_answers():
    question = "칩플레이션이 셋톱박스 업계에 미치는 영향과 IPTV사의 중장기 대응 전략"
    brief = build_rule_based_question_brief("req_chip", question)

    assert set(brief.question_context.required_answer_shapes) == {"impact", "strategy"}
    assert [answer.answer_type for answer in brief.requested_answers] == ["impact", "strategy"]
    assert [answer.subject for answer in brief.requested_answers] == [
        "칩플레이션이 셋톱박스 업계에 미치는 영향", "IPTV사의 중장기 대응 전략",
    ]
    assert {item.kind for item in brief.evidence_requirements if item.for_answer_id == "answer_1"} == {
        "causal_link", "outcome",
    }
    assert {item.kind for item in brief.evidence_requirements if item.for_answer_id == "answer_2"} == {
        "status", "risk", "action",
    }


def test_question_brief_expands_generic_answer_shapes_without_sector_terms():
    cases = {
        "해외 주요 텔레콤(통신사) 기업들의 신규 사업 추진 케이스 및 레퍼런스": {"case_study"},
        "시니어 타겟 콘텐츠 인기 순위 및 시청 트렌드 분석": {"ranking", "trend"},
        "2030 1인 가구의 유선 인터넷 가입 고려 요인 및 페인 포인트": {"driver", "pain_point"},
        "롱폼과 숏폼 미디어 소비 트랜드": {"trend", "compare"},
        "구독 상품 내 '스포츠 중계' 포함에 따른 가입 유인 효과 분석": {"causal_effect"},
    }

    for index, (question, expected_shapes) in enumerate(cases.items(), start=1):
        brief = build_rule_based_question_brief(f"req_shape_{index}", question)
        assert set(brief.question_context.required_answer_shapes) == expected_shapes


def test_question_brief_splits_ranking_trend_and_driver_pain_answers():
    ranking_trend = build_rule_based_question_brief(
        "req_rank", "시니어 타겟 콘텐츠 인기 순위 및 시청 트렌드 분석"
    )
    driver_pain = build_rule_based_question_brief(
        "req_driver", "2030 1인 가구의 유선 인터넷 가입 고려 요인 및 페인 포인트"
    )

    assert [item.answer_type for item in ranking_trend.requested_answers] == ["ranking", "trend"]
    assert [item.answer_type for item in driver_pain.requested_answers] == ["driver", "pain_point"]


def test_validator_rejects_merging_rule_separated_explicit_answers():
    question = "칩플레이션이 셋톱박스 업계에 미치는 영향과 IPTV사의 중장기 대응 전략"
    draft = build_rule_based_question_brief("req_no_merge", question)
    invalid = QuestionBrief.model_validate({
        **draft.model_dump(),
        "requested_answers": [{
            "answer_id": "answer_merged",
            "question_anchor": question,
            "answer_type": "strategy",
            "subject": question,
            "origin": "ai_refined",
            "rationale": "두 요청을 하나의 전략 질문으로 합쳤습니다.",
        }],
    })

    try:
        validate_question_brief(invalid, draft)
    except ValueError as exc:
        assert "merged" in str(exc)
    else:
        raise AssertionError("validator accepted a merge of explicit requested answers")


def test_refinement_prompt_has_the_nonnegotiable_contract_guards():
    assert "Do not answer or assess fulfillment" in _REFINEMENT_PROMPT
    assert "Every user-explicit requested answer in the draft must" in _REFINEMENT_PROMPT
    assert "valid `for_answer_id`" in _REFINEMENT_PROMPT
    assert "include a concise, concrete `rationale`" in _REFINEMENT_PROMPT
    assert "Do not use audience labels, report-purpose labels, report" in _REFINEMENT_PROMPT
    assert "do not merge them into a broader answer" in _REFINEMENT_PROMPT
    assert "Do not copy, pool, or substitute requirements across distinct" in _REFINEMENT_PROMPT
    assert "rankings need the same population, period, and measure" in _REFINEMENT_PROMPT


def test_ai_schema_is_strict_for_every_nested_object():
    schema = _schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["QuestionContext"]["additionalProperties"] is False
    assert set(schema["$defs"]["EvidenceRequirement"]["properties"]).issubset(
        schema["$defs"]["EvidenceRequirement"]["required"]
    )
