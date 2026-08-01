from common.contracts import DocumentAnalysis, ReportPurposeClassification
from core.report_generator.generator import generate_report
from core.report_planner.planner import plan_report
from core.synthesis.synthesizer import synthesize


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

    report = generate_report("어떻게 대응해야 하나?", synthesis, plan, "executive")
    sections = {section.section_id: section for section in report.sections}

    assert report.executive_summary
    assert sections["issue"].risks
    assert sections["impact"].key_points
    assert sections["response_actions"].actions
    assert sections["issue"].summary != sections["response_actions"].summary
    assert report.generation_mode == "rule_based"


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
    assert user_payload["synthesis"]["risks"] == synthesis.risks
    assert user_payload["synthesis"]["evidence"] == synthesis.evidence
    assert user_payload["synthesis"]["recommended_actions"] == synthesis.recommended_actions
    assert report.generation_mode == "openai"
    assert report.executive_summary == "경영진 요약"
    assert [section.section_id for section in report.sections] == plan.sections
    assert any("누락한 섹션" in limitation for limitation in report.limitations)
