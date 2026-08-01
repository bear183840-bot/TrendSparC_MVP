"""Shared helpers for Firecrawl search results."""

from __future__ import annotations


def response_markdown(response) -> str | None:
    """Read markdown from SDK objects or mapping-shaped fallback responses."""
    if response is None:
        return None
    markdown = getattr(response, "markdown", None)
    if markdown:
        return markdown
    if isinstance(response, dict):
        markdown = response.get("markdown")
        if markdown:
            return markdown
        data = response.get("data")
        if isinstance(data, dict):
            return data.get("markdown")
    data = getattr(response, "data", None)
    return getattr(data, "markdown", None) if data is not None else None
