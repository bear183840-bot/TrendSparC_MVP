import json
import types

from common.contracts import EvidenceCoverageAssessment, PlannedSource, WebSearchContext
from sources.collectors import ai_search_harness as harness_module
from sources.collectors.ai_search_harness import (
    HarnessConfig,
    _attribute_source,
    _doc_id,
    _initial_query,
    _parse_round_judgment,
    run_ai_search_harness,
    run_question_search_harness,
    run_question_search_harness_result,
)


def _citation_annotation(url, title="제목"):
    return types.SimpleNamespace(type="url_citation", url=url, title=title)


def _response(citations=None, sufficient=False, next_queries=None, include_judgment=True):
    block = types.SimpleNamespace(annotations=citations or [])
    message_item = types.SimpleNamespace(type="message", content=[block])
    output_text = "관련 기사를 찾았습니다."
    if include_judgment:
        judgment = json.dumps(
            {"sufficient": sufficient, "next_queries": next_queries or []}, ensure_ascii=False
        )
        output_text = f"{output_text}\n{judgment}"
    return types.SimpleNamespace(output=[message_item], output_text=output_text)


def _response_with_tool_sources(sources, sufficient=True):
    response = _response(citations=[], sufficient=sufficient)
    web_search_call = types.SimpleNamespace(
        type="web_search_call",
        action=types.SimpleNamespace(sources=sources),
    )
    response.output.append(web_search_call)
    return response


class _FakeResponses:
    def __init__(self, responses, parsed_responses=None):
        self._responses = list(responses)
        self._parsed_responses = list(parsed_responses or [])
        self.calls: list[dict] = []
        self.parse_calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("no more fake responses queued")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        if not self._parsed_responses:
            raise AssertionError("no more fake parsed responses queued")
        result = self._parsed_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return types.SimpleNamespace(output_parsed=result)


class _FakeOpenAI:
    def __init__(self, responses, parsed_responses=None):
        self.responses = _FakeResponses(responses, parsed_responses)


class _FakeFirecrawl:
    def __init__(self, markdown_by_url=None, default_markdown=None):
        self.markdown_by_url = markdown_by_url or {}
        self.default_markdown = default_markdown if default_markdown is not None else "본문 내용" * 100
        self.scrape_calls: list[str] = []

    def scrape(self, url, formats):
        self.scrape_calls.append(url)
        if url in self.markdown_by_url:
            markdown = self.markdown_by_url[url]
            if markdown is None:
                raise RuntimeError("simulated scrape failure")
            return types.SimpleNamespace(markdown=markdown)
        return types.SimpleNamespace(markdown=self.default_markdown)


def _source(
    name="SK브로드밴드 뉴스룸",
    url="https://news.sktelecom.com/tag/skbroadband",
    role="official",
    topics=None,
    reliability_tier="official",
):
    return PlannedSource(
        name=name,
        url=url,
        role=role,
        topics=topics if topics is not None else ["B tv", "IPTV"],
        reliability_tier=reliability_tier,
    )


_KEYWORDS = ["SK브로드밴드", "IPTV 신규 서비스"]


def test_question_harness_runs_one_session_without_per_source_search_slots():
    sources = [
        _source(),
        _source(
            name="전자신문 (통신)",
            url="https://www.etnews.com/news/section.html?id1=03",
            role="search",
            reliability_tier="analyst_media",
        ),
    ]
    citations = [
        _citation_annotation("https://news.sktelecom.com/a"),
        _citation_annotation("https://www.etnews.com/b"),
    ]
    openai_client = _FakeOpenAI([_response(citations=citations, sufficient=True)])
    firecrawl_client = _FakeFirecrawl()
    context = WebSearchContext(question="SK브로드밴드 IPTV 경쟁력은?", suggested_terms=_KEYWORDS)

    docs = run_question_search_harness(
        openai_client,
        firecrawl_client,
        sources,
        _KEYWORDS,
        HarnessConfig(target_docs=6),
        context,
    )

    assert len(openai_client.responses.calls) == 1
    request = json.loads(openai_client.responses.calls[0]["input"][1]["content"])
    assert request["current_round_query"] == context.question
    assert "registered_source_hint" not in request
    assert [doc.source_id for doc in docs] == ["SK브로드밴드 뉴스룸", "전자신문 (통신)"]


