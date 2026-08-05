import json
import types

from common.contracts import PlannedSource
from sources.collectors import ai_search_harness as harness_module
from sources.collectors.ai_search_harness import (
    HarnessConfig,
    _attribute_source,
    _doc_id,
    _parse_round_judgment,
    run_ai_search_harness,
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


class _FakeResponses:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("no more fake responses queued")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeOpenAI:
    def __init__(self, responses):
        self.responses = _FakeResponses(responses)


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


def test_harness_does_not_stop_on_sufficient_when_every_citation_failed_to_scrape():
    # Live-verified gap (2026-08-05): the model judges "sufficient" right
    # after seeing citations, before it's known whether Firecrawl can even
    # scrape them (e.g. a domain Firecrawl can't reach at all). If every
    # citation in the round fails to scrape, "sufficient" must not be
    # trusted -- the harness should keep going instead of returning nothing.
    source = _source(topics=["B tv 신규 서비스"])
    unscrapable_citation = _citation_annotation("https://news.sktelecom.com/blocked")
    round1 = _response(citations=[unscrapable_citation], sufficient=True, next_queries=[])
    round2_citation = _citation_annotation("https://news.sktelecom.com/found")
    round2 = _response(citations=[round2_citation], sufficient=True)
    openai_client = _FakeOpenAI([round1, round2])
    firecrawl_client = _FakeFirecrawl(markdown_by_url={unscrapable_citation.url: None})  # raises -> scrape fails

    docs = run_ai_search_harness(openai_client, firecrawl_client, source, [source], _KEYWORDS)

    assert len(docs) == 1
    assert docs[0].url == round2_citation.url
    assert len(openai_client.responses.calls) == 2  # round 1's false "sufficient" did not end the loop
    round2_user_message = openai_client.responses.calls[1]["input"][1]["content"]
    assert "B tv 신규 서비스" in round2_user_message  # fell back to source.topics since next_queries was empty


def test_harness_stops_when_model_says_sufficient_even_below_target_docs():
    source = _source()
    citation = _citation_annotation("https://news.sktelecom.com/a1")
    openai_client = _FakeOpenAI([_response(citations=[citation], sufficient=True)])
    firecrawl_client = _FakeFirecrawl()

    docs = run_ai_search_harness(
        openai_client, firecrawl_client, source, [source], _KEYWORDS, HarnessConfig(target_docs=5)
    )

    assert len(docs) == 1
    assert len(openai_client.responses.calls) == 1


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
