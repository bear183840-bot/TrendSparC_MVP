"""Build a SourcePlan from the sector's source registry.

Registries live under sources/registry/<sector_id>/*.json. In this scaffold
every registry is empty, so every plan comes back with an explicit
template_only note rather than pretending sources are configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import SourcePlan


def plan_sources(request_id: str, sector_id: str, registry_root: Path) -> SourcePlan:
    sector_registry_dir = registry_root / sector_id
    planned_sources: list[str] = []

    if sector_registry_dir.is_dir():
        for registry_file in sorted(sector_registry_dir.glob("*.json")):
            try:
                data = json.loads(registry_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            planned_sources.extend(data.get("sources", []))

    notes = None if planned_sources else "no sources registered for this sector — template_only"
    return SourcePlan(
        request_id=request_id,
        sector_id=sector_id,
        planned_sources=planned_sources,
        notes=notes,
    )
