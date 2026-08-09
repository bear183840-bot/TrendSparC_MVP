"""Bridge Source Router output to the existing TrendSparC source contract."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from common.contracts import PlannedSource, SourceCollectionResult, SourceDocument, SourcePlan
from sources.collectors.source_router.contracts import SourceRouterResult, WebSearchResult


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "external-source").casefold()


def match_registry_source(
    url: str, registered_sources: list[PlannedSource]
) -> PlannedSource | None:
    """Match exact/subdomain ownership without treating registry as a whitelist."""
    domain = _domain(url)
    for source in registered_sources:
        if not source.url:
            continue
        registered_domain = _domain(source.url)
        if domain == registered_domain or domain.endswith(f".{registered_domain}"):
            return source
    return None


def _doc_id(source_id: str, url: str) -> str:
    digest = hashlib.sha1(f"source-router:{source_id}:{url}".encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{digest}"


def _table_cells(line: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]


def semanticize_markdown_tables(content: str) -> str:
    """Repeat exact table cells as header=value text without inventing values."""
    lines = content.splitlines()
    rendered_rows: list[str] = []
    index = 0
    while index + 1 < len(lines):
        header_line = lines[index]
        separator_line = lines[index + 1]
        if not (header_line.lstrip().startswith("|") and separator_line.lstrip().startswith("|")):
            index += 1
            continue
        headers = _table_cells(header_line)
        separators = _table_cells(separator_line)
        if not separators or not all(
            re.fullmatch(r":?-{3,}:?", cell) for cell in separators if cell
        ):
            index += 1
            continue
        row_index = index + 2
        while row_index < len(lines) and lines[row_index].lstrip().startswith("|"):
            values = _table_cells(lines[row_index])
            pairs = [
                f"{header}={values[column]}"
                for column, header in enumerate(headers)
                if header and column < len(values) and values[column]
            ]
            if len(pairs) >= 2:
                rendered_rows.append("표 원문 행: " + "; ".join(pairs) + ".")
            row_index += 1
        index = row_index
    if not rendered_rows:
        return content
    return content + "\n\n[표 원문 행 구조화]\n\n" + "\n\n".join(rendered_rows)


def _document_from_result(
    result: WebSearchResult, registered_sources: list[PlannedSource]
) -> tuple[SourceDocument, dict]:
    registry = match_registry_source(result.url, registered_sources)
    source_id = registry.name if registry else _domain(result.url)
    content = semanticize_markdown_tables(result.original_content or "")
    document = SourceDocument(
        doc_id=_doc_id(source_id, result.url),
        source_id=source_id,
        title=result.title or "Untitled",
        url=result.url,
        content=content,
        media_type=result.media_type,
        reliability_tier=registry.reliability_tier if registry else None,
    )
    lineage = {
        "url": result.url,
        "search_query": result.search_query,
        "query_role": result.query_role,
        "evidence_need_ids": list(result.evidence_need_ids),
        "registry_match": registry.name if registry else None,
        "original_source": True,
        "document_id": document.doc_id,
        "verification": result.verification.model_dump() if result.verification else None,
    }
    return document, lineage


def source_router_result_to_collection(
    result: SourceRouterResult, source_plan: SourcePlan
) -> SourceCollectionResult:
    """Only inspected original sources enter Processor/Validator/Analyzer."""
    registered = source_plan.registered_sources or source_plan.planned_sources
    documents: list[SourceDocument] = []
    lineage: list[dict] = []
    for item in result.results:
        if item.evidence_depth != "original_source" or not item.original_content:
            continue
        document, record = _document_from_result(item, registered)
        documents.append(document)
        lineage.append(record)
    by_id = {document.doc_id: document for document in documents}
    return SourceCollectionResult(
        documents=list(by_id.values()),
        collection_mode="source_router",
        minimum_validated_documents=0,
        router_trace={
            "question": result.question,
            "search_plan": result.search_plan.model_dump(),
            "sources": lineage,
            "coverage_history": [item.model_dump() for item in result.coverage_history],
            "final_coverage": result.final_coverage.model_dump() if result.final_coverage else None,
            "stop_reason": result.stop_reason,
            "search_calls_used": result.search_calls_used,
        },
    )
