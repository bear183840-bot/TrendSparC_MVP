"""Shared type for every entry in the block registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel

from common.contracts import DashboardBlock

BlockRenderFn = Callable[[DashboardBlock], None]


@dataclass(frozen=True)
class SlotContext:
    """Everything a live dashboard block is allowed to read.

    The live dashboard resolves a slot against the *synthesis*, not against a
    trimmed `DashboardBlock`, so its renderers need a wider input than
    `BlockRenderFn` gives. Passing one frozen context instead of eight
    positional arguments is what let the live dispatch move into the registry
    without every block growing a different signature.
    """

    result: Any
    synthesis: Any
    items: list[str]
    risks: list[str]
    opportunities: list[str]
    strengths: list[str]
    weaknesses: list[str]
    presentation: Any | None = None
    question: str = ""
    # Direct registry callers historically receive the complete block.
    # The dashboard opts into the first-screen budget explicitly.
    compact: bool = False
    # Evidence identities an earlier slot on this page already drew, in the
    # namespace `purpose_slots._consumption()` uses. Slot resolution can only
    # drop a block whose facts are *entirely* already shown; a block that
    # draws a set - one card per composed whole - subtracts these itself so
    # the half of it that is new still gets drawn. Empty means "nothing yet",
    # which is what a caller rendering one block in isolation wants.
    drawn_before: frozenset[str] = frozenset()


# Returns a zero-arg callable that draws the block, or None when the data
# would draw nothing. None is what keeps an empty titled card off the page,
# so it is part of the contract, not an error path.
SlotRenderFn = Callable[[SlotContext], Callable[[], None] | None]


@dataclass(frozen=True)
class BlockDefinition:
    block_type: str
    schema: type[BaseModel]
    render: BlockRenderFn
    description: str
    # The live dashboard's renderer for this same block type. Optional
    # because the two paths were built separately: `render` draws a
    # layout-generated `DashboardBlock`, `slot_render` draws a slot the
    # purpose skeleton resolved. A block may have either or both, and
    # registering one never erases the other.
    slot_render: SlotRenderFn | None = None