def test_question_harness_uses_scraped_evidence_gaps_for_follow_up_search():
    source_a = _source(name="출처 A", url="https://a.example.com", reliability_tier="official")
    source_b = _source(name="출처 B", url="https://b.example.com", reliability_tier="analyst_media")
    url_a = "https://a.example.com/report"
    irrelevant_url = "https://a.example.com/passing-mention"
    url_b = "https://b.example.com/analysis"
    doc_a = _doc_id(source_a.name, url_a)
    irrelevant_doc = _doc_id(source_a.name, irrelevant_url)
    doc_b = _doc_id(source_b.name, url_b)
    search_rounds = [
        _response(
            citations=[_citation_annotation(url_a), _citation_annotation(irrelevant_url)],
            sufficient=True,
        ),
        _response(citations=[_citation_annotation(url_b)], sufficient=True),
    ]
    assessments = [
        EvidenceCoverageAssessment(
            sufficient=False,
            relevant_doc_ids=[doc_a],
            covered_information_needs=["competition"],
            missing_information_needs=["strategy_investment"],
            next_queries=["SK브로드밴드 B tv 전략 투자"],
            reason="전략 근거가 부족함",
        ),
        EvidenceCoverageAssessment(
            sufficient=True,
            relevant_doc_ids=[doc_a, doc_b],
            covered_information_needs=["competition", "strategy_investment"],
            missing_information_needs=[],
            next_queries=[],
            reason="독립 출처 두 곳에서 필요한 근거를 확보함",
        ),
    ]
    openai_client = _FakeOpenAI(search_rounds, assessments)
    firecrawl_client = _FakeFirecrawl()
    context = WebSearchContext(
        question="IPTV 경쟁 변화가 B tv 전략에 미치는 영향은?",
        information_needs=["competition", "strategy_investment"],
        suggested_terms=["IPTV", "B tv"],
    )

    result = run_question_search_harness_result(
        openai_client,
        firecrawl_client,
        [source_a, source_b],
        ["IPTV", "B tv"],
        HarnessConfig(target_docs=6, assess_scraped_evidence=True),
        context,
    )

    assert result.sufficient is True
    assert [document.doc_id for document in result.documents] == [doc_a, doc_b]
    assert irrelevant_doc not in [document.doc_id for document in result.documents]
    assert result.covered_information_needs == ["competition", "strategy_investment"]
    assert result.missing_information_needs == []
    assert result.rounds_completed == 2
    assert len(openai_client.responses.parse_calls) == 2
    second_search_payload = json.loads(openai_client.responses.calls[1]["input"][1]["content"])
    assert second_search_payload["current_round_query"] == "SK브로드밴드 B tv 전략 투자"


def test_harness_attributes_citation_to_matching_registered_domain():
    source = _source()
    other_source = _source(
        name="전자신문 (통신)", url="https://www.etnews.com/news/section.html?id1=03",
        role="search", topics=["IPTV"], reliability_tier="analyst_media",
    )
    all_sources = [source, other_source]
    citation = _citation_annotation("https://www.etnews.com/a/123", title="IPTV 기사")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, all_sources, _KEYWORDS)

    assert len(docs) == 1
    assert docs[0].source_id == "전자신문 (통신)"
    assert docs[0].reliability_tier == "analyst_media"
    assert docs[0].url == "https://www.etnews.com/a/123"


def test_harness_requires_live_search_and_passes_full_question_context():
    source = _source()
    citation = _citation_annotation("https://news.sktelecom.com/context")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl()
    context = WebSearchContext(
        question="KT와 비교한 SK브로드밴드 IPTV 경쟁력은?",
        perspective="competitor_comparison",
        report_purpose_id="current_status",
        information_needs=["competitor_strategy", "market_metrics"],
        suggested_terms=_KEYWORDS,
        as_of_date="2026-08-05",
        country_code="KR",
    )

    docs = run_ai_search_harness(
        openai_client,
        firecrawl_client,
        source,
        [source],
        _KEYWORDS,
        search_context=context,
    )

    assert len(docs) == 1
    call = openai_client.responses.calls[0]
    assert call["tool_choice"] == "required"
    assert call["include"] == ["web_search_call.action.sources"]
    assert call["tools"][0]["external_web_access"] is True
    assert call["tools"][0]["user_location"] == {"type": "approximate", "country": "KR"}
    payload = json.loads(call["input"][1]["content"])
    assert payload["search_context"]["question"] == context.question
    assert payload["search_context"]["information_needs"] == context.information_needs
    assert payload["current_round_query"] == context.question


