from common.contracts import PlannedSource
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms


def test_long_question_queries_cover_front_middle_and_tail_before_single_fallback():
    terms = ["SK브로드밴드", "IPTV", "OTT", "경쟁 현황", "주요 리스크", "대응 전략"]

    queries = build_search_queries(terms)

    assert "SK브로드밴드" in queries[0]
    assert "대응 전략" in queries[0]
    assert any("주요 리스크" in query and "대응 전략" in query for query in queries[:-1])
    assert queries[-1] == "SK브로드밴드"


def test_source_topics_and_full_question_are_both_retained_for_every_sector():
    source = PlannedSource(
        name="competitor",
        url="https://example.com",
        role="competitor_official",
        topics=["경쟁사 서비스", "AI 플랫폼"],
    )
    question = ["대상 기업", "시장 현황", "수익성 리스크", "대응 방안"]

    ordered = build_source_search_terms(source, question)
    queries = build_search_queries(ordered)

    assert set(source.topics).issubset(ordered)
    assert set(question).issubset(ordered)
    assert any("경쟁사 서비스" in query for query in queries)
    assert any("대응 방안" in query for query in queries)
