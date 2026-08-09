from __future__ import annotations

import json

import pytest
from types import SimpleNamespace

from common.contracts import PlannedSource, SectorProfile, SectorRoute, SourcePlan, WebSearchContext
from common.errors import PipelineStageError
from core.request_pipeline import pipeline as pipeline_module
from sources.collectors.source_router import coverage as coverage_module
from sources.collectors.source_router import planner as planner_module
from sources.collectors.source_router import refiner as refiner_module
from sources.collectors.source_router import router as router_module
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.source_router.adapter import (
    match_registry_source,
    semanticize_markdown_tables,
    source_router_result_to_collection,
)
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    ConfirmedFact,
    CoverageDecision,
    EvidenceNeed,
    EvidenceVerification,
    NextQuery,
    SearchPlan,
    SearchPlanQuery,
    SourceRouterResult,
    WebSearchResult,
)


def _plan(*queries: str) -> SearchPlan:
    return SearchPlan(
        intent="IPTV status",
        queries=[SearchPlanQuery(query=query, priority=1) for query in queries],
    )


def test_iptv_evidence_needs_keep_direct_before_time_series_and_comparison():
    needs = refiner_module.build_evidence_needs(
        "IPTV 가입자 수 현황은?",
        ["현재 IPTV 가입자 현황"],
        ["동일 metric의 여러 실제 시점 데이터", "주요 사업자의 동일 시점·동일 기준 비교"],
        purpose_id="current_status",
    )

    assert [need.requirement_type for need in needs] == ["direct", "supporting", "supporting"]
    assert "현재 IPTV 가입자" in needs[0].text
    assert "시점" in needs[1].text
    assert "사업자" in needs[2].text


def test_issue_response_evidence_needs_prioritize_issue_and_response():
    needs = refiner_module.build_evidence_needs(
        "중앙그룹 회생 사태에 IPTV사는 어떻게 대응해야 하나?",
        ["중앙그룹 회생 사태와 IPTV사의 대응"],
        ["실제 영향 규모", "비교 가능한 대응 사례"],
        purpose_id="issue_response",
    )

    assert needs[0].requirement_type == "direct"
    assert "대응" in needs[0].text
    assert all(need.priority <= 2 for need in needs)


def test_refiner_keeps_plan_when_existing_query_covers_need(monkeypatch):
    monkeypatch.setattr(refiner_module._solar, "call_json", lambda *args, **kwargs: None)
    plan = _plan("IPTV 가입자 수 현재 현황")

    refined = refiner_module.refine_search_plan(
        "IPTV 가입자 수 현황은?",
        plan,
        ["IPTV 가입자 수 현재 현황"],
        [],
    )

    assert refined.refinement.action == "KEEP"
    assert refined.refinement.added_queries == []
    assert [query.query for query in refined.queries] == ["IPTV 가입자 수 현재 현황"]


def test_refiner_never_rewrites_direct_query_and_respects_total_budget(monkeypatch):
    monkeypatch.setattr(
        refiner_module._solar,
        "call_json",
        lambda *args, **kwargs: {
            "action": "REWRITE",
            "rewrites": [{"replace_query": "직접 질의", "query": "삭제된 직접 질의"}],
            "add_queries": [
                {"query": "지원 질의 1", "evidence_need_ids": ["support-1"]},
                {"query": "지원 질의 2", "evidence_need_ids": ["support-1"]},
            ],
        },
    )
    refined = refiner_module.refine_search_plan(
        "질문",
        _plan("직접 질의", "두 번째 계획 질의"),
        ["직접 답변"],
        ["지원 근거"],
        max_total_queries=2,
    )

    assert refined.queries[0].query == "직접 질의"
    assert refined.queries[0].query_role == "direct"
    assert len(refined.queries) <= 2
    assert all(query.query != "삭제된 직접 질의" for query in refined.queries)


