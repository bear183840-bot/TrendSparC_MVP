"""collector for the sk_hynix sector adapter.

Fetches each source registered in sources/registry/sk_hynix/sources.json via
the Firecrawl API (crawl -> markdown per page) and converts the result into
SourceDocument objects. A document is only ever produced from a real
Firecrawl response for a registered source's URL — nothing here fabricates
content, and no reliability_tier is invented (the registry only carries a
free-text reliability_reason, not a tier taxonomy, so the field is left
unset until one is defined).
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime

from firecrawl import Firecrawl

from common.contracts import PlannedSource, SourceDocument, SourcePlan
from common.errors import PipelineStageError

_API_KEY_ENV_VAR = "FIRECRAWL_API_KEY"
_PAGES_PER_SOURCE = 10
_STAGE = "sectors.sk_hynix.adapter.collector"


def _doc_id(source: PlannedSource, url: str) -> str:
    digest = hashlib.sha1(f"{source.name}:{url}".encode("utf-8")).hexdigest()[:16]
    return f"{source.name}:{digest}"


def _parse_published_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _crawl_source(client: Firecrawl, source: PlannedSource) -> list[SourceDocument]:
    try:
        job = client.crawl(source.url, limit=_PAGES_PER_SOURCE, formats=["markdown"])
    except Exception as exc:  # Firecrawl SDK/network failure, not a template_only case
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"failed to crawl source '{source.name}'",
            detail=str(exc),
        ) from exc

    documents: list[SourceDocument] = []
    for page in job.data or []:
        page_url = page.metadata.url if page.metadata else None
        if not page.markdown or not page_url:
            continue
        documents.append(
            SourceDocument(
                doc_id=_doc_id(source, page_url),
                source_id=source.name,
                title=(page.metadata.title if page.metadata else None) or source.name,
                url=page_url,
                published_at=_parse_published_at(page.metadata.published_time if page.metadata else None),
                content=page.markdown,
            )
        )
    return documents


def collect(source_plan: SourcePlan) -> list[SourceDocument]:
    if not source_plan.planned_sources:
        raise PipelineStageError(
            stage=_STAGE,
            reason="template_only: no sources registered for sk_hynix",
        )

    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"template_only: {_API_KEY_ENV_VAR} is not configured",
        )

    client = Firecrawl(api_key=api_key)
    documents: list[SourceDocument] = []
    for source in source_plan.planned_sources:
        if not source.url:
            continue
        documents.extend(_crawl_source(client, source))

    return documents
