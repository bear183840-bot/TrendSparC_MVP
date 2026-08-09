"""Standalone, sector-agnostic Source Router.

Implements final_research_router.md ("doc1") as a NEW system, kept
deliberately parallel to sources/collectors/ai_search_harness.py (the
existing sk_broadband harness, left untouched) per explicit user decision —
see C:\\Users\\noogs\\.claude\\plans\\query-gentle-sketch.md for the full
context and the tracked, non-blocking warnings against the current system
and against doc2/doc3's alignment requirements.

Not wired into core/request_pipeline/pipeline.py or any sector adapter yet.
Usage:

    from sources.collectors.source_router import run_source_router
    result = run_source_router("질문")
"""

from __future__ import annotations

from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    DocumentChunk,
    DocumentSection,
    KeyFact,
    ParsedDocument,
    SearchPlan,
    SearchPlanQuery,
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
    "KeyFact",
    "ParsedDocument",
    "SearchPlan",
    "SearchPlanQuery",
    "SourceRouterResult",
    "SourceToInspect",
    "WebSearchResult",
    "run_source_router",
]
