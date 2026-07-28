"""Build a SourcePlan from the sector's source registry.

Registries live under sources/registry/<sector_id>/*.json. Each registered
source is parsed into a PlannedSource so a sector's adapter/collector can act
on SourcePlan alone, without re-reading and re-parsing the registry itself.
Only fields already present in the registry entry are carried over — nothing
here invents a reliability tier or other field for an unregistered source.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import PlannedSource, SourcePlan


def plan_sources(request_id: str, sector_id: str, registry_root: Path) -> SourcePlan:
    sector_registry_dir = registry_root / sector_id
    planned_sources: list[PlannedSource] = []

    if sector_registry_dir.is_dir():
        for registry_file in sorted(sector_registry_dir.glob("*.json")):
            try:
                data = json.loads(registry_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for raw_source in data.get("sources", []):
                planned_sources.append(PlannedSource.model_validate(raw_source))

    notes = None if planned_sources else "no sources registered for this sector — template_only"
    return SourcePlan(
        request_id=request_id,
        sector_id=sector_id,
        planned_sources=planned_sources,
        notes=notes,
    )
