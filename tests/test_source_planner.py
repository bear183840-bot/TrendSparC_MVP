import json
from pathlib import Path

from core.source_planner.planner import plan_sources, select_top_sources


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


def _write_mixed_content_type_sources(registry_root: Path) -> None:
    sector_dir = registry_root / "sk_planet"
    sector_dir.mkdir(parents=True)
    (sector_dir / "sources.json").write_text(
        json.dumps({
            "sources": [
                {"name": "공식 뉴스룸", "url": "https://a.example.com", "content_type": "press_release"},
                {"name": "무태그 소스", "url": "https://b.example.com"},
                {"name": "전문지 분석", "url": "https://c.example.com", "content_type": "analysis"},
            ]
        }),
        encoding="utf-8",
    )


def test_market_landscape_perspective_reorders_analysis_sources_first(tmp_path):
    registry_root = tmp_path / "registry"
    _write_mixed_content_type_sources(registry_root)

    plan = plan_sources("req_test_source_planner", "sk_planet", registry_root, perspective="market_landscape")

    assert [s.name for s in plan.planned_sources] == ["전문지 분석", "무태그 소스", "공식 뉴스룸"]


def test_company_update_perspective_reorders_press_release_sources_first(tmp_path):
    registry_root = tmp_path / "registry"
    _write_mixed_content_type_sources(registry_root)

    plan = plan_sources("req_test_source_planner", "sk_planet", registry_root, perspective="company_update")

    assert [s.name for s in plan.planned_sources] == ["공식 뉴스룸", "무태그 소스", "전문지 분석"]


def test_no_perspective_keeps_registry_order(tmp_path):
    registry_root = tmp_path / "registry"
    _write_mixed_content_type_sources(registry_root)

    plan = plan_sources("req_test_source_planner", "sk_planet", registry_root)

    assert [s.name for s in plan.planned_sources] == ["공식 뉴스룸", "무태그 소스", "전문지 분석"]


def test_unmapped_perspective_keeps_registry_order(tmp_path):
    registry_root = tmp_path / "registry"
    _write_mixed_content_type_sources(registry_root)

    plan = plan_sources("req_test_source_planner", "sk_planet", registry_root, perspective="regulatory_policy")

    assert [s.name for s in plan.planned_sources] == ["공식 뉴스룸", "무태그 소스", "전문지 분석"]


def test_select_top_sources_keeps_everything_when_registry_is_small(tmp_path):
    # Opt-in narrowing: plan_sources() itself never trims, and select_top_sources()
    # only trims once a sector's registry actually exceeds the cap — a 3-source
    # registry gets all 3 back either way.
    registry_root = tmp_path / "registry"
    _write_mixed_content_type_sources(registry_root)

    plan = plan_sources("req_test_source_planner", "sk_planet", registry_root, perspective="market_landscape")
    narrowed = select_top_sources(plan, perspective="market_landscape")

    assert len(narrowed.planned_sources) == 3
    assert [s.name for s in narrowed.planned_sources] == ["전문지 분석", "무태그 소스", "공식 뉴스룸"]


def test_select_top_sources_keeps_small_same_role_registry_intact(tmp_path):
    # Role quotas only diversify an oversized candidate pool. A registry that
    # already fits under the overall cap must not lose otherwise valid sources.
    registry_root = tmp_path / "registry"
    sector_dir = registry_root / "sk_broadband"
    sector_dir.mkdir(parents=True)
    (sector_dir / "sources.json").write_text(
        json.dumps({
            "sources": [
                {"name": "경쟁사 A", "url": "https://a.example.com", "role": "competitor_official", "frequency": "daily"},
                {"name": "경쟁사 B", "url": "https://b.example.com", "role": "competitor_official", "frequency": "weekly"},
                {"name": "경쟁사 C", "url": "https://c.example.com", "role": "competitor_official", "frequency": "weekly"},
                {"name": "경쟁사 D", "url": "https://d.example.com", "role": "competitor_official", "frequency": "weekly"},
            ]
        }),
        encoding="utf-8",
    )

    plan = plan_sources("req_test_source_planner", "sk_broadband", registry_root)
    narrowed = select_top_sources(plan)

    assert [s.name for s in narrowed.planned_sources] == ["경쟁사 A", "경쟁사 B", "경쟁사 C", "경쟁사 D"]


