import json
import types

import pytest

from common.contracts import (
    PlannedSource,
    SourceCollectionResult,
    SourceDocument,
    SourcePlan,
    WebSearchContext,
    WebSearchHarnessResult,
)
from common.errors import PipelineStageError
from core.source_planner.query_strategy import build_source_search_terms
from sectors.sk_broadband.adapter import analyzer as analyzer_module
from sectors.sk_broadband.adapter import collector as collector_module
from sectors.sk_broadband.adapter.analyzer import analyze
from sectors.sk_broadband.adapter.collector import _crawl_source, collect
from sectors.sk_broadband.adapter.processor import process
from sectors.sk_broadband.adapter.validator import validate


def _collected_documents(result):
    return result.documents if isinstance(result, SourceCollectionResult) else result


def _make_result(markdown, title="제목", url="https://example.com/article", published_time="2026-01-01T00:00:00+09:00"):
    metadata = types.SimpleNamespace(title=title, url=url, published_time=published_time)
    return types.SimpleNamespace(markdown=markdown, metadata=metadata, title=title, url=url)


def _search_data(results):
    return types.SimpleNamespace(web=results)


class _FastClient:
    def __init__(self, results):
        self._results = results

    def search(self, query, include_domains, limit, scrape_options):
        return _search_data(self._results)

    def scrape(self, url, formats):
        return types.SimpleNamespace(markdown="직접 스크랩 본문" * 100)


def test_broadband_web_source_collects_real_search_result():
    source = PlannedSource(
        name="전자신문 (통신)",
        url="https://www.etnews.com/news/section.html?id1=03",
        collection_method=["firecrawl_search"],
        reliability_tier="analyst_media",
    )
    result = _make_result("본문" * 200, title="OTT 시장 변화", url="https://www.etnews.com/a")

    docs = _crawl_source(_FastClient([result]), source, "test-key", ["OTT", "IPTV"])

    assert len(docs) == 1
    assert docs[0].source_id == "전자신문 (통신)"
    assert docs[0].reliability_tier == "analyst_media"
    assert docs[0].url == "https://www.etnews.com/a"


def test_broadband_web_source_scrapes_search_result_url_when_markdown_is_missing():
    source = PlannedSource(
        name="네이버 뉴스",
        url="https://news.naver.com",
        collection_method=["crawling"],
        planning_priority="core",
    )
    result = _make_result(None, title="검색 결과", url="https://n.news.naver.com/article/001/1")

    docs = _crawl_source(_FastClient([result]), source, "test-key", ["IPTV", "OTT"])

    assert len(docs) == 1
    assert docs[0].source_id == "네이버 뉴스"
    assert docs[0].content.startswith("직접 스크랩 본문")


def test_broadband_web_source_uses_site_query_after_domain_search_is_empty():
    source = PlannedSource(name="네이버 뉴스", url="https://news.naver.com", planning_priority="core")
    result = _make_result("네이버 기사 본문" * 100, url="https://news.naver.com/main/read.naver?id=1")

    class _SiteFallbackClient:
        def search(self, query, include_domains, limit, scrape_options):
            return _search_data([result] if include_domains == [] and query.startswith("site:news.naver.com") else [])

    docs = _crawl_source(_SiteFallbackClient(), source, "test-key", ["IPTV", "OTT"])

    assert len(docs) == 1
    assert docs[0].url.startswith("https://news.naver.com/")


def test_competitor_and_regulatory_searches_put_registry_topics_first():
    competitor = PlannedSource(
        name="KT 뉴스룸",
        url="https://corp.kt.com/news",
        role="competitor_official",
        topics=["KT 지니TV", "IPTV"],
    )
    official = PlannedSource(
        name="SK브로드밴드 뉴스룸",
        url="https://news.sktelecom.com/skb",
        role="official",
        topics=["B tv"],
    )
    question_terms = ["SK브로드밴드", "경쟁 현황", "IPTV"]

    assert build_source_search_terms(competitor, question_terms)[:2] == ["IPTV", "KT 지니TV"]
    assert build_source_search_terms(official, question_terms)[:2] == ["SK브로드밴드", "경쟁 현황"]


def test_broadband_kofic_source_uses_pdf_helper(monkeypatch):
    source = PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        collection_method=["kofic_pdf_post_download", "firecrawl_parse"],
        reliability_tier="official",
    )
    search_result = _make_result(
        "상세 링크",
        title="KOFIC 보고서",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=69184",
    )
    attachment = types.SimpleNamespace(download_name="2025년 상반기 한국 영화산업 결산 보고서.pdf")
    parsed = types.SimpleNamespace(detail_url=search_result.url, attachment=attachment, markdown="KOFIC PDF 본문" * 100)
    monkeypatch.setattr(collector_module, "collect_pdf_markdown_from_detail_url", lambda detail_url, api_key: parsed)
    # No question/openai_api_key passed via _crawl_source's legacy path, so
    # search-discovery itself would normally return [] (no GPT query, no
    # ladder fallback anymore) - stub the query generator so this test can
    # still exercise "a search result was found -> PDF helper is used".
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "영화산업")

    docs = _crawl_source(_FastClient([search_result]), source, "test-key", ["영화산업", "OTT"])

    assert len(docs) == 1
    assert docs[0].title == "2025년 상반기 한국 영화산업 결산 보고서.pdf"
    assert docs[0].source_id == "영화진흥위원회(KOFIC)"
    assert docs[0].content.startswith("KOFIC PDF 본문")


# Trimmed excerpt of kofic.or.kr's real listing-page JS (live-verified
# 2026-08-06): the only literal "selectBoardDetail.do?boardNumber=2" text on
# the page is inside this function *definition* - missing boardSeqNumber
# entirely, and a URL built from it 420s. The real per-post id only exists
# in each row's own onclick handler further down.
_KOFIC_LISTING_JS_EXCERPT = """
    function fn_detailPage(boardSeqNumber){
        var form = $("#form_searchBoardList")[0];
        form.method = "post";
        form.action =
            "selectBoardDetail.do?boardNumber=2"
            + "&boardSeqNumber=" + encodeURIComponent(boardSeqNumber);
        form.submit();
    }
"""
_KOFIC_LISTING_ROW_EXCERPT = (
    '<a href="#none" onclick="fn_goDetailPage(74481 , \'10031001\' , \'\');return false;">'
    "2026년 상반기 한국 영화산업 결산 보고서</a>"
    '<a href="#none" onclick="fn_zipFileDownload(\'2\',\'74481\',\'1\')">'
    '<img src="/kofic/comm/img/common/icon_diskette.png" /></a>'
)


def test_extract_kofic_board_seq_numbers_ignores_the_js_template_and_finds_real_row_ids():
    seq_numbers = collector_module._extract_kofic_board_seq_numbers(
        _KOFIC_LISTING_JS_EXCERPT + _KOFIC_LISTING_ROW_EXCERPT
    )

    # "2" (from the broken template's "boardNumber=2") must never appear -
    # only the real per-post id from fn_goDetailPage/fn_zipFileDownload.
    assert seq_numbers == ["74481"]


def test_extract_kofic_board_seq_numbers_dedupes_same_id_from_both_handlers():
    html = (
        '<a onclick="fn_goDetailPage(74481, \'10031001\', \'\');return false;">제목</a>'
        '<a onclick="fn_zipFileDownload(\'2\',\'74481\',\'1\')"><img /></a>'
    )

    assert collector_module._extract_kofic_board_seq_numbers(html) == ["74481"]


