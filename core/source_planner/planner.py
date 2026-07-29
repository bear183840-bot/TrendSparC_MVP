"""Build a SourcePlan from the sector's source registry.

Registries live under sources/registry/<sector_id>/*.json. Each registered
source is parsed into a PlannedSource so a sector's adapter/collector can act
on SourcePlan alone, without re-reading and re-parsing the registry itself.
Only fields already present in the registry entry are carried over — nothing
here invents a reliability tier or other field for an unregistered source.

sources/registry/common/*.json is merged into every sector's SourcePlan
regardless of sector_id — it holds sources useful across all sectors (see
sources/registry/common/README.md), not sector-specific business sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import PlannedSource, SourcePlan

_COMMON_REGISTRY_DIR_NAME = "common"


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
) -> SourcePlan:
    planned_sources = _load_registry_dir(registry_root / sector_id) + _load_registry_dir(
        registry_root / _COMMON_REGISTRY_DIR_NAME
    )

    notes = None if planned_sources else "no sources registered for this sector — template_only"
    return SourcePlan(
        request_id=request_id,
        sector_id=sector_id,
        planned_sources=planned_sources,
        question_keywords=question_keywords or [],
        notes=notes,
    )