def test_select_top_sources_backfills_when_role_quotas_leave_open_slots(tmp_path):
    registry_root = tmp_path / "registry"
    sector_dir = registry_root / "sk_broadband"
    sector_dir.mkdir(parents=True)
    sources = [
        {
            "name": f"경쟁사 {i}",
            "url": f"https://{i}.example.com",
            "role": "competitor_official",
            "frequency": "daily" if i == 0 else "weekly",
        }
        for i in range(8)
    ]
    (sector_dir / "sources.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")

    plan = plan_sources("req_test_source_planner", "sk_broadband", registry_root)
    narrowed = select_top_sources(plan)

    assert len(narrowed.planned_sources) == 6
    assert narrowed.planned_sources[0].name == "경쟁사 0"


def test_select_top_sources_narrows_broadband_registry_to_six(tmp_path):
    # A registry bigger than the cap should actually get trimmed, unlike
    # plan_sources() alone.
    registry_root = tmp_path / "registry"
    sector_dir = registry_root / "sk_broadband"
    sector_dir.mkdir(parents=True)
    sources = [{"name": f"소스 {i}", "url": f"https://{i}.example.com"} for i in range(9)]
    (sector_dir / "sources.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")

    plan = plan_sources("req_test_source_planner", "sk_broadband", registry_root)
    assert len(plan.planned_sources) == 9

    narrowed = select_top_sources(plan)
    assert len(narrowed.planned_sources) == 6


def test_real_broadband_registry_select_top_sources_respects_quotas():
    project_root = Path(__file__).resolve().parent.parent
    registry_root = project_root / "sources" / "registry"

    plan = plan_sources(
        "req_test_source_planner",
        "sk_broadband",
        registry_root,
        question_keywords=["OTT", "IPTV"],
        perspective="market_landscape",
    )
    narrowed = select_top_sources(plan, perspective="market_landscape")

    assert len(narrowed.planned_sources) == 6
    role_counts: dict[str | None, int] = {}
    for source in narrowed.planned_sources:
        role_counts[source.role] = role_counts.get(source.role, 0) + 1
    # competitor_official has 4 registered candidates (KT, LG유플러스, Netflix, Disney+)
    # but the quota caps that role at 1.
    assert role_counts.get("competitor_official", 0) <= 1
    assert role_counts.get("market_analysis", 0) <= 2
    assert role_counts.get("search", 0) <= 2


def test_competitor_comparison_perspective_raises_the_competitor_role_ceiling():
    project_root = Path(__file__).resolve().parent.parent
    registry_root = project_root / "sources" / "registry"

    plan = plan_sources(
        "req_test_source_planner",
        "sk_broadband",
        registry_root,
        question_keywords=["KT", "LG유플러스", "Netflix", "경쟁"],
        perspective="competitor_comparison",
    )
    narrowed = select_top_sources(plan, perspective="competitor_comparison")

    role_counts: dict[str | None, int] = {}
    for source in narrowed.planned_sources:
        role_counts[source.role] = role_counts.get(source.role, 0) + 1
    # sk_broadband has 4 registered competitor_official sources (KT, LG유플러스,
    # Netflix, Disney+) — a comparison question should be able to pull in more
    # than the usual ceiling of 1.
    assert role_counts.get("competitor_official", 0) > 1
    assert role_counts.get("competitor_official", 0) <= 3


def test_non_comparison_perspective_keeps_the_competitor_role_ceiling_at_one():
    project_root = Path(__file__).resolve().parent.parent
    registry_root = project_root / "sources" / "registry"

    plan = plan_sources(
        "req_test_source_planner",
        "sk_broadband",
        registry_root,
        question_keywords=["OTT", "IPTV"],
        perspective="market_landscape",
    )
    narrowed = select_top_sources(plan, perspective="market_landscape")

    role_counts: dict[str | None, int] = {}
    for source in narrowed.planned_sources:
        role_counts[source.role] = role_counts.get(source.role, 0) + 1
    assert role_counts.get("competitor_official", 0) <= 1


