"""Firecrawl — HTML source → Clean Markdown. doc1 §10.

Reuses the shared FIRECRAWL_API_KEY (already sector-agnostic, see
sources/collectors/kofic_pdf.py and every sector's Firecrawl-based
collector) rather than minting a new dedicated env var for this package.
"""

from __future__ import annotations

import os
import sys

_API_KEY_ENV_VAR = "FIRECRAWL_API_KEY"


def extract_html(url: str, *, timeout_seconds: int = 120) -> str | None:
    """Return clean markdown for a URL, or None on any failure (missing key,
    network error, empty content). A miss means "still needs full text" to
    the caller, never a crash."""
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key:
        print("[source_router.html_extractor] FIRECRAWL_API_KEY not set", file=sys.stderr)
        return None
    try:
        from firecrawl import Firecrawl  # imported lazily — unit tests don't need network/API setup

        client = Firecrawl(api_key=api_key, timeout=timeout_seconds, max_retries=1)
        document = client.scrape(url, formats=["markdown"])
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.html_extractor] scrape failed for {url}: {exc}", file=sys.stderr)
        return None
    markdown = getattr(document, "markdown", None)
    if not markdown and isinstance(document, dict):
        markdown = document.get("markdown")
    return markdown or None
