"""Self-contained Pydantic contracts for the Source Router package.

Deliberately NOT common/contracts.py's MetricPoint/ComparisonPoint/
GroundedClaim. These describe what a *search and retrieval* run knows - a
query, a URL, whether the original text was read and verified - which is a
different subject from the evidence contracts the report is built out of.
`adapter.py` is the single translation point between the two, so the router
can change its own shapes without touching downstream contracts.

Shapes follow final_research_router.md §22, with one additive field the
attached doc2/doc3 alignment notes asked for (optional, so a strict
doc1-only reading of a payload still validates):
  - WebSearchResult.evidence_depth: doc2 §7's "Level 1 vs Level 2" split.
(CoverageDecision.semantic_sufficient/structural_sufficient, doc2 §8's other
additive field, was removed 2026-08-11 - the coverage.md prompt actually in
use (replaced 2026-08-09, see below) never asks the model for either value,
so both were permanently None/dead in every real response; nothing in
router.py ever read them either.)

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

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# "planned" added 2026-08-11: live-verified, a web_search KeyFact for a
# stated roadmap/schedule item ("12단은 2025년에 공급 예정") raised a
# pydantic ValidationError against the original 5 values, halting the whole
# collector stage. It is not "target" (a company's own aspirational goal
# figure) or "guidance" (official forward financial guidance) or "forecast"
# (an analyst's prediction) - a scheduled roadmap commitment is none of
# those, so folding it into an existing value would misrepresent what the
# source actually said rather than just widen a category. This field is
# populated by a plain-text-prompted model response (see web_search.py's
# `_system_prompt`, not a strict JSON-schema tool call), so the prompt's own
# allowed-value list was updated alongside this enum - schema alone doesn't
# enforce it here.
ValueType = Literal["actual", "estimate", "forecast", "target", "guidance", "planned"]
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
QueryRole = Literal["direct", "supporting"]
RefinerAction = Literal["KEEP", "ADD", "REWRITE"]


class EvidenceNeed(BaseModel):
    """Short semantic evidence requirement used by query refinement.

    This deliberately contains no block or renderer vocabulary.  ``direct``
    needs come from the user's explicit answer requirements; ``supporting``
    needs add only the comparison/time/impact structure needed to make the
    answer useful and verifiable.
    """

    evidence_need_id: str
    text: str
    requirement_type: Literal["direct", "supporting", "optional"] = "supporting"
    priority: int = Field(default=2, ge=1, le=3)
    answer_requirement_ids: list[str] = Field(default_factory=list)


class QueryRefinement(BaseModel):
    """Auditable result of the small slot-aware query refinement stage."""

    action: RefinerAction = "KEEP"
    added_queries: list[str] = Field(default_factory=list)
    rewritten_queries: list[str] = Field(default_factory=list)
    covered_evidence_need_ids: list[str] = Field(default_factory=list)
    missing_evidence_need_ids: list[str] = Field(default_factory=list)
    method: Literal["ai", "rule_fallback"] = "rule_fallback"
    reason: str = ""


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
    # Capped to planner.py's _MAX_KEY_TERMS_PER_QUERY (2) regardless of how
    # many the model names - multiple quoted exact-phrase terms in one query
    # are effectively ANDed by web search, so quoting more than a couple
    # makes a match across all of them vanishingly unlikely. Live-verified
    # 2026-08-10: a query with 5 quoted terms returned almost nothing across
    # 8 search calls. This list always reflects what was actually quoted in
    # `query`, not everything the model originally named - terms beyond the
    # cap are dropped before quoting, not just left unquoted.
    key_terms: list[str] = Field(default_factory=list)
    query_role: QueryRole = "direct"
    evidence_need_ids: list[str] = Field(default_factory=list)


class SearchPlan(BaseModel):
    intent: str = ""
    queries: list[SearchPlanQuery] = Field(default_factory=list)
    evidence_needs: list[EvidenceNeed] = Field(default_factory=list)
    refinement: Optional[QueryRefinement] = None
    # Which of the 4 report purposes shaped this plan's STEP 2.5 axis
    # expansion (prompts/planner.md) - the caller's value if one was given,
    # else the planner model's own classification (defensively clamped to
    # these 4 values, None if the model returned something else). Recorded
    # here (not just passed as an argument) so a SearchPlan is self-
    # describing about what context actually shaped it, same reasoning as
    # `intent` above.
    purpose_id: Optional[Literal[
        "current_status", "issue_response", "future_business", "root_cause"
    ]] = None
    # Which of the 4 report audiences shaped this plan's STEP 2.6 axis
    # adjustment. Always an echo of the caller-supplied value - audience is
    # never inferred from the question (see planner.py's plan_searches()).
    audience: Optional[Literal[
        "practitioner", "executive", "management", "external"
    ]] = None
    # The as_of_date this plan's query generation used to resolve
    # freshness-sensitive year/date terms (planner_common_tail.md's
    # freshness rule) - always an echo of the caller-supplied value, never
    # invented here. None means the caller passed none (as_of_date is
    # optional upstream too - see common/contracts.py's WebSearchContext).
    as_of_date: Optional[str] = None
    # The recency window (in days) common.recency.max_age_days() derived
    # from `question`/`as_of_date`/`purpose_id` - a planning hint surfaced
    # to the model, not a hard filter (source_router has no post-hoc age
    # filter of its own). None means either no as_of_date was available or
    # the question implies no bound (e.g. a historical question).
    resolved_max_age_days: Optional[int] = None

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
    # Query lineage is attached mechanically by router._run_queries(), never
    # inferred from the search model's prose.
    search_query: str = ""
    query_role: QueryRole = "supporting"
    evidence_need_ids: list[str] = Field(default_factory=list)
    # Exact source material retained after HTML/PDF inspection so the existing
    # Analyzer can re-check claims against real passages. Search summaries are
    # never copied into this field.
    original_content: Optional[str] = None
    media_type: Optional[str] = None
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)


class SourceToInspect(BaseModel):
    url: str
    reason: str = ""
    # What specifically to look for in the full text — Coverage prompt B's
    # addition; empty when the model (or the doc1-only fallback) doesn't
    # supply it.
    target_information: list[str] = Field(default_factory=list)


class CoverageDecision(BaseModel):
    """Coverage/Gap Check output — doc1 §6/§22, plus prompt B's richer
    per-aspect coverage and contradiction detection (additive; a doc1-only
    consumer that never reads the new fields still works).

    Does not carry a semantic/structural sufficiency split - doc2 §8 asked
    for one, but coverage.md (replaced 2026-08-09) never asks the model to
    produce it, so the field was always None in practice. Removed
    2026-08-11 rather than kept as permanently-dead observability."""

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
    # Text of every covered/covered_information claim this round's model
    # response made that _parse_coverage_aspects/_parse_covered_items
    # rejected for citing no real source_urls in this round's evidence pool
    # (the same claims that print an UNGROUNDED CLAIM WARNING to stderr).
    # Added 2026-08-11 so router.py can feed this list back into the NEXT
    # round's check_coverage() call (previously_rejected_claims) - without
    # it, the model has no memory of what it fabricated last round and can
    # repeat the exact same ungrounded claim indefinitely.
    rejected_claims: list[str] = Field(default_factory=list)
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
    pool. `adapter.source_router_result_to_collection()` turns the entries
    that reached original-source depth into the SourceDocument list the
    existing processor/validator/analyzer consume."""

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
    # The budget this run actually had, which is NOT
    # config.max_web_search_calls - that is only a ceiling. router's
    # _search_budget() derives a smaller per-question number from the
    # question's own complexity, so a plain status question runs on 6 while
    # the config reads 12. Recording only `search_calls_used` made
    # "search_call_budget_exhausted at 6 of 12" look like a premature abort;
    # it was the budget being met exactly. `search_budget_basis` names each
    # term so the derivation can be read off the trace instead of re-derived
    # from the source.
    search_budget: Optional[int] = None
    search_budget_basis: dict[str, int] = Field(default_factory=dict)
