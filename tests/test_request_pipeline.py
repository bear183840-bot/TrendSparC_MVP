import sectors.sk_hynix.adapter.analyzer as sk_hynix_analyzer
import sectors.sk_hynix.adapter.collector as sk_hynix_collector
import sectors.sk_hynix.adapter.processor as sk_hynix_processor
import sectors.sk_hynix.adapter.validator as sk_hynix_validator
import sectors.sk_broadband.adapter.analyzer as sk_broadband_analyzer
import sectors.sk_broadband.adapter.collector as sk_broadband_collector
import sectors.sk_broadband.adapter.processor as sk_broadband_processor
import sectors.sk_broadband.adapter.validator as sk_broadband_validator
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
    assert result.report_purpose is not None
    assert result.report_purpose.purpose_id == "future_business"
    assert result.report_plan.primary_intent == "future_business"
    assert result.report_plan.report_purpose.purpose_id == "future_business"
    assert result.sector_route is not None
    assert result.sector_route.status == "routed"
    assert result.source_plan is not None
    assert result.source_plan.search_context is not None
    assert result.source_plan.search_context.question == request.question
    assert result.source_plan.search_context.perspective == result.entities.perspective
    assert result.source_plan.search_context.report_purpose_id == "future_business"
    assert result.source_plan.search_context.information_needs == result.entities.information_needs
    assert result.source_plan.search_context.suggested_terms == result.source_plan.question_keywords
    assert result.source_plan.search_context.country_code == "KR"
    assert result.synthesis is not None
    assert result.report_plan is not None
    assert result.audience_adaptation is not None
    assert result.layout is not None

    statuses = {trace.stage: trace.status for trace in result.trace}
    assert statuses["entity"] == StageStatus.OK
    assert statuses["sector_router"] == StageStatus.OK
    assert statuses["report_purpose"] == StageStatus.OK
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

    def fake_analyze(documents, question, information_needs=None):
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
    monkeypatch.setattr(
        sk_hynix_validator,
        "validate",
        lambda documents, search_context=None: documents,
    )
    monkeypatch.setattr(sk_hynix_analyzer, "analyze", fake_analyze)

    request = _make_request("SK하이닉스 HBM 시장 전망", requested_sector_id="sk_hynix")
    result = run_pipeline(request, dry_run=False)

    assert result.halted_at_stage is None
    assert result.collected_source_documents == fake_documents
    assert [analysis.doc_id for analysis in result.document_analyses] == ["d1"]


def test_pipeline_recollects_when_validation_leaves_fewer_than_profile_minimum(monkeypatch):
    first_documents = [
        SourceDocument(doc_id="d1", source_id="source-1", title="자료 1", url="https://one.example.com/a", content="가" * 300),
        SourceDocument(doc_id="bad", source_id="source-x", title="제거 자료", url="https://bad.example.com/a", content="나" * 300),
    ]
    retry_documents = [
        SourceDocument(doc_id="d2", source_id="source-2", title="자료 2", url="https://two.example.com/a", content="다" * 300),
        SourceDocument(doc_id="d3", source_id="source-3", title="자료 3", url="https://three.example.com/a", content="라" * 300),
    ]
    collector_plans = []

    def fake_collect(source_plan):
        collector_plans.append(source_plan)
        return first_documents if len(collector_plans) == 1 else retry_documents

    validation_calls = []

    def fake_validate(documents, search_context=None):
        validation_calls.append((list(documents), search_context))
        return [documents[0]] if len(validation_calls) == 1 else list(documents[:2])

    def fake_analyze(documents, question, information_needs=None):
        return [
            DocumentAnalysis(
                doc_id=document.doc_id,
                summary="관련",
                key_points=["근거"],
                sentiment="neutral",
                relevant_to_question=True,
            )
            for document in documents
        ]

    monkeypatch.setattr(sk_broadband_collector, "collect", fake_collect)
    monkeypatch.setattr(sk_broadband_processor, "process", lambda documents: documents)
    monkeypatch.setattr(sk_broadband_validator, "validate", fake_validate)
    monkeypatch.setattr(sk_broadband_analyzer, "analyze", fake_analyze)

    request = _make_request(
        "SK브로드밴드의 최신 IPTV 경쟁 현황은?",
        requested_sector_id="sk_broadband",
    )
    result = run_pipeline(request, dry_run=False)

    assert result.halted_at_stage is None
    assert len(collector_plans) == 2
    retry_context = collector_plans[1].search_context
    assert set(retry_context.excluded_urls) == {
        "https://one.example.com/a",
        "https://bad.example.com/a",
    }
    assert retry_context.validation_feedback
    assert [analysis.doc_id for analysis in result.document_analyses] == ["d1", "d2"]
    assert any(trace.stage == "sector_adapter.collector.recollection" for trace in result.trace)


