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

2026-08-09: the user replaced all 5 Solar-role prompts (prompts/*.md) with a
richer prompt suite (labeled A-E in the source material) that returns
substantially more structured judgment than doc1's original minimal shapes —
per-aspect coverage, contradictions, source-quality assessment, evidence
strength, per-selection reasoning. The models below were extended to capture
all of it (user's explicit choice: "전면 정합 — 새 구조 다 반영" over a
minimal compatibility patch) rather than silently dropping fields the new
prompts ask the model to produce.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ValueType = Literal["actual", "estimate", "forecast", "target", "guidance"]
SourceType = Literal["official", "research", "independent", "news", "other"]
StopReason = Literal[
    "sufficient",
    "no_new_information",
    # 2026-08-09: split out of the old catch-all "budget_exhausted" - a live
    # run showed the label couldn't distinguish "the model had nothing left
    # to propose" from "we hit a numeric cap" from "we used up every gap-loop
    # round" (three genuinely different situations for a human reading the
    # result to reason about). See router.py's research().
    "no_further_queries",
    "search_call_budget_exhausted",
    "gap_loop_iterations_exhausted",
]
CoverageStatus = Literal["covered", "partially_covered", "missing", "uncertain"]
RelevanceLevel = Literal["high", "medium", "low"]
EvidenceQualityLevel = Literal["high", "medium", "low", "unclear"]
SummaryVerificationStatus = Literal[
    "accurate", "partially_accurate", "misleading", "unsupported", "unavailable"
]
EvidenceStrength = Literal["direct", "indirect", "contextual", "insufficient"]


class SearchPlanQuery(BaseModel):
    """One planned query — doc1 §4 / prompt A."""

    query: str
    angle: str = ""
    purpose: str = ""
    # 1 = run first; 2 = run only if priority-1 results are insufficient;
    # 3 = last resort (rarely used, doc1 §4's "매우 복잡/논쟁적" case).
    priority: int = 1
    # Precise multi-word entity/regulatory/product terms this query needs
    # exact-phrase matching on (e.g. "중앙그룹", "프로그램 사용료"). The model
    # only has to name these; planner.py mechanically wraps each one in
    # quotation marks inside `query` in code, rather than trusting the model
    # to remember to add the quote marks itself every time. Added 2026-08-09
    # after live testing showed the model quoting "중앙그룹" in only 4 of 7
    # queries and "프로그램 사용료" in 0 of the queries containing it, despite
    # the prompt directly asking for it - a formatting habit turned out to be
    # much less reliable than a plain content judgment ("what are the key
    # terms here?") for the same model.
    key_terms: list[str] = Field(default_factory=list)


class SearchPlan(BaseModel):
    intent: str = ""
    queries: list[SearchPlanQuery] = Field(default_factory=list)

    def by_priority(self, priority: int) -> list[SearchPlanQuery]:
        return [query for query in self.queries if query.priority == priority]


class KeyFact(BaseModel):
    """One structured fact from a *search-summary-level* source — doc1 §6
    recommended shape, with doc2 §6's instruction to keep the fact
    structured rather than a bare string. Only populated when the source
    text actually states it; a field left None means "not stated," never a
    guess. This is web_search.py's (GPT-5 mini) shape — the Evidence
    Verifier's (prompt E, Solar) shape is the qualitative ConfirmedFact
    below, not this one; see EvidenceVerification's docstring for why they
    aren't merged."""

    text: str
    metric: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    time: Optional[str] = None
    value_type: Optional[ValueType] = None


class NextQuery(BaseModel):
    """One follow-up search query proposed by Coverage/Gap Check (prompt B)
    or the Evidence Verifier (prompt E) — replaces the earlier plain string,
    since both prompts now return an object with a stated purpose/priority
    rather than a bare query string."""

    query: str
    purpose: str = ""
    priority: int = 1


class CoverageAspect(BaseModel):
    """One evidence dimension's status — prompt B's per-aspect coverage
    breakdown (STEP 2), finer-grained than the plain covered/missing lists.

    `source_urls` grounds a "covered"/"partially_covered" verdict the same
    way SourceToInspect.url is grounded — check_coverage() only keeps a URL
    here if it's actually one of the results the model was shown, and
    downgrades the status to "uncertain" if none survive. Added 2026-08-09
    after a live run showed a "covered" aspect whose reason cited a claim
    ("KT Genie TV froze subscription fees...") absent from every result in
    the evidence pool — sources_to_inspect's URL had grounding, this
    free-text verdict had none."""

    aspect: str
    status: CoverageStatus = "uncertain"
    reason: str = ""
    source_urls: list[str] = Field(default_factory=list)


class CoveredItem(BaseModel):
    """One confirmed-covered claim from Coverage/Gap Check's
    covered_information list — same grounding rationale as CoverageAspect
    above. A claim with no source_urls surviving the known_urls filter is
    dropped by check_coverage() rather than kept as an unverified string."""

    text: str
    source_urls: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    """Conflicting evidence. Prompt B (coverage, cross-result) reports
    `sources`; prompt E (evidence verifier, one just-inspected source vs.
    prior evidence) reports `conflicts_with`/`possible_explanation` instead —
    both shapes live here since each caller only ever populates the fields
    its own prompt asked for; the rest stay None/empty."""

    issue: str
    sources: list[str] = Field(default_factory=list)
    conflicts_with: Optional[str] = None
    possible_explanation: Optional[str] = None
    needs_resolution: bool = True


class SourceAssessment(BaseModel):
    """Prompt E's judgment of the inspected source itself."""

    url: str = ""
    relevance: Optional[RelevanceLevel] = None
    evidence_quality: Optional[EvidenceQualityLevel] = None


class SummaryVerification(BaseModel):
    """Prompt E's check of whether the earlier search summary/key_facts for
    this source actually held up against the real text."""

    status: Optional[SummaryVerificationStatus] = None
    important_omissions: list[str] = Field(default_factory=list)


class ConfirmedFact(BaseModel):
    """One fact prompt E confirms the source text actually states —
    qualitative (fact + strength + context), not the numeric metric/value/
    unit/time breakdown KeyFact uses for web_search.py's snippet-level
    facts. Deliberately not merged with KeyFact: the two prompts ask for
    genuinely different shapes and forcing one onto the other would either
    invent numeric fields the source-verifier prompt never asked for, or
    drop the qualitative strength/context fields KeyFact has no room for."""

    fact: str
    evidence_strength: EvidenceStrength = "insufficient"
    context: str = ""


class EvidenceVerification(BaseModel):
    """Full output of the Evidence Verifier / Gap Detector stage (prompt E)
    — what a scraped/parsed original source actually establishes, replacing
    the earlier key-facts-only extraction. Carried on
    WebSearchResult.verification so nothing this stage produces (contradic-
    tions, limitations, remaining gaps, its own per-source sufficiency
    judgment) is silently dropped, even though the router's own loop control
    still only acts on CoverageDecision (see router.py's _inspect_source) —
    prompt B stays the single authority for when the loop stops, so this
    stage's own `sufficient`/`next_queries` are informational, not wired
    into control flow, to avoid two independent judges fighting for it."""

    source_assessment: Optional[SourceAssessment] = None
    summary_verification: Optional[SummaryVerification] = None
    confirmed_facts: list[ConfirmedFact] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    remaining_gaps: list[str] = Field(default_factory=list)
    sufficient: bool = False
    next_queries: list[NextQuery] = Field(default_factory=list)


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
    # Populated only when evidence_depth == "original_source" — the full
    # prompt-E judgment behind this result's key_facts/summary.
    verification: Optional[EvidenceVerification] = None


class SourceToInspect(BaseModel):
    url: str
    reason: str = ""
    # What specifically to look for in the full text — Coverage prompt B's
    # addition; empty when the model (or the doc1-only fallback) doesn't
    # supply it.
    target_information: list[str] = Field(default_factory=list)


class CoverageDecision(BaseModel):
    """Coverage/Gap Check output — doc1 §6/§22, plus doc2 §8's additive
    semantic/structural split, plus prompt B's richer per-aspect coverage
    and contradiction detection (all additive; a doc1-only consumer that
    never reads the new fields still works)."""

    sufficient: bool = False
    coverage: list[CoverageAspect] = Field(default_factory=list)
    covered: list[CoveredItem] = Field(default_factory=list)
    # missing stays bare strings deliberately - claiming something is absent
    # doesn't carry the same fabrication risk a "this is covered" claim does,
    # so it doesn't need the same source_urls grounding.
    missing: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    needs_full_text: bool = False
    sources_to_inspect: list[SourceToInspect] = Field(default_factory=list)
    next_queries: list[NextQuery] = Field(default_factory=list)
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


class SectionSelection(BaseModel):
    """One section chosen by prompt C (Section Selector), with its own
    reasoning preserved rather than reduced to a bare section_id."""

    section_id: str
    reason: str = ""
    evidence_role: list[str] = Field(default_factory=list)
    requires_chunk_selection: bool = False


class ChunkSelection(BaseModel):
    """One chunk chosen by prompt D (Chunk Selector), same rationale as
    SectionSelection above."""

    chunk_id: str
    reason: str = ""
    evidence_role: list[str] = Field(default_factory=list)


class SourceRouterResult(BaseModel):
    """Final output of `research()` — the router's own accumulated evidence
    pool. Not consumed by anything downstream yet (see plan file)."""

    question: str
    search_plan: SearchPlan
    results: list[WebSearchResult] = Field(default_factory=list)
    rounds_completed: int = 0
    coverage_history: list[CoverageDecision] = Field(default_factory=list)
    final_coverage: Optional[CoverageDecision] = None
    stop_reason: StopReason = "gap_loop_iterations_exhausted"
    # How many of config.max_web_search_calls were actually spent — added
    # 2026-08-09 so this is visible on the result itself instead of only
    # derivable by counting web_search.py's stderr log lines by hand.
    search_calls_used: int = 0