def test_build_kofic_detail_url_uses_board_number_from_registered_source_url():
    url = collector_module._build_kofic_detail_url(
        "https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        "74481",
    )

    assert url == (
        "https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do"
        "?boardNumber=2&boardSeqNumber=74481"
    )


def test_build_kofic_detail_url_returns_none_without_a_board_number():
    url = collector_module._build_kofic_detail_url(
        "https://www.kofic.or.kr/kofic/business/board/selectBoardList.do", "74481"
    )

    assert url is None


def test_discover_kofic_detail_urls_from_listing_builds_real_urls_not_the_broken_template(monkeypatch):
    source = PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        collection_method=["kofic_pdf_post_download"],
    )
    fake_response = types.SimpleNamespace(
        text=_KOFIC_LISTING_JS_EXCERPT + _KOFIC_LISTING_ROW_EXCERPT,
        encoding="utf-8",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(collector_module.requests, "get", lambda *a, **k: fake_response)

    urls = collector_module._discover_kofic_detail_urls_from_listing(source)

    assert urls == [
        "https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do"
        "?boardNumber=2&boardSeqNumber=74481"
    ]


def test_crawl_kofic_pdf_source_logs_when_no_post_ids_are_discovered(monkeypatch, capsys):
    source = PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        collection_method=["kofic_pdf_post_download"],
    )
    monkeypatch.setattr(collector_module, "_discover_kofic_detail_urls_from_search", lambda *a, **k: [])
    monkeypatch.setattr(collector_module, "_discover_kofic_detail_urls_from_listing", lambda *a, **k: [])

    docs = collector_module._crawl_kofic_pdf_source(_FastClient([]), source, "test-key", ["영화산업"])

    assert docs == []
    assert "no post ids discovered" in capsys.readouterr().err


class _FakeChatOpenAI:
    """Fake for the `from openai import OpenAI` done inline inside
    _ai_source_gate_relevant/_ai_select_relevant_candidates - patched via
    monkeypatch.setattr("openai.OpenAI", ...) since the import happens at
    call time, not at collector_module's top level."""

    def __init__(self, content=None, raise_error=False):
        self._content = content
        self._raise_error = raise_error
        self.calls: list[dict] = []

    def __call__(self, api_key):  # instantiated as OpenAI(api_key=...)
        return self

    @property
    def chat(self):
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._raise_error:
                    raise RuntimeError("simulated API failure")
                message = types.SimpleNamespace(content=outer._content, refusal=None)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        return types.SimpleNamespace(completions=_Completions())


def _kofic_source(topics=None):
    return PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        collection_method=["kofic_pdf_post_download"],
        topics=topics if topics is not None else ["영화산업", "박스오피스", "콘텐츠 소비"],
    )


def test_extract_kofic_board_seq_and_titles_pairs_seq_with_its_title():
    pairs = collector_module._extract_kofic_board_seq_and_titles(
        _KOFIC_LISTING_JS_EXCERPT + _KOFIC_LISTING_ROW_EXCERPT
    )

    assert pairs == [("74481", "2026년 상반기 한국 영화산업 결산 보고서")]


def test_kofic_question_gate_fails_open_without_openai_key():
    assert collector_module._ai_source_gate_relevant("IPTV 사업 현황은?", _kofic_source(), None) is True


def test_kofic_question_gate_fails_open_without_registered_topics():
    assert collector_module._ai_source_gate_relevant("IPTV 사업 현황은?", _kofic_source(topics=[]), "key") is True


def test_kofic_question_gate_fails_open_without_a_question():
    assert collector_module._ai_source_gate_relevant("", _kofic_source(), "key") is True


def test_kofic_question_gate_returns_model_judgment_when_irrelevant(monkeypatch):
    fake = _FakeChatOpenAI(content=json.dumps({"relevant": False}))
    monkeypatch.setattr("openai.OpenAI", fake)

    result = collector_module._ai_source_gate_relevant("SK브로드밴드 IPTV 사업 현황은?", _kofic_source(), "key")

    assert result is False
    assert len(fake.calls) == 1


def test_kofic_question_gate_returns_model_judgment_when_relevant(monkeypatch):
    fake = _FakeChatOpenAI(content=json.dumps({"relevant": True}))
    monkeypatch.setattr("openai.OpenAI", fake)

    result = collector_module._ai_source_gate_relevant("영화 콘텐츠 소비 동향은?", _kofic_source(), "key")

    assert result is True


def test_kofic_question_gate_fails_open_on_api_error(monkeypatch, capsys):
    monkeypatch.setattr("openai.OpenAI", _FakeChatOpenAI(raise_error=True))

    result = collector_module._ai_source_gate_relevant("IPTV 사업 현황은?", _kofic_source(), "key")

    assert result is True
    assert "relevance gate call failed" in capsys.readouterr().err


def test_ai_select_relevant_candidates_returns_none_without_openai_key():
    posts = [("1", "제목1"), ("2", "제목2")]

    assert collector_module._ai_select_relevant_candidates("질문", posts, None) is None


def test_ai_select_relevant_candidates_returns_none_without_a_question():
    posts = [("1", "제목1")]

    assert collector_module._ai_select_relevant_candidates("", posts, "key") is None


def test_ai_select_relevant_candidates_filters_to_model_selected_ids(monkeypatch):
    posts = [("1", "무관한 제목"), ("2", "질문과 관련된 제목")]
    fake = _FakeChatOpenAI(content=json.dumps({"relevant_ids": ["2"]}))
    monkeypatch.setattr("openai.OpenAI", fake)

    result = collector_module._ai_select_relevant_candidates("질문", posts, "key")

    assert result == ["2"]


def test_ai_select_relevant_candidates_ignores_hallucinated_ids_not_in_the_candidate_list(monkeypatch):
    posts = [("1", "제목1")]
    # Model returns an id that was never offered - must be dropped, not trusted.
    fake = _FakeChatOpenAI(content=json.dumps({"relevant_ids": ["1", "999"]}))
    monkeypatch.setattr("openai.OpenAI", fake)

    result = collector_module._ai_select_relevant_candidates("질문", posts, "key")

    assert result == ["1"]


def test_ai_select_relevant_candidates_can_return_an_empty_but_meaningful_list(monkeypatch):
    posts = [("1", "무관한 제목")]
    fake = _FakeChatOpenAI(content=json.dumps({"relevant_ids": []}))
    monkeypatch.setattr("openai.OpenAI", fake)

    result = collector_module._ai_select_relevant_candidates("질문", posts, "key")

    assert result == []  # genuinely "found nothing relevant" - distinct from None


def test_ai_select_relevant_candidates_returns_none_on_api_error(monkeypatch, capsys):
    posts = [("1", "제목1")]
    monkeypatch.setattr("openai.OpenAI", _FakeChatOpenAI(raise_error=True))

    result = collector_module._ai_select_relevant_candidates("질문", posts, "key")

    assert result is None
    assert "post-selection call failed" in capsys.readouterr().err


def test_crawl_kofic_pdf_source_skips_entirely_when_gate_says_irrelevant(monkeypatch):
    source = _kofic_source()
    monkeypatch.setattr(collector_module, "_ai_source_gate_relevant", lambda *a, **k: False)
    monkeypatch.setattr(
        collector_module, "_discover_kofic_detail_urls_from_search",
        lambda *a, **k: pytest.fail("discovery must not run once the gate says irrelevant"),
    )

    docs = collector_module._crawl_kofic_pdf_source(
        _FastClient([]), source, "test-key", ["영화산업"], question="SK브로드밴드 IPTV 사업 현황은?", openai_api_key="key",
    )

    assert docs == []


