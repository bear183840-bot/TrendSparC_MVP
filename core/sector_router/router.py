"""Dynamic sector registry + routing.

The set of known sectors is never hardcoded here. It is discovered at call
time by scanning `sectors/*/profile.json`. Adding or removing a folder under
`sectors/` changes routing behavior with zero changes to this file.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import EntityExtractionResult, SectorProfile, SectorRoute

FALLBACK_SECTOR_ID = "general"


def scan_sectors(sectors_dir: Path) -> dict[str, SectorProfile]:
    """Read every sectors/*/profile.json into a sector_id -> SectorProfile map.

    Folders without a valid profile.json are skipped rather than failing the
    whole scan, so a work-in-progress sector folder can't break routing for
    every other sector.
    """
    profiles: dict[str, SectorProfile] = {}
    if not sectors_dir.is_dir():
        return profiles

    for entry in sorted(sectors_dir.iterdir()):
        profile_path = entry / "profile.json"
        if not entry.is_dir() or not profile_path.is_file():
            continue
        try:
            raw = json.loads(profile_path.read_text(encoding="utf-8"))
            profile = SectorProfile.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        profiles[profile.sector_id] = profile

    return profiles


def route_request(
    request_id: str,
    entities: EntityExtractionResult,
    profiles: dict[str, SectorProfile],
    requested_sector_id: str | None = None,
) -> SectorRoute:
    """Match extracted entities/keywords against registered sector profiles.

    If the caller names a sector explicitly and it isn't registered, routing
    fails clearly as unsupported rather than silently falling back.
    """
    if requested_sector_id is not None:
        profile = profiles.get(requested_sector_id)
        if profile is None:
            return SectorRoute(
                request_id=request_id,
                sector_id=requested_sector_id,
                status="unsupported",
                reason=f"sector '{requested_sector_id}' is not registered under sectors/",
            )
        return SectorRoute(
            request_id=request_id,
            sector_id=profile.sector_id,
            status="routed",
            matched_profile=profile,
        )

    signals = {s.lower() for s in (*entities.organizations, *entities.technologies, *entities.keywords)}
    for profile in profiles.values():
        candidates = {s.lower() for s in (*profile.aliases, *profile.keywords)}
        if signals & candidates:
            return SectorRoute(
                request_id=request_id,
                sector_id=profile.sector_id,
                status="routed",
                matched_profile=profile,
            )

    fallback = profiles.get(FALLBACK_SECTOR_ID)
    if fallback is not None:
        return SectorRoute(
            request_id=request_id,
            sector_id=fallback.sector_id,
            status="routed",
            matched_profile=fallback,
            reason="no sector-specific signal matched; routed to fallback sector",
        )

    return SectorRoute(
        request_id=request_id,
        sector_id=None,
        status="unsupported",
        reason="no sector matched and no fallback sector is registered",
    )
