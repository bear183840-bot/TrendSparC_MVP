"""The block registry itself - block_type string -> BlockDefinition.

`known_types()` is what makes the registry actually extensible: it reads
`BLOCK_REGISTRY` live, so a block registered by any file gets recognized
immediately, with no edits here or in renderer.py.
"""

from __future__ import annotations

import logging
from typing import Any

from dataclasses import replace

from reporting.dashboard_streamlit.blocks.base import BlockDefinition

_LOGGER = logging.getLogger("trendsparc.blocks")

BLOCK_REGISTRY: dict[str, BlockDefinition] = {}

# Content shapes that didn't fit any registered block type, logged for a
# human to review - never used to generate a block automatically. Cleared
# only by restarting the process; tests read/clear this directly.
SUGGESTED_BLOCK_TYPES: list[dict[str, Any]] = []


def register(definition: BlockDefinition) -> None:
    """Add a block, or fill in a half a block type was still missing.

    The two rendering paths register separately - `render` from the
    layout-block modules, `slot_render` from the live dashboard's table - and
    both name the same block types. A plain overwrite would mean whichever
    module imported last silently deleted the other's renderer.

    So a second registration only *fills gaps*: it can supply a renderer the
    block type didn't have, and it can never replace one it did. Whichever
    module owns a field keeps owning it regardless of import order, which is
    the property that makes the merge safe to reason about.
    """
    existing = BLOCK_REGISTRY.get(definition.block_type)
    if existing is not None:
        definition = replace(
            existing,
            render=existing.render or definition.render,
            slot_render=existing.slot_render or definition.slot_render,
        )
    BLOCK_REGISTRY[definition.block_type] = definition


def slot_renderer(block_type: str):
    """The live dashboard's renderer for this block type, or None."""
    definition = BLOCK_REGISTRY.get(block_type)
    return definition.slot_render if definition else None


def get(block_type: str) -> BlockDefinition | None:
    return BLOCK_REGISTRY.get(block_type)


def known_types() -> set[str]:
    return set(BLOCK_REGISTRY.keys())


def suggest_new_block_type(section: str, content: dict[str, Any], reason: str) -> None:
    """Log a candidate new block type - detection only, never auto-created.

    A human reviews `_LOGGER`'s output (or SUGGESTED_BLOCK_TYPES in-process)
    and decides whether it's worth a real block file, per the same
    checklist as any other block in this package.
    """
    entry = {"section": section, "reason": reason, "content_keys": sorted(content.keys())}
    SUGGESTED_BLOCK_TYPES.append(entry)
    _LOGGER.info("candidate new block type for section '%s': %s (keys=%s)", section, reason, entry["content_keys"])