def test_router_requires_original_source_before_direct_sufficiency(monkeypatch):
    monkeypatch.setattr(planner_module, "plan_searches", lambda *args, **kwargs: _plan("직접 질의"))
    monkeypatch.setattr(refiner_module._solar, "call_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        web_search_module,
        "execute_web_search",
        lambda *args, **kwargs: [WebSearchResult(url="https://example.com/a", summary="snippet")],
    )
    coverage_calls = {"count": 0}

    def _coverage(*args, **kwargs):
        coverage_calls["count"] += 1
        return CoverageDecision(sufficient=True, reason="summary looked sufficient")

    monkeypatch.setattr(coverage_module, "check_coverage", _coverage)
    monkeypatch.setattr(
        router_module,
        "_inspect_source",
        lambda question, source, config: source.model_copy(update={
            "evidence_depth": "original_source",
            "original_content": "원문에서 직접 확인된 IPTV 가입자 수",
            "verification": EvidenceVerification(
                confirmed_facts=[ConfirmedFact(fact="IPTV 가입자 수", evidence_strength="direct")]
            ),
        }),
    )

    result = router_module.research(
        "IPTV 가입자 수 현황은?",
        SourceRouterConfig(max_gap_loop_iterations=2),
        answer_requirements=["현재 IPTV 가입자 현황"],
    )

    assert result.stop_reason == "sufficient"
    assert coverage_calls["count"] == 2
    assert result.results[0].original_content.startswith("원문")


def test_short_source_with_direct_verified_fact_is_not_rejected(monkeypatch):
    monkeypatch.setattr(router_module.html_extractor, "extract_html", lambda *args, **kwargs: "짧은 직접 근거 42%")
    monkeypatch.setattr(
        coverage_module,
        "verify_evidence",
        lambda *args, **kwargs: EvidenceVerification(
            confirmed_facts=[ConfirmedFact(fact="직접 근거 42%", evidence_strength="direct")]
        ),
    )
    source = WebSearchResult(url="https://example.com/short", title="short")

    inspected = router_module._inspect_html(
        "질문", source, SourceRouterConfig(min_content_length=250)
    )

    assert inspected is not None
    assert inspected.original_content == "짧은 직접 근거 42%"


def test_pdf_detection_reuses_shared_media_detector(monkeypatch):
    source = WebSearchResult(url="https://example.com/download.do?fileSeq=1", title="보고서")
    sentinel = source.model_copy(update={
        "evidence_depth": "original_source", "original_content": "pdf"
    })
    monkeypatch.setattr(router_module, "detect_document_media_type", lambda *args: "application/pdf")
    monkeypatch.setattr(router_module, "_inspect_pdf", lambda *args: sentinel)
    monkeypatch.setattr(
        router_module,
        "_inspect_html",
        lambda *args: (_ for _ in ()).throw(AssertionError("HTML path must not run")),
    )

    assert router_module._inspect_source("질문", source, SourceRouterConfig()) is sentinel


def test_registry_match_and_adapter_preserve_original_content_without_inventing_tier():
    registry = PlannedSource(
        name="공식 통계",
        url="https://data.example.com",
        reliability_tier="official",
    )
    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        registered_sources=[registry],
        search_context=WebSearchContext(question="질문"),
    )
    result = SourceRouterResult(
        question="질문",
        search_plan=_plan("질문"),
        results=[
            WebSearchResult(
                url="https://data.example.com/report",
                title="통계",
                evidence_depth="original_source",
                original_content="정확한 원문 42%",
                media_type="text/markdown",
                search_query="질문",
                query_role="direct",
                evidence_need_ids=["direct-1"],
            ),
            WebSearchResult(
                url="https://outside.example.org/a",
                title="외부",
                evidence_depth="original_source",
                original_content="외부 원문",
            ),
        ],
    )

    collection = source_router_result_to_collection(result, plan)

    assert match_registry_source("https://sub.data.example.com/x", [registry]) is registry
    assert collection.collection_mode == "source_router"
    assert collection.documents[0].source_id == "공식 통계"
    assert collection.documents[0].reliability_tier == "official"
    assert collection.documents[0].content == "정확한 원문 42%"
    assert collection.documents[1].reliability_tier is None
    assert collection.router_trace["sources"][0]["evidence_need_ids"] == ["direct-1"]


def test_markdown_table_preprocessing_repeats_only_exact_cells():
    content = "| 사업자 | 가입자 |\n|---|---:|\n| SKB | 100 |\n| KT | 120 |"

    rendered = semanticize_markdown_tables(content)

    assert "사업자=SKB; 가입자=100" in rendered
    assert "사업자=KT; 가입자=120" in rendered


def test_pipeline_collector_boundary_uses_source_router(monkeypatch):
    from sources.collectors.source_router import integration

    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        search_context=WebSearchContext(question="IPTV 가입자 수 현황은?"),
    )
    expected = SimpleNamespace(documents=[])
    monkeypatch.setattr(integration, "collect", lambda received: expected if received is plan else None)
    route = SectorRoute(
        request_id="req",
        sector_id="sk_broadband",
        status="routed",
        matched_profile=SectorProfile(
            sector_id="sk_broadband",
            display_name="SK Broadband",
            status="active",
            pipeline_entrypoint="sectors.sk_broadband.adapter",
        ),
    )

    assert pipeline_module._call_sector_adapter_stage(route, "collector", plan) is expected


