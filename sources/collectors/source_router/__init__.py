"""Sector-agnostic Source Router — the production search and collection engine.

Implements final_research_router.md ("doc1"). It was built parallel to
sources/collectors/ai_search_harness.py; since the pipeline integration it is
the only engine the production collector boundary calls, and the harness
remains only for its own unit tests and for reading older runs.

core/request_pipeline/pipeline.py routes the `collector` role here through
`sources.collectors.source_router.integration.collect()`; the sector adapters
still own processing, validation and analysis. Direct usage:

    from sources.collectors.source_router import run_source_router
    result = run_source_router("질문", audience="executive", purpose_id="issue_response")
"""

from __future__ import annotations

from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    DocumentChunk,
    DocumentSection,
    EvidenceNeed,
    KeyFact,
    ParsedDocument,
    SearchPlan,
    SearchPlanQuery,
    QueryRefinement,
    SourceRouterResult,
    SourceToInspect,
    WebSearchResult,
)
from sources.collectors.source_router.router import research as run_source_router

__all__ = [
    "SourceRouterConfig",
    "CoverageDecision",
    "DocumentChunk",
    "DocumentSection",
    "EvidenceNeed",
    "KeyFact",
    "ParsedDocument",
    "SearchPlan",
    "SearchPlanQuery",
    "QueryRefinement",
    "SourceRouterResult",
    "SourceToInspect",
    "WebSearchResult",
    "run_source_router",
]