def test_discover_kofic_detail_urls_from_listing_uses_model_selected_posts_not_blind_newest(monkeypatch):
    source = _kofic_source()
    two_posts_html = (
        '<a onclick="fn_goDetailPage(74481, \'x\', \'\');return false;">무관한 최신글</a>'
        '<a onclick="fn_goDetailPage(74480, \'x\', \'\');return false;">두번째로 최신인 글</a>'
    )
    fake_response = types.SimpleNamespace(text=two_posts_html, encoding="utf-8", raise_for_status=lambda: None)
    monkeypatch.setattr(collector_module.requests, "get", lambda *a, **k: fake_response)
    # The blind (question-less) behavior would pick 74481 (the newest) - the
    # model instead picks 74480, proving the listing path actually uses the
    # selection instead of just taking the top of the page.
    monkeypatch.setattr(
        collector_module, "_ai_select_relevant_candidates", lambda question, posts, key: ["74480"]
    )

    urls = collector_module._discover_kofic_detail_urls_from_listing(source, "질문", "key")

    assert urls == [
        "https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=74480"
    ]


def test_discover_kofic_detail_urls_from_listing_falls_back_to_blind_newest_when_selection_unavailable(monkeypatch):
    source = _kofic_source()
    fake_response = types.SimpleNamespace(
        text=_KOFIC_LISTING_JS_EXCERPT + _KOFIC_LISTING_ROW_EXCERPT,
        encoding="utf-8",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(collector_module.requests, "get", lambda *a, **k: fake_response)
    monkeypatch.setattr(collector_module, "_ai_select_relevant_candidates", lambda *a, **k: None)

    urls = collector_module._discover_kofic_detail_urls_from_listing(source, "", None)

    assert urls == [
        "https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do"
        "?boardNumber=2&boardSeqNumber=74481"
    ]


class _RecordingSearchClient:
    """Fake Firecrawl client that records every query it was searched with,
    so a test can prove which query (GPT-generated vs. rule-based ladder)
    actually reached client.search()."""

    def __init__(self, results_by_query=None, default_results=None):
        self.results_by_query = results_by_query or {}
        self.default_results = default_results if default_results is not None else []
        self.search_calls: list[str] = []

    def search(self, query, include_domains, limit, scrape_options):
        self.search_calls.append(query)
        return types.SimpleNamespace(web=self.results_by_query.get(query, self.default_results))


def test_ai_generate_search_query_returns_none_without_openai_key():
    assert collector_module._ai_generate_search_query("IPTV 가입자 수는?", _kofic_source(), None) is None


def test_ai_generate_search_query_returns_none_without_a_question():
    assert collector_module._ai_generate_search_query("", _kofic_source(), "key") is None


def test_ai_generate_search_query_returns_model_query(monkeypatch):
    fake = _FakeChatOpenAI(content=json.dumps({"query": "IPTV VOD 이용 건수"}))
    monkeypatch.setattr("openai.OpenAI", fake)

    query = collector_module._ai_generate_search_query("SK브로드밴드 IPTV 가입자 수는?", _kofic_source(), "key")

    assert query == "IPTV VOD 이용 건수"
    assert len(fake.calls) == 1


def test_ai_generate_search_query_returns_none_on_api_error(monkeypatch, capsys):
    monkeypatch.setattr("openai.OpenAI", _FakeChatOpenAI(raise_error=True))

    query = collector_module._ai_generate_search_query("IPTV 가입자 수는?", _kofic_source(), "key")

    assert query is None
    assert "search-query generation failed" in capsys.readouterr().err


def test_discover_kofic_detail_urls_from_search_uses_gpt_query_first(monkeypatch):
    source = _kofic_source()
    result = _make_result(
        "본문" * 100, url="https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=74481"
    )
    client = _RecordingSearchClient(results_by_query={"IPTV VOD 이용 건수": [result]})
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "IPTV VOD 이용 건수")

    urls = collector_module._discover_kofic_detail_urls_from_search(
        client, source, ["영화산업"], question="IPTV 가입자 수는?", openai_api_key="key",
    )

    assert client.search_calls == ["IPTV VOD 이용 건수"]  # rule-based ladder never queried
    assert urls == [
        "https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=74481"
    ]


def test_discover_kofic_detail_urls_from_search_returns_empty_when_gpt_query_unavailable(monkeypatch):
    # No rule-based ladder fallback anymore - a missing/failed GPT query
    # means this function contributes nothing, full stop. The listing-page
    # path (with its own GPT selection, then its own blind-newest fallback)
    # is what actually catches this case, not a second search attempt here.
    source = _kofic_source()
    result = _make_result(
        "본문" * 100, url="https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=1"
    )
    client = _RecordingSearchClient(default_results=[result])
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: None)

    urls = collector_module._discover_kofic_detail_urls_from_search(
        client, source, ["영화산업"], question="", openai_api_key=None,
    )

    assert client.search_calls == []  # never even called client.search()
    assert urls == []


def test_discover_kofic_detail_urls_from_search_returns_empty_when_gpt_query_finds_nothing(monkeypatch):
    source = _kofic_source()
    client = _RecordingSearchClient(results_by_query={"무관한 쿼리": []})
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "무관한 쿼리")

    urls = collector_module._discover_kofic_detail_urls_from_search(
        client, source, ["영화산업"], question="질문", openai_api_key="key",
    )

    assert client.search_calls == ["무관한 쿼리"]  # tried exactly once, no second attempt
    assert urls == []


def _ai_gated_source(topics=None):
    """A generic non-KOFIC source registered with the reusable
    "ai_gated_search" collection_method - no listing page, no PDF, just plain
    web articles reached through Firecrawl's domain-restricted search."""
    return PlannedSource(
        name="예시 산업 통계 포털",
        url="https://stats.example-media.co.kr/reports",
        collection_method=["ai_gated_search"],
        reliability_tier="official",
        topics=topics if topics is not None else ["IPTV 시장 통계", "미디어 통계"],
    )


def test_crawl_source_with_ai_gated_search_skips_entirely_when_gate_says_irrelevant(monkeypatch):
    source = _ai_gated_source()
    monkeypatch.setattr(collector_module, "_ai_source_gate_relevant", lambda *a, **k: False)

    def _fail_if_called(*a, **k):
        raise AssertionError("query generation must not run once the gate says irrelevant")

    monkeypatch.setattr(collector_module, "_ai_generate_search_query", _fail_if_called)

    docs = collector_module._crawl_source_with_ai_gated_search(
        _RecordingSearchClient(), source, question="무관한 질문", openai_api_key="key"
    )

    assert docs == []


def test_crawl_source_with_ai_gated_search_returns_empty_when_query_unavailable(monkeypatch):
    # Same "no rule-based ladder fallback" policy as KOFIC's search discovery
    # - a missing/failed GPT query means this source contributes nothing.
    source = _ai_gated_source()
    client = _RecordingSearchClient(default_results=[_make_result("본문" * 100)])
    monkeypatch.setattr(collector_module, "_ai_source_gate_relevant", lambda *a, **k: True)
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: None)

    docs = collector_module._crawl_source_with_ai_gated_search(
        client, source, question="IPTV 시장 규모는?", openai_api_key="key"
    )

    assert client.search_calls == []
    assert docs == []


