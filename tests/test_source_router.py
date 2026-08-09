"""Unit tests for the standalone Source Router (sources/collectors/
source_router/), doc1(final_research_router.md)-based, kept parallel to
sources/collectors/ai_search_harness.py. No real network/API calls — every
external boundary (Solar chat completions, GPT-5 mini web_search, Firecrawl,
Upstage Document Parse, PDF download) is faked or monkeypatched.
"""

from __future__ import annotations

import json
import types

from sources.collectors.source_router import _prompts as prompts_module
from sources.collectors.source_router import _solar as solar_module
from sources.collectors.source_router import coverage as coverage_module
from sources.collectors.source_router import pdf_parser
from sources.collectors.source_router import planner as planner_module
from sources.collectors.source_router import router as router_module
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    DocumentSection,
    SearchPlan,
    SearchPlanQuery,
    SourceToInspect,
    WebSearchResult,
)

# ---------------------------------------------------------------------------
# Fakes for the Solar-role JSON chat completion (_solar.call_json)
# ---------------------------------------------------------------------------


class _FakeChatCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("no more fake chat responses queued")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        message = types.SimpleNamespace(content=json.dumps(result, ensure_ascii=False))
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeChatCompletions(responses)


class _FakeSolarOpenAI:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


def _patch_solar(monkeypatch, responses, api_key="solar-test-key"):
    monkeypatch.setenv(solar_module.API_KEY_ENV_VAR, api_key)
    monkeypatch.setattr(solar_module, "OpenAI", lambda **_: _FakeSolarOpenAI(responses))


# ---------------------------------------------------------------------------
# Fakes for GPT-5 mini + web_search (web_search.execute_web_search)
# ---------------------------------------------------------------------------


class _FakeResponses:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("no more fake search responses queued")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeSearchOpenAI:
    def __init__(self, responses):
        self.responses = _FakeResponses(responses)


def _search_response(items: list[dict], grounded_urls: list[str]):
    blocks = [
        types.SimpleNamespace(annotations=[types.SimpleNamespace(type="url_citation", url=url, title="t")])
        for url in grounded_urls
    ]
    message_item = types.SimpleNamespace(type="message", content=blocks)
    return types.SimpleNamespace(
        output=[message_item], output_text=json.dumps(items, ensure_ascii=False)
    )


def _patch_web_search(monkeypatch, responses, api_key="search-test-key"):
    monkeypatch.setenv(web_search_module._API_KEY_ENV_VAR, api_key)
    monkeypatch.setattr(web_search_module, "OpenAI", lambda **_: _FakeSearchOpenAI(responses))


# ---------------------------------------------------------------------------
# _prompts.py — external .md prompt files, one per Solar-role stage
# ---------------------------------------------------------------------------


def test_prompts_load_returns_non_empty_text_for_every_stage():
    for name in [
        "planner",
        "coverage",
        "evidence_extraction",
        "section_selection",
        "chunk_selection",
    ]:
        assert prompts_module.load(name).strip()


# ---------------------------------------------------------------------------
# planner.py
# ---------------------------------------------------------------------------


def test_plan_searches_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)

    plan = planner_module.plan_searches("HBM 시장 전망은?")

    assert len(plan.queries) == 1
    assert plan.queries[0].query == "HBM 시장 전망은?"
    assert plan.queries[0].priority == 1


def test_plan_searches_uses_ai_output_when_configured(monkeypatch):
    _patch_solar(
        monkeypatch,
        [
            {
                "intent": "HBM 시장 전망",
                "queries": [
                    {"query": "HBM market size 2026", "angle": "market", "purpose": "size", "priority": 1},
                    {"query": "SK hynix HBM capex", "angle": "company", "purpose": "capability", "priority": 2},
                ],
            }
        ],
    )

    plan = planner_module.plan_searches("HBM 시장 전망은?")

    assert [q.priority for q in plan.queries] == [1, 2]
    assert plan.by_priority(1)[0].query == "HBM market size 2026"