def test_harness_can_start_from_original_question_without_precomputed_terms():
    source = _source(topics=[])
    citation = _citation_annotation("https://news.sktelecom.com/question-first")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl()
    context = WebSearchContext(question="SK브로드밴드의 최근 AI 미디어 전략은?")

    docs = run_ai_search_harness(
        openai_client,
        firecrawl_client,
        source,
        [source],
        [],
        search_context=context,
    )

    assert len(docs) == 1
    payload = json.loads(openai_client.responses.calls[0]["input"][1]["content"])
    assert payload["current_round_query"] == context.question


def test_harness_can_scrape_grounded_web_search_action_sources():
    source = _source()
    tool_source = types.SimpleNamespace(
        url="https://news.sktelecom.com/from-tool-sources",
        title="검색 도구 후보",
    )
    openai_client = _FakeOpenAI([_response_with_tool_sources([tool_source])])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert len(docs) == 1
    assert docs[0].url == tool_source.url
    assert docs[0].title == tool_source.title


def test_harness_leaves_unregistered_domain_honestly_unattributed():
    source = _source()
    citation = _citation_annotation("https://www.hankyung.com/it/article/123", title="관련 기사")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert len(docs) == 1
    assert docs[0].reliability_tier is None
    assert docs[0].source_id == "www.hankyung.com"
    assert firecrawl_client.scrape_calls == ["https://www.hankyung.com/it/article/123"]


def test_harness_never_uses_a_url_without_a_citation_annotation():
    source = _source()
    # output_text mentions a URL in prose, but no annotation backs it.
    response = types.SimpleNamespace(
        output=[types.SimpleNamespace(type="message", content=[types.SimpleNamespace(annotations=[])])],
        output_text='본문에 https://fake.example.com/hallucinated 언급함\n{"sufficient": true, "next_queries": []}',
    )
    openai_client = _FakeOpenAI([response])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert docs == []
    assert firecrawl_client.scrape_calls == []


def test_harness_drops_documents_shorter_than_min_content_length():
    source = _source()
    citation = _citation_annotation("https://news.sktelecom.com/short-article")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl(markdown_by_url={citation.url: "짧음"})

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS, HarnessConfig(min_content_length=250)
    )

    assert docs == []


def test_harness_retries_a_failed_scrape_exactly_once_by_default():
    source = _source()
    citation = _citation_annotation("https://news.sktelecom.com/transient")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl(markdown_by_url={citation.url: None})

    docs = run_ai_search_harness(
        openai_client,
        firecrawl_client,
        source,
        [source],
        _KEYWORDS,
        HarnessConfig(max_rounds=1),
    )

    assert docs == []
    assert firecrawl_client.scrape_calls == [citation.url, citation.url]


def test_harness_keeps_document_when_single_retry_recovers():
    source = _source()
    citation = _citation_annotation("https://news.sktelecom.com/transient-success")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])

    class _TransientFirecrawl:
        def __init__(self):
            self.scrape_calls = []

        def scrape(self, url, formats):
            self.scrape_calls.append(url)
            if len(self.scrape_calls) == 1:
                raise RuntimeError("temporary failure")
            return types.SimpleNamespace(markdown="복구된 본문" * 100)

    firecrawl_client = _TransientFirecrawl()
    docs = run_ai_search_harness(
        openai_client,
        firecrawl_client,
        source,
        [source],
        _KEYWORDS,
        HarnessConfig(max_rounds=1),
    )

    assert [doc.url for doc in docs] == [citation.url]
    assert firecrawl_client.scrape_calls == [citation.url, citation.url]


def test_harness_default_budget_is_two_candidates_and_one_error_retry_per_url():
    config = HarnessConfig()

    assert config.max_candidates_per_round == 2
    assert config.max_total_scrape_calls == 12
    assert config.max_scrape_retries_per_url == 1
    assert config.min_scraped_docs_for_sufficient == 2


