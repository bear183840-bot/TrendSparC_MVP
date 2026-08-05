"""The block registry itself - block_type string -> BlockDefinition.

`known_types()` is what makes the registry actually extensible: it reads
`BLOCK_REGISTRY` live, so a block registered by any file gets recognized
immediately, with no edits here or in renderer.py.
"""

from __future__ import annotations

import logging
from typing import Any

from reporting.dashboard_streamlit.blocks.base import BlockDefinition

_LOGGER = logging.getLogger("trendsparc.blocks")

BLOCK_REGISTRY: dict[str, BlockDefinition] = {}

# Content shapes that didn't fit any registered block type, logged for a
# human to review - never used to generate a block automatically. Cleared
# only by restarting the process; tests read/clear this directly.
SUGGESTED_BLOCK_TYPES: list[dict[str, Any]] = []


def register(definition: BlockDefinition) -> None:
    BLOCK_REGISTRY[definition.block_type] = definition


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