def test_crawl_source_with_ai_gated_search_returns_empty_when_query_finds_nothing(monkeypatch):
    source = _ai_gated_source()
    client = _RecordingSearchClient(results_by_query={"IPTV 시장 통계": []})
    monkeypatch.setattr(collector_module, "_ai_source_gate_relevant", lambda *a, **k: True)
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "IPTV 시장 통계")

    docs = collector_module._crawl_source_with_ai_gated_search(
        client, source, question="질문", openai_api_key="key"
    )

    assert client.search_calls == ["IPTV 시장 통계"]  # tried exactly once, no second attempt
    assert docs == []


def test_crawl_source_with_ai_gated_search_builds_documents_from_model_query(monkeypatch):
    source = _ai_gated_source()
    result = _make_result("보고서 본문" * 100, title="IPTV 시장 통계 2026", url="https://stats.example-media.co.kr/reports/1")
    client = _RecordingSearchClient(results_by_query={"IPTV 가입자 통계": [result]})
    monkeypatch.setattr(collector_module, "_ai_source_gate_relevant", lambda *a, **k: True)
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "IPTV 가입자 통계")

    docs = collector_module._crawl_source_with_ai_gated_search(
        client, source, question="IPTV 가입자 수는?", openai_api_key="key"
    )

    assert client.search_calls == ["IPTV 가입자 통계"]
    assert len(docs) == 1
    assert docs[0].source_id == source.name
    assert docs[0].url == "https://stats.example-media.co.kr/reports/1"
    assert docs[0].title == "IPTV 시장 통계 2026"
    assert docs[0].content == "보고서 본문" * 100
    assert docs[0].reliability_tier == "official"


def test_crawl_source_with_ai_gated_search_scrapes_when_markdown_is_missing(monkeypatch):
    source = _ai_gated_source()
    result = _make_result(None, url="https://stats.example-media.co.kr/reports/2")
    client = _RecordingSearchClient(results_by_query={"쿼리": [result]})
    client.scrape = lambda url, formats: types.SimpleNamespace(markdown="직접 스크랩 본문" * 100)
    monkeypatch.setattr(collector_module, "_ai_source_gate_relevant", lambda *a, **k: True)
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "쿼리")

    docs = collector_module._crawl_source_with_ai_gated_search(
        client, source, question="질문", openai_api_key="key"
    )

    assert len(docs) == 1
    assert docs[0].content == "직접 스크랩 본문" * 100


def test_crawl_special_source_dispatches_ai_gated_search_method(monkeypatch):
    source = _ai_gated_source()
    calls = []
    monkeypatch.setattr(
        collector_module,
        "_crawl_source_with_ai_gated_search",
        lambda client, src, question="", openai_api_key=None: calls.append((src.name, question, openai_api_key))
        or ["sentinel"],
    )

    result = collector_module._crawl_special_source(
        _RecordingSearchClient(), source, "firecrawl-key", ["키워드"], question="질문", openai_api_key="ai-key"
    )

    assert result == ["sentinel"]
    assert calls == [(source.name, "질문", "ai-key")]


def test_crawl_special_source_dispatches_kofic_pdf_method(monkeypatch):
    source = _kofic_source()
    calls = []
    monkeypatch.setattr(
        collector_module,
        "_crawl_kofic_pdf_source",
        lambda client, src, api_key, keywords, question="", openai_api_key=None: calls.append(
            (src.name, api_key, keywords, question, openai_api_key)
        )
        or ["sentinel"],
    )

    result = collector_module._crawl_special_source(
        _RecordingSearchClient(), source, "firecrawl-key", ["영화산업"], question="질문", openai_api_key="ai-key"
    )

    assert result == ["sentinel"]
    assert calls == [(source.name, "firecrawl-key", ["영화산업"], "질문", "ai-key")]


def test_crawl_special_source_returns_empty_for_a_source_with_no_special_method():
    source = PlannedSource(name="일반", url="https://example.com", collection_method=["firecrawl_search"])

    result = collector_module._crawl_special_source(
        _RecordingSearchClient(), source, "firecrawl-key", ["키워드"]
    )

    assert result == []


def test_crawl_source_dispatches_ai_gated_search_in_the_legacy_per_source_path(monkeypatch):
    source = _ai_gated_source()
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "ai-key")

    def _fail_if_called(*a, **k):
        raise AssertionError("legacy Firecrawl keyword search must not run for an ai_gated_search source")

    monkeypatch.setattr(collector_module, "_crawl_web_source", _fail_if_called)
    calls = []
    monkeypatch.setattr(
        collector_module,
        "_crawl_source_with_ai_gated_search",
        lambda client, src, question="", openai_api_key=None: calls.append((src.name, question, openai_api_key))
        or ["sentinel"],
    )

    result = _crawl_source(
        _RecordingSearchClient(),
        source,
        "firecrawl-key",
        ["키워드"],
        search_context=WebSearchContext(question="IPTV 시장 규모는?"),
    )

    assert result == ["sentinel"]
    assert calls == [(source.name, "IPTV 시장 규모는?", "ai-key")]


def test_crawl_source_ai_gated_search_uses_empty_question_without_search_context(monkeypatch):
    source = _ai_gated_source()
    monkeypatch.delenv(collector_module._HARNESS_API_KEY_ENV_VAR, raising=False)
    calls = []
    monkeypatch.setattr(
        collector_module,
        "_crawl_source_with_ai_gated_search",
        lambda client, src, question="", openai_api_key=None: calls.append((question, openai_api_key)) or [],
    )

    _crawl_source(_RecordingSearchClient(), source, "firecrawl-key", ["키워드"])

    assert calls == [("", None)]


def test_broadband_question_harness_treats_ai_gated_search_source_as_special(monkeypatch):
    """Same guarantee as KOFIC (test_broadband_question_harness_keeps_special_
    kofic_collector): a source registered with "ai_gated_search" always runs
    its own dedicated collector, regardless of whether the question-level
    harness's own top-N selection would have included it."""
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    web_source = PlannedSource(name="뉴스", url="https://news.example.com", collection_method=["firecrawl_search"])
    gated = _ai_gated_source()
    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        planned_sources=[web_source],  # the ai_gated_search source may be outside the legacy top-N
        registered_sources=[web_source, gated],
        question_keywords=["OTT"],
    )
    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: object())
    monkeypatch.setattr(
        collector_module,
        "_run_question_ai_harness",
        lambda *args: WebSearchHarnessResult(
            documents=[
                SourceDocument(doc_id="w1", source_id="뉴스", url="https://news.example.com/1", content="본문" * 100),
            ],
            sufficient=True,
        ),
    )
    special_calls = []

    def fake_ai_gated(client, src, question="", openai_api_key=None):
        special_calls.append(src.name)
        return [
            SourceDocument(doc_id="g1", source_id=src.name, url="https://stats.example-media.co.kr/1", content="본문" * 100),
        ]

    monkeypatch.setattr(collector_module, "_crawl_source_with_ai_gated_search", fake_ai_gated)

    docs = _collected_documents(collect(plan))

    assert special_calls == [gated.name]
    assert {doc.source_id for doc in docs} == {"뉴스", gated.name}