def test_pipeline_recollects_when_analyzer_leaves_fewer_than_profile_minimum(monkeypatch):
    initial = [
        SourceDocument(doc_id="d1", source_id="s1", title="자료 1", url="https://one.example/a", content="가" * 300),
        SourceDocument(doc_id="d_bad", source_id="sx", title="자료 X", url="https://bad.example/a", content="나" * 300),
    ]
    replacements = [
        SourceDocument(doc_id="d2", source_id="s2", title="자료 2", url="https://two.example/a", content="다" * 300),
        SourceDocument(doc_id="d3", source_id="s3", title="자료 3", url="https://three.example/a", content="라" * 300),
    ]
    collector_plans = []
    analyzer_needs = []

    def fake_collect(source_plan):
        collector_plans.append(source_plan)
        return initial if len(collector_plans) == 1 else replacements

    def fake_analyze(documents, question, information_needs=None):
        analyzer_needs.append(list(information_needs or []))
        if len(analyzer_needs) == 1:
            return [
                DocumentAnalysis(doc_id="d1", relevant_to_question=True, usable_for_synthesis=True),
                DocumentAnalysis(
                    doc_id="d_bad",
                    relevant_to_question=True,
                    usable_for_synthesis=False,
                    analysis_validation_status="insufficient_grounding",
                ),
            ]
        return [
            DocumentAnalysis(
                doc_id=document.doc_id,
                relevant_to_question=True,
                usable_for_synthesis=True,
            )
            for document in documents
        ]

    monkeypatch.setattr(sk_broadband_collector, "collect", fake_collect)
    monkeypatch.setattr(sk_broadband_processor, "process", lambda documents: documents)
    monkeypatch.setattr(
        sk_broadband_validator,
        "validate",
        lambda documents, search_context=None: documents,
    )
    monkeypatch.setattr(sk_broadband_analyzer, "analyze", fake_analyze)

    result = run_pipeline(
        _make_request("SK브로드밴드 최신 IPTV 경쟁 현황은?", requested_sector_id="sk_broadband"),
        dry_run=False,
    )

    assert result.halted_at_stage is None
    assert len(collector_plans) == 2
    assert analyzer_needs[0] == analyzer_needs[1] == collector_plans[0].information_needs
    assert set(collector_plans[1].search_context.excluded_urls) == {
        "https://one.example/a",
        "https://bad.example/a",
    }
    assert {analysis.doc_id for analysis in result.document_analyses} == {"d1", "d2", "d3"}
    assert any(
        trace.stage == "sector_adapter.collector.analysis_recollection"
        for trace in result.trace
    )


def test_pipeline_halts_when_analyzer_still_has_fewer_than_minimum_after_recollection(monkeypatch):
    batches = [
        [
            SourceDocument(doc_id="d1", source_id="s1", title="자료 1", url="https://one.example/a", content="가" * 300),
            SourceDocument(doc_id="d2", source_id="s2", title="자료 2", url="https://two.example/a", content="나" * 300),
        ],
        [
            SourceDocument(doc_id="d3", source_id="s3", title="자료 3", url="https://three.example/a", content="다" * 300),
            SourceDocument(doc_id="d4", source_id="s4", title="자료 4", url="https://four.example/a", content="라" * 300),
        ],
    ]
    collector_calls = []

    def fake_collect(source_plan):
        batch = batches[len(collector_calls)]
        collector_calls.append(source_plan)
        return batch

    def fake_analyze(documents, question, information_needs=None):
        return [
            DocumentAnalysis(
                doc_id=document.doc_id,
                relevant_to_question=True,
                usable_for_synthesis=document.doc_id == "d1",
                analysis_validation_status=(
                    "verified" if document.doc_id == "d1" else "insufficient_grounding"
                ),
            )
            for document in documents
        ]

    monkeypatch.setattr(sk_broadband_collector, "collect", fake_collect)
    monkeypatch.setattr(sk_broadband_processor, "process", lambda documents: documents)
    monkeypatch.setattr(
        sk_broadband_validator,
        "validate",
        lambda documents, search_context=None: documents,
    )
    monkeypatch.setattr(sk_broadband_analyzer, "analyze", fake_analyze)

    result = run_pipeline(
        _make_request("SK브로드밴드 최신 IPTV 경쟁 현황은?", requested_sector_id="sk_broadband"),
        dry_run=False,
    )

    assert len(collector_calls) == 2
    assert result.halted_at_stage == "sector_adapter.analyzer"
    assert "insufficient usable analyses" in result.trace[-1].reason
