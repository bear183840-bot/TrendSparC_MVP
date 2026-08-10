"""A market/category label is not a competitor entity.

Live-reported bug: "IPTV" appeared in a Competitive Landscape panel beside
"KT"/"SKB"/"LGU+" - IPTV is the service/market itself, not a company being
compared. `entity_kind()` has no vocabulary for this distinction (a category
label and a company name are both a bare noun phrase), so the fix checks
`ComparisonPoint.entity` against the sector's own registered
`SectorProfile.market_keywords` instead - never a name-specific denylist,
never a new LLM classifier (both explicitly ruled out by the spec).
"""
from __future__ import annotations

from common.block_shapes import competitor_panels
from common.content_quality_validator import (
    exclude_market_category_entities,
    is_market_category_entity,
)
from common.contracts import ComparisonPoint
from reporting.dashboard_streamlit import components


def _points() -> list[ComparisonPoint]:
    return [
        ComparisonPoint(entity="KT", criterion="가격", value="결합할인", level="high"),
        ComparisonPoint(entity="KT", criterion="콘텐츠", value="오리지널 다수", level="high"),
        ComparisonPoint(entity="SK브로드밴드", criterion="가격", value="구독료 인상", level="low"),
        ComparisonPoint(entity="SK브로드밴드", criterion="콘텐츠", value="보통", level="medium"),
        ComparisonPoint(entity="IPTV", criterion="가격", value="상승세", level="medium"),
        ComparisonPoint(entity="IPTV", criterion="콘텐츠", value="다양화", level="medium"),
    ]


# --- the predicate ---------------------------------------------------------


def test_a_registered_market_keyword_is_a_category_not_a_competitor():
    assert is_market_category_entity("IPTV", ["IPTV", "포인트 마케팅 시장"]) is True


def test_an_unregistered_name_is_never_assumed_to_be_a_category():
    assert is_market_category_entity("KT", ["IPTV"]) is False


def test_no_registered_keywords_excludes_nothing():
    """Silence means "unknown", not "safe to drop" - a sector with no
    market_keywords registered must never lose a real competitor."""
    assert is_market_category_entity("IPTV", []) is False
    assert is_market_category_entity("IPTV", None) is False


def test_matching_is_not_case_or_whitespace_sensitive():
    assert is_market_category_entity(" iptv ", ["IPTV"]) is True


# --- filtering a comparison_points list -------------------------------------


def test_exclude_market_category_entities_drops_only_the_registered_label():
    filtered = exclude_market_category_entities(_points(), ["IPTV"])

    entities = {point.entity for point in filtered}
    assert entities == {"KT", "SK브로드밴드"}


def test_exclude_market_category_entities_is_a_noop_without_keywords():
    assert exclude_market_category_entities(_points(), None) == _points()
    assert exclude_market_category_entities(_points(), []) == _points()


# --- what actually reaches the Competitive Landscape panel ------------------


def test_the_competitor_panel_never_draws_a_market_category_label(monkeypatch):
    filtered = exclude_market_category_entities(_points(), ["IPTV"])
    panels = competitor_panels(filtered, [])

    assert {entity for entity, *_ in panels} == {"KT", "SK브로드밴드"}

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
    monkeypatch.setattr(components.st, "columns", lambda n: [_FakeColumn()] * n)
    components.render_competitor_panels(filtered, [])
    body = "".join(captured)

    assert "KT" in body
    assert "IPTV" not in body


class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_without_the_filter_the_category_label_would_have_leaked_through():
    """Confirms this is a real regression, not a test that would pass either
    way: the unfiltered points do let "IPTV" through as a fourth panel."""
    panels = competitor_panels(_points(), [])

    assert "IPTV" in {entity for entity, *_ in panels}
