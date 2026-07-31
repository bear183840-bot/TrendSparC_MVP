import json
from pathlib import Path

from common.contracts import EntityExtractionResult
from core.sector_router.router import route_request, scan_sectors

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECTORS_DIR = PROJECT_ROOT / "sectors"


def _entities(organizations=None, technologies=None, keywords=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        request_id="req_test_router",
        primary_intent="current_status",
        perspective="company_update",
        organizations=organizations or [],
        technologies=technologies or [],
        keywords=keywords or [],
    )


def _route(entities: EntityExtractionResult, requested_sector_id=None):
    return route_request("req_test_router", entities, scan_sectors(SECTORS_DIR), requested_sector_id)


def test_requesting_unregistered_sector_is_unsupported():
    route = _route(_entities(), requested_sector_id="sk_totally_made_up")

    assert route.status == "unsupported"
    assert route.sector_id == "sk_totally_made_up"
    assert route.reason is not None


def test_registered_sector_can_be_routed_explicitly():
    route = _route(_entities(), requested_sector_id="sk_hynix")

    assert route.status == "routed"
    assert route.matched_profile.sector_id == "sk_hynix"


def test_sk_planet_is_registered_after_unassigned_rename():
    route = _route(_entities(), requested_sector_id="sk_planet")

    assert route.status == "routed"
    assert route.matched_profile.sector_id == "sk_planet"


def test_router_routes_strong_sector_signals():
    cases = [
        (_entities(organizations=["SK하이닉스"], technologies=["HBM4"], keywords=["양산"]), "sk_hynix"),
        (_entities(organizations=["SK온"], keywords=["배터리", "북미 공장"]), "sk_innovation"),
        (_entities(organizations=["SK플래닛"], keywords=["OK캐쉬백", "데이터 마케팅"]), "sk_planet"),
        (_entities(organizations=["SK텔레콤"], keywords=["AI 데이터센터"]), "sk_telecom"),
        (_entities(organizations=["SK브로드밴드"], keywords=["OTT", "IPTV"]), "sk_broadband"),
        (_entities(keywords=["B tv", "AI 추천", "유료방송"]), "sk_broadband"),
    ]

    for entities, expected_sector in cases:
        route = _route(entities)
        assert route.status == "routed"
        assert route.sector_id == expected_sector


def test_router_does_not_route_on_ambiguous_single_terms():
    cases = [
        _entities(technologies=["D2D"], keywords=["반도체", "본딩"]),
        _entities(keywords=["Planet"]),
        _entities(keywords=["포인트"]),
        _entities(keywords=["A."]),
        _entities(keywords=["투자"]),
    ]

    for entities in cases:
        route = _route(entities)
        assert route.status == "routed"
        assert route.sector_id == "general"


def test_adding_and_removing_a_sector_folder_changes_registry_without_core_changes(tmp_path):
    sectors_dir = tmp_path / "sectors"
    sectors_dir.mkdir()

    hynix_dir = sectors_dir / "sk_hynix"
    hynix_dir.mkdir()
    (hynix_dir / "profile.json").write_text(
        json.dumps({"sector_id": "sk_hynix", "display_name": "SK hynix", "status": "template_only"}),
        encoding="utf-8",
    )

    profiles_before = scan_sectors(sectors_dir)
    assert set(profiles_before.keys()) == {"sk_hynix"}

    new_sector_dir = sectors_dir / "brand_new_sector"
    new_sector_dir.mkdir()
    (new_sector_dir / "profile.json").write_text(
        json.dumps({"sector_id": "brand_new_sector", "display_name": "Brand New Sector", "status": "template_only"}),
        encoding="utf-8",
    )

    profiles_after_add = scan_sectors(sectors_dir)
    assert set(profiles_after_add.keys()) == {"sk_hynix", "brand_new_sector"}

    for item in hynix_dir.glob("*"):
        item.unlink()
    hynix_dir.rmdir()

    profiles_after_remove = scan_sectors(sectors_dir)
    assert set(profiles_after_remove.keys()) == {"brand_new_sector"}