def test_plan_searches_falls_back_on_call_failure(monkeypatch):
    monkeypatch.setenv(solar_module.API_KEY_ENV_VAR, "key")
    monkeypatch.setattr(
        solar_module, "OpenAI", lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    plan = planner_module.plan_searches("질문")

    assert len(plan.queries) == 1
    assert plan.queries[0].purpose == "fallback"


# ---------------------------------------------------------------------------
# web_search.py
# ---------------------------------------------------------------------------


def test_execute_web_search_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv(web_search_module._API_KEY_ENV_VAR, raising=False)

    assert web_search_module.execute_web_search("HBM market size") == []


def test_execute_web_search_only_trusts_grounded_urls(monkeypatch):
    items = [
        {"url": "https://real.example.com/a", "title": "A", "summary": "s", "key_facts": [], "relevance": "r"},
        {"url": "https://fabricated.example.com/b", "title": "B", "summary": "s", "key_facts": [], "relevance": "r"},
    ]
    _patch_web_search(monkeypatch, [_search_response(items, ["https://real.example.com/a"])])

    results = web_search_module.execute_web_search("query")

    assert [r.url for r in results] == ["https://real.example.com/a"]
    assert results[0].evidence_depth == "search_summary"


def test_execute_web_search_parses_key_facts(monkeypatch):
    items = [
        {
            "url": "https://real.example.com/a",
            "title": "A",
            "summary": "s",
            "key_facts": [
                {"text": "HBM market $41B in 2026", "metric": "HBM market size", "value": 41, "unit": "USD billion", "time": "2026", "value_type": "forecast"}
            ],
            "relevance": "r",
        }
    ]
    _patch_web_search(monkeypatch, [_search_response(items, ["https://real.example.com/a"])])

    results = web_search_module.execute_web_search("query")

    assert results[0].key_facts[0].value == 41
    assert results[0].key_facts[0].value_type == "forecast"


# ---------------------------------------------------------------------------
# coverage.py
# ---------------------------------------------------------------------------


def _result(url="https://a.example.com", summary="something") -> WebSearchResult:
    return WebSearchResult(url=url, summary=summary)


def test_check_coverage_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result(), _result("https://b.example.com")])

    assert decision.sufficient is True
    assert decision.needs_full_text is False


def test_check_coverage_rejects_uninvented_inspect_url(monkeypatch):
    _patch_solar(
        monkeypatch,
        [
            {
                "sufficient": False,
                "needs_full_text": True,
                "sources_to_inspect": [
                    {"url": "https://not-in-results.example.com", "reason": "fabricated"},
                ],
                "next_queries": [],
            }
        ],
    )
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result()])

    assert decision.sources_to_inspect == []
    assert decision.needs_full_text is False  # forced false — no valid source survived


def test_check_coverage_accepts_valid_inspect_url(monkeypatch):
    _patch_solar(
        monkeypatch,
        [
            {
                "sufficient": False,
                "semantic_sufficient": True,
                "structural_sufficient": False,
                "needs_full_text": True,
                "sources_to_inspect": [{"url": "https://a.example.com", "reason": "need numbers"}],
                "next_queries": [],
            }
        ],
    )
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result()])

    assert decision.needs_full_text is True
    assert decision.sources_to_inspect[0].url == "https://a.example.com"
    assert decision.structural_sufficient is False


def test_extract_key_facts_empty_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)

    assert coverage_module.extract_key_facts("질문", "본문") == []


# ---------------------------------------------------------------------------
# pdf_parser.py — size routing, chunking, selection fallback
# ---------------------------------------------------------------------------


def test_classify_size():
    assert pdf_parser.classify_size(10_000, 25_000, 80_000) == "small"
    assert pdf_parser.classify_size(50_000, 25_000, 80_000) == "large"
    assert pdf_parser.classify_size(100_000, 25_000, 80_000) == "huge"


def test_build_chunk_map_splits_long_section():
    section = DocumentSection(
        section_id="S1",
        title="Results",
        full_text="\n".join(f"paragraph {i} " * 50 for i in range(20)),
    )

    chunks = pdf_parser.build_chunk_map(section, chars_per_token_estimate=2.0, target_chunk_tokens=200)

    assert len(chunks) > 1
    assert all(chunk.section_id == "S1" for chunk in chunks)
    assert chunks[0].chunk_id == "S1-C1"


def test_select_sections_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)
    sections = [
        DocumentSection(section_id="S1", title="Intro"),
        DocumentSection(section_id="S2", title="Methodology"),
        DocumentSection(section_id="S3", title="Results"),
    ]

    selected = pdf_parser.select_sections("질문", sections, max_sections=2)

    assert selected == ["S1", "S2"]


