from common.contracts import EntityExtractionResult, SectorProfile
from core.entity.search_terms import build_search_terms


def _entities(
    organizations=None,
    technologies=None,
    keywords=None,
    primary_intent="current_status",
    perspective="company_update",
):
    return EntityExtractionResult(
        request_id="req_test",
        primary_intent=primary_intent,
        perspective=perspective,
        organizations=organizations or [],
        technologies=technologies or [],
        keywords=keywords or [],
    )


def _sector_profile(market_keywords=None):
    return SectorProfile(
        sector_id="sk_planet",
        display_name="SK플래닛",
        status="active",
        market_keywords=market_keywords or [],
    )


def test_pairs_entity_with_topic_instead_of_two_technologies():
    # the exact live-observed case that motivated this fix
    entities = _entities(
        organizations=[],
        technologies=["OK캐쉬백", "Syrup 포인트"],
        keywords=["포인트 마케팅", "시장 현황", "소비자 리워드"],
    )

    result = build_search_terms(entities)

    assert result[:2] == ["OK캐쉬백", "포인트 마케팅"]


def test_anchor_entity_prefers_organizations_over_technologies():
    entities = _entities(
        organizations=["SK플래닛"],
        technologies=["Syrup"],
        keywords=["시장 현황"],
    )

    result = build_search_terms(entities)

    assert result[0] == "SK플래닛"
    assert result[1] == "시장 현황"


def test_falls_back_to_intent_framing_word_when_no_topic_keyword_exists():
    entities = _entities(
        organizations=["SK하이닉스"],
        technologies=["HBM"],
        keywords=[],
        primary_intent="future_business",
    )

    result = build_search_terms(entities)

    assert result[0] == "SK하이닉스"
    assert result[1] == "전망"


def test_returns_empty_list_when_everything_is_empty():
    entities = _entities()

    assert build_search_terms(entities) == []


def test_no_duplicate_terms_in_output():
    entities = _entities(
        organizations=["SK플래닛"],
        technologies=[],
        keywords=["SK플래닛", "시장 현황"],
    )

    result = build_search_terms(entities)

    assert result.count("SK플래닛") == 1


def test_market_landscape_perspective_anchors_on_market_keyword():
    # the exact live-observed case: even entity+topic pairing ("OK캐쉬백" +
    # "포인트 마케팅") still surfaced OK캐쉬백's own coverage, not market
    # coverage — anchoring on a registered market_keywords term instead fixes it.
    entities = _entities(
        organizations=[],
        technologies=["OK캐쉬백", "Syrup 포인트"],
        keywords=["포인트 마케팅", "시장 현황", "소비자 리워드"],
        perspective="market_landscape",
    )
    sector_profile = _sector_profile(market_keywords=["포인트 마케팅 시장", "리워드 플랫폼 시장"])

    result = build_search_terms(entities, sector_profile)

    assert result[0] == "포인트 마케팅 시장"
    assert "OK캐쉬백" not in result[:2]


def test_market_landscape_perspective_falls_back_when_no_market_keywords_registered():
    entities = _entities(
        organizations=[],
        technologies=["OK캐쉬백", "Syrup 포인트"],
        keywords=["포인트 마케팅", "시장 현황"],
        perspective="market_landscape",
    )
    sector_profile = _sector_profile(market_keywords=[])

    result = build_search_terms(entities, sector_profile)

    assert result[:2] == ["OK캐쉬백", "포인트 마케팅"]


def test_non_market_landscape_perspective_ignores_market_keywords():
    entities = _entities(
        organizations=[],
        technologies=["OK캐쉬백"],
        keywords=["신규 서비스 출시"],
        perspective="company_update",
    )
    sector_profile = _sector_profile(market_keywords=["포인트 마케팅 시장"])

    result = build_search_terms(entities, sector_profile)

    assert result[0] == "OK캐쉬백"
    assert "포인트 마케팅 시장" not in result[:2]
