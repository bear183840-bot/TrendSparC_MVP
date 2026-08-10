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
from sources.collectors.source_router import question_type_ai_based
from sources.collectors.source_router import question_type_classifier
from sources.collectors.source_router import router as router_module
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    ConfirmedFact,
    DocumentChunk,
    DocumentSection,
    EvidenceNeed,
    EvidenceVerification,
    NextQuery,
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
        "planner_common_head",
        "planner_common_tail",
        "planner_purposes/current_status",
        "planner_purposes/issue_response",
        "planner_purposes/future_business",
        "planner_purposes/root_cause",
        "planner_audiences/practitioner",
        "planner_audiences/executive",
        "planner_audiences/management",
        "planner_audiences/external",
        "coverage",
        "evidence_extraction",
        "section_selection",
        "chunk_selection",
    ]:
        assert prompts_module.load(name).strip()


# ---------------------------------------------------------------------------
# planner.md content invariants — regression guard for the audience/
# purpose_id STEP 2.5/2.6/2.7 refactor (this file's first prompt-text
# invariant test, same spirit as tests/test_prompt_invariants.py for the
# main pipeline's prompts). planner.md itself no longer exists — it was
# split into prompts/planner_common_head.md, prompts/planner_purposes/*.md,
# prompts/planner_audiences/*.md and prompts/planner_common_tail.md (see
# planner_module._assemble_system_prompt). Calling
# `_assemble_system_prompt(purpose_id=None, purpose_confidence=None,
# audience=None)` reproduces the old "send everything" behavior these tests
# were written against, so they migrate with no behavioral change.
# ---------------------------------------------------------------------------


def _full_planner_prompt() -> str:
    return planner_module._assemble_system_prompt(None, None, None)


def test_planner_prompt_preserves_step2_candidate_dimensions():
    """STEP 2's general candidate-angle list must survive the STEP 2.5/2.6/
    2.7 insertion untouched - this feature adds axes, it must not narrow
    the ones already there. (2026-08-10: planner_common_head.md replaced
    with a Korean translation - dimensions checked in Korean now.)"""
    text = _full_planner_prompt()
    for dimension in [
        "공식 / 1차 자료",
        "직접 비교",
        "정량 데이터",
        "독립 평가",
        "비판 / 반대 근거",
    ]:
        assert dimension in text


def test_planner_prompt_preserves_strategy_response_subitems_after_move_into_step25():
    """The former standalone "Strategy / Response / Recommendation
    Questions" section's 6 sub-items were moved into STEP 2.5's
    issue_response branch, not deleted."""
    text = _full_planner_prompt()
    for heading in [
        "Current factual state",
        "Affected relationships and dependencies",
        "Applicable regulatory, legal, contractual, or policy framework",
        "Operational and financial risks",
        "Precedents or comparable cases, when useful",
        "Evidence needed to derive actionable recommendations",
    ]:
        assert heading in text


def test_planner_prompt_documents_audience_and_purpose_id_inputs():
    text = _full_planner_prompt()
    assert "audience" in text
    assert "purpose_id" in text
    assert "STEP 2.5" in text
    assert "STEP 2.6" in text
    assert "STEP 2.7" in text


# ---------------------------------------------------------------------------
# planner.py — _assemble_system_prompt / _pick_branch_ids / _pick_audience_ids
# cut-and-assemble behavior (the actual cutting, not just "is this text
# present somewhere" as the migrated invariants above check).
# ---------------------------------------------------------------------------


def test_assemble_system_prompt_sends_only_the_confident_purpose_branch():
    text = planner_module._assemble_system_prompt("current_status", "high", None)

    assert "current_status" in text
    assert "Snapshot → Trend → Comparison" in text  # current_status's own narrative arc
    for other_marker in [
        "Applicable regulatory, legal, contractual, or policy framework",  # issue_response
        "Current Position → Future Change",  # future_business
        "Problem Evidence → Cause Structure",  # root_cause
    ]:
        assert other_marker not in text


def test_assemble_system_prompt_falls_back_to_all_purposes_when_confidence_low():
    text = planner_module._assemble_system_prompt("current_status", "low", None)

    for marker in [
        "Snapshot → Trend → Comparison",
        "Applicable regulatory, legal, contractual, or policy framework",
        "Current Position → Future Change",
        "Problem Evidence → Cause Structure",
    ]:
        assert marker in text


def test_assemble_system_prompt_falls_back_to_all_purposes_when_unclassified():
    text = planner_module._assemble_system_prompt(None, None, None)

    for marker in [
        "Snapshot → Trend → Comparison",
        "Applicable regulatory, legal, contractual, or policy framework",
        "Current Position → Future Change",
        "Problem Evidence → Cause Structure",
    ]:
        assert marker in text


def test_assemble_system_prompt_sends_only_the_selected_audience_branch():
    text = planner_module._assemble_system_prompt(None, None, "practitioner")

    assert "practitioner — focus: HOW" in text
    for other_marker in [
        "executive — focus: IMPACT & PRIORITY",
        "management — focus: DECISION & STRATEGY",
        "external — focus: WHAT & WHY",
    ]:
        assert other_marker not in text


def test_assemble_system_prompt_omits_audience_section_entirely_when_unset():
    text = planner_module._assemble_system_prompt(None, None, None)

    for marker in [
        "practitioner — focus: HOW",
        "executive — focus: IMPACT & PRIORITY",
        "management — focus: DECISION & STRATEGY",
        "external — focus: WHAT & WHY",
    ]:
        assert marker not in text


# question_type (Troubleshooting/Navigating/Investigating/Sensing) cutting -
# same _pick_branch_ids-driven behavior as purpose_id above, one marker
# string per prompts/planner_question_types/*.md file.
_QUESTION_TYPE_MARKERS = {
    "troubleshooting": "문제의 실체 → 영향 범위 → 대응 가능한 수단 → 실제 대응 사례 → 중장기 대응 방향",
    "navigating": "평가기준 정의 → 후보 탐색 → 후보별 정량/정성 근거 → 성공 사례 → 비교 → 추천 근거 확보",
    "investigating": "현상 확인 → 가능한 원인/요인 탐색 → 정량 근거 → 대상 집단별 차이 → 관계/효과 검증 → 설명 가능한 결론",
    "sensing": "현재 상태 → 과거 대비 변화 → 규모/이용률 → 세그먼트별 차이 → 주요 트렌드 → 최근 변화",
}


def test_assemble_system_prompt_sends_only_the_confident_question_type_branch():
    text = planner_module._assemble_system_prompt(None, None, None, "troubleshooting", "high")

    assert _QUESTION_TYPE_MARKERS["troubleshooting"] in text
    for type_id in ("navigating", "investigating", "sensing"):
        assert _QUESTION_TYPE_MARKERS[type_id] not in text


def test_assemble_system_prompt_falls_back_to_all_question_types_when_confidence_low():
    text = planner_module._assemble_system_prompt(None, None, None, "troubleshooting", "low")

    for marker in _QUESTION_TYPE_MARKERS.values():
        assert marker in text


def test_assemble_system_prompt_falls_back_to_all_question_types_when_unclassified():
    text = planner_module._assemble_system_prompt(None, None, None, None, None)

    for marker in _QUESTION_TYPE_MARKERS.values():
        assert marker in text


def test_assemble_system_prompt_places_question_type_branch_before_purpose_and_audience():
    """question_type was designed as a co-equal 1st-pass generator alongside
    STEP 2 (in planner_common_head.md), not a 2nd-pass refinement like
    purpose_id/audience - so its text must sit between head and the
    purpose/audience branches, not after them."""
    text = planner_module._assemble_system_prompt(
        "current_status", "high", "practitioner", "troubleshooting", "high"
    )

    head_pos = text.index("STEP 2 — candidate search angle 생성")
    question_type_pos = text.index(_QUESTION_TYPE_MARKERS["troubleshooting"])
    purpose_pos = text.index("Snapshot → Trend → Comparison")
    audience_pos = text.index("practitioner — focus: HOW")

    assert head_pos < question_type_pos < purpose_pos < audience_pos


# ---------------------------------------------------------------------------
# _solar.py — shared Solar Pro 3 JSON-chat helper
# ---------------------------------------------------------------------------