def test_harness_does_not_accept_model_sufficiency_when_scraping_found_nothing():
    source = _source()
    failed_url = "https://news.sktelecom.com/failed"
    recovered_url = "https://news.sktelecom.com/recovered"
    round1 = _response(
        citations=[_citation_annotation(failed_url)],
        sufficient=True,
        next_queries=["실제 원문 재검색"],
    )
    round2 = _response(
        citations=[_citation_annotation(recovered_url)],
        sufficient=True,
        next_queries=["추가 원문 검색"],
    )
    second_recovered_url = "https://news.sktelecom.com/recovered-2"
    round3 = _response(
        citations=[_citation_annotation(second_recovered_url)],
        sufficient=True,
    )
    openai_client = _FakeOpenAI([round1, round2, round3])
    firecrawl_client = _FakeFirecrawl(markdown_by_url={failed_url: None})

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert [doc.url for doc in docs] == [recovered_url, second_recovered_url]
    assert len(openai_client.responses.calls) == 3


def test_harness_caps_candidates_and_total_scrape_calls():
    source = _source()
    citations = [
        _citation_annotation(f"https://news.sktelecom.com/candidate-{index}")
        for index in range(6)
    ]
    openai_client = _FakeOpenAI([_response(citations=citations, sufficient=False)])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client,
        firecrawl_client,
        source,
        [source],
        _KEYWORDS,
        HarnessConfig(
            max_rounds=1,
            target_docs=10,
            max_candidates_per_round=2,
            max_total_scrape_calls=2,
            max_scrape_retries_per_url=1,
        ),
    )

    assert len(docs) == 2
    assert len(firecrawl_client.scrape_calls) == 2


def test_harness_stops_once_target_docs_reached_within_one_round():
    source = _source()
    citations = [
        _citation_annotation("https://news.sktelecom.com/a1", title="기사1"),
        _citation_annotation("https://news.sktelecom.com/a2", title="기사2"),
    ]
    openai_client = _FakeOpenAI([_response(citations=citations, sufficient=False, next_queries=["다른 쿼리"])])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS, HarnessConfig(target_docs=2)
    )

    assert len(docs) == 2
    assert len(openai_client.responses.calls) == 1  # target hit within round 1, no round 2


def test_harness_requires_two_scraped_documents_before_accepting_model_sufficiency():
    source = _source()
    citation1 = _citation_annotation("https://news.sktelecom.com/a1")
    citation2 = _citation_annotation("https://news.sktelecom.com/a2")
    openai_client = _FakeOpenAI([
        _response(citations=[citation1], sufficient=True, next_queries=["두 번째 원문"]),
        _response(citations=[citation2], sufficient=True),
    ])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS, HarnessConfig(target_docs=5)
    )

    assert len(docs) == 2
    assert len(openai_client.responses.calls) == 2


def test_harness_uses_model_proposed_next_queries_across_rounds_not_a_ladder():
    source = _source()
    round1 = _response(citations=[], sufficient=False, next_queries=["대안 쿼리 A", "대안 쿼리 B"])
    round2 = _response(
        citations=[_citation_annotation("https://news.sktelecom.com/found")], sufficient=True
    )
    openai_client = _FakeOpenAI([round1, round2])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert len(docs) == 1
    round2_user_message = openai_client.responses.calls[1]["input"][1]["content"]
    assert "대안 쿼리 A" in round2_user_message


def test_harness_deprioritizes_a_domain_that_already_failed_to_scrape_this_run():
    # Real pattern live-observed against sk_broadband: skbroadband.com's own
    # press pages repeatedly failed to scrape (proxy/tunnel error, timeout)
    # across rounds, while other candidates the model already found for a
    # later round went untried because the failing domain kept winning the
    # per-round top-N slots on relevance alone.
    domain_a_first = "https://a.example.com/press-1"
    domain_a_second = "https://a.example.com/press-2"
    domain_b = "https://b.example.com/article"
    domain_c = "https://c.example.com/article"
    round1 = _response(citations=[_citation_annotation(domain_a_first)], sufficient=False, next_queries=["다음 쿼리"])
    round2 = _response(
        # domain A's new page still ranks first per the model's own order -
        # only our own within-run failure memory should push it back.
        citations=[
            _citation_annotation(domain_a_second),
            _citation_annotation(domain_b),
            _citation_annotation(domain_c),
        ],
        sufficient=True,
    )
    openai_client = _FakeOpenAI([round1, round2])
    firecrawl_client = _FakeFirecrawl(markdown_by_url={domain_a_first: None, domain_a_second: None})

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, _source(), [_source()], _KEYWORDS, HarnessConfig(max_candidates_per_round=2)
    )

    # domain_a_second never gets a scrape attempt at all - deprioritized out
    # of round 2's top-2 selection in favor of the two fresh domains.
    assert domain_a_second not in firecrawl_client.scrape_calls
    assert domain_b in firecrawl_client.scrape_calls
    assert domain_c in firecrawl_client.scrape_calls
    assert len(docs) == 2


