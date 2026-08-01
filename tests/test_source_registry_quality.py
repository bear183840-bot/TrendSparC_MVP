import json
from pathlib import Path

from common.contracts import PlannedSource
from core.source_planner.planner import plan_sources

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_ROOT = PROJECT_ROOT / "sources" / "registry"


def test_broadband_source_registry_uses_expected_reliability_tiers():
    data = json.loads((REGISTRY_ROOT / "sk_broadband" / "sources.json").read_text(encoding="utf-8"))
    sources = [PlannedSource.model_validate(raw) for raw in data["sources"]]

    tiers = {source.name: source.reliability_tier for source in sources}
    assert tiers["SK브로드밴드 뉴스룸"] == "official"
    assert tiers["영화진흥위원회(KOFIC)"] == "official"
    assert tiers["전자신문 (통신)"] == "analyst_media"
    assert tiers["왓챠피디아"] == "user_generated"


def test_broadband_source_plan_keeps_sector_sources_plus_common_source():
    plan = plan_sources(
        "req_source_registry",
        "sk_broadband",
        REGISTRY_ROOT,
        question_keywords=["OTT", "IPTV"],
        perspective="market_landscape",
    )

    names = [source.name for source in plan.planned_sources]
    assert "영화진흥위원회(KOFIC)" in names
    assert "SK브로드밴드 뉴스룸" in names
    assert any("네이버" in name or "Naver" in name for name in names)
    assert len(names) == 14  # 13 sk_broadband sources (expanded 2026-08-01) + 1 common (Naver)
    assert plan.planned_sources[0].content_type == "analysis"


def test_planet_source_registry_has_verified_role_coverage():
    data = json.loads((REGISTRY_ROOT / "sk_planet" / "sources.json").read_text(encoding="utf-8"))
    sources = [PlannedSource.model_validate(raw) for raw in data["sources"]]

    assert len(sources) == 16
    roles = {source.role for source in sources}
    assert {"official", "competitor_official", "market_analysis", "search", "regulatory_official"} <= roles

    names = {source.name for source in sources}
    assert {"카카오페이 보도자료", "쿠팡 뉴스룸", "과학기술정보통신부 보도자료", "나스미디어 정기보고서"} <= names


def test_planet_source_plan_keeps_sector_sources_plus_common_source():
    plan = plan_sources(
        "req_planet_source_registry",
        "sk_planet",
        REGISTRY_ROOT,
        question_keywords=["멤버십", "Ad-tech", "개인정보"],
        perspective="market_landscape",
    )

    names = [source.name for source in plan.planned_sources]
    assert len(names) == 17  # 16 sk_planet sources + 1 common (Naver)
    assert "카카오페이 보도자료" in names
    assert "과학기술정보통신부 보도자료" in names