def test_call_json_uses_cancellable_sdk_timeout_without_background_retry(monkeypatch):
    captured = {}
    response = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"ok": true}'))]
    )

    class _FakeOpenAI:
        def __init__(self):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **_: response)
            )

    def _fake_openai(**kwargs):
        captured.update(kwargs)
        return _FakeOpenAI()

    monkeypatch.setenv(solar_module.API_KEY_ENV_VAR, "solar-test-key")
    monkeypatch.setattr(solar_module, "OpenAI", _fake_openai)
    result = solar_module.call_json("system prompt", {"q": "x"}, caller="test", timeout_seconds=0.2)

    assert result == {"ok": True}
    assert captured["timeout"] == 0.2
    assert captured["max_retries"] == 0


# ---------------------------------------------------------------------------
# planner.py
# ---------------------------------------------------------------------------


def test_plan_searches_forwards_timeout_seconds_to_solar(monkeypatch):
    """2026-08-09 fix: config.call_timeout_seconds used to never reach this
    call site — plan_searches() always used call_json's hardcoded 30s
    default regardless of what SourceRouterConfig said."""
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["timeout_seconds"] = timeout_seconds
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    planner_module.plan_searches("질문", timeout_seconds=77)

    assert captured["timeout_seconds"] == 77


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


def test_apply_quoting_wraps_each_key_term_found_in_query():
    result = planner_module._apply_quoting(
        "방송통신위원회 중앙그룹 프로그램 사용료 가이드라인", ["중앙그룹", "프로그램 사용료"]
    )

    assert result == '방송통신위원회 "중앙그룹" "프로그램 사용료" 가이드라인'


def test_apply_quoting_skips_term_the_model_already_quoted():
    result = planner_module._apply_quoting('방송통신위원회 "중앙그룹" 가이드라인', ["중앙그룹"])

    assert result == '방송통신위원회 "중앙그룹" 가이드라인'  # not double-quoted


def test_apply_quoting_ignores_key_term_not_actually_used_in_query():
    result = planner_module._apply_quoting("방송통신위원회 가이드라인", ["중앙그룹"])

    assert result == "방송통신위원회 가이드라인"  # nothing to insert out of context


def test_plan_searches_applies_quoting_from_model_supplied_key_terms(monkeypatch):
    """2026-08-09 fix: live testing showed the model reliably identifies key
    terms but unreliably remembers to quote them itself inside `query` - so
    quoting is now applied mechanically in code from a separate key_terms
    list, not trusted to the model's own formatting."""
    _patch_solar(
        monkeypatch,
        [
            {
                "intent": "중앙그룹 회생 사태",
                "queries": [
                    {
                        "query": "방송통신위원회 중앙그룹 프로그램 사용료 가이드라인",
                        "angle": "regulatory",
                        "purpose": "확인",
                        "priority": 1,
                        "key_terms": ["중앙그룹", "프로그램 사용료"],
                    }
                ],
            }
        ],
    )

    plan = planner_module.plan_searches("중앙그룹 회생 사태에 따른 IPTV사의 대응 방안")

    assert plan.queries[0].query == '방송통신위원회 "중앙그룹" "프로그램 사용료" 가이드라인'
    assert plan.queries[0].key_terms == ["중앙그룹", "프로그램 사용료"]