def test_harness_never_scrapes_a_registry_blocked_domain():
    # SectorProfile.blocked_scrape_domains -> WebSearchContext.excluded_domains:
    # a site the scrape provider currently cannot reach at all (verified
    # 2026-08-06 for skbroadband.com) must not consume candidate slots or
    # scrape budget, even though the model still surfaces it as relevant.
    blocked = "https://www.blocked.example.com/press-1"
    blocked_subdomain = "https://corp.blocked.example.com/press-2"
    allowed = "https://allowed.example.com/article"
    response = _response(
        citations=[
            _citation_annotation(blocked),
            _citation_annotation(blocked_subdomain),
            _citation_annotation(allowed),
        ],
        sufficient=True,
    )
    openai_client = _FakeOpenAI([response])
    firecrawl_client = _FakeFirecrawl()
    context = WebSearchContext(question="질문", excluded_domains=["blocked.example.com"])

    docs = run_question_search_harness(
        openai_client, firecrawl_client, [_source()], _KEYWORDS, HarnessConfig(), context
    )

    assert firecrawl_client.scrape_calls == [allowed]
    assert [doc.url for doc in docs] == [allowed]


def test_harness_tells_the_model_about_excluded_domains():
    openai_client = _FakeOpenAI([_response(citations=[], sufficient=True)])
    context = WebSearchContext(question="질문", excluded_domains=["blocked.example.com"])

    run_question_search_harness(
        openai_client, _FakeFirecrawl(), [_source()], _KEYWORDS, HarnessConfig(), context
    )

    system_prompt = openai_client.responses.calls[0]["input"][0]["content"]
    payload = json.loads(openai_client.responses.calls[0]["input"][1]["content"])
    assert "excluded_domains" in system_prompt
    assert payload["search_context"]["excluded_domains"] == ["blocked.example.com"]


def test_harness_falls_back_to_deterministic_query_when_judgment_unparseable():
    source = _source(topics=["B tv 신규 서비스"])
    round1 = _response(citations=[], sufficient=False, include_judgment=False)  # no JSON block at all
    round2 = _response(citations=[_citation_annotation("https://news.sktelecom.com/found")], sufficient=True)
    openai_client = _FakeOpenAI([round1, round2])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert len(docs) == 1
    round2_user_message = openai_client.responses.calls[1]["input"][1]["content"]
    assert "B tv 신규 서비스" in round2_user_message  # source.topics-based fallback query


def test_harness_stops_when_model_and_fallback_both_exhausted(monkeypatch):
    source = _source(topics=[])  # no topics -> fallback reuses question_keywords[:2]
    round1 = _response(citations=[], sufficient=False, next_queries=[])
    openai_client = _FakeOpenAI([round1])
    firecrawl_client = _FakeFirecrawl()

    # Fallback query would equal the initial query (same question_keywords[:2]
    # source), so the harness must stop rather than loop forever.
    monkeypatch.setattr(harness_module, "_fallback_next_query", lambda *a, **k: None)

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert docs == []
    assert len(openai_client.responses.calls) == 1


def test_harness_stops_on_diminishing_returns_even_if_model_says_insufficient():
    source = _source()
    same_citation = _citation_annotation("https://news.sktelecom.com/repeat")
    round1 = _response(citations=[same_citation], sufficient=False, next_queries=["재시도 쿼리"])
    round2 = _response(citations=[same_citation], sufficient=False, next_queries=["재시도 쿼리2"])
    openai_client = _FakeOpenAI([round1, round2])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS, HarnessConfig(target_docs=5)
    )

    assert len(docs) == 1  # only the one real document, deduped by URL
    assert len(openai_client.responses.calls) == 2  # stopped after round 2's zero *new* urls


