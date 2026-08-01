import json
import types

import pytest

from common.contracts import PlannedSource, SourceDocument, SourcePlan
from common.errors import PipelineStageError
from core.source_planner.query_strategy import build_source_search_terms
from sectors.sk_broadband.adapter import analyzer as analyzer_module
from sectors.sk_broadband.adapter import collector as collector_module
from sectors.sk_broadband.adapter.analyzer import analyze
from sectors.sk_broadband.adapter.collector import _crawl_source, collect
from sectors.sk_broadband.adapter.processor import process
from sectors.sk_broadband.adapter.validator import validate


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

    docs = _crawl_source(_FastClient([search_result]), source, "test-key", ["영화산업", "OTT"])

    assert len(docs) == 1
    assert docs[0].title == "2025년 상반기 한국 영화산업 결산 보고서.pdf"
    assert docs[0].source_id == "영화진흥위원회(KOFIC)"
    assert docs[0].content.startswith("KOFIC PDF 본문")


def test_broadband_collect_continues_when_one_source_fails(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    sources = [
        PlannedSource(name="broken", url="https://broken.example.com", collection_method=["firecrawl_search"]),
        PlannedSource(name="ok", url="https://ok.example.com", collection_method=["firecrawl_search"]),
    ]
    plan = SourcePlan(request_id="req", sector_id="sk_broadband", planned_sources=sources, question_keywords=["OTT"])

    class _PerDomainClient:
        def search(self, query, include_domains, limit, scrape_options):
            if include_domains[0] == "broken.example.com":
                raise RuntimeError("boom")
            return _search_data([_make_result("본문" * 200, url="https://ok.example.com/a")])

    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: _PerDomainClient())

    docs = collect(plan)

    assert len(docs) == 1
    assert docs[0].source_id == "ok"


def test_broadband_collect_caps_total_documents_at_twelve(monkeypatch):
    # 8 sources * 2 results each (_MAX_RESULTS_PER_SOURCE) would be 16 raw
    # documents; collect() must stop at _MAX_COLLECTED_DOCUMENTS (12) so the
    # validator/analyzer never see an unbounded set.
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    sources = [
        PlannedSource(name=f"source{i}", url=f"https://s{i}.example.com", collection_method=["firecrawl_search"])
        for i in range(8)
    ]
    plan = SourcePlan(request_id="req", sector_id="sk_broadband", planned_sources=sources, question_keywords=["OTT"])

    class _TwoResultsClient:
        def search(self, query, include_domains, limit, scrape_options):
            domain = include_domains[0]
            return _search_data([
                _make_result("본문" * 200, url=f"https://{domain}/a"),
                _make_result("본문" * 200, url=f"https://{domain}/b"),
            ])

    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: _TwoResultsClient())

    docs = collect(plan)

    assert len(docs) == 12


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


def _make_response(summary="요약", key_points=None, sentiment="mixed", relevant_to_question=True, refusal=None):
    message = types.SimpleNamespace(
        content=json.dumps(
            {
                "summary": summary,
                "key_points": key_points or ["시장 변화: OTT 경쟁 심화", "Action: 경쟁사 전략 모니터링"],
                "sentiment": sentiment,
                "relevant_to_question": relevant_to_question,
                "business_impact": "IPTV 경쟁력과 콘텐츠 투자 판단에 영향",
                "risk": "OTT 경쟁 심화로 가입자 이탈 가능성",
                "opportunity": "AI 추천 기반 개인화 서비스 강화 기회",
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


def test_broadband_analyzer_uses_structured_schema(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", "test-key")
    fake_openai = _FakeOpenAI(_make_response())
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([_document()], "OTT 시장 변화가 SK브로드밴드에 주는 영향은?")

    assert result[0].summary == "요약"
    assert result[0].relevant_to_question is True
    assert result[0].risk == "OTT 경쟁 심화로 가입자 이탈 가능성"
    assert result[0].recommended_actions == ["Review: 경쟁사 OTT 번들링 전략 비교"]
    schema = fake_openai.chat.completions.last_kwargs["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False


def test_broadband_analyzer_missing_key_raises_stage_error(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(PipelineStageError):
        analyze([_document()], "질문")
