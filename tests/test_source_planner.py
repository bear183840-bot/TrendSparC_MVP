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


def test_planned_source_has_no_fabricated_reliability_tier():
    from common.contracts import PlannedSource

    assert "reliability_tier" not in PlannedSource.model_fields