def test_select_sections_rejects_hallucinated_id(monkeypatch):
    _patch_solar(
        monkeypatch,
        [{"selected_sections": [{"section_id": "S99", "reason": "fake"}]}],
    )
    sections = [DocumentSection(section_id="S1", title="Intro")]

    selected = pdf_parser.select_sections("질문", sections)

    assert selected == ["S1"]  # invalid id dropped -> falls back to document order


# ---------------------------------------------------------------------------
# router.py — orchestration, monkeypatching this package's own module
# functions directly (simpler and just as faithful as mocking three layers
# of OpenAI clients for pure control-flow assertions).
# ---------------------------------------------------------------------------


def _plan(*queries_by_priority: tuple[str, int]) -> SearchPlan:
    return SearchPlan(
        intent="질문",
        queries=[SearchPlanQuery(query=q, priority=p) for q, p in queries_by_priority],
    )


def test_research_stops_when_sufficient_after_priority1(monkeypatch):
    plan = _plan(("q1", 1), ("q2", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(
        web_search_module,
        "execute_web_search",
        lambda query, **_: [_result(f"https://a.example.com/{query}")],
    )
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=True, reason="enough"),
    )

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "sufficient"
    assert result.rounds_completed == 1
    assert len(result.results) == 2


def test_research_runs_priority2_after_insufficient_then_stops(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)

    call_count = {"n": 0}

    def _fake_search(query, **_):
        call_count["n"] += 1
        return [_result(f"https://a.example.com/{call_count['n']}")]

    monkeypatch.setattr(web_search_module, "execute_web_search", _fake_search)

    decisions = [
        CoverageDecision(sufficient=False, next_queries=["q2"], reason="gap"),
        CoverageDecision(sufficient=True, reason="now enough"),
    ]

    def _fake_coverage(*a, **k):
        return decisions.pop(0)

    monkeypatch.setattr(coverage_module, "check_coverage", _fake_coverage)

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "sufficient"
    assert result.rounds_completed == 2
    assert call_count["n"] == 2  # priority-1 once, next_queries once


def test_research_inspects_source_when_needs_full_text(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(
        web_search_module,
        "execute_web_search",
        lambda query, **_: [_result("https://a.example.com")],
    )

    decisions = [
        CoverageDecision(
            sufficient=False,
            needs_full_text=True,
            sources_to_inspect=[SourceToInspect(url="https://a.example.com", reason="need numbers")],
            reason="gap",
        ),
        CoverageDecision(sufficient=True, reason="now enough"),
    ]
    monkeypatch.setattr(coverage_module, "check_coverage", lambda *a, **k: decisions.pop(0))
    monkeypatch.setattr(
        router_module.html_extractor, "extract_html", lambda url, **_: "실제 원문 내용 " * 30
    )
    monkeypatch.setattr(coverage_module, "extract_key_facts", lambda *a, **k: [])

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "sufficient"
    inspected = next(r for r in result.results if r.url == "https://a.example.com")
    assert inspected.evidence_depth == "original_source"


def test_research_stops_no_new_information_when_next_queries_yield_nothing(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **_: [])
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=["q2"], reason="gap"),
    )

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "no_new_information"


def test_research_stops_at_budget_exhausted_when_never_sufficient(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)

    counter = {"n": 0}

    def _fake_search(query, **_):
        counter["n"] += 1
        return [_result(f"https://a.example.com/{counter['n']}")]

    monkeypatch.setattr(web_search_module, "execute_web_search", _fake_search)
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=["q-next"], reason="never enough"),
    )

    config = SourceRouterConfig(max_gap_loop_iterations=2, max_web_search_calls=10)
    result = router_module.research("질문", config)

    assert result.stop_reason == "budget_exhausted"
    assert result.rounds_completed == 2


def test_research_never_exceeds_max_web_search_calls(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)

    counter = {"n": 0}

    def _fake_search(query, **_):
        counter["n"] += 1
        return [_result(f"https://a.example.com/{counter['n']}")]

    monkeypatch.setattr(web_search_module, "execute_web_search", _fake_search)
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=["q-next"], reason="never enough"),
    )

    config = SourceRouterConfig(max_gap_loop_iterations=10, max_web_search_calls=3)
    router_module.research("질문", config)

    assert counter["n"] <= 3