# --- audit: what the coverage model is allowed to see --------------------


def test_coverage_check_never_resends_original_source_text(monkeypatch):
    """Original text is kept for the Analyzer, not re-billed to coverage.

    Retaining `original_content` on the result is what lets the Analyzer
    re-verify a passage later. Sending it back into the coverage prompt would
    duplicate the entire HTML/PDF body on every gap-loop round, which is the
    TPM failure this exclusion exists to prevent.
    """
    captured: dict = {}

    def _call_json(system_prompt, user_payload, **kwargs):
        captured["payload"] = user_payload
        return {"sufficient": True, "reason": "ok"}

    monkeypatch.setattr(coverage_module._solar, "call_json", _call_json)
    monkeypatch.setattr(coverage_module._prompts, "load", lambda name: "system")

    coverage_module.check_coverage(
        "질문",
        _plan("질의"),
        [
            WebSearchResult(
                url="https://example.com/a",
                summary="요약",
                evidence_depth="original_source",
                original_content="x" * 50_000,
            )
        ],
    )

    serialized = json.dumps(captured["payload"], ensure_ascii=False)
    assert "original_content" not in serialized
    assert "x" * 1_000 not in serialized
    # The compact judgment the coverage model actually needs is still there.
    assert captured["payload"]["results"][0]["evidence_depth"] == "original_source"


# --- audit: what counts as a satisfied DIRECT requirement ----------------


def _direct_plan() -> SearchPlan:
    return SearchPlan(
        intent="IPTV status",
        queries=[SearchPlanQuery(query="직접 질의", priority=1, query_role="direct",
                                 evidence_need_ids=["direct-1"])],
        evidence_needs=[
            EvidenceNeed(evidence_need_id="direct-1", text="현재 IPTV 가입자 수",
                         requirement_type="direct", priority=1)
        ],
    )


def _direct_result(**overrides) -> WebSearchResult:
    base = {
        "url": "https://example.com/a",
        "summary": "요약",
        "evidence_depth": "original_source",
        "original_content": "원문 텍스트",
        "query_role": "direct",
        "evidence_need_ids": ["direct-1"],
    }
    base.update(overrides)
    return WebSearchResult(**base)


def test_original_text_without_verification_does_not_satisfy_a_direct_need():
    decision = router_module._enforce_direct_original_sources(
        CoverageDecision(sufficient=True, reason="looked fine"),
        _direct_plan(),
        [_direct_result(verification=None)],
        set(),
    )

    assert decision.sufficient is False
    assert any("direct-1" in item for item in decision.missing)


def test_contextual_only_verification_does_not_satisfy_a_direct_need():
    """A page that merely discusses the topic is not the figure being asked for."""
    decision = router_module._enforce_direct_original_sources(
        CoverageDecision(sufficient=True, reason="looked fine"),
        _direct_plan(),
        [
            _direct_result(
                verification=EvidenceVerification(
                    confirmed_facts=[
                        ConfirmedFact(fact="IPTV 시장 언급", evidence_strength="contextual")
                    ]
                )
            )
        ],
        set(),
    )

    assert decision.sufficient is False


def test_direct_confirmed_fact_leaves_the_coverage_decision_untouched():
    original = CoverageDecision(sufficient=True, reason="verified")
    decision = router_module._enforce_direct_original_sources(
        original,
        _direct_plan(),
        [
            _direct_result(
                verification=EvidenceVerification(
                    confirmed_facts=[
                        ConfirmedFact(fact="가입자 946만 명", evidence_strength="direct")
                    ]
                )
            )
        ],
        set(),
    )

    assert decision is original


# --- audit: one budget covers planner, refiner and follow-up -------------