def test_plan_searches_sends_unspecified_and_infer_defaults_in_payload(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured.update(payload)
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    planner_module.plan_searches("질문")

    assert captured["audience"] == "unspecified"
    assert captured["purpose_id"] == "infer"


def test_plan_searches_forwards_given_audience_and_purpose_id_in_payload(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured.update(payload)
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    planner_module.plan_searches("질문", audience="executive", purpose_id="issue_response")

    assert captured["audience"] == "executive"
    assert captured["purpose_id"] == "issue_response"


def test_plan_searches_confident_purpose_sends_only_that_branch_to_solar(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["system_prompt"] = system_prompt
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    planner_module.plan_searches("질문", purpose_id="current_status", purpose_confidence="high")

    assert "Snapshot → Trend → Comparison" in captured["system_prompt"]
    assert "Applicable regulatory, legal, contractual, or policy framework" not in captured["system_prompt"]


def test_plan_searches_low_confidence_sends_all_purpose_branches_to_solar(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["system_prompt"] = system_prompt
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    planner_module.plan_searches("질문", purpose_id="current_status", purpose_confidence="low")

    assert "Applicable regulatory, legal, contractual, or policy framework" in captured["system_prompt"]


def test_plan_searches_classifies_question_type_and_cuts_branch_to_solar(monkeypatch):
    """Wiring regression: plan_searches() must actually call
    classify_question_type -> refine_question_type_ai (question_type is
    computed locally, never passed in by a caller - see plan_searches'
    docstring) and feed the result into _assemble_system_prompt so only the
    matching question_type branch reaches the model."""
    captured = {}

    def _fake_classify(question):
        captured["classify_input"] = question
        return (None, "low")

    def _fake_refine(rule_based_result, question, *, model_override=None, timeout_seconds=30):
        captured["refine_input"] = (rule_based_result, question)
        return ("sensing", "high")

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["system_prompt"] = system_prompt
        return None

    monkeypatch.setattr(planner_module, "classify_question_type", _fake_classify)
    monkeypatch.setattr(planner_module, "refine_question_type_ai", _fake_refine)
    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    planner_module.plan_searches("질문")

    assert captured["classify_input"] == "질문"
    assert captured["refine_input"] == ((None, "low"), "질문")
    assert _QUESTION_TYPE_MARKERS["sensing"] in captured["system_prompt"]
    assert _QUESTION_TYPE_MARKERS["troubleshooting"] not in captured["system_prompt"]


def _plan_response(**overrides):
    base = {
        "intent": "질문",
        "queries": [{"query": "쿼리", "angle": "a", "purpose": "p", "priority": 1}],
    }
    base.update(overrides)
    return base


def test_plan_searches_keeps_explicit_purpose_id_over_model_resolved_value(monkeypatch):
    """A caller-supplied purpose_id (already classified upstream by
    core/report_purpose/classifier.py) is more trustworthy than the
    planner's own guess - resolved_purpose_id must never override it."""
    _patch_solar(monkeypatch, [_plan_response(resolved_purpose_id="root_cause")])

    plan = planner_module.plan_searches("질문", purpose_id="issue_response")

    assert plan.purpose_id == "issue_response"


def test_plan_searches_clamps_model_resolved_purpose_id_when_not_given(monkeypatch):
    _patch_solar(monkeypatch, [_plan_response(resolved_purpose_id="current_status")])

    plan = planner_module.plan_searches("질문")

    assert plan.purpose_id == "current_status"


def test_plan_searches_rejects_invalid_model_resolved_purpose_id(monkeypatch):
    _patch_solar(monkeypatch, [_plan_response(resolved_purpose_id="not_a_real_purpose")])

    plan = planner_module.plan_searches("질문")

    assert plan.purpose_id is None


def test_plan_searches_echoes_audience_ignoring_model_output(monkeypatch):
    """audience is never inferred by the model - only echoed from the
    caller-supplied value, regardless of what (if anything) the response
    contains."""
    _patch_solar(monkeypatch, [_plan_response()])

    plan = planner_module.plan_searches("질문", audience="practitioner")

    assert plan.audience == "practitioner"


def test_plan_searches_fallback_carries_audience_and_purpose_id(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)

    plan = planner_module.plan_searches(
        "HBM 시장 전망은?", audience="management", purpose_id="future_business"
    )

    assert plan.audience == "management"
    assert plan.purpose_id == "future_business"


def test_plan_searches_caps_quoted_key_terms_at_two(monkeypatch):
    """Live-verified 2026-08-10: a query quoting 5 key_terms ("20대" "30대"
    "40대" "TV광고" "IPTV 광고 효과") returned almost nothing across 8 search
    calls, because web search treats multiple quoted phrases as roughly an
    AND. Only the first 2 key_terms may be quoted, regardless of how many
    the model names."""
    _patch_solar(
        monkeypatch,
        [
            {
                "intent": "질문",
                "queries": [
                    {
                        "query": "20대 30대 40대 TV광고 선호 매체 IPTV 광고 효과",
                        "angle": "a",
                        "purpose": "p",
                        "priority": 1,
                        "key_terms": ["20대", "30대", "40대", "TV광고", "IPTV 광고 효과"],
                    }
                ],
            }
        ],
    )

    plan = planner_module.plan_searches("질문")

    assert plan.queries[0].key_terms == ["20대", "30대"]
    assert plan.queries[0].query == '"20대" "30대" 40대 TV광고 선호 매체 IPTV 광고 효과'


def test_plan_searches_keeps_key_terms_at_or_below_cap_unaffected(monkeypatch):
    _patch_solar(
        monkeypatch,
        [
            {
                "intent": "질문",
                "queries": [
                    {
                        "query": "방송통신위원회 중앙그룹 프로그램 사용료 가이드라인",
                        "angle": "regulatory",
                        "purpose": "확인",
                        "priority": 1,
                        "key_terms": ["중앙그룹", "프로그램 사용료"],
                    }
                ],
            }
        ],
    )

    plan = planner_module.plan_searches("질문")

    assert plan.queries[0].key_terms == ["중앙그룹", "프로그램 사용료"]
    assert plan.queries[0].query == '방송통신위원회 "중앙그룹" "프로그램 사용료" 가이드라인'


def test_planner_prompt_documents_key_terms_cap_and_segment_splitting():
    text = prompts_module.load("planner_common_tail")
    assert "최대 2개" in text
    assert "segment별로 query를 생성" in text


def test_planner_prompt_documents_quantitative_benchmark_institution_queries():
    """Added after comparing this planner's queries against a human
    analyst's manual research for a media/ad-model recommendation question -
    the human anchored on named benchmark providers (reach %, reputation
    index, rate cards) instead of generic phrasing; this section teaches the
    same named-provider + precise-metric pattern already proven by the
    Regulatory / institutional terminology queries section above it.

    2026-08-10: tail replaced with a Korean-translated, generalized version
    - the concrete real institution names (KISDI, 코바코, 닐슨미디어코리아,
    etc.) were themselves only ever relevant to one of this shared engine's
    five sectors (broadcast/media), so generalizing them to placeholder
    names loses nothing sector-agnostic; this test now checks the pattern
    itself survived rather than any one sector's specific institution
    names."""
    text = prompts_module.load("planner_common_tail")
    assert "Quantitative benchmark" in text
    assert "리서치기관" in text and "규제기관" in text
    assert "그럴듯해 보이는 index나 institution name을 만들어내지 마십시오" in text


def test_coverage_prompt_documents_entity_anchored_followup():
    """First prompt-text invariant test for coverage.md (parallel to the
    planner.md ones above). Same comparison against a human analyst's manual
    research: a broad discovery search found a specific named candidate, and
    the human's next queries anchored on that literal name instead of
    repeating the same broad search - this step teaches check_coverage() to
    do the same via the existing next_queries mechanism, without letting it
    crowd out ordinary missing_information gaps (router.py takes only the
    first `max_priority2_queries` of next_queries, in returned order)."""
    text = prompts_module.load("coverage")
    assert "newly-discovered named candidates" in text
    assert "does not override STEP 6" in text.replace("**", "")
    assert "does not by itself obligate a dedicated query" in text


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


def test_execute_web_search_truncates_to_max_urls_even_if_model_ignores_the_prompt(monkeypatch):
    """Cost guard: the prompt asks for at most `max_urls`, but a model that
    ignores it must not be able to blow up this call's output size or the
    router's accumulated results pool downstream."""
    urls = [f"https://real.example.com/{i}" for i in range(5)]
    items = [
        {"url": url, "title": "t", "summary": "s", "key_facts": [], "relevance": "r"} for url in urls
    ]
    _patch_web_search(monkeypatch, [_search_response(items, urls)])

    results = web_search_module.execute_web_search("query", max_urls=2)

    assert len(results) == 2


def test_execute_web_search_coerces_approximate_text_value_instead_of_crashing(monkeypatch):
    """2026-08-09 live bug: a full-budget run crashed with a pydantic
    ValidationError because the model wrote a key_fact value as approximate
    text ("약 500") instead of a bare number, and KeyFact.value is a strict
    float. The whole search call - and every other result alongside it -
    must not be lost to one malformed fact."""
    url = "https://real.example.com/a"
    items = [
        {
            "url": url,
            "title": "t",
            "summary": "s",
            "relevance": "r",
            "key_facts": [{"text": "대출 규모", "value": "약 500", "unit": "억원"}],
        }
    ]
    _patch_web_search(monkeypatch, [_search_response(items, [url])])

    results = web_search_module.execute_web_search("query")

    assert len(results) == 1
    assert results[0].key_facts[0].value == 500.0


def test_execute_web_search_key_fact_value_none_when_no_number_present(monkeypatch):
    url = "https://real.example.com/b"
    items = [
        {
            "url": url,
            "title": "t",
            "summary": "s",
            "relevance": "r",
            "key_facts": [{"text": "정확한 규모 미상", "value": "미공개"}],
        }
    ]
    _patch_web_search(monkeypatch, [_search_response(items, [url])])

    results = web_search_module.execute_web_search("query")

    assert results[0].key_facts[0].value is None


def test_execute_web_search_handles_call_exception_gracefully(monkeypatch):
    _patch_web_search(monkeypatch, [RuntimeError("boom")])

    assert web_search_module.execute_web_search("query") == []


def test_execute_web_search_uses_cancellable_sdk_timeout_without_retry(monkeypatch):
    captured = {}
    response = _search_response([], [])

    class _FakeOpenAI:
        def __init__(self):
            self.responses = types.SimpleNamespace(create=lambda **_: response)

    def _fake_openai(**kwargs):
        captured.update(kwargs)
        return _FakeOpenAI()

    monkeypatch.setenv(web_search_module._API_KEY_ENV_VAR, "search-test-key")
    monkeypatch.setattr(web_search_module, "OpenAI", _fake_openai)
    results = web_search_module.execute_web_search("query", timeout_seconds=0.2)

    assert results == []
    assert captured["timeout"] == 0.2
    assert captured["max_retries"] == 0


# ---------------------------------------------------------------------------
# coverage.py
# ---------------------------------------------------------------------------


def _result(url="https://a.example.com", summary="something") -> WebSearchResult:
    return WebSearchResult(url=url, summary=summary)


def test_check_coverage_forwards_timeout_seconds_to_solar(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["timeout_seconds"] = timeout_seconds
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    coverage_module.check_coverage("질문", plan, [_result()], timeout_seconds=77)

    assert captured["timeout_seconds"] == 77


def test_verify_evidence_forwards_timeout_seconds_to_solar(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["timeout_seconds"] = timeout_seconds
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)

    coverage_module.verify_evidence("질문", "본문", url="https://a.example.com", timeout_seconds=77)

    assert captured["timeout_seconds"] == 77


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


def test_check_coverage_parses_new_prompt_b_structure(monkeypatch):
    """Real prompt B (coverage.md, replaced 2026-08-09) shape: covered_
    information/missing_information (not covered/missing), per-aspect
    coverage[], contradictions[], and object-shaped next_queries. Every
    "covered" claim here cites a real result URL, so grounding passes."""
    _patch_solar(
        monkeypatch,
        [
            {
                "sufficient": False,
                "coverage": [
                    {
                        "aspect": "market size",
                        "status": "covered",
                        "reason": "found 3 reports",
                        "source_urls": ["https://a.example.com"],
                    },
                    {"aspect": "competitor share", "status": "missing", "reason": "not found"},
                ],
                "covered_information": [
                    {"text": "market size", "source_urls": ["https://a.example.com"]}
                ],
                "missing_information": ["competitor share"],
                "contradictions": [
                    {"issue": "conflicting revenue figures", "sources": ["https://a.example.com"], "needs_resolution": True}
                ],
                "needs_full_text": False,
                "sources_to_inspect": [],
                "next_queries": [
                    {"query": "competitor market share 2026", "purpose": "fill the gap", "priority": 1}
                ],
            }
        ],
    )
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result()])

    assert [aspect.status for aspect in decision.coverage] == ["covered", "missing"]
    assert decision.covered[0].text == "market size"
    assert decision.covered[0].source_urls == ["https://a.example.com"]
    assert decision.missing == ["competitor share"]
    assert decision.contradictions[0].issue == "conflicting revenue figures"
    assert decision.next_queries[0].query == "competitor market share 2026"
    assert decision.next_queries[0].priority == 1


def test_check_coverage_drops_covered_information_with_no_real_citation(monkeypatch, capsys):
    """Live-found gap (2026-08-09): a full run reported a 'covered' claim
    that appeared nowhere in the actual result pool. covered_information
    items with no source_urls in the known result set must be dropped, not
    trusted."""
    _patch_solar(
        monkeypatch,
        [
            {
                "sufficient": False,
                "coverage": [],
                "covered_information": [
                    {"text": "a claim with no real backing", "source_urls": ["https://not-in-results.example.com"]},
                    {"text": "a claim with no citation at all"},
                    {"text": "a properly grounded claim", "source_urls": ["https://a.example.com"]},
                ],
                "missing_information": [],
                "needs_full_text": False,
                "sources_to_inspect": [],
                "next_queries": [],
            }
        ],
    )
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result()])

    assert [item.text for item in decision.covered] == ["a properly grounded claim"]
    assert "UNGROUNDED CLAIM WARNING" in capsys.readouterr().err


def test_check_coverage_downgrades_ungrounded_covered_aspect_to_uncertain(monkeypatch, capsys):
    """Same grounding rule for the per-aspect coverage[] list - a "covered"
    verdict with no real source_urls gets downgraded rather than trusted."""
    _patch_solar(
        monkeypatch,
        [
            {
                "sufficient": False,
                "coverage": [
                    {"aspect": "unsupported claim", "status": "covered", "reason": "sounds right"},
                    {
                        "aspect": "supported claim",
                        "status": "partially_covered",
                        "reason": "one source touches on it",
                        "source_urls": ["https://a.example.com"],
                    },
                ],
                "covered_information": [],
                "missing_information": [],
                "needs_full_text": False,
                "sources_to_inspect": [],
                "next_queries": [],
            }
        ],
    )
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result()])

    assert decision.coverage[0].status == "uncertain"  # downgraded, no real citation
    assert decision.coverage[1].status == "partially_covered"  # kept, real citation
    assert "UNGROUNDED CLAIM WARNING" in capsys.readouterr().err


