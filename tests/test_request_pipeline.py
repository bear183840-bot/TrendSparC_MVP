import sectors.sk_hynix.adapter.analyzer as sk_hynix_analyzer
import sectors.sk_hynix.adapter.collector as sk_hynix_collector
import sectors.sk_hynix.adapter.processor as sk_hynix_processor
import sectors.sk_hynix.adapter.validator as sk_hynix_validator
from common.contracts import DocumentAnalysis, SourceDocument, UserRequest
from common.errors import StageStatus
from core.request_pipeline.pipeline import run_pipeline


def _make_request(question: str, **kwargs) -> UserRequest:
    return UserRequest(request_id="req_test_pipeline", question=question, **kwargs)


def test_dry_run_passes_every_stage_with_valid_contracts():
    request = _make_request("SK하이닉스 HBM 시장 전망", target_audience="practitioner")
    result = run_pipeline(request, dry_run=True)

    assert result.halted_at_stage is None
    assert result.entities is not None
    assert result.entities.primary_intent == "future_business"
    assert result.report_plan.primary_intent == "future_business"
    assert result.sector_route is not None
    assert result.sector_route.status == "routed"
    assert result.source_plan is not None
    assert result.synthesis is not None
    assert result.report_plan is not None
    assert result.audience_adaptation is not None
    assert result.layout is not None

    statuses = {trace.stage: trace.status for trace in result.trace}
    assert statuses["entity"] == StageStatus.OK
    assert statuses["sector_router"] == StageStatus.OK
    assert statuses["source_planner"] == StageStatus.OK
    assert statuses["synthesis"] == StageStatus.OK
    assert statuses["report_planner"] == StageStatus.OK
    assert statuses["audience_adapter"] == StageStatus.OK
    assert statuses["layout_generator"] == StageStatus.OK
    for role in ("collector", "processor", "validator", "analyzer"):
        assert statuses[f"sector_adapter.{role}"] == StageStatus.SKIPPED

    assert all(trace.status != StageStatus.FAILED for trace in result.trace)


def test_no_sector_specified_falls_back_to_general():
    request = _make_request("오늘 점심 뭐 먹지")
    result = run_pipeline(request, dry_run=True)

    assert result.sector_route.status == "routed"
    assert result.sector_route.sector_id == "general"


def test_request_level_sector_selection_is_honored_when_param_omitted():
    request = _make_request("오늘 점심 뭐 먹지", requested_sector_id="sk_hynix")
    result = run_pipeline(request, dry_run=True)

    assert result.sector_route.status == "routed"
    assert result.sector_route.sector_id == "sk_hynix"


def test_explicit_param_overrides_request_level_sector_selection():
    request = _make_request("오늘 점심 뭐 먹지", requested_sector_id="sk_hynix")
    result = run_pipeline(request, dry_run=True, requested_sector_id="sk_planet")

    assert result.sector_route.status == "routed"
    assert result.sector_route.sector_id == "sk_planet"


def test_analyzer_documents_flagged_irrelevant_are_dropped_before_synthesis(monkeypatch):
    fake_documents = [
        SourceDocument(doc_id="d1", source_id="source", title="t1", content="c1"),
        SourceDocument(doc_id="d2", source_id="source", title="t2", content="c2"),
    ]

    def fake_analyze(documents, question):
        assert question == "SK하이닉스 HBM 시장 전망"
        return [
            DocumentAnalysis(
                doc_id="d1", summary="관련", key_points=["포인트 A"], sentiment="neutral", relevant_to_question=True
            ),
            DocumentAnalysis(
                doc_id="d2", summary="무관", key_points=["엉뚱한 포인트"], sentiment="neutral", relevant_to_question=False
            ),
        ]

    monkeypatch.setattr(sk_hynix_collector, "collect", lambda source_plan: fake_documents)
    monkeypatch.setattr(sk_hynix_processor, "process", lambda documents: documents)
    monkeypatch.setattr(sk_hynix_validator, "validate", lambda documents: documents)
    monkeypatch.setattr(sk_hynix_analyzer, "analyze", fake_analyze)

    request = _make_request("SK하이닉스 HBM 시장 전망", requested_sector_id="sk_hynix")
    result = run_pipeline(request, dry_run=False)

    assert result.halted_at_stage is None
    assert [analysis.doc_id for analysis in result.document_analyses] == ["d1"]
