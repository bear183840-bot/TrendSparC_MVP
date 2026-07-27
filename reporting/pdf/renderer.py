"""One-page PDF renderer stub. No real PDF generation is implemented yet."""

from __future__ import annotations

from common.contracts import DynamicLayout


def render(layout: DynamicLayout) -> str:
    return (
        f"template_only: pdf renderer not implemented "
        f"(request_id={layout.request_id}, {len(layout.blocks)} block(s) pending)"
    )
