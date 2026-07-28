import json
from pathlib import Path

from common.contracts import EntityExtractionResult
from core.sector_router.router import route_request, scan_sectors

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECTORS_DIR = PROJECT_ROOT / "sectors"


def _empty_entities() -> EntityExtractionResult:
    return EntityExtractionResult(request_id="req_test_router", organizations=[], technologies=[], keywords=[])


def test_requesting_unregistered_sector_is_unsupported():
    profiles = scan_sectors(SECTORS_DIR)
    route = route_request("req_test_router", _empty_entities(), profiles, requested_sector_id="sk_totally_made_up")

    assert route.status == "unsupported"
    assert route.sector_id == "sk_totally_made_up"
    assert route.reason is not None


def test_registered_sector_can_be_routed_explicitly():
    profiles = scan_sectors(SECTORS_DIR)
    route = route_request("req_test_router", _empty_entities(), profiles, requested_sector_id="sk_hynix")

    assert route.status == "routed"
    assert route.matched_profile.sector_id == "sk_hynix"


def test_sk_planet_is_registered_after_unassigned_rename():
    profiles = scan_sectors(SECTORS_DIR)
    route = route_request("req_test_router", _empty_entities(), profiles, requested_sector_id="sk_planet")

    assert route.status == "routed"
    assert route.matched_profile.sector_id == "sk_planet"


def test_adding_and_removing_a_sector_folder_changes_registry_without_core_changes(tmp_path):
    sectors_dir = tmp_path / "sectors"
    sectors_dir.mkdir()

    hynix_dir = sectors_dir / "sk_hynix"
    hynix_dir.mkdir()
    (hynix_dir / "profile.json").write_text(
        json.dumps({
            "sector_id": "sk_hynix",
            "display_name": "SK hynix",
            "status": "template_only",
        }),
        encoding="utf-8",
    )

    profiles_before = scan_sectors(sectors_dir)
    assert set(profiles_before.keys()) == {"sk_hynix"}

    new_sector_dir = sectors_dir / "brand_new_sector"
    new_sector_dir.mkdir()
    (new_sector_dir / "profile.json").write_text(
        json.dumps({
            "sector_id": "brand_new_sector",
            "display_name": "Brand New Sector",
            "status": "template_only",
        }),
        encoding="utf-8",
    )

    profiles_after_add = scan_sectors(sectors_dir)
    assert set(profiles_after_add.keys()) == {"sk_hynix", "brand_new_sector"}

    for item in hynix_dir.glob("*"):
        item.unlink()
    hynix_dir.rmdir()

    profiles_after_remove = scan_sectors(sectors_dir)
    assert set(profiles_after_remove.keys()) == {"brand_new_sector"}