def test_every_search_call_shares_one_run_budget(monkeypatch):
    """Initial, refined and gap-loop queries draw on the same allowance.

    The prototype capped each tier separately, so a run could spend 15 + 15.
    Coverage here always reports a gap and always asks for more queries, so
    the loop only stops when the shared budget does.
    """
    calls: list[str] = []
    plan = SearchPlan(
        intent="비교",
        queries=[
            SearchPlanQuery(query=f"질의{index}", priority=1,
                            query_role="direct" if index < 3 else "supporting")
            for index in range(10)
        ],
    )
    monkeypatch.setattr(planner_module, "plan_searches", lambda *args, **kwargs: plan)
    monkeypatch.setattr(refiner_module._solar, "call_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *args, **kwargs: CoverageDecision(
            sufficient=False,
            reason="still missing",
            next_queries=[NextQuery(query="추가 질의", purpose="gap")],
        ),
    )

    def _search(query, **kwargs):
        calls.append(query)
        return [WebSearchResult(url=f"https://example.com/{len(calls)}", summary="요약")]

    monkeypatch.setattr(web_search_module, "execute_web_search", _search)

    config = SourceRouterConfig(max_web_search_calls=5, max_gap_loop_iterations=20)
    result = router_module.research("IPTV 가입자 비교 추이 대응 전략은?", config)

    assert len(calls) <= config.max_web_search_calls
    assert result.search_calls_used == len(calls)
    assert result.stop_reason in {"search_call_budget_exhausted", "max_rounds_reached",
                                  "no_new_results", "no_further_queries"}


# --- audit: the registry attributes, it does not gatekeep ----------------


def test_registry_matches_the_domain_it_owns_and_nothing_that_merely_looks_like_it():
    registry = PlannedSource(name="공식 통계", url="https://data.example.com",
                             reliability_tier="official")

    assert match_registry_source("https://data.example.com/a", [registry]) is registry
    assert match_registry_source("https://sub.data.example.com/a", [registry]) is registry
    # A different registrable domain that merely ends in the same letters.
    assert match_registry_source("https://fake-data.example.com/a", [registry]) is None
    assert match_registry_source("https://example.com/a", [registry]) is None


# --- audit: the router already bounds its own follow-up ------------------


def test_source_router_collection_switches_off_the_legacy_recollection_loops():
    """The router runs its own bounded gap loop, so the pipeline must not add
    a second search loop on top of the first."""
    collection = source_router_result_to_collection(
        SourceRouterResult(
            question="질문",
            search_plan=_plan("질의"),
            results=[
                WebSearchResult(
                    url="https://example.com/a",
                    evidence_depth="original_source",
                    original_content="원문",
                )
            ],
        ),
        SourcePlan(request_id="req", sector_id="sk_broadband",
                   search_context=WebSearchContext(question="질문")),
    )

    # Validator: `minimum > 0` gates its recollection while-loop, so 0 turns
    # it off. The analyzer side is pinned behaviourally in
    # tests/test_request_pipeline.py::
    # test_source_router_collection_does_not_start_a_second_search_loop -
    # asserting on the pipeline's source text would keep passing after the
    # behaviour it describes was removed.
    assert collection.collection_mode == "source_router"
    assert collection.minimum_validated_documents == 0


def test_retrieval_failure_is_reported_as_retrieval_not_as_missing_evidence(monkeypatch):
    """Search worked, original-source retrieval did not.

    With the HTML/PDF fetch layer down or out of credit every inspection
    returns None, so no result reaches original-source depth and the
    collection is empty. Handing that back as an empty document list makes it
    surface three stages later as "no evidence", pointing at the question or
    the sources rather than at the fetch layer that actually failed.
    """
    from sources.collectors.source_router import integration

    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        search_context=WebSearchContext(question="IPTV 가입자 수 현황은?"),
    )
    monkeypatch.setattr(integration, "search_is_configured", lambda: True)
    monkeypatch.setattr(
        integration,
        "research",
        lambda *args, **kwargs: SourceRouterResult(
            question="IPTV 가입자 수 현황은?",
            search_plan=_plan("질의"),
            # Found by search, never read as an original source.
            results=[WebSearchResult(url="https://example.com/a", summary="요약")],
            search_calls_used=3,
        ),
    )

    with pytest.raises(PipelineStageError) as caught:
        integration.collect(plan)

    assert "retrieved 0 original sources" in caught.value.reason
    assert "Firecrawl" in caught.value.reason
    assert caught.value.stage == "sector_adapter.collector"


def test_a_verified_original_source_still_collects_normally(monkeypatch):
    from sources.collectors.source_router import integration

    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        search_context=WebSearchContext(question="질문"),
    )
    monkeypatch.setattr(integration, "search_is_configured", lambda: True)
    monkeypatch.setattr(
        integration,
        "research",
        lambda *args, **kwargs: SourceRouterResult(
            question="질문",
            search_plan=_plan("질의"),
            results=[
                WebSearchResult(
                    url="https://example.com/a",
                    evidence_depth="original_source",
                    original_content="원문 42%",
                )
            ],
        ),
    )

    collection = integration.collect(plan)

    assert [document.content for document in collection.documents] == ["원문 42%"]