def test_check_coverage_clamps_unrecognized_enum_values(monkeypatch):
    """An LLM in plain json_object mode can return any string for a
    Literal-typed field — must not crash the router."""
    _patch_solar(
        monkeypatch,
        [
            {
                "sufficient": False,
                "coverage": [{"aspect": "x", "status": "sort-of-covered-ish", "reason": "r"}],
                "next_queries": [],
            }
        ],
    )
    plan = SearchPlan(queries=[SearchPlanQuery(query="q", priority=1)])

    decision = coverage_module.check_coverage("질문", plan, [_result()])

    assert decision.coverage[0].status == "uncertain"  # unrecognized value clamped to a safe default


def test_verify_evidence_empty_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)

    verification = coverage_module.verify_evidence("질문", "본문")

    assert verification == EvidenceVerification()


def test_verify_evidence_parses_full_prompt_e_structure(monkeypatch):
    _patch_solar(
        monkeypatch,
        [
            {
                "source_assessment": {"url": "https://a.example.com", "relevance": "high", "evidence_quality": "high"},
                "summary_verification": {"status": "accurate", "important_omissions": []},
                "confirmed_facts": [
                    {"fact": "HBM market reached $41B in 2026", "evidence_strength": "direct", "context": "per company IR"}
                ],
                "limitations": ["vendor-conducted benchmark"],
                "contradictions": [
                    {"issue": "differs from analyst estimate", "conflicts_with": "https://b.example.com", "possible_explanation": "different scope", "needs_resolution": True}
                ],
                "remaining_gaps": ["independent verification"],
                "sufficient": False,
                "next_queries": [{"query": "independent HBM market estimate", "purpose": "verify", "priority": 1}],
            }
        ],
    )

    verification = coverage_module.verify_evidence("질문", "본문", url="https://a.example.com")

    assert verification.source_assessment.relevance == "high"
    assert verification.confirmed_facts[0].fact == "HBM market reached $41B in 2026"
    assert verification.confirmed_facts[0].evidence_strength == "direct"
    assert verification.contradictions[0].conflicts_with == "https://b.example.com"
    assert verification.remaining_gaps == ["independent verification"]
    assert verification.next_queries[0].query == "independent HBM market estimate"


def test_key_facts_from_verification_bridges_confirmed_facts():
    verification = EvidenceVerification(
        confirmed_facts=[
            {"fact": "fact one", "evidence_strength": "direct", "context": ""},
            {"fact": "fact two", "evidence_strength": "indirect", "context": ""},
        ]
    )

    key_facts = coverage_module.key_facts_from_verification(verification)

    assert [fact.text for fact in key_facts] == ["fact one", "fact two"]
    assert key_facts[0].value is None  # never invents a numeric breakdown ConfirmedFact doesn't have


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


class _FakeDocParseResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _patch_document_parse_post(monkeypatch, payload, api_key="test-key"):
    monkeypatch.setenv(pdf_parser._API_KEY_ENV_VAR, api_key)
    captured: dict = {}

    def _fake_post(url, headers, files, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return _FakeDocParseResponse(payload)

    monkeypatch.setattr(pdf_parser.requests, "post", _fake_post)
    return captured


def test_call_document_parse_sends_nightly_auto_and_output_formats(monkeypatch):
    """2026-08-09 decision (see pdf_parser.py module docstring): auto mode on
    the nightly build, markdown requested first via output_formats — without
    output_formats the real API returns markdown/text empty (live-verified)."""
    captured = _patch_document_parse_post(monkeypatch, {"content": {}, "elements": []})

    pdf_parser._call_document_parse(b"%PDF-1.4 fake", "test.pdf", 30)

    assert captured["data"]["model"] == "document-parse-nightly"
    assert captured["data"]["mode"] == "auto"
    assert json.loads(captured["data"]["output_formats"]) == ["markdown", "html", "text"]


def test_call_document_parse_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv(pdf_parser._API_KEY_ENV_VAR, raising=False)

    assert pdf_parser._call_document_parse(b"%PDF-1.4 fake", "test.pdf", 30) is None


def test_element_text_prefers_markdown_over_text_and_html():
    element = {
        "id": 1,
        "page": 1,
        "category": "table",
        "content": {"markdown": "| a | b |", "text": "a b", "html": "<table>a b</table>"},
    }

    assert pdf_parser._element_text(element) == "| a | b |"


def test_element_text_falls_back_to_html_tag_strip_and_warns(capsys):
    element = {"id": 5, "page": 2, "category": "table", "content": {"markdown": "", "text": "", "html": "<p>fallback text</p>"}}

    result = pdf_parser._element_text(element)

    assert result == "fallback text"
    assert "NIGHTLY MODEL DRIFT WARNING" in capsys.readouterr().err


def test_element_text_returns_empty_when_content_totally_empty():
    element = {"id": 6, "page": 3, "category": "paragraph", "content": {"markdown": "", "text": "", "html": ""}}

    assert pdf_parser._element_text(element) == ""


def test_sections_from_elements_reads_nested_content_not_flat_text_key():
    """Regression: the pre-2026-08-09 version read element["text"] (always
    absent in the real response shape - text lives under
    element["content"]["markdown"/"text"/"html"]), so heading titles silently
    fell back to generic "Section N" and every section body was empty."""
    elements = [
        {"id": 0, "page": 1, "category": "heading1", "content": {"markdown": "Overview", "text": "Overview", "html": "<h1>Overview</h1>"}},
        {"id": 1, "page": 1, "category": "paragraph", "content": {"markdown": "First paragraph.", "text": "First paragraph.", "html": "<p>First paragraph.</p>"}},
        {"id": 2, "page": 2, "category": "heading1", "content": {"markdown": "Details", "text": "Details", "html": "<h1>Details</h1>"}},
        {"id": 3, "page": 2, "category": "paragraph", "content": {"markdown": "Second paragraph.", "text": "Second paragraph.", "html": "<p>Second paragraph.</p>"}},
    ]

    sections = pdf_parser._sections_from_elements(elements, chars_per_token_estimate=2.0)

    assert [s.title for s in sections] == ["Overview", "Details"]
    assert sections[0].full_text == "First paragraph."
    assert sections[1].full_text == "Second paragraph."


def test_sections_from_elements_strips_markdown_heading_syntax_from_title():
    """Live-verified 2026-08-09: a heading1 element's own markdown IS
    markdown heading syntax (e.g. "# 2. Some Title") - title should read as
    plain text, not leak the '#' source markup."""
    elements = [
        {"id": 0, "page": 3, "category": "heading1", "content": {"markdown": "# 2. Multi-page Benchmark Table", "text": "", "html": ""}},
        {"id": 1, "page": 3, "category": "paragraph", "content": {"markdown": "Body.", "text": "", "html": ""}},
    ]

    sections = pdf_parser._sections_from_elements(elements, chars_per_token_estimate=2.0)

    assert sections[0].title == "2. Multi-page Benchmark Table"


def test_parse_response_uses_markdown_when_present():
    payload = {
        "content": {"markdown": "# Title\n\nBody text.", "html": "<h1>Title</h1><p>Body text.</p>", "text": "Title Body text."},
        "elements": [],
        "title": "Doc",
    }

    parsed = pdf_parser._parse_response(payload, source_url="https://example.com/a.pdf", chars_per_token_estimate=2.0)

    assert parsed is not None
    assert parsed.full_text == "# Title\n\nBody text."


def test_parse_response_falls_back_to_html_when_markdown_and_text_empty(capsys):
    """Live-verified 2026-08-09: without output_formats, the real API returns
    exactly this shape (html populated, markdown/text empty) - this is the
    drift safety net, not a hypothetical."""
    payload = {
        "content": {"markdown": "", "text": "", "html": "<p>Only html here</p>"},
        "elements": [],
        "title": "Doc",
    }

    parsed = pdf_parser._parse_response(payload, source_url="https://example.com/a.pdf", chars_per_token_estimate=2.0)

    assert parsed is not None
    assert "Only html here" in parsed.full_text
    assert "NIGHTLY MODEL DRIFT WARNING" in capsys.readouterr().err


def test_parse_response_returns_none_when_content_entirely_empty():
    payload = {"content": {"markdown": "", "text": "", "html": ""}, "elements": [], "title": "Doc"}

    parsed = pdf_parser._parse_response(payload, source_url="https://example.com/a.pdf", chars_per_token_estimate=2.0)

    assert parsed is None


def test_select_sections_forwards_timeout_seconds_to_solar(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["timeout_seconds"] = timeout_seconds
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)
    sections = [DocumentSection(section_id="S1", title="Intro")]

    pdf_parser.select_sections("질문", sections, timeout_seconds=77)

    assert captured["timeout_seconds"] == 77


def test_select_chunks_forwards_timeout_seconds_to_solar(monkeypatch):
    captured = {}

    def _fake_call_json(system_prompt, payload, *, caller, model_override=None, timeout_seconds=30):
        captured["timeout_seconds"] = timeout_seconds
        return None

    monkeypatch.setattr(solar_module, "call_json", _fake_call_json)
    chunks = [DocumentChunk(chunk_id="S1-C1", section_id="S1")]

    pdf_parser.select_chunks("질문", chunks, timeout_seconds=77)

    assert captured["timeout_seconds"] == 77


def test_select_sections_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)
    sections = [
        DocumentSection(section_id="S1", title="Intro"),
        DocumentSection(section_id="S2", title="Methodology"),
        DocumentSection(section_id="S3", title="Results"),
    ]

    selected = pdf_parser.select_sections("질문", sections, max_sections=2)

    assert [item.section_id for item in selected] == ["S1", "S2"]