def test_broadband_collect_requires_harness_key_and_does_not_fall_back(monkeypatch):
    # collect() used to fall back to a per-source loop when the harness key
    # was missing, degrading silently instead of failing (KOFIC lost its
    # AI-drafted query, every ai_gated_search source returned zero documents
    # outright). That fallback is gone - a missing harness key now halts the
    # stage, matching every other stage's "raise, never fake data" contract.
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.delenv(collector_module._HARNESS_API_KEY_ENV_VAR, raising=False)
    source = PlannedSource(name="ok", url="https://ok.example.com", collection_method=["firecrawl_search"])
    plan = SourcePlan(request_id="req", sector_id="sk_broadband", planned_sources=[source], question_keywords=["OTT"])

    with pytest.raises(PipelineStageError, match=collector_module._HARNESS_API_KEY_ENV_VAR):
        collect(plan)


def test_broadband_crawl_source_keeps_legacy_firecrawl_path():
    source = PlannedSource(
        name="전자신문 (통신)", url="https://www.etnews.com/news/section.html?id1=03",
        collection_method=["firecrawl_search"], reliability_tier="analyst_media",
    )
    result = _make_result("본문" * 200, title="OTT 시장 변화", url="https://www.etnews.com/a")

    docs = _crawl_source(_FastClient([result]), source, "test-key", ["OTT", "IPTV"])

    assert len(docs) == 1  # legacy path still works exactly as before this change


def test_broadband_kofic_source_bypasses_harness_even_when_enabled(monkeypatch):
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    source = PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        collection_method=["kofic_pdf_post_download", "firecrawl_parse"],
        reliability_tier="official",
    )
    search_result = _make_result(
        "상세 링크", title="KOFIC 보고서",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=69184",
    )
    attachment = types.SimpleNamespace(download_name="2025년 상반기 한국 영화산업 결산 보고서.pdf")
    parsed = types.SimpleNamespace(detail_url=search_result.url, attachment=attachment, markdown="KOFIC PDF 본문" * 100)
    monkeypatch.setattr(collector_module, "collect_pdf_markdown_from_detail_url", lambda detail_url, api_key: parsed)
    monkeypatch.setattr(collector_module, "_ai_generate_search_query", lambda *a, **k: "영화산업")

    docs = _crawl_source(_FastClient([search_result]), source, "test-key", ["영화산업", "OTT"])

    assert len(docs) == 1


def test_broadband_collect_runs_question_harness_once_for_all_sources(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    sources = [
        PlannedSource(name="broken", url="https://broken.example.com", collection_method=["firecrawl_search"]),
        PlannedSource(name="ok", url="https://ok.example.com", collection_method=["firecrawl_search"]),
    ]
    plan = SourcePlan(request_id="req", sector_id="sk_broadband", planned_sources=sources, question_keywords=["OTT"])
    plan.registered_sources = list(sources)
    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: object())
    calls = []

    def fake_harness(openai_client, firecrawl_client, registered_sources, keywords, config, search_context=None):
        calls.append((registered_sources, keywords, config))
        return WebSearchHarnessResult(
            documents=[
                SourceDocument(doc_id="d1", source_id="broken", url="https://broken.example.com/a", content="본문" * 100),
                SourceDocument(doc_id="d2", source_id="ok", url="https://ok.example.com/b", content="본문" * 100),
            ],
            sufficient=True,
            covered_information_needs=[],
            missing_information_needs=[],
            rounds_completed=1,
            scrape_call_count=2,
        )

    monkeypatch.setattr(collector_module, "run_question_search_harness_result", fake_harness)

    result = collect(plan)
    assert isinstance(result, SourceCollectionResult)
    assert result.collection_mode == "ai_search_harness"
    assert result.minimum_validated_documents == 5
    docs = result.documents

    assert len(docs) == 2
    assert docs[0].source_id == "broken"
    assert len(calls) == 1
    assert calls[0][0] == sources
    assert calls[0][2].target_docs == 5
    assert calls[0][2].max_collected_docs == 10
    assert calls[0][2].min_scraped_docs_for_sufficient == 5
    assert calls[0][2].min_independent_sources_for_sufficient == 2
    assert calls[0][2].assess_scraped_evidence is True
    # Raised from the ai_search_harness module default of 2 -> more raw
    # documents considered per round, with the scrape-call ceiling raised to
    # match so it isn't the thing actually bounding each round instead.
    assert calls[0][2].max_candidates_per_round == 5
    assert calls[0][2].max_rounds == 3
    assert calls[0][2].max_total_scrape_calls == 25


def test_broadband_question_harness_keeps_special_kofic_collector(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    web_source = PlannedSource(name="뉴스", url="https://news.example.com", collection_method=["firecrawl_search"])
    kofic = PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/board",
        collection_method=["kofic_pdf_post_download", "firecrawl_parse"],
    )
    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        planned_sources=[web_source],  # KOFIC may be outside the legacy top-N
        registered_sources=[web_source, kofic],
        question_keywords=["OTT"],
    )
    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: object())
    monkeypatch.setattr(
        collector_module,
        "_run_question_ai_harness",
        lambda *args: WebSearchHarnessResult(
            documents=[
                SourceDocument(
                    doc_id=f"w{index}",
                    source_id=f"뉴스{index}",
                    url=f"https://news{index}.example.com/{index}",
                    content="본문" * 100,
                )
                for index in range(1, 8)
            ],
            sufficient=True,
        ),
    )
    special_calls = []

    def fake_kofic(client, source, api_key, keywords, **kwargs):
        special_calls.append(source.name)
        return [
            SourceDocument(doc_id="k1", source_id=source.name, url="https://www.kofic.or.kr/report-1", content="본문" * 100),
            SourceDocument(doc_id="k2", source_id=source.name, url="https://www.kofic.or.kr/report-2", content="본문" * 100),
        ]

    monkeypatch.setattr(collector_module, "_crawl_kofic_pdf_source", fake_kofic)

    docs = _collected_documents(collect(plan))

    assert special_calls == ["영화진흥위원회(KOFIC)"]
    assert len(docs) == 9
    assert [doc.doc_id for doc in docs] == ["w1", "w2", "w3", "w4", "w5", "w6", "w7", "k1", "k2"]


def test_broadband_question_harness_rejects_fewer_than_two_documents(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    source = PlannedSource(name="뉴스", url="https://news.example.com", collection_method=["firecrawl_search"])
    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        planned_sources=[source],
        registered_sources=[source],
        question_keywords=["OTT"],
    )
    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: object())
    monkeypatch.setattr(
        collector_module,
        "_run_question_ai_harness",
        lambda *args: WebSearchHarnessResult(
            documents=[
                SourceDocument(doc_id="only", source_id="뉴스", url="https://news.example.com/only", content="본문" * 100)
            ],
            sufficient=False,
            missing_information_needs=["competition"],
        ),
    )

    with pytest.raises(PipelineStageError, match="insufficient relevant evidence"):
        collect(plan)


def test_broadband_question_harness_accepts_partial_coverage_instead_of_all_or_nothing(monkeypatch):
    # Not all-or-nothing: two documents from two independent sources is a
    # real corroborated core of evidence, even though the harness itself
    # couldn't cover every information_need (missing customer_market here).
    # The report should surface that gap honestly rather than the whole
    # collector stage refusing to produce anything.
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    source = PlannedSource(name="뉴스", url="https://news.example.com", collection_method=["firecrawl_search"])
    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        planned_sources=[source],
        registered_sources=[source],
        question_keywords=["매출"],
    )
    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: object())
    monkeypatch.setattr(
        collector_module,
        "_run_question_ai_harness",
        lambda *args: WebSearchHarnessResult(
            documents=[
                SourceDocument(doc_id="a", source_id="전자신문", url="https://a.example.com", content="본문" * 100),
                SourceDocument(doc_id="b", source_id="미래에셋증권", url="https://b.example.com", content="본문" * 100),
            ],
            sufficient=False,
            covered_information_needs=["financial_performance", "strategy_investment"],
            missing_information_needs=["customer_market"],
        ),
    )

    docs = _collected_documents(collect(plan))

    assert [doc.doc_id for doc in docs] == ["a", "b"]