def test_harness_stops_at_max_rounds_when_still_insufficient():
    # Each round finds one *new* citation (so diminishing-returns never
    # triggers) but never reaches target_docs, so max_rounds is the only
    # thing that ends the loop.
    source = _source()
    round1 = _response(
        citations=[_citation_annotation("https://news.sktelecom.com/a1")], sufficient=False, next_queries=["다음 시도1"]
    )
    round2 = _response(
        citations=[_citation_annotation("https://news.sktelecom.com/a2")], sufficient=False, next_queries=["다음 시도2"]
    )
    round3 = _response(
        citations=[_citation_annotation("https://news.sktelecom.com/a3")], sufficient=False, next_queries=["다음 시도3"]
    )
    openai_client = _FakeOpenAI([round1, round2, round3])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS,
        HarnessConfig(max_rounds=3, target_docs=10),
    )

    assert len(docs) == 3
    assert len(openai_client.responses.calls) == 3


def test_harness_stops_early_when_all_rounds_find_nothing():
    source = _source()
    empty_round = _response(citations=[], sufficient=False, next_queries=["다음 시도"])
    openai_client = _FakeOpenAI([empty_round, empty_round, empty_round])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS, HarnessConfig(max_rounds=3)
    )

    assert docs == []
    # round 1 finding zero is not "diminishing returns" (no baseline yet), but
    # round 2 finding zero *new* results again is -> stops after round 2.
    assert len(openai_client.responses.calls) == 2


def test_harness_recovers_from_call_exception_without_raising():
    source = _source()
    openai_client = _FakeOpenAI([RuntimeError("boom")])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert docs == []


def test_harness_short_circuits_when_no_query_can_be_built():
    source = _source(topics=[])
    openai_client = _FakeOpenAI([])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], [])

    assert docs == []
    assert openai_client.responses.calls == []


def test_doc_id_is_consistent_across_search_slots_for_the_same_attributed_source():
    # Two different search "slots" (competitor_official vs official) both
    # find the same URL, which both attribute to the same registered source
    # -> doc_id must match so processor.py's existing dedup collapses them.
    official = _source(name="SK브로드밴드 뉴스룸", url="https://news.sktelecom.com/tag/skbroadband")
    competitor = _source(name="KT 뉴스룸", url="https://corp.kt.com/news", role="competitor_official")
    all_sources = [official, competitor]
    url = "https://news.sktelecom.com/shared-article"

    source_id_from_official_slot, _ = _attribute_source(url, all_sources)
    source_id_from_competitor_slot, _ = _attribute_source(url, all_sources)

    assert source_id_from_official_slot == source_id_from_competitor_slot == "SK브로드밴드 뉴스룸"
    assert _doc_id(source_id_from_official_slot, url) == _doc_id(source_id_from_competitor_slot, url)


def test_parse_round_judgment_returns_false_and_empty_on_garbage_text():
    response = types.SimpleNamespace(output=[], output_text="이건 그냥 산문이고 JSON이 아닙니다.")

    sufficient, next_queries = _parse_round_judgment(response)

    assert sufficient is False
    assert next_queries == []


def test_initial_query_anchors_vague_self_reference_to_company_name():
    context = WebSearchContext(
        question="우리회사 매출 추이 알려주고 앞으로 전망 알려줘",
        company_name="SK브로드밴드",
    )

    query = _initial_query(None, [], context)

    assert query == "SK브로드밴드 우리회사 매출 추이 알려주고 앞으로 전망 알려줘"


def test_initial_query_does_not_duplicate_company_name_already_in_question():
    context = WebSearchContext(
        question="SK브로드밴드 매출 추이는?",
        company_name="SK브로드밴드",
    )

    query = _initial_query(None, [], context)

    assert query == "SK브로드밴드 매출 추이는?"


def test_initial_query_unchanged_when_no_company_name():
    context = WebSearchContext(question="시장 동향은?")

    query = _initial_query(None, [], context)

    assert query == "시장 동향은?"
