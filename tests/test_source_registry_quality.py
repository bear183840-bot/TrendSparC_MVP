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
    assert len(names) == 7
    assert plan.planned_sources[0].content_type == "analysis"