def test_broadband_question_harness_counts_kofic_toward_sufficiency(monkeypatch):
    # Real bug this reproduces: the harness alone found only 1 document (not
    # enough on its own), but KOFIC (a special source run in the same
    # collect() call) independently supplied a second, real document - the
    # combined evidence pool is sufficient and must not be rejected just
    # because the harness's own document count was checked in isolation.
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv(collector_module._HARNESS_API_KEY_ENV_VAR, "test-key")
    news_source = PlannedSource(name="뉴스", url="https://news.example.com", collection_method=["firecrawl_search"])
    kofic_source = PlannedSource(
        name="영화진흥위원회(KOFIC)",
        url="https://www.kofic.or.kr/kofic/business/board/selectBoardList.do?boardNumber=2",
        collection_method=["kofic_pdf_post_download"],
    )
    plan = SourcePlan(
        request_id="req",
        sector_id="sk_broadband",
        planned_sources=[news_source],
        registered_sources=[news_source, kofic_source],
        question_keywords=["가입자"],
    )
    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: object())
    monkeypatch.setattr(
        collector_module,
        "_run_question_ai_harness",
        lambda *args: WebSearchHarnessResult(
            documents=[SourceDocument(doc_id="a", source_id="전자신문", url="https://a.example.com", content="본문" * 100)],
            sufficient=False,
            covered_information_needs=["customer_market"],
            missing_information_needs=["competition"],
        ),
    )
    monkeypatch.setattr(
        collector_module,
        "_crawl_kofic_pdf_source",
        lambda *args, **kwargs: [
            SourceDocument(doc_id="k1", source_id="영화진흥위원회(KOFIC)", url="https://kofic.example.com/1", content="본문" * 100)
        ],
    )

    docs = _collected_documents(collect(plan))

    assert {doc.doc_id for doc in docs} == {"a", "k1"}


def test_broadband_processor_strips_boilerplate_and_deduplicates():
    doc = SourceDocument(
        doc_id="doc1",
        source_id="source",
        title="  제목  ",
        url="https://example.com/a",
        content="본문입니다.\n본문입니다.\n무단전재 및 재배포 금지\nreporter@example.com",
    )

    docs = process([doc, doc])

    assert len(docs) == 1
    assert docs[0].title == "제목"
    assert "무단전재" not in docs[0].content
    assert "reporter@example.com" not in docs[0].content


def test_broadband_validator_filters_short_or_unattributed_documents():
    valid = SourceDocument(doc_id="1", source_id="source", title="title", url="https://example.com", content="가" * 300)
    short = SourceDocument(doc_id="2", source_id="source", title="title", url="https://example.com/2", content="짧음")
    no_url = SourceDocument(doc_id="3", source_id="source", title="title", content="가" * 300)

    assert validate([valid, short, no_url]) == [valid]


