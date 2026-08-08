from common.contracts import (
    ComparisonPoint,
    DocumentAnalysis,
    GroundedClaim,
    MetricPoint,
    ReportPurposeClassification,
)
from core.report_generator.generator import generate_report
from core.report_planner.planner import plan_report
from core.synthesis.synthesizer import synthesize
from core.report_generator import generator as generator_module


def _synthesis():
    return synthesize(
        "req_report",
        "general",
        [
            DocumentAnalysis(
                doc_id="attachment:brief",
                summary="요약",
                key_points=["수요가 증가했다"],
                business_impact="운영 비용이 증가한다",
                risk="공급 지연 위험이 있다",
                opportunity="대체 공급처 확보 기회가 있다",
                recommended_actions=["대체 공급처를 검토한다"],
                monitoring_indicators=["월별 납기"],
                evidence=["첨부자료의 2분기 납기 표"],
                analysis_confidence="high",
            )
        ],
    )


def test_synthesis_preserves_strategy_fields_with_document_traceability():
    synthesis = _synthesis()

    assert "공급 지연" in synthesis.risks[0]
    assert "[doc_id=attachment:brief]" in synthesis.risks[0]
    assert synthesis.opportunities and synthesis.recommended_actions
    assert synthesis.evidence and synthesis.monitoring_indicators


def test_synthesis_distinguishes_documents_from_unique_sources():
    analyses = [
        DocumentAnalysis(doc_id="kocca:1", source_id="KOCCA", key_points=["A"]),
        DocumentAnalysis(doc_id="kocca:2", source_id="KOCCA", key_points=["B"]),
    ]

    synthesis = synthesize("req", "sk_broadband", analyses)

    assert synthesis.source_count == 2
    assert synthesis.unique_source_count == 1
    assert synthesis.source_ids == ["KOCCA"]


