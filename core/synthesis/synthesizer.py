"""Sector-agnostic aggregation of DocumentAnalysis into a TrendSynthesis.

This performs structural aggregation only (counting, concatenating points
already produced by a sector's analyzer) — it never invents insights. With
no document analyses (the normal case in this scaffold, since every sector
adapter is stub-only), it returns an explicitly empty synthesis.
"""

from __future__ import annotations

from common.contracts import DocumentAnalysis, TrendSynthesis


def synthesize(
    request_id: str,
    sector_id: str,
    document_analyses: list[DocumentAnalysis],
) -> TrendSynthesis:
    highlights: list[str] = []
    for analysis in document_analyses:
        highlights.extend(analysis.key_points)

    return TrendSynthesis(
        request_id=request_id,
        sector_id=sector_id,
        highlights=highlights,
        synthesis_text=None,
        source_count=len(document_analyses),
    )