def test_broadband_validator_rejects_stale_documents_but_keeps_undated_ones():
    from datetime import datetime, timedelta, timezone

    stale = SourceDocument(
        doc_id="1", source_id="source", title="옛날 기사", url="https://example.com/old",
        content="가" * 300, published_at=datetime.now(timezone.utc) - timedelta(days=800),
    )
    fresh = SourceDocument(
        doc_id="2", source_id="source", title="최근 기사", url="https://example.com/new",
        content="나" * 300, published_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    undated = SourceDocument(
        doc_id="3", source_id="source", title="날짜 없는 기사", url="https://example.com/undated", content="다" * 300,
    )

    result = validate([stale, fresh, undated])

    assert stale not in result
    assert fresh in result
    assert undated in result


def test_broadband_validator_drops_cross_source_title_duplicates():
    original = SourceDocument(
        doc_id="1", source_id="전자신문", title="SK브로드밴드 AI 서비스 출시", url="https://etnews.example.com/a", content="가" * 300,
    )
    syndicated = SourceDocument(
        doc_id="2", source_id="디지털데일리", title="  SK브로드밴드   AI 서비스 출시  ", url="https://ddaily.example.com/b", content="나" * 300,
    )

    result = validate([original, syndicated])

    assert len(result) == 1
    assert result[0].doc_id == "1"


def test_broadband_validator_keeps_untitled_documents_when_urls_differ():
    first = SourceDocument(
        doc_id="1", source_id="출처 A", title="Untitled",
        url="https://a.example.com/one", content="가" * 300,
    )
    second = SourceDocument(
        doc_id="2", source_id="출처 B", title="Untitled",
        url="https://b.example.com/two", content="나" * 300,
    )

    result = validate([first, second])

    assert [document.doc_id for document in result] == ["1", "2"]


def test_broadband_validator_uses_question_specific_recency_window():
    from datetime import datetime, timezone

    recent = SourceDocument(
        doc_id="recent", source_id="source", title="최근 자료",
        url="https://example.com/recent", content="가" * 300,
        published_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    medium_age = SourceDocument(
        doc_id="medium", source_id="source", title="몇 달 전 자료",
        url="https://example.com/medium", content="다" * 300,
        published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    older = SourceDocument(
        doc_id="older", source_id="source", title="과거 자료",
        url="https://example.com/older", content="나" * 300,
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    undated = SourceDocument(
        doc_id="undated", source_id="source", title="날짜 없는 자료",
        url="https://example.com/undated", content="라" * 300,
    )
    latest_context = WebSearchContext(
        question="가장 최신 IPTV 현황은?",
        report_purpose_id="current_status",
        as_of_date="2026-08-05",
    )
    current_context = WebSearchContext(
        question="현재 IPTV 현황은?",
        report_purpose_id="current_status",
        as_of_date="2026-08-05",
    )
    historical_context = WebSearchContext(
        question="IPTV 도입 배경과 과거 변화는?",
        report_purpose_id="root_cause",
        as_of_date="2026-08-05",
    )

    documents = [recent, medium_age, older, undated]
    assert validate(documents, latest_context) == [recent]
    assert {document.doc_id for document in validate(documents, current_context)} == {
        "recent", "medium", "undated"
    }
    assert {document.doc_id for document in validate(documents, historical_context)} == {
        "recent", "medium", "older", "undated"
    }


def test_broadband_validator_caps_at_eight_and_prefers_official_sources():
    documents = []
    for i in range(10):
        documents.append(
            SourceDocument(
                doc_id=str(i),
                source_id="source",
                title=f"기사 제목 {i}",
                url=f"https://example.com/{i}",
                content=f"본문 {i} " * 100,
                reliability_tier="user_generated" if i < 9 else "official",
            )
        )

    result = validate(documents)

    assert len(result) == 8
    # the single official-tier document must survive the cap even though it
    # was the last one appended, since ranking runs before trimming.
    assert any(doc.reliability_tier == "official" for doc in result)


def _document():
    return SourceDocument(
        doc_id="doc1",
        source_id="전자신문 (통신)",
        title="OTT 시장 변화",
        url="https://example.com/a",
        content="OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다." * 50,
        reliability_tier="analyst_media",
    )


def _make_response(
    summary="요약",
    key_points=None,
    sentiment="mixed",
    relevance_level="direct",
    grounded_claims=None,
    metric_points=None,
    comparison_points=None,
    refusal=None,
):
    message = types.SimpleNamespace(
        content=json.dumps(
            {
                "summary": summary,
                "key_points": key_points or ["시장 변화: OTT 경쟁 심화", "Action: 경쟁사 전략 모니터링"],
                "sentiment": sentiment,
                "relevance_level": relevance_level,
                "relevance_reason": "IPTV 경쟁 변화에 관한 직접 근거를 포함함",
                "grounded_claims": grounded_claims if grounded_claims is not None else [
                    {
                        "claim_id": "c1",
                        "claim_type": "key_point",
                        "claim": "OTT 시장 변화가 IPTV 경쟁에 영향을 준다.",
                        "evidence_quote": "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다.",
                        "evidence_location": "본문",
                        "as_of_date": None,
                        "confidence": "high",
                    },
                    {
                        "claim_id": "c2",
                        "claim_type": "risk",
                        "claim": "OTT 경쟁 심화로 가입자 이탈 가능성",
                        "evidence_quote": "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다.",
                        "evidence_location": "본문",
                        "as_of_date": None,
                        "confidence": "medium",
                    },
                    {
                        "claim_id": "c3",
                        "claim_type": "action",
                        "claim": "Review: 경쟁사 OTT 번들링 전략 비교",
                        "evidence_quote": "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다.",
                        "evidence_location": "본문",
                        "as_of_date": None,
                        "confidence": "medium",
                    },
                    {
                        "claim_id": "c4",
                        "claim_type": "opportunity",
                        "claim": "AI 추천 기반 개인화 서비스 강화 기회",
                        "evidence_quote": "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다.",
                        "evidence_location": "본문",
                        "as_of_date": None,
                        "confidence": "medium",
                    },
                ],
                "covered_information_needs": ["OTT와 IPTV 경쟁 변화"],
                "missing_information_needs": ["경쟁사별 가입자 수치"],
                "business_impact": "IPTV 경쟁력과 콘텐츠 투자 판단에 영향",
                "risk": "OTT 경쟁 심화로 가입자 이탈 가능성",
                "opportunity": "AI 추천 기반 개인화 서비스 강화 기회",
                "strength": "",
                "weakness": "",
                "metric_points": metric_points or [],
                "comparison_points": comparison_points or [],
                "recommended_actions": ["Review: 경쟁사 OTT 번들링 전략 비교"],
                "monitoring_indicators": ["OTT 가입자 변화", "B tv ARPU 변화"],
                "evidence": ["문서에서 OTT 경쟁과 IPTV 서비스 변화가 언급됨"],
                "action_level": "Review",
                "analysis_confidence": "medium",
            },
            ensure_ascii=False,
        ),
        refusal=refusal,
    )
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _make_quote_repair_response(repairs, refusal=None):
    message = types.SimpleNamespace(
        content=json.dumps({"repairs": repairs}, ensure_ascii=False),
        refusal=refusal,
    )
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FakeCompletions:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeOpenAI:
    def __init__(self, response):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(response))


class _SequenceFakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("no more fake analyzer responses queued")
        return self._responses.pop(0)


class _SequenceFakeOpenAI:
    def __init__(self, responses):
        self.chat = types.SimpleNamespace(
            completions=_SequenceFakeCompletions(responses)
        )


def test_broadband_analyzer_uses_structured_schema(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    fake_openai = _FakeOpenAI(_make_response())
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze(
        [_document()],
        "OTT 시장 변화가 SK브로드밴드에 주는 영향은?",
        ["OTT와 IPTV 경쟁 변화", "경쟁사별 가입자 수치"],
    )

    assert result[0].summary == "요약"
    assert result[0].relevant_to_question is True
    assert result[0].relevance_level == "direct"
    assert result[0].relevance_reason
    assert result[0].grounded_claims[0].source_url == "https://example.com/a"
    assert result[0].covered_information_needs == ["OTT와 IPTV 경쟁 변화"]
    assert result[0].missing_information_needs == ["경쟁사별 가입자 수치"]
    assert "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다." in result[0].evidence
    assert result[0].risk == "OTT 경쟁 심화로 가입자 이탈 가능성"
    assert result[0].opportunity == "AI 추천 기반 개인화 서비스 강화 기회"
    assert result[0].recommended_actions == ["Review: 경쟁사 OTT 번들링 전략 비교"]
    schema = fake_openai.chat.completions.last_kwargs["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert "relevant_to_question" not in schema["properties"]
    assert "risk" not in schema["properties"]
    assert "recommended_actions" not in schema["properties"]
    user_payload = json.loads(fake_openai.chat.completions.last_kwargs["messages"][1]["content"])
    assert user_payload["required_information_needs"] == [
        "OTT와 IPTV 경쟁 변화",
        "경쟁사별 가입자 수치",
    ]
    assert "content" not in user_payload["document"]
    assert user_payload["document"]["evidence_passages"][0]["passage_id"] == "P001"


def test_broadband_analyzer_chunks_any_long_pdf_and_merges_one_document(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    first_quote = "PDF 앞부분에 IPTV 시장 현황이 있다."
    later_quote = "2026년 IPTV 가입자는 120만 명이다."
    document = SourceDocument(
        doc_id="kmcc:70246",
        source_id="방송미디어통신위원회",
        title="방송시장 보고서",
        url="https://www.kmcc.go.kr/download.do?fileSeq=70246",
        content=first_quote + ("가" * 11900) + "\n\n" + later_quote + ("나" * 1000),
        media_type="application/pdf",
        reliability_tier="official",
    )
    first_response = _make_response(
        summary="시장 현황 요약",
        grounded_claims=[
            {
                "claim_id": "c1",
                "claim_type": "key_point",
                "claim": "IPTV 시장 현황을 제시한다.",
                "evidence_quote": first_quote,
                "evidence_location": "본문 앞부분",
                "as_of_date": None,
                "confidence": "high",
            }
        ],
    )
    second_response = _make_response(
        summary="가입자 수치 요약",
        grounded_claims=[
            {
                "claim_id": "c1",
                "claim_type": "metric",
                "claim": "2026년 IPTV 가입자는 120만 명이다.",
                "evidence_quote": later_quote,
                "evidence_location": "후반부 표",
                "as_of_date": "2026년",
                "confidence": "high",
            }
        ],
        metric_points=[
            {
                "label": "IPTV 가입자",
                "period": "2026년",
                "value": 120,
                "unit": "만 명",
                "evidence_claim_id": "c1",
            }
        ],
    )
    fake_openai = _SequenceFakeOpenAI([first_response, second_response])
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    results = analyze(
        [document],
        "IPTV 시장 현황과 가입자는?",
        ["OTT와 IPTV 경쟁 변화"],
    )

    assert len(results) == 1
    assert len(fake_openai.chat.completions.calls) == 2
    assert [claim.claim_id for claim in results[0].grounded_claims] == [
        "pdf1:c1",
        "pdf2:c1",
    ]
    assert results[0].grounded_claims[1].evidence_location.startswith("PDF 청크 2/2")
    assert results[0].grounded_claims[1].evidence_passage_id.startswith("pdf2:P")
    assert results[0].metric_points[0].evidence_claim_id == "pdf2:c1"
    assert results[0].metric_points[0].evidence_quote == later_quote
    assert results[0].source_url == document.url


def test_broadband_analyzer_rejects_claim_quote_not_found_in_source(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    response = _make_response(
        grounded_claims=[
            {
                "claim_id": "bad1",
                "claim_type": "key_point",
                "claim": "원문에 없는 주장",
                "evidence_quote": "원문에는 존재하지 않는 인용문",
                "evidence_location": None,
                "as_of_date": None,
                "confidence": "high",
            }
        ]
    )
    fake_openai = _FakeOpenAI(response)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([_document()], "OTT 시장 변화는?")[0]

    assert result.grounded_claims == []
    assert result.evidence == []
    assert result.covered_information_needs == []
    assert result.relevant_to_question is True
    assert result.relevance_level == "direct"
    assert result.analysis_validation_status == "insufficient_grounding"
    assert result.usable_for_synthesis is False


def test_broadband_analyzer_repairs_failed_quote_once_without_changing_claim(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    exact_quote = "2026년 IPTV 가입자는 120만 명으로 집계됐다."
    document = _document().model_copy(
        update={"content": f"시장 개요 문단이다.\n\n{exact_quote}\n\n후속 설명이다."}
    )
    original_claim = "2026년 IPTV 가입자는 120만 명이다."
    analysis_response = _make_response(
        grounded_claims=[
            {
                "claim_id": "c1",
                "claim_type": "metric",
                "claim": original_claim,
                "evidence_passage_id": "P001",
                "evidence_quote": "가입자가 약 120만 명이다.",
                "evidence_location": "가입자 현황",
                "as_of_date": "2026년",
                "confidence": "high",
            }
        ]
    )
    repair_response = _make_quote_repair_response(
        [
            {
                "claim_id": "c1",
                "evidence_passage_id": "P002",
                "evidence_quote": exact_quote,
            }
        ]
    )
    fake_openai = _SequenceFakeOpenAI([analysis_response, repair_response])
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([document], "2026년 IPTV 가입자는?")[0]

    assert len(fake_openai.chat.completions.calls) == 2
    assert len(result.grounded_claims) == 1
    assert result.grounded_claims[0].claim == original_claim
    assert result.grounded_claims[0].evidence_quote == exact_quote
    assert result.grounded_claims[0].evidence_passage_id == "P002"
    assert result.analysis_validation_status == "verified"
    assert result.usable_for_synthesis is True
    repair_payload = json.loads(
        fake_openai.chat.completions.calls[1]["messages"][1]["content"]
    )
    assert repair_payload["claims_to_repair"][0]["claim"] == original_claim
    assert "P002" in repair_payload["claims_to_repair"][0]["candidate_passage_ids"]
    assert any(
        passage["passage_id"] == "P002"
        for passage in repair_payload["candidate_passages"]
    )


def test_broadband_analyzer_keeps_valid_claim_when_other_quote_repair_fails(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    exact_quote = "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다."
    analysis_response = _make_response(
        grounded_claims=[
            {
                "claim_id": "good",
                "claim_type": "key_point",
                "claim": "OTT와 IPTV가 경쟁한다.",
                "evidence_passage_id": "P001",
                "evidence_quote": exact_quote,
                "evidence_location": "본문",
                "as_of_date": None,
                "confidence": "high",
            },
            {
                "claim_id": "bad",
                "claim_type": "risk",
                "claim": "원문에 없는 위험이다.",
                "evidence_passage_id": "P001",
                "evidence_quote": "원문에 없는 인용",
                "evidence_location": None,
                "as_of_date": None,
                "confidence": "low",
            },
        ]
    )
    repair_response = _make_quote_repair_response(
        [
            {
                "claim_id": "bad",
                "evidence_passage_id": "P001",
                "evidence_quote": "여전히 원문에 없는 인용",
            }
        ]
    )
    fake_openai = _SequenceFakeOpenAI([analysis_response, repair_response])
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([_document()], "OTT 시장 변화는?")[0]

    assert [claim.claim_id for claim in result.grounded_claims] == ["good"]
    assert result.analysis_validation_status == "partial_grounding"
    assert result.usable_for_synthesis is True


def test_broadband_analyzer_normalizes_safe_pdf_spacing_artifacts(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    document = _document().model_copy(
        update={"content": "IPTV\u00a0가입자는 120만\u200b 명이다."}
    )
    response = _make_response(
        grounded_claims=[
            {
                "claim_id": "c1",
                "claim_type": "metric",
                "claim": "IPTV 가입자는 120만 명이다.",
                "evidence_passage_id": "P001",
                "evidence_quote": "IPTV 가입자는 120만 명이다.",
                "evidence_location": "본문",
                "as_of_date": None,
                "confidence": "high",
            }
        ]
    )
    fake_openai = _FakeOpenAI(response)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([document], "IPTV 가입자는?")[0]

    assert [claim.claim_id for claim in result.grounded_claims] == ["c1"]
    assert result.analysis_validation_status == "verified"


def test_broadband_analyzer_keeps_only_metrics_found_in_source(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    document = _document().model_copy(
        update={"content": "2025년 IPTV 가입자는 100만 명이다. OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다."}
    )
    response = _make_response(
        grounded_claims=[
            {
                "claim_id": "metric1",
                "claim_type": "metric",
                "claim": "2025년 IPTV 가입자는 100만 명이다.",
                "evidence_quote": "2025년 IPTV 가입자는 100만 명이다.",
                "evidence_location": "본문",
                "as_of_date": "2025년",
                "confidence": "high",
            }
        ],
        metric_points=[
            {
                "label": "IPTV 가입자",
                "period": "2025년",
                "value": 100,
                "unit": "만 명",
                "evidence_claim_id": "metric1",
            },
            {
                "label": "매출",
                "period": "2024년",
                "value": 999,
                "unit": "억원",
                "evidence_claim_id": "metric1",
            },
        ]
    )
    fake_openai = _FakeOpenAI(response)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([document], "IPTV 가입자는?")[0]

    assert len(result.metric_points) == 1
    assert result.metric_points[0].period == "2025년"
    assert result.metric_points[0].value == 100
    assert result.metric_points[0].evidence_claim_id == "metric1"
    assert result.metric_points[0].evidence_quote == "2025년 IPTV 가입자는 100만 명이다."


def test_broadband_analyzer_keeps_only_comparisons_linked_to_verified_claims(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    response = _make_response(
        grounded_claims=[
            {
                "claim_id": "cmp1",
                "claim_type": "comparison",
                "claim": "IPTV와 OTT의 경쟁이 심화됐다.",
                "evidence_quote": "OTT 시장 변화와 IPTV 경쟁에 관한 본문입니다.",
                "evidence_location": "본문",
                "as_of_date": None,
                "confidence": "high",
            }
        ],
        comparison_points=[
            {
                "entity": "OTT",
                "criterion": "경쟁 강도",
                "value": "심화",
                "level": "high",
                "evidence_claim_id": "cmp1",
            },
            {
                "entity": "근거 없는 대상",
                "criterion": "가격",
                "value": "낮음",
                "level": "low",
                "evidence_claim_id": "missing",
            },
        ],
    )
    fake_openai = _FakeOpenAI(response)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([_document()], "OTT와 IPTV 경쟁은?")[0]

    assert len(result.comparison_points) == 1
    assert result.comparison_points[0].entity == "OTT"
    assert result.comparison_points[0].evidence_claim_id == "cmp1"


def test_broadband_analyzer_missing_key_raises_stage_error(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(PipelineStageError):
        analyze([_document()], "질문")
