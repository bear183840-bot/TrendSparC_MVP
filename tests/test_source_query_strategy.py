from common.contracts import PlannedSource
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms


def test_long_question_queries_cover_front_middle_and_tail_before_single_fallback():
    terms = ["SK브로드밴드", "IPTV", "OTT", "경쟁 현황", "주요 리스크", "대응 전략"]

    queries = build_search_queries(terms)

    assert queries[0] == "SK브로드밴드 IPTV"
    assert any("SK브로드밴드" in query and "대응 전략" in query for query in queries[:-1])
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


def test_competitor_source_pairs_its_identity_with_question_anchor_early():
    source = PlannedSource(
        name="competitor",
        url="https://example.com",
        role="competitor_official",
        topics=["삼성전자", "DRAM/NAND", "투자·수율"],
    )

    ordered = build_source_search_terms(source, ["HBM4", "개발 현황", "경쟁사"])
    queries = build_search_queries(ordered)

    assert ordered[:3] == ["삼성전자", "HBM4", "개발 현황"]
    assert queries[0] == "삼성전자 HBM4"
    assert queries[1] == "삼성전자 HBM4 개발 현황"


def test_official_source_keeps_registry_topics_as_fallback_for_vague_questions():
    source = PlannedSource(
        name="official",
        url="https://example.com",
        role="official",
        topics=["정식 회사명", "핵심 서비스", "실적"],
    )

    ordered = build_source_search_terms(source, ["사업 현황", "주요 성과"])
    queries = build_search_queries(ordered)

    assert ordered[:2] == ["사업 현황", "주요 성과"]
    assert set(source.topics).issubset(ordered)
    assert any("정식 회사명" in query for query in queries)
    assert any("실적" in query for query in queries)


def test_general_search_source_starts_with_company_and_kpi_not_generic_registry_topic():
    source = PlannedSource(
        name="news portal",
        url="https://example.com",
        role="search",
        topics=["최신 뉴스", "산업 동향"],
    )

    ordered = build_source_search_terms(source, ["SK브로드밴드", "매출", "사업 현황"])
    queries = build_search_queries(ordered)

    assert ordered[:2] == ["SK브로드밴드", "매출"]
    assert queries[0] == "SK브로드밴드 매출"