def test_report_sections_preserve_internal_conclusion_and_claim_links(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    synthesis = synthesize(
        "req_provenance",
        "sk_broadband",
        [
            DocumentAnalysis(
                doc_id="doc:1",
                source_id="source1",
                grounded_claims=[
                    GroundedClaim(
                        claim_id="risk1",
                        claim_type="risk",
                        claim="해지율 상승 위험",
                        evidence_quote="해지율이 상승했다",
                        confidence="high",
                    )
                ],
            )
        ],
    )
    # issue_response is the purpose whose structure carries risk-type claims
    # ("issue"); the section list follows the purpose, not the audience.
    plan = plan_report(synthesis, "management", "issue_response")

    report = generate_report("주요 위험은?", synthesis, plan, "management")
    issue_section = next(section for section in report.sections if section.section_id == "issue")

    assert [claim.synthesis_claim_id for claim in issue_section.grounded_claims] == [
        "doc:1:risk1"
    ]
    assert issue_section.conclusions[0].supporting_claim_ids == ["doc:1:risk1"]


def test_report_generator_creates_distinct_issue_impact_action_sections(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    synthesis = _synthesis()
    purpose = ReportPurposeClassification(
        request_id="req_report",
        purpose_id="issue_response",
        display_name="이슈 대응",
        recommended_sections=["issue", "impact", "response_actions"],
    )
    plan = plan_report(synthesis, "executive", purpose)

    # The purpose's own sections, not the audience's old fixed page shape.
    assert plan.sections[:4] == ["overview", "issue", "impact", "response_actions"]

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    sections = {section.section_id: section for section in report.sections}

    assert report.executive_summary
    assert sections["issue"].risks
    assert sections["response_actions"].actions
    assert sections["sources"].evidence
    assert sections["issue"].summary != sections["response_actions"].summary
    assert report.generation_mode == "rule_based"
    assert report.unique_source_count == 1
    assert any("고유 출처" in limitation for limitation in report.limitations)


def test_fallback_report_carries_structured_fields_into_market_status_section():
    analysis = DocumentAnalysis(
        doc_id="attachment:brief",
        summary="요약",
        business_impact="운영 비용이 증가한다",
        metric_points=[
            MetricPoint(label="가입자", period="2019", value=519.0, unit="만 명"),
            MetricPoint(label="가입자", period="2023", value=946.0, unit="만 명"),
        ],
        comparison_points=[
            ComparisonPoint(entity="A사", criterion="가격", value="1만원", level="medium"),
            ComparisonPoint(entity="B사", criterion="가격", value="9천원", level="low"),
        ],
    )
    synthesis = synthesize("req_report", "general", [analysis])
    purpose = ReportPurposeClassification(
        request_id="req_report",
        purpose_id="current_status",
        display_name="현황 파악",
        recommended_sections=["market_status"],
    )
    # "external" is the audience whose fixed report_structure actually includes
    # market_status - see audience/profiles/external.md.
    plan = plan_report(synthesis, "external", purpose)
    assert "market_status" in plan.sections

    report = generate_report("시장 현황이 어때?", synthesis, plan, "external")
    market_section = next(section for section in report.sections if section.section_id == "market_status")

    assert len(market_section.metric_points) == 2
    assert {point.period for point in market_section.metric_points} == {"2019", "2023"}
    assert len(market_section.comparison_points) == 2


def test_fallback_report_gives_each_metric_point_single_ownership_across_sections(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # market_status and opportunity independently ask for metric_points from
    # the same synthesis.metric_series, so without single-ownership dedup the
    # one real data point would get mechanically copied into both.
    analysis = DocumentAnalysis(
        doc_id="attachment:brief",
        summary="요약",
        metric_points=[MetricPoint(label="특수관계자 매출 비중", period="2025년 1분기", value=15.9, unit="%")],
    )
    synthesis = synthesize("req_dedup", "sk_broadband", [analysis])
    purpose = ReportPurposeClassification(
        request_id="req_dedup",
        purpose_id="current_status",
        display_name="현황 파악",
        recommended_sections=["market_status", "opportunity"],
    )
    plan = plan_report(synthesis, "external", purpose)
    assert "market_status" in plan.sections and "opportunity" in plan.sections

    report = generate_report("매출 추이는?", synthesis, plan, "external")
    market_status = next(s for s in report.sections if s.section_id == "market_status")
    opportunity = next(s for s in report.sections if s.section_id == "opportunity")

    assert len(market_status.metric_points) == 1
    assert opportunity.metric_points == []


def test_report_planner_keeps_the_root_cause_shape_for_every_audience():
    synthesis = _synthesis()
    purpose = ReportPurposeClassification(
        request_id="req_report",
        purpose_id="root_cause",
        display_name="문제 분석",
        recommended_sections=["problem", "root_cause", "improvement_plan"],
    )

    for audience in ("executive", "practitioner", "management", "external"):
        plan = plan_report(synthesis, audience, purpose)

        assert plan.sections[:4] == ["overview", "problem", "root_cause", "improvement_plan"], audience


def test_report_generator_openai_path_receives_full_synthesis(monkeypatch):
    import json
    import openai

    synthesis = _synthesis()
    purpose = ReportPurposeClassification(
        request_id="req_report",
        purpose_id="issue_response",
        display_name="이슈 대응",
        recommended_sections=["issue", "impact", "response_actions"],
    )
    plan = plan_report(synthesis, "executive", purpose)
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            sections = [
                {
                    "section_id": section_id,
                    "title": section_id,
                    "summary": f"{section_id} 완성 문장",
                    "key_points": [],
                    "evidence": ["근거 [doc_id=attachment:brief]"],
                    "risks": [],
                    "opportunities": [],
                    "actions": [],
                    "monitoring_indicators": [],
                    "confidence": "high",
                }
                for section_id in plan.sections[:-1]
            ]
            payload = {
                "title": "완성 보고서",
                "executive_summary": "경영진 요약",
                "sections": sections,
                "limitations": [],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")

    user_payload = json.loads(captured["input"][1]["content"])
    system_prompt = captured["input"][0]["content"]
    assert user_payload["synthesis"]["risks"] == synthesis.risks
    assert user_payload["synthesis"]["evidence"] == synthesis.evidence
    assert user_payload["synthesis"]["recommended_actions"] == synthesis.recommended_actions
    assert "all narrative text must be Korean" in system_prompt
    assert "key metrics, timeline, decision required, risk, sources" in system_prompt
    assert "authoritative style/structure rules" in system_prompt
    assert "audience.description" in system_prompt
    assert "purpose.instructions" in system_prompt
    assert report.generation_mode == "openai"
    assert report.executive_summary == "경영진 요약"
    assert [section.section_id for section in report.sections] == plan.sections
    assert any("누락한 섹션" in limitation for limitation in report.limitations)


# --- Timeline fallback no longer duplicates Overview verbatim (problem 9) ---


def _issue_response_plan(synthesis, request_id: str):
    purpose = ReportPurposeClassification(
        request_id=request_id,
        purpose_id="issue_response",
        display_name="이슈 대응",
        # timeline is requested explicitly so these tests exercise how the
        # generator *fills* a timeline section, independent of the planner's
        # separate rule for when a timeline is warranted.
        recommended_sections=["issue", "impact", "response_actions", "timeline"],
    )
    return plan_report(synthesis, "executive", purpose)


def test_fallback_timeline_uses_dated_evidence_instead_of_overview_key_points(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = DocumentAnalysis(
        doc_id="attachment:brief",
        summary="요약",
        key_points=["일반 핵심 요약 문장"],
        evidence=[
            "2024년 7월 서비스 개편이 있었다.",
            "2025년 3월 요금제가 개정됐다.",
            "시점이 명시되지 않은 일반 서술",
        ],
    )
    synthesis = synthesize("req_timeline", "general", [analysis])
    plan = _issue_response_plan(synthesis, "req_timeline")
    assert "timeline" in plan.sections

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    timeline_section = next(s for s in report.sections if s.section_id == "timeline")
    overview_section = next(s for s in report.sections if s.section_id == "overview")

    assert timeline_section.key_points != overview_section.key_points
    assert any("2024년 7월" in point for point in timeline_section.key_points)
    assert not any("일반 핵심 요약 문장" in point for point in timeline_section.key_points)


def test_fallback_timeline_uses_metric_period_labels_when_no_dated_evidence(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = DocumentAnalysis(
        doc_id="attachment:brief",
        summary="요약",
        metric_points=[
            MetricPoint(label="시청률", period="도입 전", value=3.2, unit="%"),
            MetricPoint(label="시청률", period="도입 후", value=4.1, unit="%"),
        ],
        evidence=["시점이 명시되지 않은 일반 서술"],
    )
    synthesis = synthesize("req_timeline_metric", "general", [analysis])
    plan = _issue_response_plan(synthesis, "req_timeline_metric")

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    timeline_section = next(s for s in report.sections if s.section_id == "timeline")

    assert any("도입 전" in point for point in timeline_section.key_points)
    assert any("도입 후" in point for point in timeline_section.key_points)


def test_timeline_section_is_omitted_with_a_reason_when_nothing_is_dated(monkeypatch):
    """No dated material anywhere -> the section is dropped and the reason
    recorded, rather than rendering an empty 타임라인 panel."""
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = DocumentAnalysis(
        doc_id="attachment:brief",
        summary="요약",
        key_points=["일반 핵심 요약 문장"],
        evidence=["시점이 명시되지 않은 일반 서술"],
    )
    synthesis = synthesize("req_timeline_empty", "general", [analysis])
    plan = _issue_response_plan(synthesis, "req_timeline_empty")

    assert "timeline" not in plan.sections
    assert "timeline" in plan.omitted_sections

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    assert all(section.section_id != "timeline" for section in report.sections)


# --- recommended_actions never silently dropped by the OpenAI writer (problem 8) ---


def test_generate_report_openai_path_keeps_every_recommended_action_reachable(monkeypatch):
    import json
    import openai

    analyses = [
        DocumentAnalysis(doc_id=f"doc:{i}", summary="요약", recommended_actions=[f"조치 {i}를 수행한다"])
        for i in range(1, 7)
    ]
    synthesis = synthesize("req_actions", "general", analyses)
    assert len(synthesis.recommended_actions) == 6
    plan = _issue_response_plan(synthesis, "req_actions")

    class FakeResponses:
        def create(self, **kwargs):
            sections = []
            for section_id in plan.sections:
                # Only "decision_required" surfaces any actions, and only 2 of
                # the 6 the analyzer actually extracted - simulates the OpenAI
                # writer under-filling an action-role section.
                actions = synthesis.recommended_actions[:2] if section_id == "decision_required" else []
                sections.append(
                    {
                        "section_id": section_id,
                        "title": section_id,
                        "summary": f"{section_id} 완성 문장",
                        "key_points": [],
                        "evidence": [],
                        "risks": [],
                        "opportunities": [],
                        "actions": actions,
                        "monitoring_indicators": [],
                        "confidence": "high",
                    }
                )
            payload = {
                "title": "완성 보고서",
                "executive_summary": "경영진 요약",
                "sections": sections,
                "limitations": [],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")

    reachable_doc_ids = {
        generator_module._doc_id(action) for section in report.sections for action in section.actions
    }
    expected_doc_ids = {generator_module._doc_id(action) for action in synthesis.recommended_actions}
    assert expected_doc_ids <= reachable_doc_ids


def test_fallback_report_discloses_missing_information_needs_honestly(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    synthesis = _synthesis()
    plan = _issue_response_plan(synthesis, "req_report")

    report = generate_report(
        "어떻게 대응해야 하나?",
        synthesis,
        plan,
        "executive",
        missing_information_needs=["customer_market"],
    )

    assert any("customer_market" in limitation for limitation in report.limitations)
    assert any("확인 안 됨" in limitation for limitation in report.limitations)


def test_fallback_report_has_no_missing_needs_limitation_when_nothing_missing(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    synthesis = _synthesis()
    plan = _issue_response_plan(synthesis, "req_report")

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")

    assert not any("확인 안 됨" in limitation for limitation in report.limitations)


def test_ensure_all_actions_reachable_is_a_no_op_when_nothing_missing(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    synthesis = _synthesis()
    plan = _issue_response_plan(synthesis, "req_report")

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    before = [section.model_copy() for section in report.sections]
    after = generator_module._ensure_all_actions_reachable(report.sections, synthesis)

    assert [s.actions for s in after] == [s.actions for s in before]


# --- report_generator quote repair, mirroring sk_broadband's
# _repair_failed_claim_quotes ("B안") ---


def _repair_synthesis():
    analysis = DocumentAnalysis(
        doc_id="doc:cmp",
        summary="요약",
        evidence=[
            "A사 요금제 가격은 월 8,900원이다.",
            "업계 2위 사업자의 요금제는 월 9,900원이다.",
        ],
    )
    return synthesize("req_repair", "general", [analysis])


def _repair_plan(synthesis, request_id):
    purpose = ReportPurposeClassification(
        request_id=request_id,
        purpose_id="current_status",
        display_name="현황 파악",
        recommended_sections=["market_status"],
    )
    return plan_report(synthesis, "external", purpose)


def _repair_sections_payload(plan):
    return [
        {
            "section_id": section_id,
            "title": section_id,
            "summary": "요약",
            "key_points": [],
            "evidence": [],
            "risks": [],
            "opportunities": [],
            "actions": [],
            "monitoring_indicators": [],
            "confidence": "high",
        }
        for section_id in plan.sections
    ]


class _FakeChatCompletions:
    """Records every call and answers via `responder(payload) -> repairs list`."""

    def __init__(self, responder):
        self._responder = responder
        self.calls: list[dict] = []

    def create(self, **kwargs):
        import json as _json

        self.calls.append(kwargs)
        payload = _json.loads(kwargs["messages"][1]["content"])
        repairs = self._responder(payload)
        content = _json.dumps({"repairs": repairs}, ensure_ascii=False)
        message = type("Message", (), {"content": content, "refusal": None})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def _repairs_selecting_by_text(item_id: str, sentence_text: str):
    """Repairs the given item to whichever candidate carries `sentence_text`,
    and declines every other item offered."""

    def responder(payload):
        sentence_id_by_text = {s["text"]: s["sentence_id"] for s in payload["candidate_sentences"]}
        return [
            {
                "item_id": item["item_id"],
                "sentence_id": sentence_id_by_text.get(sentence_text) if item["item_id"] == item_id else None,
            }
            for item in payload["items_to_repair"]
        ]

    return responder


def test_repair_revives_a_comparison_point_with_a_paraphrased_source_sentence(monkeypatch):
    import json
    import openai

    synthesis = _repair_synthesis()
    plan = _repair_plan(synthesis, "req_repair")
    target_sentence = synthesis.evidence[1]

    class FakeResponses:
        def create(self, **kwargs):
            payload = {
                "title": "보고서",
                "executive_summary": "요약",
                "sections": _repair_sections_payload(plan),
                "limitations": [],
                "comparison_points": [
                    {
                        "entity": "A사", "criterion": "요금제 가격", "value": "8,900원",
                        "level": None, "source_sentence": synthesis.evidence[0],
                    },
                    {
                        "entity": "B사", "criterion": "요금제 가격", "value": "9,900원",
                        "level": None,
                        # Paraphrased - not a verbatim substring of the corpus,
                        # and "B사" itself is never mentioned in the evidence
                        # either, so this fails both legs of the corpus check.
                        "source_sentence": "B사 요금제 가격은 9,900원이다.",
                    },
                ],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    chat = _FakeChatCompletions(_repairs_selecting_by_text("c1", target_sentence))

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
            self.chat = type("Chat", (), {"completions": chat})()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("가격 비교는?", synthesis, plan, "external")

    assert len(chat.calls) == 1
    assert {point.entity for point in report.extracted_comparison_points} == {"A사", "B사"}


def test_repair_never_receives_structurally_invalid_failures(monkeypatch):
    import json
    import openai

    synthesis = _repair_synthesis()
    plan = _repair_plan(synthesis, "req_repair_structural")

    class FakeResponses:
        def create(self, **kwargs):
            payload = {
                "title": "보고서",
                "executive_summary": "요약",
                "sections": _repair_sections_payload(plan),
                "limitations": [],
                "action_impacts": [
                    {
                        # Not in synthesis.recommended_actions - structural
                        # failure, not a quote problem, so repair must never
                        # see it.
                        "action": "존재하지 않는 조치를 수행한다",
                        "expected_impact": "매출 10% 증가",
                        "impact_value": None,
                        "impact_unit": None,
                        "source_sentence": "관련 없는 문장",
                    }
                ],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    chat = _FakeChatCompletions(lambda payload: [])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
            self.chat = type("Chat", (), {"completions": chat})()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("무엇을 해야 하나?", synthesis, plan, "external")

    assert chat.calls == []
    assert report.action_impacts == []


def test_repair_ignores_a_sentence_id_outside_the_offered_candidates(monkeypatch):
    import json
    import openai

    synthesis = _repair_synthesis()
    plan = _repair_plan(synthesis, "req_repair_offlist")

    class FakeResponses:
        def create(self, **kwargs):
            payload = {
                "title": "보고서",
                "executive_summary": "요약",
                "sections": _repair_sections_payload(plan),
                "limitations": [],
                "comparison_points": [
                    {
                        "entity": "A사", "criterion": "요금제 가격", "value": "8,900원",
                        "level": None, "source_sentence": synthesis.evidence[0],
                    },
                    {
                        "entity": "B사", "criterion": "요금제 가격", "value": "9,900원",
                        "level": None, "source_sentence": "B사 요금제 가격은 9,900원이다.",
                    },
                ],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    def responder(payload):
        return [
            {"item_id": item["item_id"], "sentence_id": "S999"}
            for item in payload["items_to_repair"]
        ]

    chat = _FakeChatCompletions(responder)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
            self.chat = type("Chat", (), {"completions": chat})()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("가격 비교는?", synthesis, plan, "external")

    assert len(chat.calls) == 1
    assert {point.entity for point in report.extracted_comparison_points} == set()


def test_repair_api_exception_does_not_break_report_generation(monkeypatch):
    import json
    import openai

    synthesis = _repair_synthesis()
    plan = _repair_plan(synthesis, "req_repair_exception")

    class FakeResponses:
        def create(self, **kwargs):
            payload = {
                "title": "보고서",
                "executive_summary": "요약",
                "sections": _repair_sections_payload(plan),
                "limitations": [],
                "comparison_points": [
                    {
                        "entity": "A사", "criterion": "요금제 가격", "value": "8,900원",
                        "level": None, "source_sentence": synthesis.evidence[0],
                    },
                    {
                        "entity": "B사", "criterion": "요금제 가격", "value": "9,900원",
                        "level": None, "source_sentence": "B사 요금제 가격은 9,900원이다.",
                    },
                ],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class RaisingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("repair endpoint unavailable")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
            self.chat = type("Chat", (), {"completions": RaisingCompletions()})()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("가격 비교는?", synthesis, plan, "external")

    assert report.generation_mode == "openai"
    assert {point.entity for point in report.extracted_comparison_points} == set()


def test_repair_is_never_called_when_nothing_failed_verification(monkeypatch):
    import json
    import openai

    synthesis = _repair_synthesis()
    plan = _repair_plan(synthesis, "req_repair_no_failures")

    class ExplodingCompletions:
        def create(self, **kwargs):
            raise AssertionError("repair should not be called when nothing failed verification")

    class FakeResponses:
        def create(self, **kwargs):
            payload = {
                "title": "보고서",
                "executive_summary": "요약",
                "sections": _repair_sections_payload(plan),
                "limitations": [],
                "comparison_points": [
                    {
                        "entity": "A사", "criterion": "요금제 가격", "value": "8,900원",
                        "level": None, "source_sentence": synthesis.evidence[0],
                    },
                ],
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
            self.chat = type("Chat", (), {"completions": ExplodingCompletions()})()

    monkeypatch.setenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    report = generate_report("가격은?", synthesis, plan, "external")

    assert report.generation_mode == "openai"
