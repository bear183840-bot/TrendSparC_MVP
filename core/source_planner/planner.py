"""Build a SourcePlan from the sector's source registry.

Registries live under sources/registry/<sector_id>/*.json. Each registered
source is parsed into a PlannedSource so a sector's adapter/collector can act
on SourcePlan alone, without re-reading and re-parsing the registry itself.
Only fields already present in the registry entry are carried over — nothing
here invents a reliability tier or other field for an unregistered source.

sources/registry/common/*.json is merged into every sector's SourcePlan
regardless of sector_id — it holds sources useful across all sectors (see
sources/registry/common/README.md), not sector-specific business sources.

When a `perspective` is given (see EntityExtractionResult.perspective),
planned_sources is stable-sorted by each source's `content_type` so the
sources most likely to have the right kind of content get searched first
under the collector's shared rate-limit budget: analytical/industry-press
coverage first for market_landscape questions, official/press_release
coverage first for company_update questions. Sources with no content_type
set, or a perspective with no defined priority, keep the registry's
original order.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import PlannedSource, SourcePlan

_COMMON_REGISTRY_DIR_NAME = "common"

_CONTENT_TYPE_PRIORITY_BY_PERSPECTIVE: dict[str, dict[str | None, int]] = {
    "market_landscape": {"analysis": 0, None: 1, "press_release": 2},
    "company_update": {"press_release": 0, None: 1, "analysis": 2},
}


def _load_registry_dir(registry_dir: Path) -> list[PlannedSource]:
    planned_sources: list[PlannedSource] = []
    if not registry_dir.is_dir():
        return planned_sources

    for registry_file in sorted(registry_dir.glob("*.json")):
        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for raw_source in data.get("sources", []):
            planned_sources.append(PlannedSource.model_validate(raw_source))

    return planned_sources


def plan_sources(
    request_id: str,
    sector_id: str,
    registry_root: Path,
    question_keywords: list[str] | None = None,
    perspective: str | None = None,
) -> SourcePlan:
    planned_sources = _load_registry_dir(registry_root / sector_id) + _load_registry_dir(
        registry_root / _COMMON_REGISTRY_DIR_NAME
    )

    priority_map = _CONTENT_TYPE_PRIORITY_BY_PERSPECTIVE.get(perspective)
    if priority_map:
        planned_sources = sorted(planned_sources, key=lambda source: priority_map.get(source.content_type, 1))

    notes = None if planned_sources else "no sources registered for this sector — template_only"
    return SourcePlan(
        request_id=request_id,
        sector_id=sector_id,
        planned_sources=planned_sources,
        question_keywords=question_keywords or [],
        notes=notes,
    )