def test_select_sections_rejects_hallucinated_id(monkeypatch):
    _patch_solar(
        monkeypatch,
        [{"selected_sections": [{"section_id": "S99", "reason": "fake"}]}],
    )
    sections = [DocumentSection(section_id="S1", title="Intro")]

    selected = pdf_parser.select_sections("질문", sections)

    assert [item.section_id for item in selected] == ["S1"]  # invalid id dropped -> falls back to document order


def test_select_sections_parses_new_prompt_c_structure(monkeypatch):
    """Real prompt C shape adds reason/evidence_role/requires_chunk_
    selection per selected section — must not be lost."""
    _patch_solar(
        monkeypatch,
        [
            {
                "selected_sections": [
                    {
                        "section_id": "S2",
                        "reason": "methodology needed to interpret results",
                        "evidence_role": ["methodology"],
                        "requires_chunk_selection": True,
                    }
                ],
                "excluded_high_probability_sections": [{"section_id": "S1", "reason": "generic intro"}],
                "selection_complete": True,
            }
        ],
    )
    sections = [
        DocumentSection(section_id="S1", title="Intro"),
        DocumentSection(section_id="S2", title="Methodology"),
    ]

    selected = pdf_parser.select_sections("질문", sections)

    assert selected[0].section_id == "S2"
    assert selected[0].evidence_role == ["methodology"]
    assert selected[0].requires_chunk_selection is True


def test_select_chunks_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)
    chunks = [
        DocumentChunk(chunk_id="S1-C1", section_id="S1"),
        DocumentChunk(chunk_id="S1-C2", section_id="S1"),
    ]

    selected = pdf_parser.select_chunks("질문", chunks, max_chunks=1)

    assert [item.chunk_id for item in selected] == ["S1-C1"]


def test_select_chunks_parses_object_shaped_selection(monkeypatch):
    """Real prompt D shape wraps chunk_id in an object with reason/
    evidence_role — the earlier code expected bare chunk_id strings and
    would have silently discarded every real selection."""
    _patch_solar(
        monkeypatch,
        [
            {
                "selected_chunks": [
                    {"chunk_id": "S1-C2", "reason": "has the benchmark table", "evidence_role": ["quantitative_results"]}
                ],
                "potentially_missing_information": [],
                "selection_complete": True,
            }
        ],
    )
    chunks = [
        DocumentChunk(chunk_id="S1-C1", section_id="S1"),
        DocumentChunk(chunk_id="S1-C2", section_id="S1"),
    ]

    selected = pdf_parser.select_chunks("질문", chunks)

    assert [item.chunk_id for item in selected] == ["S1-C2"]
    assert selected[0].evidence_role == ["quantitative_results"]


# ---------------------------------------------------------------------------
# question_type_classifier.py — rule-based 1st pass over planner.py's 3rd
# axis (now wired into _assemble_system_prompt/plan_searches - see the
# "question_type cutting" tests above and prompts/planner_question_types/
# *.md). This section only tests the classifier in isolation. Example
# questions below are the user-supplied representative examples from the
# source material, not invented.
# ---------------------------------------------------------------------------


def test_classify_question_type_returns_none_for_empty_question():
    assert question_type_classifier.classify_question_type("") == (None, "low")
    assert question_type_classifier.classify_question_type(None) == (None, "low")


def test_classify_question_type_returns_none_when_no_signal_matches():
    assert question_type_classifier.classify_question_type("안녕하세요") == (None, "low")


def test_classify_question_type_detects_troubleshooting_with_high_confidence():
    result = question_type_classifier.classify_question_type(
        "중앙그룹 회생 사태에 따른 IPTV사의 대응 방안"
    )
    assert result == ("troubleshooting", "high")


def test_classify_question_type_detects_navigating_with_high_confidence():
    result = question_type_classifier.classify_question_type(
        "SK브로드밴드 브랜드 이미지 개선에 맞는 연령층별 광고 매체 및 모델 추천"
    )
    assert result == ("navigating", "high")


def test_classify_question_type_detects_investigating_with_high_confidence():
    result = question_type_classifier.classify_question_type(
        "2030 1인 가구의 유선 인터넷 가입 고려 요인 및 페인 포인트"
    )
    assert result == ("investigating", "high")


def test_classify_question_type_detects_sensing_with_high_confidence():
    result = question_type_classifier.classify_question_type(
        "지난 5년간 OTT 생태계의 변화 추이 (국내 vs 글로벌 비교)"
    )
    assert result == ("sensing", "high")


def test_classify_question_type_returns_low_confidence_when_top_two_scores_are_close():
    """This is the source material's own worked example for why the gap
    between the top two scores matters more than the absolute top score -
    the question genuinely mixes an investigating angle ("미치는 영향")
    with a troubleshooting one ("대응 전략")."""
    question_type, confidence = question_type_classifier.classify_question_type(
        "칩플레이션(반도체 가격 상승)이 셋톱박스 업계에 미치는 영향과 IPTV사의 중장기 대응 전략"
    )
    assert confidence == "low"
    assert question_type in question_type_classifier.QUESTION_TYPE_IDS


def test_classify_question_type_does_not_guess_from_a_word_no_list_actually_contains():
    """The source material's own caution: "전략" alone is ambiguous across
    types ("대응 전략" -> troubleshooting, "성장 전략" -> navigating), so
    it deliberately does NOT appear as a bare general-signal word in any
    list - only inside specific multi-word strong phrases. A question that
    only contains the bare word should score 0 everywhere and return no
    guess at all, rather than default to any one type."""
    assert question_type_classifier.classify_question_type("경쟁사 전략 분석") == (None, "low")


