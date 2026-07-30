import json
from pathlib import Path

from core.source_planner.planner import plan_sources


def test_empty_registry_returns_template_only_note(tmp_path):
    registry_root = tmp_path / "registry"
    (registry_root / "sk_broadband").mkdir(parents=True)

    plan = plan_sources("req_test_source_planner", "sk_broadband", registry_root)

    assert plan.planned_sources == []
    assert plan.notes == "no sources registered for this sector — template_only"


def test_structured_registry_sources_parse_without_validation_error(tmp_path):
    registry_root = tmp_path / "registry"
    sector_dir = registry_root / "sk_hynix"
    sector_dir.mkdir(parents=True)
    (sector_dir / "sources.json").write_text(
        json.dumps({
            "sources": [
                {
                    "name": "SK하이닉스 뉴스룸",
                    "country": "KR",
                    "type": "official_newsroom",
                    "url": "https://news.skhynix.co.kr/all/",
                    "collection_method": ["rss", "crawling"],
                    "frequency": "daily",
                    "category": ["투자", "기술"],
                    "reliability_reason": "회사 공식 1차 자료",
                }
            ]
        }),
        encoding="utf-8",
    )

    plan = plan_sources("req_test_source_planner", "sk_hynix", registry_root)

    assert plan.notes is None
    assert len(plan.planned_sources) == 1
    source = plan.planned_sources[0]
    assert source.name == "SK하이닉스 뉴스룸"
    assert source.url == "https://news.skhynix.co.kr/all/"
    assert source.collection_method == ["rss", "crawling"]
    assert source.category == ["투자", "기술"]
    assert source.reliability_reason == "회사 공식 1차 자료"


def test_planned_source_reliability_tier_defaults_to_none_not_fabricated():
    # reliability_tier exists (a real, domain-expert-defined 3-tier convention —
    # see common/contracts.py's PlannedSource docstring), but it must never be
    # auto-populated: a source registered without one stays None, it's not
    # guessed from the source's name/url/type.
    from common.contracts import PlannedSource

    source = PlannedSource(name="untiered source", url="https://example.com")
    assert source.reliability_tier is None


def _write_common_naver_source(registry_root: Path) -> None:
    common_dir = registry_root / "common"
    common_dir.mkdir(parents=True)
    (common_dir / "sources.json").write_text(
        json.dumps({
            "sources": [
                {
                    "name": "네이버 뉴스",
                    "country": "KR",
                    "type": "news_portal",
                    "url": "https://news.naver.com",
                    "collection_method": ["crawling"],
                    "frequency": "daily",
                    "category": [],
                    "reliability_reason": "포털 종합 뉴스",
                }
            ]
        }),
        encoding="utf-8",
    )


def test_common_registry_source_is_merged_into_every_sector(tmp_path):
    registry_root = tmp_path / "registry"
    _write_common_naver_source(registry_root)
    (registry_root / "sk_hynix").mkdir(parents=True)
    (registry_root / "sk_hynix" / "sources.json").write_text(
        json.dumps({"sources": [{"name": "SK하이닉스 뉴스룸", "url": "https://news.skhynix.co.kr/all/"}]}),
        encoding="utf-8",
    )

    plan = plan_sources("req_test_source_planner", "sk_hynix", registry_root)

    names = {source.name for source in plan.planned_sources}
    assert names == {"SK하이닉스 뉴스룸", "네이버 뉴스"}


def test_common_registry_source_applies_even_with_no_sector_specific_folder(tmp_path):
    # Mirrors the `general` (fallback/unmatched) sector: no sector-specific
    # registry folder exists at all, yet the common source still applies.
    registry_root = tmp_path / "registry"
    _write_common_naver_source(registry_root)

    plan = plan_sources("req_test_source_planner", "general", registry_root)

    assert plan.notes is None
    assert len(plan.planned_sources) == 1
    assert plan.planned_sources[0].name == "네이버 뉴스"
