"""Names belonging to *other* registered sectors.

A search for one SK affiliate routinely returns articles that report a sibling
affiliate's results in the same piece - an SK텔레콤 earnings story that also
mentions SK브로드밴드, say. Whatever reads that article can then lift the
wrong company's figure into the report, and `MetricPoint` has no subject
field, so once a number is in `metric_series` it reads as this company's own.

Resolved from the registered `sectors/*/profile.json` files at runtime, never
from a hardcoded list, so registering a new affiliate protects every existing
one automatically.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

_SECTORS_DIR = Path(__file__).resolve().parent.parent.parent / "sectors"

# Names too generic to disqualify a figure. "SK" appears inside every
# affiliate's own name, so matching on it would throw away the very rows we
# want to keep.
_TOO_GENERIC = {"sk", "SK", "에스케이"}


def _profile_names(profile: Any) -> Iterable[str]:
    for value in (
        getattr(profile, "display_name", None),
        getattr(profile, "canonical_name", None),
        *(getattr(profile, "aliases", None) or []),
    ):
        if value and value not in _TOO_GENERIC and len(value) > 2:
            yield value


def own_entity_names(sector_id: str, profiles: dict[str, Any]) -> set[str]:
    profile = profiles.get(sector_id)
    return set(_profile_names(profile)) if profile else set()


def foreign_entity_names(sector_id: str, profiles: dict[str, Any]) -> set[str]:
    """Names that identify a different registered sector than `sector_id`.

    Anything that is also one of this sector's own names is excluded, so an
    alias two affiliates happen to share can never disqualify a figure.
    """
    own = own_entity_names(sector_id, profiles)
    foreign: set[str] = set()
    for other_id, profile in profiles.items():
        if other_id == sector_id:
            continue
        foreign |= set(_profile_names(profile))
    return {name for name in foreign if name not in own}


@lru_cache(maxsize=8)
def foreign_entity_names_for(sector_id: str) -> frozenset[str]:
    """Convenience wrapper that scans the registry itself.

    Cached because the profile set is fixed for a process, and callers sit on
    per-item loops where re-reading a dozen JSON files would be wasteful.
    """
    from core.sector_router.router import scan_sectors

    return frozenset(foreign_entity_names(sector_id, scan_sectors(_SECTORS_DIR)))


def names_another_company(text: str, foreign_names: set[str], own_names: set[str]) -> bool:
    """True when `text` names a different affiliate and not this one.

    A sentence that mentions both ("SK텔레콤과 SK브로드밴드는 …") is kept: it is
    genuinely about this company too, and dropping it would lose real evidence.
    Only text that names *only* the other company is rejected.
    """
    if not text:
        return False
    if any(name in text for name in own_names):
        return False
    return any(name in text for name in foreign_names)


def drop_other_affiliates_metrics(metric_points: list[Any], sector_id: str) -> list[Any]:
    """Remove figures whose own label says they belong to another affiliate.

    Observed live: a question about SK브로드밴드 returned an article covering
    SK텔레콤's earnings, and "SK텔레콤 영업이익 5,376억원" was rendered in the
    KPI row of a SK브로드밴드 report. `MetricPoint` carries no subject, so a
    row in `metric_series` is read as this company's own number - the label
    naming someone else is the one signal available, and it is decisive.

    Applies to metric_series only. `ComparisonPoint` is explicitly
    entity-vs-entity, so a competitor there is the point, not a contaminant.
    """
    from core.sector_router.router import scan_sectors

    profiles = scan_sectors(_SECTORS_DIR)
    foreign = foreign_entity_names(sector_id, profiles)
    if not foreign:
        return metric_points
    own = own_entity_names(sector_id, profiles)
    kept = []
    for point in metric_points:
        if names_another_company(getattr(point, "label", "") or "", foreign, own):
            print(
                f"[synthesis] metric dropped - names another affiliate: "
                f"{getattr(point, 'label', '')} ({getattr(point, 'period', '')})",
                file=sys.stderr,
            )
            continue
        kept.append(point)
    return kept