# ---------------------------------------------------------------------------
# question_type_ai_based.py — optional 2nd-pass AI refinement over
# question_type_classifier.py's rule-based 1st pass. `refine_question_type_ai`
# is now called by planner.py's plan_searches() (see the
# test_plan_searches_classifies_question_type_and_cuts_branch_to_solar wiring
# test above) - these tests exercise the module in isolation, same as the
# rule-based classifier tests above.
# ---------------------------------------------------------------------------


def test_classify_question_type_ai_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)

    assert question_type_ai_based.classify_question_type_ai("질문") is None


def test_classify_question_type_ai_parses_valid_response(monkeypatch):
    _patch_solar(
        monkeypatch,
        [{"type": "Troubleshooting", "confidence": 0.92, "reason": "대응책을 찾는 질문"}],
    )

    result = question_type_ai_based.classify_question_type_ai("반도체 가격 상승에 어떻게 대응해야 하는가")

    assert result == ("troubleshooting", "high")


def test_classify_question_type_ai_maps_confidence_tiers(monkeypatch):
    _patch_solar(monkeypatch, [{"type": "Sensing", "confidence": 0.5, "reason": "r"}])
    assert question_type_ai_based.classify_question_type_ai("질문") == ("sensing", "medium")

    _patch_solar(monkeypatch, [{"type": "Sensing", "confidence": 0.1, "reason": "r"}])
    assert question_type_ai_based.classify_question_type_ai("질문") == ("sensing", "low")


def test_classify_question_type_ai_returns_none_for_unrecognized_type(monkeypatch):
    _patch_solar(monkeypatch, [{"type": "NotARealType", "confidence": 0.9, "reason": "r"}])

    assert question_type_ai_based.classify_question_type_ai("질문") is None


def test_classify_question_type_ai_returns_none_on_call_failure(monkeypatch):
    monkeypatch.setenv(solar_module.API_KEY_ENV_VAR, "key")
    monkeypatch.setattr(
        solar_module, "OpenAI", lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert question_type_ai_based.classify_question_type_ai("질문") is None


# --- refine_question_type_ai: the 1st->2nd pass orchestration itself -------


def test_refine_question_type_ai_skips_ai_call_when_rule_based_is_high(monkeypatch):
    """A "high" rule-based confidence is trusted as-is - no API call spent
    confirming it. Asserting on solar_module.call_json's call log (rather
    than just the returned value) proves the AI pass was never invoked, not
    merely that its result happened to match."""
    calls = []
    monkeypatch.setattr(
        solar_module, "call_json", lambda *a, **k: calls.append(1) or {"type": "Sensing", "confidence": 0.9}
    )

    result = question_type_ai_based.refine_question_type_ai(("troubleshooting", "high"), "질문")

    assert result == ("troubleshooting", "high")
    assert calls == []


def test_refine_question_type_ai_calls_ai_when_rule_based_is_low(monkeypatch):
    _patch_solar(monkeypatch, [{"type": "Navigating", "confidence": 0.8, "reason": "r"}])

    result = question_type_ai_based.refine_question_type_ai((None, "low"), "질문")

    assert result == ("navigating", "high")


def test_refine_question_type_ai_calls_ai_when_rule_based_is_medium(monkeypatch):
    """The rule-based classifier itself never emits "medium" today, but the
    orchestration threshold is written generically against this codebase's
    full low/medium/high scale - not hardcoded to only "low" - so this must
    keep working if that ever changes."""
    _patch_solar(monkeypatch, [{"type": "Sensing", "confidence": 0.8, "reason": "r"}])

    result = question_type_ai_based.refine_question_type_ai(("troubleshooting", "medium"), "질문")

    assert result == ("sensing", "high")


def test_refine_question_type_ai_falls_back_to_rule_based_when_ai_unavailable(monkeypatch):
    monkeypatch.delenv(solar_module.API_KEY_ENV_VAR, raising=False)

    result = question_type_ai_based.refine_question_type_ai(("investigating", "low"), "질문")

    assert result == ("investigating", "low")


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


def test_research_forwards_audience_and_purpose_id_to_plan_searches(monkeypatch):
    """Regression guard: research() already accepted audience/purpose_id as
    its own kwargs, but used to call plan_searches() with only `question` -
    so STEP 2.5/2.6 in planner.md never actually saw them. Fixed by threading
    both through at the one call site."""
    captured = {}

    def _fake_plan_searches(question, **kwargs):
        captured.update(kwargs)
        return _plan(("q1", 1))

    monkeypatch.setattr(planner_module, "plan_searches", _fake_plan_searches)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **_: [])
    monkeypatch.setattr(
        coverage_module, "check_coverage", lambda *a, **k: CoverageDecision(sufficient=True, reason="enough")
    )

    router_module.research(
        "질문", SourceRouterConfig(), purpose_id="issue_response", audience="executive"
    )

    assert captured["audience"] == "executive"
    assert captured["purpose_id"] == "issue_response"


def test_research_forwards_purpose_confidence_to_plan_searches(monkeypatch):
    """Same wiring pattern as audience/purpose_id above, for the new
    purpose_confidence kwarg that gates the cut-and-assemble prompt's
    confidence fallback (see planner_module._pick_branch_ids)."""
    captured = {}

    def _fake_plan_searches(question, **kwargs):
        captured.update(kwargs)
        return _plan(("q1", 1))

    monkeypatch.setattr(planner_module, "plan_searches", _fake_plan_searches)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **_: [])
    monkeypatch.setattr(
        coverage_module, "check_coverage", lambda *a, **k: CoverageDecision(sufficient=True, reason="enough")
    )

    router_module.research(
        "질문",
        SourceRouterConfig(),
        purpose_id="issue_response",
        purpose_confidence="low",
        audience="executive",
    )

    assert captured["purpose_confidence"] == "low"


def test_research_stops_when_sufficient_after_priority1(monkeypatch):
    plan = _plan(("q1", 1), ("q2", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(
        web_search_module,
        "execute_web_search",
        lambda query, **_: [_result(f"https://a.example.com/{query}").model_copy(update={
            "evidence_depth": "original_source", "original_content": "verified source text",
            "verification": EvidenceVerification(confirmed_facts=[
                ConfirmedFact(fact="verified", evidence_strength="direct")
            ]),
        })],
    )
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=True, reason="enough"),
    )

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "sufficient"
    assert result.rounds_completed == 1
    assert len(result.results) == 1


def test_research_runs_priority2_after_insufficient_then_stops(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)

    call_count = {"n": 0}

    def _fake_search(query, **_):
        call_count["n"] += 1
        return [_result(f"https://a.example.com/{call_count['n']}").model_copy(update={
            "evidence_depth": "original_source", "original_content": "verified source text",
            "verification": EvidenceVerification(confirmed_facts=[
                ConfirmedFact(fact="verified", evidence_strength="direct")
            ]),
        })]

    monkeypatch.setattr(web_search_module, "execute_web_search", _fake_search)

    decisions = [
        CoverageDecision(sufficient=False, next_queries=[NextQuery(query="q2")], reason="gap"),
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
    monkeypatch.setattr(
        coverage_module,
        "verify_evidence",
        lambda *a, **k: EvidenceVerification(
            confirmed_facts=[{"fact": "확인된 사실", "evidence_strength": "direct", "context": ""}]
        ),
    )

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "sufficient"
    inspected = next(r for r in result.results if r.url == "https://a.example.com")
    assert inspected.evidence_depth == "original_source"
    assert inspected.key_facts[0].text == "확인된 사실"
    assert inspected.verification.confirmed_facts[0].fact == "확인된 사실"


def test_research_inspects_every_flagged_source_not_just_first_three(monkeypatch):
    """sources_to_inspect is already coverage's own deficient-only selection
    (bounded by the results pool, itself capped at max_results) — the old
    max_sources_to_inspect=3 default used to arbitrarily defer some of a
    larger batch to a later round for no benefit; the default is now 10 so
    all of coverage's picks get inspected in one pass."""
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    urls = [f"https://a.example.com/{i}" for i in range(5)]
    monkeypatch.setattr(
        web_search_module,
        "execute_web_search",
        lambda query, **_: [_result(url) for url in urls],
    )

    decisions = [
        CoverageDecision(
            sufficient=False,
            needs_full_text=True,
            sources_to_inspect=[SourceToInspect(url=url, reason="need numbers") for url in urls],
            reason="gap",
        ),
        CoverageDecision(sufficient=True, reason="now enough"),
    ]
    monkeypatch.setattr(coverage_module, "check_coverage", lambda *a, **k: decisions.pop(0))
    monkeypatch.setattr(router_module.html_extractor, "extract_html", lambda url, **_: "실제 원문 내용 " * 30)
    monkeypatch.setattr(coverage_module, "verify_evidence", lambda *a, **k: EvidenceVerification())

    result = router_module.research("질문", SourceRouterConfig())

    inspected_urls = {r.url for r in result.results if r.evidence_depth == "original_source"}
    assert inspected_urls == set(urls)  # all 5 inspected, not just the first 3


def test_research_stops_no_new_information_when_next_queries_yield_nothing(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **_: [])
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=[NextQuery(query="q2")], reason="gap"),
    )

    result = router_module.research("질문", SourceRouterConfig())

    assert result.stop_reason == "no_new_information"


