"""Extensible dashboard block registry.

Adding a new block type requires exactly two edits: one new file in this
package (defining a schema, a render function, and a description, then
self-registering) and one import line added below. `registry.py` and
`renderer.py` never need to change - `renderer.normalized_block_type()`
checks `registry.known_types()`, which reads whatever is currently
registered, not a fixed list.

Checklist for a new block file:
  1. Define a Pydantic model describing the shape of `DashboardBlock.content`
     (or `.data`) this block expects - the schema is documentation and a
     validation tool for tests, not a runtime gate (DashboardBlock.content
     stays a loose dict[str, Any] so unrelated stages never break).
  2. Write a `render(block: DashboardBlock) -> None` function. Style only
     through the CSS custom properties already defined in theme.py
     (--ts-accent, --ts-orange, --ts-teal, --ts-ink, --ts-line, --ts-panel,
     ...) - never a hardcoded hex color, so every block automatically
     follows the light/dark and orange/burgundy toggles.
  3. Call `registry.register(BlockDefinition(block_type=..., schema=...,
     render=..., description=...))` at module level.
  4. Import the new module below so it actually registers on package import.
"""

from __future__ import annotations

from reporting.dashboard_streamlit.blocks import (  # noqa: F401
    action_list,
    bar,
    cause_map,
    evidence,
    kpi_card,
    line_area,
    matrix,
    misc,
    radar,
    table,
    timeline,
)
