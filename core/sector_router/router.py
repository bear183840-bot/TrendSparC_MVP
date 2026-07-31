"""Dynamic sector registry + routing.

The set of known sectors is discovered by scanning ``sectors/*/profile.json``.
Routing uses profile aliases/keywords, but avoids routing on one ambiguous
standalone word such as "Planet", "A.", "011", "투자", or "가격". That keeps the
router profile-driven while reducing false positives from generic glossary terms.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import EntityExtractionResult, SectorProfile, SectorRoute

FALLBACK_SECTOR_ID = "general"
_MIN_ROUTE_SCORE = 3

# Cross-sector ambiguous tokens that should never route a question by themselves.
# They may still contribute weak support when a stronger organization/service/
# industry signal is also present.
_AMBIGUOUS_SIGNALS = {
    "planet",
    "플래닛",
    "point",
    "포인트",
    "reward",
    "리워드",
    "web3",
    "a.",
    "011",
    "d2d",
    "투자",
    "실적",
    "매출",
    "영업이익",
    "가격",
    "수요",
    "미국",
    "중국",
    "규제",
    "리스크",
    "전략",
    "에너지",
}


def _normalize(value: str) -> str:
    return value.strip().lower()


def scan_sectors(sectors_dir: Path) -> dict[str, SectorProfile]:
    """Read every sectors/*/profile.json into a sector_id -> profile map."""

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


def _score_profile(entities: EntityExtractionResult, profile: SectorProfile) -> tuple[int, list[str]]:
    aliases = {_normalize(value) for value in profile.aliases}
    keywords = {_normalize(value) for value in profile.keywords}
    market_keywords = {_normalize(value) for value in profile.market_keywords}
    matched: list[str] = []
    score = 0
    strong_match_count = 0

    weighted_terms: list[tuple[str, int, str]] = []
    weighted_terms.extend((term, 10, "organization") for term in entities.organizations)
    weighted_terms.extend((term, 5, "technology") for term in entities.technologies)
    weighted_terms.extend((term, 3, "keyword") for term in entities.keywords)

    for raw_term, base_weight, origin in weighted_terms:
        term = _normalize(raw_term)
        if not term:
            continue
        is_ambiguous = term in _AMBIGUOUS_SIGNALS

        if term in aliases:
            weight = 1 if is_ambiguous else base_weight + 3
        elif term in keywords:
            weight = 1 if is_ambiguous else base_weight
        elif term in market_keywords:
            weight = 1 if is_ambiguous else 2
        else:
            continue

        score += weight
        matched.append(f"{origin}:{raw_term}")
        if not is_ambiguous and weight >= 2:
            strong_match_count += 1

    if strong_match_count == 0:
        return 0, matched
    return score, matched


def route_request(
    request_id: str,
    entities: EntityExtractionResult,
    profiles: dict[str, SectorProfile],
    requested_sector_id: str | None = None,
) -> SectorRoute:
    """Match extracted entities/keywords against registered sector profiles.

    Explicit sector selection is still honored. Without explicit selection, the
    router chooses the highest scoring profile and falls back to ``general`` when
    only weak/generic terms matched.
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

    best_profile: SectorProfile | None = None
    best_score = 0
    best_matches: list[str] = []
    for profile in profiles.values():
        if profile.sector_id == FALLBACK_SECTOR_ID:
            continue
        score, matches = _score_profile(entities, profile)
        if score > best_score:
            best_profile = profile
            best_score = score
            best_matches = matches

    if best_profile is not None and best_score >= _MIN_ROUTE_SCORE:
        return SectorRoute(
            request_id=request_id,
            sector_id=best_profile.sector_id,
            status="routed",
            matched_profile=best_profile,
            reason=f"matched profile signals: {', '.join(best_matches)}; score={best_score}",
        )

    fallback = profiles.get(FALLBACK_SECTOR_ID)
    if fallback is not None:
        return SectorRoute(
            request_id=request_id,
            sector_id=fallback.sector_id,
            status="routed",
            matched_profile=fallback,
            reason="no sector-specific strong signal matched; routed to fallback sector",
        )

    return SectorRoute(
        request_id=request_id,
        sector_id=None,
        status="unsupported",
        reason="no sector matched and no fallback sector is registered",
    )