def test_research_stops_at_gap_loop_iterations_exhausted_when_never_sufficient(monkeypatch):
    """search_call_calls stays well under max_web_search_calls=10 and
    next_queries is always present - the only reason this terminates is the
    for loop running out of its 2 allotted rounds, so the label must say
    exactly that, not the old generic "budget_exhausted".

    rounds_completed is 3, not 2: the 2nd (last) round merges new results
    from next_queries, which — per the 2026-08-09 stale-final-coverage fix
    below — triggers one extra, uncounted check_coverage() re-assessment
    after the loop's iteration budget is used up, so the returned
    final_coverage reflects the round-2 evidence instead of going stale."""
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
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=[NextQuery(query="q-next")], reason="never enough"),
    )

    config = SourceRouterConfig(max_gap_loop_iterations=2, max_web_search_calls=10)
    result = router_module.research("질문", config)

    assert result.stop_reason == "gap_loop_iterations_exhausted"
    assert result.rounds_completed == 3


def test_research_reassesses_coverage_after_last_round_inspects_sources(monkeypatch):
    """2026-08-09 fix, live-verified stale-state bug: when the loop's last
    allotted iteration ends via a successful source inspection (`continue`),
    the pre-inspection decision used to be returned as final_coverage even
    though `results` already contained the newly-inspected evidence — a real
    run's final_coverage kept listing a URL under sources_to_inspect that
    results already showed as evidence_depth="original_source". Now one
    more, uncounted check_coverage() call re-assesses the merged results
    before returning, so final_coverage never goes stale."""
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(
        web_search_module, "execute_web_search", lambda query, **_: [_result("https://a.example.com")]
    )
    monkeypatch.setattr(router_module.html_extractor, "extract_html", lambda url, **_: "실제 원문 내용 " * 30)
    monkeypatch.setattr(coverage_module, "verify_evidence", lambda *a, **k: EvidenceVerification())

    stale_decision = CoverageDecision(
        sufficient=False,
        needs_full_text=True,
        sources_to_inspect=[SourceToInspect(url="https://a.example.com", reason="need numbers")],
        reason="pre-inspection",
    )
    fresh_decision = CoverageDecision(sufficient=False, reason="post-inspection, still not enough")
    decisions = [stale_decision, fresh_decision]
    monkeypatch.setattr(coverage_module, "check_coverage", lambda *a, **k: decisions.pop(0))

    config = SourceRouterConfig(max_gap_loop_iterations=1)
    result = router_module.research("질문", config)

    assert result.stop_reason == "gap_loop_iterations_exhausted"
    assert result.final_coverage.reason != "pre-inspection"
    # The re-assessment's own verdict is what reaches the caller. This used
    # to read "verified original source" instead, but only incidentally: the
    # inspected source carried an empty `EvidenceVerification()`, so the old
    # fourth AND condition in `_enforce_direct_original_sources` rejected it
    # and overwrote the reason. Now a fetched-and-verified source clears that
    # gate, so the fresh decision survives - which is what this test is about.
    assert result.final_coverage.reason == "post-inspection, still not enough"
    assert result.rounds_completed == 2  # 1 allotted iteration + 1 free re-assessment
    inspected = next(r for r in result.results if r.url == "https://a.example.com")
    assert inspected.evidence_depth == "original_source"


def test_research_no_extra_reassessment_when_last_round_did_not_change_results(monkeypatch):
    """The extra re-assessment call is conditional — a run that stops
    because next_queries came back empty never merged anything after its
    last check_coverage() call, so there is nothing stale to re-check."""
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **_: [_result("https://a.example.com")])
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=[], reason="nothing left"),
    )

    result = router_module.research("질문", SourceRouterConfig(max_gap_loop_iterations=3))

    assert result.stop_reason == "no_further_queries"
    assert result.rounds_completed == 1  # no extra call — check_coverage was mocked to return exactly this


def test_research_reports_search_calls_used(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(
        web_search_module,
        "execute_web_search",
        lambda query, **_: [_result(f"https://a.example.com/{query}")],
    )
    decisions = [
        CoverageDecision(sufficient=False, next_queries=[NextQuery(query="q2")], reason="gap"),
        CoverageDecision(sufficient=True, reason="enough"),
    ]
    monkeypatch.setattr(coverage_module, "check_coverage", lambda *a, **k: decisions.pop(0))

    result = router_module.research("질문", SourceRouterConfig())

    assert result.search_calls_used == 2  # priority-1 round (q1) + next_queries round (q2)


def test_research_stops_at_no_further_queries_when_model_proposes_nothing(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **_: [_result("https://a.example.com/1")])
    monkeypatch.setattr(
        coverage_module,
        "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=[], reason="nothing left to try"),
    )

    result = router_module.research("질문", SourceRouterConfig(max_gap_loop_iterations=3, max_web_search_calls=10))

    assert result.stop_reason == "no_further_queries"
    assert result.rounds_completed == 1


def test_research_stops_at_search_call_budget_exhausted(monkeypatch):
    """next_queries is always present (the model would keep proposing more),
    but the numeric search-call cap is what actually stops the loop - must
    not be confused with no_further_queries or the iteration cap."""
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
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=[NextQuery(query="q-next")], reason="never enough"),
    )

    # max_priority1_queries=1 uses exactly 1 call up front; max_web_search_calls=1
    # means the first gap-loop round already finds search_call_count >= cap.
    config = SourceRouterConfig(max_priority1_queries=1, max_gap_loop_iterations=5, max_web_search_calls=1)
    result = router_module.research("질문", config)

    assert result.stop_reason == "search_call_budget_exhausted"


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
        lambda *a, **k: CoverageDecision(sufficient=False, next_queries=[NextQuery(query="q-next")], reason="never enough"),
    )

    config = SourceRouterConfig(max_gap_loop_iterations=10, max_web_search_calls=3)
    router_module.research("질문", config)

    assert counter["n"] <= 3


# ---------------------------------------------------------------------------
# Cost guards — max_urls_per_query / max_results (added after a live-cost
# review found both points uncapped: a single web_search call could return
# unlimited URLs, and the accumulated results pool was resent in full on
# every check_coverage() call with no size limit).
# ---------------------------------------------------------------------------


def test_cap_results_keeps_all_original_source_entries():
    inspected = [
        WebSearchResult(url=f"https://insp.example.com/{i}", evidence_depth="original_source")
        for i in range(4)
    ]
    summaries = [
        WebSearchResult(url=f"https://sum.example.com/{i}", evidence_depth="search_summary")
        for i in range(10)
    ]

    capped = router_module._cap_results(inspected + summaries, max_results=6)

    assert all(r.evidence_depth == "original_source" for r in capped[:4])
    assert len(capped) == 6  # 4 original_source (never dropped) + 2 most recent search_summary


def test_cap_results_keeps_most_recently_added_search_summary_entries():
    summaries = [
        WebSearchResult(url=f"https://sum.example.com/{i}", evidence_depth="search_summary")
        for i in range(5)
    ]

    capped = router_module._cap_results(summaries, max_results=2)

    assert [r.url for r in capped] == ["https://sum.example.com/3", "https://sum.example.com/4"]


