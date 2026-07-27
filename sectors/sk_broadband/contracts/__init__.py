"""Sector-local contract re-exports for SK Broadband.

No sector-specific fields have been added yet — this module re-exports the
shared contracts so sector code always imports from its own local
`contracts` package, keeping the door open to add sk_broadband-specific
extensions later without touching call sites elsewhere.
"""

from common.contracts import (
    DocumentAnalysis,
    ReportPlan,
    SourceDocument,
    SourcePlan,
    TrendSynthesis,
)

__all__ = [
    "DocumentAnalysis",
    "ReportPlan",
    "SourceDocument",
    "SourcePlan",
    "TrendSynthesis",
]