def test_guaranteed_role_is_never_squeezed_to_zero_by_a_perspective_boost(tmp_path):
    # Extreme synthetic case: many high-scoring competitor sources plus a
    # perspective boost that raises their ceiling to 3 — without the
    # guarantee, all 6 slots could go to competitor_official and official/
    # search/market_analysis would vanish entirely even though each has a
    # real registered source.
    registry_root = tmp_path / "registry"
    sector_dir = registry_root / "sk_broadband"
    sector_dir.mkdir(parents=True)
    sources = [
        {
            "name": f"경쟁사 {i}",
            "url": f"https://competitor-{i}.example.com",
            "role": "competitor_official",
            "reliability_tier": "official",
            "frequency": "daily",
            "topics": ["경쟁", "비교"],
        }
        for i in range(6)
    ] + [
        {"name": "공식 뉴스룸", "url": "https://official.example.com", "role": "official", "frequency": "daily"},
        {"name": "전문지", "url": "https://search.example.com", "role": "search", "frequency": "daily"},
        {"name": "시장조사", "url": "https://market.example.com", "role": "market_analysis", "frequency": "daily"},
    ]
    (sector_dir / "sources.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")

    plan = plan_sources(
        "req_test_source_planner",
        "sk_broadband",
        registry_root,
        question_keywords=["경쟁", "비교"],
        perspective="competitor_comparison",
    )
    narrowed = select_top_sources(plan, perspective="competitor_comparison")

    roles_present = {source.role for source in narrowed.planned_sources}
    assert {"official", "search", "market_analysis"} <= roles_present
    assert len(narrowed.planned_sources) == 6


def test_real_naver_common_source_always_survives_selection():
    # 네이버 뉴스 is registered with planning_priority: "core" in
    # sources/registry/common/sources.json specifically so it's never
    # squeezed out by role quotas or perspective boosts, across every sector.
    project_root = Path(__file__).resolve().parent.parent
    registry_root = project_root / "sources" / "registry"

    for sector_id, perspective in [
        ("sk_broadband", "competitor_comparison"),
        ("sk_hynix", "market_landscape"),
        ("sk_telecom", "company_update"),
        ("sk_planet", None),
        ("sk_innovation", "regulatory_policy"),
    ]:
        plan = plan_sources(
            "req_test_source_planner", sector_id, registry_root, question_keywords=["테스트"], perspective=perspective
        )
        narrowed = select_top_sources(plan, perspective=perspective)
        assert "네이버 뉴스" in [source.name for source in narrowed.planned_sources], sector_id


def test_core_common_source_is_guaranteed_a_top_six_slot(tmp_path):
    registry_root = tmp_path / "registry"
    sector_dir = registry_root / "sk_planet"
    common_dir = registry_root / "common"
    sector_dir.mkdir(parents=True)
    common_dir.mkdir(parents=True)
    sector_sources = [
        {
            "name": f"high-score-{index}",
            "url": f"https://{index}.example.com",
            "role": "market_analysis",
            "reliability_tier": "official",
            "frequency": "daily",
            "topics": ["정확한 질문 주제"],
        }
        for index in range(8)
    ]
    (sector_dir / "sources.json").write_text(json.dumps({"sources": sector_sources}), encoding="utf-8")
    (common_dir / "sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "core-news-search",
                        "url": "https://news.example.com",
                        "role": "search",
                        "planning_priority": "core",
                        "frequency": "monthly",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    plan = plan_sources(
        "req_core_source",
        "sk_planet",
        registry_root,
        question_keywords=["정확한 질문 주제"],
        perspective="market_landscape",
    )
    narrowed = select_top_sources(plan, "market_landscape", "current_status")

    assert len(narrowed.planned_sources) == 6
    assert "core-news-search" in [source.name for source in narrowed.planned_sources]