def test_cap_results_noop_when_under_budget():
    results = [WebSearchResult(url="https://a.example.com")]

    assert router_module._cap_results(results, max_results=10) == results


def test_research_caps_accumulated_results_pool(monkeypatch):
    """End-to-end: even if every web_search call returns the per-query
    max_urls, the pool sent to check_coverage() never exceeds max_results."""
    plan = _plan(("q1", 1), ("q2", 1), ("q3", 1), ("q4", 1), ("q5", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)

    def _fake_search(query, **_):
        return [
            _result(f"https://a.example.com/{query}/{i}") for i in range(2)
        ]  # matches default max_urls_per_query

    monkeypatch.setattr(web_search_module, "execute_web_search", _fake_search)

    seen_pool_sizes: list[int] = []

    def _fake_coverage(question, search_plan, results, **_):
        seen_pool_sizes.append(len(results))
        return CoverageDecision(sufficient=True, reason="enough")

    monkeypatch.setattr(coverage_module, "check_coverage", _fake_coverage)

    config = SourceRouterConfig(max_priority1_queries=5, max_web_search_calls=8, max_results=6)
    result = router_module.research("질문", config)

    assert len(result.results) <= 6
    assert all(size <= 6 for size in seen_pool_sizes)


def test_research_passes_max_urls_per_query_to_web_search(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)

    seen_kwargs: dict = {}

    def _fake_search(query, **kwargs):
        seen_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(web_search_module, "execute_web_search", _fake_search)
    monkeypatch.setattr(
        coverage_module, "check_coverage", lambda *a, **k: CoverageDecision(sufficient=True, reason="enough")
    )

    config = SourceRouterConfig(max_urls_per_query=1)
    router_module.research("질문", config)

    assert seen_kwargs["max_urls"] == 1


def test_str_list_keeps_a_bare_string_whole():
    """A model answering with a sentence must not become a list of letters.

    A live run recorded limitations as ["I", "P", "T", "V", "가", ...] -
    the schema asked for an array, the model sent one string, and iterating
    it destroyed the explanation.
    """
    assert coverage_module._str_list("IPTV 가입자 수는 반기 기준입니다.") == [
        "IPTV 가입자 수는 반기 기준입니다."
    ]


def test_str_list_still_flattens_real_lists_and_drops_blanks():
    assert coverage_module._str_list(["  a  ", "", "  ", "b"]) == ["a", "b"]
    assert coverage_module._str_list(None) == []
    assert coverage_module._str_list([]) == []


def test_str_list_wraps_a_non_iterable_scalar():
    assert coverage_module._str_list(7) == ["7"]


def test_plan_searches_clamps_the_pipeline_default_audience(monkeypatch):
    """`_default` is a real runtime value, not a bad input.

    The pipeline falls back to DEFAULT_AUDIENCE_ID ("_default") whenever the
    caller named no audience, which is every run that did not pass
    --audience. Before this clamp that value reached SearchPlan.audience -
    a Literal of the 4 selectable personas - and every such run died with a
    ValidationError before the first search call.
    """
    monkeypatch.setattr(
        solar_module, "call_json",
        lambda *a, **k: {"intent": "i", "queries": [{"query": "q", "angle": "a", "purpose": "p", "priority": 1}]},
    )
    plan = planner_module.plan_searches("IPTV 가입자 수 현황은?", audience="_default")

    assert plan.audience is None
    assert plan.queries


def test_plan_searches_still_echoes_a_real_audience(monkeypatch):
    monkeypatch.setattr(
        solar_module, "call_json",
        lambda *a, **k: {"intent": "i", "queries": [{"query": "q", "angle": "a", "purpose": "p", "priority": 1}]},
    )
    plan = planner_module.plan_searches("질문", audience="executive")

    assert plan.audience == "executive"


def test_fallback_plan_clamps_audience_too():
    """The empty-question fallback builds a SearchPlan of its own."""
    assert planner_module._fallback_plan("", audience="_default").audience is None
    assert planner_module._fallback_plan("질문", audience="_default").audience is None
    assert planner_module._fallback_plan("질문", audience="external").audience == "external"


# --- search budget observability -------------------------------------------
def test_search_budget_terms_explain_the_derived_number():
    """config.max_web_search_calls is a ceiling, not the run's budget.

    "IPTV 가입자 수 현황은?" names no comparison/trend/strategy token, so it
    derives 4 + 2 = 6 against a ceiling of 12. Recording only
    `search_calls_used` made stopping at 6 read as a premature abort.
    """
    plan = SearchPlan(
        intent="i",
        queries=[SearchPlanQuery(query="q", angle="a", purpose="p", priority=1)],
        evidence_needs=[
            EvidenceNeed(evidence_need_id="direct-1", text="t1", requirement_type="direct"),
            EvidenceNeed(evidence_need_id="direct-2", text="t2", requirement_type="direct"),
        ],
    )
    terms = router_module._search_budget_terms("IPTV 가입자 수 현황은?", plan, 12)

    assert terms == {
        "base": 4,
        "evidence_needs_bonus": 2,
        "comparison_temporal_bonus": 0,
        "strategy_bonus": 0,
        "ceiling": 12,
    }
    assert router_module._search_budget("IPTV 가입자 수 현황은?", plan, 12) == 6


def test_search_budget_terms_stay_consistent_with_the_budget():
    """The basis is the same arithmetic, not a second implementation."""
    plan = SearchPlan(
        intent="i",
        queries=[SearchPlanQuery(query="q", angle="a", purpose="p", priority=1)],
        evidence_needs=[
            EvidenceNeed(evidence_need_id="d1", text="t", requirement_type="direct"),
            EvidenceNeed(evidence_need_id="d2", text="t", requirement_type="direct"),
        ],
    )
    for question in ("IPTV 가입자 수 현황은?", "경쟁사 대비 추이는?", "원인과 대응 전략은?"):
        terms = router_module._search_budget_terms(question, plan, 12)
        expected = min(12, terms["base"] + terms["evidence_needs_bonus"]
                       + terms["comparison_temporal_bonus"] + terms["strategy_bonus"])
        assert router_module._search_budget(question, plan, 12) == expected


def test_ceiling_still_caps_a_complex_question():
    plan = SearchPlan(
        intent="i",
        queries=[SearchPlanQuery(query="q", angle="a", purpose="p", priority=1)],
        evidence_needs=[
            EvidenceNeed(evidence_need_id="d1", text="t", requirement_type="direct"),
            EvidenceNeed(evidence_need_id="d2", text="t", requirement_type="direct"),
        ],
    )
    question = "경쟁사 대비 추이와 대응 전략은?"

    assert router_module._search_budget(question, plan, 12) == 10
    assert router_module._search_budget(question, plan, 6) == 6


def test_result_carries_the_budget_it_actually_had(monkeypatch):
    plan = _plan(("q1", 1))
    monkeypatch.setattr(planner_module, "plan_searches", lambda question, **_: plan)
    monkeypatch.setattr(web_search_module, "execute_web_search", lambda query, **k: [])
    monkeypatch.setattr(
        coverage_module, "check_coverage",
        lambda *a, **k: CoverageDecision(sufficient=True, reason="enough"),
    )

    result = router_module.research("IPTV 가입자 수 현황은?", SourceRouterConfig())

    assert result.search_budget == 4
    assert result.search_budget_basis["ceiling"] == SourceRouterConfig().max_web_search_calls
    assert result.search_budget_basis["base"] == 4


# --- planner prompt: institution anchors must not replace DIRECT ------------
def test_planner_prompt_blocks_anchoring_a_plain_status_question():
    prompt = prompts_module.load("planner_common_tail")

    assert "단순 current-state" in prompt
    assert "서비스 A 이용자 수 현황은?" in prompt


def test_planner_prompt_requires_one_unanchored_question_first_query():
    prompt = prompts_module.load("planner_common_tail")

    assert "Keep one unanchored question-first query" in prompt
    assert "priority: 1" in prompt


def test_planner_prompt_still_teaches_the_benchmark_pattern():
    """The anchor guidance is narrowed, never removed - a multi-candidate
    recommendation question still needs it. (2026-08-10: no longer checks
    specific real institution names - see
    test_planner_prompt_documents_quantitative_benchmark_institution_queries's
    docstring for why those were generalized away.)"""
    prompt = prompts_module.load("planner_common_tail")

    assert "Quantitative benchmark / ranking-index queries" in prompt
    assert "리서치기관" in prompt
