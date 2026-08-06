import pytest

from common.contracts import EntityExtractionResult, UserRequest
from core.request_pipeline import pipeline as pipeline_module
from core.request_pipeline.pipeline import run_pipeline
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms


CASES = [
    ("하이닉스 에이치비엠 요즘 잘팔림?ㅋㅋ", "sk_hynix", "HBM", "판매 현황", True),
    (
        "회사 후배가 그러는데 우리 메모리 반도체 요즘 엔비디아쪽이랑 "
        "잘되고있다던데 진짜임?",
        "sk_hynix", "HBM", "NVIDIA 수요", False,
    ),
    ("비티비 요새 넷플처럼 오리지널 콘텐츠 만든다는데 반응 어떄", "sk_broadband", "B tv", "오리지널 콘텐츠 반응", True),
    ("인터넷 결합상품 요즘 다들 어디로 갈아타나요 우리쪽은 괜찮은가", "sk_broadband", "인터넷 결합상품", "가입자 이탈", False),
    ("에스케이티 에이닷인가 그거 AI서비스 요즘 잘되나요??", "sk_telecom", "에이닷", "이용 현황", True),
    ("요새 자꾸 통신사들 AI데이터센터 짓는다고 뉴스나오던데 우리회사도 하고있음?", "sk_telecom", "AI 데이터센터", "투자 현황", False),
    ("오케캐시백이랑 시럽 요새 반응 어떰 다들 잘씀?", "sk_planet", "OK캐쉬백", "이용자 반응", True),
    ("포인트 적립 서비스들 요즘 경쟁 빡세다는데 우리 상황은 어떤지 궁금함", "sk_planet", "포인트 마케팅", "경쟁 현황", False),
    ("에스케이온 배터리 요즘 잘팔리나 미국공장은 잘돌아가고있음?", "sk_innovation", "전기차 배터리", "북미 공장 가동률", True),
    ("전기차 요즘 잘 안팔린다는데 우리 배터리 사업 괜찮은거야?", "sk_innovation", "전기차 배터리", "수요 둔화", False),
]


@pytest.mark.parametrize(("question", "sector_id", "entity", "topic", "explicit"), CASES)
def test_messy_question_becomes_clean_search_queries(
    monkeypatch, question, sector_id, entity, topic, explicit
):
    calls = []

    def fake_ai(request, rule_based_result, profiles, requested_sector_id=None):
        calls.append(request.question)
        return EntityExtractionResult(
            request_id=request.request_id,
            primary_intent="current_status",
            perspective="company_update",
            organizations=[],
            technologies=[entity],
            keywords=[topic],
            sector_id=sector_id,
            routing_confidence="high",
            routing_reason="normalized by test AI",
            needs_ai_routing=False,
        )

    monkeypatch.setattr(pipeline_module, "extract_entities_ai", fake_ai)
    result = run_pipeline(
        UserRequest(request_id="req_messy", question=question),
        dry_run=True,
        requested_sector_id=sector_id if explicit else None,
    )

    assert calls == [question]
    assert result.sector_route.sector_id == sector_id
    assert result.source_plan.question_keywords[:2] == [entity, topic]
    assert result.source_plan.planned_sources
    source_terms = build_source_search_terms(result.source_plan.planned_sources[0], result.source_plan.question_keywords)
    queries = build_search_queries(source_terms)
    assert queries
    assert any(entity in query for query in queries)
    assert all(noise not in " ".join(result.source_plan.question_keywords) for noise in ("ㅋㅋ", "요즘", "어떰", "우리회사"))


def test_executive_report_uses_shared_decision_order(monkeypatch):
    from common.contracts import DocumentAnalysis, ReportPurposeClassification
    from core.report_generator.generator import generate_report
    from core.report_planner.planner import plan_report
    from core.report_purpose.classifier import recommended_sections_for
    from core.synthesis.synthesizer import synthesize

    monkeypatch.delenv("TRENDSPARC_REPORT_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    synthesis = synthesize(
        "req_exec",
        "sk_hynix",
        [
            DocumentAnalysis(
                doc_id="news:1",
                source_id="newsroom",
                key_points=["HBM 샘플 공급이 확인됐다"],
                risk="양산 일정 변동 위험",
                recommended_actions=["추가 공급 계획 검토"],
                monitoring_indicators=["수율", "샘플 승인 시점"],
                evidence=["공식 발표"],
            )
        ],
    )
    purpose = ReportPurposeClassification(
        request_id="req_exec",
        purpose_id="current_status",
        display_name="현황 파악",
        recommended_sections=recommended_sections_for("current_status"),
    )
    plan = plan_report(synthesis, "executive", purpose)
    report = generate_report("HBM 개발 현황 알려줘", synthesis, plan, "executive")

    section_ids = [section.section_id for section in report.sections]
    # The 현황파악 shape, from the purpose rather than the audience.
    assert section_ids[0] == "overview"
    assert "current_situation" in section_ids
    assert "near_term_outlook" in section_ids
    # This synthesis carries no figures, so the numeric panels are dropped
    # with a recorded reason instead of rendering empty.
    assert "key_metrics" not in section_ids
    assert plan.omitted_sections["key_metrics"]
