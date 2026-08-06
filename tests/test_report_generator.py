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
    plan = plan_report(synthesis, "management", "current_status")

    report = generate_report("주요 위험은?", synthesis, plan, "management")
    risk_section = next(section for section in report.sections if section.section_id == "risk")

    assert [claim.synthesis_claim_id for claim in risk_section.grounded_claims] == [
        "doc:1:risk1"
    ]
    assert risk_section.conclusions[0].supporting_claim_ids == ["doc:1:risk1"]


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

    assert plan.sections == ["overview", "key_metrics", "timeline", "decision_required", "risk", "sources"]

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    sections = {section.section_id: section for section in report.sections}

    assert report.executive_summary
    assert sections["risk"].risks
    assert sections["decision_required"].actions
    assert sections["sources"].evidence
    assert sections["risk"].summary != sections["decision_required"].summary
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
    # "external" audience's fixed report_structure is
    # ["overview", "market_status", "opportunity", "sources"] - both
    # market_status and opportunity independently ask for metric_points from
    # the same synthesis.metric_series, so without single-ownership dedup
    # the one real data point would get mechanically copied into both.
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
        recommended_sections=["market_status"],
    )
    plan = plan_report(synthesis, "external", purpose)
    assert plan.sections == ["overview", "market_status", "opportunity", "sources"]

    report = generate_report("매출 추이는?", synthesis, plan, "external")
    market_status = next(s for s in report.sections if s.section_id == "market_status")
    opportunity = next(s for s in report.sections if s.section_id == "opportunity")

    assert len(market_status.metric_points) == 1
    assert opportunity.metric_points == []


def test_report_planner_keeps_problem_and_root_cause_but_removes_audience_aliases():
    synthesis = _synthesis()
    purpose = ReportPurposeClassification(
        request_id="req_report",
        purpose_id="root_cause",
        display_name="문제 분석",
        recommended_sections=["problem", "root_cause", "improvement_plan"],
    )

    plan = plan_report(synthesis, "executive", purpose)

    assert plan.sections == ["overview", "key_metrics", "timeline", "decision_required", "risk", "sources"]


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
        recommended_sections=["issue", "impact", "response_actions"],
    )
    return plan_report(synthesis, "executive", purpose)


def test_fallback_timeline_uses_dated_evidence_instead_of_overview_key_points(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    analysis = DocumentAnalysis(
        doc_id="attachment:brief",
        summary="요약",
        key_points=["일반 핵심 요약 문장"],
        evidence=["2024년 7월 서비스 개편이 있었다.", "시점이 명시되지 않은 일반 서술"],
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


def test_fallback_timeline_is_honestly_empty_when_nothing_extractable(monkeypatch):
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

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    timeline_section = next(s for s in report.sections if s.section_id == "timeline")

    assert timeline_section.key_points == []


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
