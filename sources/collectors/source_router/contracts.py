"""Self-contained Pydantic contracts for the standalone Source Router.

Deliberately NOT common/contracts.py's MetricPoint/ComparisonPoint/
GroundedClaim, even though those already cover most of this shape. This is a
tracked, non-blocking warning (see
C:\\Users\\noogs\\.claude\\plans\\query-gentle-sketch.md, "경고 사항") — the
user explicitly prioritized building doc1's design as a new parallel system
over reusing existing downstream contracts for this first pass.

Shapes follow final_research_router.md §22, with two additive fields the
attached doc2/doc3 alignment notes asked for (both optional, so a strict
doc1-only reading of a payload still validates):
  - WebSearchResult.evidence_depth: doc2 §7's "Level 1 vs Level 2" split.
  - CoverageDecision.semantic_sufficient / structural_sufficient: doc2 §8.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ValueType = Literal["actual", "estimate", "forecast", "target", "guidance"]
SourceType = Literal["official", "research", "independent", "news", "other"]
StopReason = Literal["sufficient", "budget_exhausted", "no_new_information"]


class SearchPlanQuery(BaseModel):
    """One planned query — doc1 §4."""

    query: str
    angle: str = ""
    purpose: str = ""
    # 1 = run first; 2 = run only if priority-1 results are insufficient;
    # 3 = last resort (rarely used, doc1 §4's "매우 복잡/논쟁적" case).
    priority: int = 1


class SearchPlan(BaseModel):
    intent: str = ""
    queries: list[SearchPlanQuery] = Field(default_factory=list)

    def by_priority(self, priority: int) -> list[SearchPlanQuery]:
        return [query for query in self.queries if query.priority == priority]


class KeyFact(BaseModel):
    """One structured fact from a source — doc1 §6 recommended shape, with
    doc2 §6's instruction to keep the fact structured rather than a bare
    string. Only populated when the source text actually states it; a field
    left None means "not stated," never a guess."""

    text: str
    metric: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    time: Optional[str] = None
    value_type: Optional[ValueType] = None


class WebSearchResult(BaseModel):
    """One source found (or later deepened) by the router — doc1 §5/§22."""

    url: str
    title: str = ""
    source_type: SourceType = "other"
    summary: str = ""
    key_facts: list[KeyFact] = Field(default_factory=list)
    relevance: str = ""
    # doc2 §7's Level 1/Level 2 split: was this confirmed from a search
    # snippet/summary, or from the actually-scraped/parsed original source.
    evidence_depth: Literal["search_summary", "original_source"] = "search_summary"


class SourceToInspect(BaseModel):
    url: str
    reason: str = ""


class CoverageDecision(BaseModel):
    """Coverage/Gap Check output — doc1 §6/§22, plus doc2 §8's additive
    semantic/structural split (both optional; a doc1-only consumer that
    never reads them still works)."""

    sufficient: bool = False
    covered: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    needs_full_text: bool = False
    sources_to_inspect: list[SourceToInspect] = Field(default_factory=list)
    next_queries: list[str] = Field(default_factory=list)
    semantic_sufficient: Optional[bool] = None
    structural_sufficient: Optional[bool] = None
    reason: str = ""


class DocumentSection(BaseModel):
    """Large/Huge PDF Section Map entry — doc1 §13/§16.

    `full_text` is an implementation-detail extension beyond doc1's example
    JSON (which only sketches title/pages/preview) — it's how a selected
    section's original text travels from pdf_parser.py to router.py without
    a second parse call. `preview` stays short by convention even though
    `full_text` holds everything.
    """

    section_id: str
    title: str = ""
    pages: str = ""
    token_count: Optional[int] = None
    preview: str = ""
    subsections: list[str] = Field(default_factory=list)
    full_text: Optional[str] = None


class DocumentChunk(BaseModel):
    """Huge PDF Chunk Map entry — doc1 §14/§17. `text` is populated once the
    chunk is selected and loaded (same extension rationale as
    DocumentSection.full_text above)."""

    chunk_id: str
    section_id: str = ""
    heading: str = ""
    pages: str = ""
    token_count: Optional[int] = None
    preview: str = ""
    text: Optional[str] = None


class ParsedDocument(BaseModel):
    """Upstage Document Parse output, before size-based routing — doc1 §11."""

    source_url: str
    document_title: str = ""
    token_count: int = 0
    full_text: Optional[str] = None
    sections: list[DocumentSection] = Field(default_factory=list)


class SourceRouterResult(BaseModel):
    """Final output of `research()` — the router's own accumulated evidence
    pool. Not consumed by anything downstream yet (see plan file)."""

    question: str
    search_plan: SearchPlan
    results: list[WebSearchResult] = Field(default_factory=list)
    rounds_completed: int = 0
    coverage_history: list[CoverageDecision] = Field(default_factory=list)
    final_coverage: Optional[CoverageDecision] = None
    stop_reason: StopReason = "budget_exhausted"
