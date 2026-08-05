"""Shared type for every entry in the block registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from common.contracts import DashboardBlock

BlockRenderFn = Callable[[DashboardBlock], None]


@dataclass(frozen=True)
class BlockDefinition:
    block_type: str
    schema: type[BaseModel]
    render: BlockRenderFn
    description: str
