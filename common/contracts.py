"""Shared Pydantic contracts for every block boundary in the pipeline.

Every block (core stage, sector adapter, audience adapter, reporting renderer)
communicates only through these models or the sector-local contracts that wrap
them. Do not branch on sector name or audience name anywhere that consumes
these models — always resolve behavior through a registered profile instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    attachment_id: str
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    source_path: Optional[str] = None
    content_base64: Optional[str] = Field(default=None, exclude=True, repr=False)


class AttachmentExtraction(BaseModel):
    attachment_id: str
    filename: str
    status: Literal["extracted", "empty", "unsupported", "failed"]
    character_count: int = 0
    truncated: bool = False
    error: Optional[str] = None


class UserRequest(BaseModel):
    request_id: str
    question: str
    requested_by: Optional[str] = None
    target_audience: Optional[str] = None
    requested_sector_id: Optional[str] = None
    attachments: list[Attachment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EntityExtractionResult(BaseModel):
    request_id: str
    primary_intent: str
    # What kind of question this is, distinct from primary_intent: whether it's
    # asking about the market/industry as a whole (market_landscape), a specific
    # company's own service/results (company_update), a head-to-head comparison
    # (competitor_comparison), or law/regulation (regulatory_policy). Used by
    # core/entity/search_terms.py to decide whether to search with brand names
    # or sector-level market terms — a brand-name search tends to surface that
    # brand's own press coverage, which is wrong for a market_landscape question.
    perspective: str
    organizations: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    # Evidence categories required to answer the question. These are shared
    # across sectors and matched against registry-owned source capabilities.
    information_needs: list[str] = Field(default_factory=list)
    # Conversational questions do not enter the report pipeline. Report-worthy
    # questions without an SK-sector match continue through the general route.
    response_mode: Optional[Literal["report", "direct_answer"]] = None
    direct_answer: Optional[str] = None
    # Optional routing metadata. Existing consumers can ignore these fields;
    # the router uses them only when the second-pass AI made a final decision.
    sector_id: Optional[str] = None
    routing_confidence: Optional[Literal["low", "medium", "high"]] = None
    routing_reason: Optional[str] = None
    needs_ai_routing: Optional[bool] = None
    extraction_method: Optional[Literal["ai", "rule_fallback"]] = None
    extraction_error: Optional[str] = None


class ReportPurposeClassification(BaseModel):
    """Question-level report purpose contract.

    This is intentionally separate from EntityExtractionResult.primary_intent.
    Entity extraction answers "what is mentioned in the question?" while report
    purpose answers "what kind of report should be generated?". Downstream
    stages should depend on this contract rather than re-reading prompt text or
    branching on raw user wording.
    """

    request_id: str
    purpose_id: Literal["current_status", "issue_response", "future_business", "root_cause"]
    display_name: str
    description: Optional[str] = None
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: Optional[str] = None
    classifier_version: str = "rule_based_v1"
    recommended_sections: list[str] = Field(default_factory=list)
    dashboard_block_hints: list[str] = Field(default_factory=list)
    prompt_path: Optional[str] = None
    # Set when a runner-up purpose independently clears its own signal threshold
    # (see content_quality_validator.detect_secondary_purpose) - a compound
    # question like "현황은? 그리고 어떻게 개선하지?" is both current_status and
    # root_cause/future_business at once, not a single winner-take-all purpose.
    secondary_purpose_id: Optional[
        Literal["current_status", "issue_response", "future_business", "root_cause"]
    ] = None


class SectorProfile(BaseModel):
    sector_id: str
    display_name: str
    canonical_name: Optional[str] = None
    status: Literal["active", "template_only", "unsupported"]
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    # Sector/industry-level terms (e.g. "포인트 마케팅 시장"), distinct from the
    # brand/product terms in `keywords` above — used as the search anchor for
    # market_landscape-perspective questions instead of a brand name.
    market_keywords: list[str] = Field(default_factory=list)
    # Registry-owned business context supplied to AI stages. Core code never
    # branches on a sector id; adding a new sector only requires profile data.
    key_metrics: list[str] = Field(default_factory=list)
    strategic_dimensions: list[str] = Field(default_factory=list)
    # Optional, registry-owned list of domains to keep out of AI web-search
    # results for this sector - for a site that is currently unscrapable
    # (e.g. the scrape provider cannot reach it) rather than one that is
    # untrustworthy. Core reads this generically and never branches on a
    # sector id. Remove an entry once the site works again; it is a
    # temporary operational block, not a judgement about the source.
    blocked_scrape_domains: list[str] = Field(default_factory=list)
    # Optional, registry-owned post-validation recovery policy. Core reads
    # these values generically and never branches on a sector id.
    min_validated_documents: int = 0
    max_validation_recollection_attempts: int = 0
    min_analyzed_documents: int = 0
    # Desired evidence depth. The pipeline recollects toward this value but
    # only halts when `min_analyzed_documents` is not met.
    target_analyzed_documents: int = 0
    max_analysis_recollection_attempts: int = 0
    pipeline_entrypoint: Optional[str] = None
    system_prompt_path: Optional[str] = None


class SectorRoute(BaseModel):
    request_id: str
    sector_id: Optional[str] = None
    status: Literal["routed", "unsupported"]
    matched_profile: Optional[SectorProfile] = None
    reason: Optional[str] = None
    confidence: Optional[Literal["low", "medium", "high"]] = None
    routing_method: Optional[Literal["user_selected", "rule_based", "ai", "fallback"]] = None
    needs_ai_routing: bool = False


class PlannedSource(BaseModel):
    name: str
    url: Optional[str] = None
    country: Optional[str] = None
    type: Optional[str] = None
    collection_method: list[str] = Field(default_factory=list)
    frequency: Optional[str] = None
    category: list[str] = Field(default_factory=list)
    reliability_reason: Optional[str] = None
    # Optional, free-text but meant to follow a shared 3-tier convention
    # (confirmed with an SK브로드밴드 domain expert, not invented by us):
    #   "official"       — government/company's own first-party statements
    #   "analyst_media"   — industry press or aggregator/database (interprets
    #                       or curates, doesn't just publish raw fact)
    #   "user_generated"  — audience reviews/reactions; not fact-checked and
    #                       not meant to be — it's a signal of sentiment, not
    #                       a claim to verify. Left unset until a sector
    #                       defines its own tiering (no sector-name branching
    #                       on this — each sector's own registry decides).
    reliability_tier: Optional[str] = None
    # Optional: whether this source's typical content is a company's own
    # press_release-style announcement, or analysis (industry press/market
    # research that interprets the market, not just one company). Left unset
    # when neither fits (e.g. user-review platforms) — never guessed. Used by
    # core/source_planner/planner.py to reorder sources per question perspective.
    content_type: Optional[Literal["press_release", "analysis"]] = None
    # Optional: this source's role in a per-sector coverage quota, distinct
    # from content_type above (role is about *why this source is registered*,
    # not what kind of writing it produces). Free-text, not a fixed enum,
    # because sectors may need their own roles beyond the three core ones:
    #   "official"        — the sector's own SK 계열사 official newsroom/press
    #                       channel (every sector should have >= 1)
    #   "search"           — general-purpose trade press/news media used for
    #                       broad info search (every sector should have >= 2)
    #   "market_analysis"  — market research firms, traffic/data analytics, or
    #                       deep-analysis trade press that interprets the
    #                       market/competitive landscape (every sector should
    #                       have >= 1)
    # Sector-specific custom roles (e.g. "competitor_official",
    # "user_sentiment", "commodity_market") are added only when genuinely
    # meaningful for that sector's registered sources — never invented to
    # fill a quota. Left unset (not guessed) when a source doesn't clearly
    # fit any role.
    role: Optional[str] = None
    # Free-text subject tags describing what this specific source tends to
    # cover (e.g. ["망 사용료", "AI 미디어"]) — distinct from a sector's own
    # profile.json keywords/market_keywords, which describe the sector as a
    # whole. Used by core/source_planner/planner.py to score a source's
    # topical match against a question's extracted keywords/organizations/
    # technologies when selecting the top sources for a given question.
    # Left empty when a source's coverage is too broad/general to tag
    # meaningfully — never guessed.
    topics: list[str] = Field(default_factory=list)
    # What kinds of evidence this source can normally provide. Values use the
    # same shared vocabulary as EntityExtractionResult.information_needs.
    capabilities: list[str] = Field(default_factory=list)
    # Registry-driven planning importance. "core" sources receive a reserved
    # Top-N slot but still pass the same document relevance/quality validation.
    planning_priority: Optional[Literal["core", "standard", "supporting"]] = None


class WebSearchContext(BaseModel):
    """Question-level context supplied to an AI web-search stage.

    Suggested terms are hints from the deterministic entity/search-term
    stages, not a query the model must copy verbatim.  The original question
    and evidence needs remain authoritative so the search model can choose a
    better first query when the precomputed terms are too narrow.
    """

    question: str
    # The routed sector's canonical company name (e.g. "SK브로드밴드"), so a
    # question that only says "우리회사"/"our company" still resolves to a
    # specific, searchable company instead of leaving the search model to
    # guess from the raw question text alone. None for sectors with no single
    # company (e.g. "general").
    company_name: Optional[str] = None
    perspective: Optional[str] = None
    report_purpose_id: Optional[str] = None
    information_needs: list[str] = Field(default_factory=list)
    suggested_terms: list[str] = Field(default_factory=list)
    as_of_date: Optional[str] = None
    country_code: str = "KR"
    excluded_urls: list[str] = Field(default_factory=list)
    # Whole domains to keep out of results, unlike the per-URL excluded_urls
    # above. Sourced from the routed SectorProfile.blocked_scrape_domains.
    excluded_domains: list[str] = Field(default_factory=list)
    validation_feedback: list[str] = Field(default_factory=list)


class SourcePlan(BaseModel):
    request_id: str
    sector_id: str
    planned_sources: list[PlannedSource] = Field(default_factory=list)
    # Complete registry snapshot used for attribution/validation after an
    # open-web discovery pass. `planned_sources` may be narrowed for legacy
    # per-source collectors; this list deliberately remains untrimmed.
    registered_sources: list[PlannedSource] = Field(default_factory=list)
    question_keywords: list[str] = Field(default_factory=list)
    information_needs: list[str] = Field(default_factory=list)
    search_context: Optional[WebSearchContext] = None
    notes: Optional[str] = None


class SourceCollectionEvent(BaseModel):
    """One observable source-collection step for UI progress and audit logs."""

    source_name: str
    source_index: int
    source_total: int
    status: Literal["started", "completed", "failed", "skipped"]
    document_count: int = 0
    detail: Optional[str] = None


class SourceDocument(BaseModel):
    doc_id: str
    source_id: str
    # Optional: some Firecrawl responses carry no title in either the top-level
    # result or its metadata. A missing title doesn't make the content
    # unusable, so the collector still records the document — validator's
    # _is_valid() is what actually filters out title-less documents before
    # they reach analysis, not this contract.
    title: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    content: Optional[str] = None
    # MIME type detected by the collector. This is necessary for direct
    # download endpoints whose URL/title has no `.pdf` suffix.
    media_type: Optional[str] = None
    reliability_tier: Optional[str] = None


class SourceCollectionResult(BaseModel):
    """Documents plus the collection policy required by downstream stages.

    Legacy collectors may still return ``list[SourceDocument]``. A collector
    that enables a stricter mode uses this contract so the pipeline does not
    need to inspect sector names or environment variables.
    """

    documents: list[SourceDocument] = Field(default_factory=list)
    collection_mode: Literal["legacy", "ai_search_harness"] = "legacy"
    minimum_validated_documents: Optional[int] = None


class EvidenceCoverageAssessment(BaseModel):
    """LLM judgment over successfully scraped source text, not search snippets."""

    sufficient: bool
    relevant_doc_ids: list[str]
    covered_information_needs: list[str]
    missing_information_needs: list[str]
    next_queries: list[str]
    reason: str


class WebSearchHarnessResult(BaseModel):
    documents: list[SourceDocument] = Field(default_factory=list)
    sufficient: bool = False
    covered_information_needs: list[str] = Field(default_factory=list)
    missing_information_needs: list[str] = Field(default_factory=list)
    rounds_completed: int = 0
    scrape_call_count: int = 0


class MetricPoint(BaseModel):
    """One evidence-stated number tied to a time period (e.g. subscriber count in a given
    year). Never estimated or interpolated — only populated when a document states it."""

    label: str
    period: str
    value: float
    unit: Optional[str] = None
    # Stable synthesis-level identity and provenance. Analyzer-produced points
    # may leave these empty; the rule-based synthesizer fills them without
    # asking an LLM to invent or alter a number.
    metric_id: Optional[str] = None
    evidence_claim_id: Optional[str] = None
    evidence_synthesis_claim_id: Optional[str] = None
    evidence_quote: Optional[str] = None
    doc_id: Optional[str] = None
    source_id: Optional[str] = None
    source_url: Optional[str] = None


class ComparisonPoint(BaseModel):
    """One evidence-stated fact comparing an entity against a shared criterion (e.g. a
    competitor's price tier). `level` is only set when the document itself states an
    explicit ranking — never inferred from tone or absence of information."""

    entity: str
    criterion: str
    value: str
    level: Optional[Literal["low", "medium", "high"]] = None
    comparison_id: Optional[str] = None
    evidence_claim_id: Optional[str] = None
    evidence_synthesis_claim_id: Optional[str] = None
    doc_id: Optional[str] = None
    source_id: Optional[str] = None
    source_url: Optional[str] = None


class GroundedClaim(BaseModel):
    """A claim whose supporting quote was verified against one source document."""

    claim_id: str
    claim_type: Literal[
        "key_point",
        "business_impact",
        "risk",
        "opportunity",
        "strength",
        "weakness",
        "comparison",
        "metric",
        "action",
        "monitoring",
    ]
    claim: str
    evidence_quote: str
    # Stable analyzer-local paragraph identifier used to verify/repair the
    # quote. It is provenance metadata and need not be rendered in the UI.
    evidence_passage_id: Optional[str] = None
    evidence_location: Optional[str] = None
    as_of_date: Optional[str] = None
    source_url: Optional[str] = None
    confidence: Literal["low", "medium", "high"]


class DocumentAnalysis(BaseModel):
    doc_id: str
    source_id: Optional[str] = None
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    reliability_tier: Optional[str] = None
    summary: Optional[str] = None
    key_points: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    # Strategy fields are optional for backward compatibility, but every
    # sector analyzer should populate them when enough source evidence exists.
    business_impact: Optional[str] = None
    risk: Optional[str] = None
    opportunity: Optional[str] = None
    # The other half of a SWOT pair with risk/opportunity above — same
    # optional-string, evidence-only convention.
    strength: Optional[str] = None
    weakness: Optional[str] = None
    # Structured numeric/comparison facts, only when the document states them
    # explicitly (see MetricPoint/ComparisonPoint docstrings) — empty list is
    # the default and correct state for most documents.
    metric_points: list[MetricPoint] = Field(default_factory=list)
    comparison_points: list[ComparisonPoint] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    action_level: Optional[Literal["Monitor", "Review", "Prepare", "Act", "insufficient_data"]] = None
    analysis_confidence: Optional[Literal["low", "medium", "high"]] = None
    relevance_level: Optional[Literal["direct", "partial", "background", "irrelevant"]] = None
    relevance_reason: Optional[str] = None
    grounded_claims: list[GroundedClaim] = Field(default_factory=list)
    covered_information_needs: list[str] = Field(default_factory=list)
    missing_information_needs: list[str] = Field(default_factory=list)
    analysis_validation_status: Optional[
        Literal["verified", "partial_grounding", "insufficient_grounding", "not_applicable"]
    ] = None
    usable_for_synthesis: Optional[bool] = None
    # None until a question-aware analyzer actually judges this document;
    # True/False once it does. The pipeline drops False entries before they
    # ever reach synthesis — see core/request_pipeline/pipeline.py.
    relevant_to_question: Optional[bool] = None


class ContradictingClaim(BaseModel):
    """One side of a Contradiction — a single document's version of a claim."""

    claim: str
    doc_id: str
    source_id: Optional[str] = None


class Contradiction(BaseModel):
    """Two or more collected documents make conflicting claims about the same
    topic. Populated only by the AI refinement pass in core/synthesis/ai_based.py
    (best-effort, silently absent whenever that pass doesn't run) — never
    fabricated by the rule-based synthesizer.
    """

    topic: str
    conflicting_claims: list[ContradictingClaim] = Field(default_factory=list)


class SynthesisSource(BaseModel):
    """Auditable source metadata preserved at the synthesis handoff boundary."""

    doc_id: str
    source_id: str
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    reliability_tier: Optional[str] = None


class SynthesisClaim(BaseModel):
    """A verified analyzer claim with document and source provenance intact."""

    synthesis_claim_id: str
    claim_id: str
    claim_type: Literal[
        "key_point",
        "business_impact",
        "risk",
        "opportunity",
        "strength",
        "weakness",
        "comparison",
        "metric",
        "action",
        "monitoring",
    ]
    claim: str
    evidence_quote: str
    evidence_location: Optional[str] = None
    as_of_date: Optional[str] = None
    confidence: Literal["low", "medium", "high"]
    doc_id: str
    source_id: str
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    reliability_tier: Optional[str] = None


class SynthesisConclusion(BaseModel):
    """One synthesized conclusion linked only to verified analyzer claims.

    The IDs are internal audit metadata. UI renderers intentionally show the
    conclusion text without exposing its claim graph.
    """

    conclusion_id: str
    conclusion: str
    supporting_claim_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


class CorroboratedPoint(BaseModel):
    """A claim confirmed by >= 2 documents from genuinely independent
    registered sources (distinct source_id, not just distinct doc_id — two
    documents from the same source don't corroborate each other). Independence
    is verified in code from TrendSynthesis.doc_source_map, never trusted from
    the model's own count.
    """

    claim: str
    supporting_doc_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)


class TrendSynthesis(BaseModel):
    request_id: str
    sector_id: str
    highlights: list[str] = Field(default_factory=list)
    synthesis_text: Optional[str] = None
    source_count: int = 0
    unique_source_count: int = 0
    source_ids: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    business_impacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    metric_series: list[MetricPoint] = Field(default_factory=list)
    comparison_points: list[ComparisonPoint] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence_labels: list[str] = Field(default_factory=list)
    # doc_id -> source_id, populated by the rule-based synthesizer (pure
    # bookkeeping, no LLM) so the AI refinement pass can verify how many
    # *independent* sources back a claim without re-deriving this mapping.
    doc_source_map: dict[str, str] = Field(default_factory=dict)
    # Stable handoff for downstream report planning/generation. Unlike the
    # legacy tagged strings above, these preserve the verified quote and full
    # document/source provenance without requiring string parsing.
    grounded_claims: list[SynthesisClaim] = Field(default_factory=list)
    conclusions: list[SynthesisConclusion] = Field(default_factory=list)
    sources: list[SynthesisSource] = Field(default_factory=list)
    covered_information_needs: list[str] = Field(default_factory=list)
    missing_information_needs: list[str] = Field(default_factory=list)
    analysis_validation_status_by_doc_id: dict[str, str] = Field(default_factory=dict)
    # Claims backed by >= 2 independent sources. Empty unless the AI
    # refinement pass ran and found some — never fabricated.
    corroborated_points: list[CorroboratedPoint] = Field(default_factory=list)
    # Claims that appear in only one independent source. Kept and labeled
    # explicitly rather than dropped, so a report can flag them as unverified
    # instead of silently presenting them with the same confidence as a
    # corroborated point.
    uncorroborated_points: list[str] = Field(default_factory=list)
    # Conflicting claims across documents, grouped by topic. Empty unless the
    # AI refinement pass ran and found some.
    contradictions: list[Contradiction] = Field(default_factory=list)


class SectionEvidenceRefs(BaseModel):
    """Internal evidence routing for one report section; never UI copy."""

    conclusion_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    comparison_ids: list[str] = Field(default_factory=list)


class ReportPlan(BaseModel):
    request_id: str
    audience_id: str
    # Kept for backwards compatibility with existing tests/callers. New code
    # should treat `report_purpose.purpose_id` as the canonical report type.
    primary_intent: str
    report_purpose: Optional[ReportPurposeClassification] = None
    sections: list[str] = Field(default_factory=list)
    section_evidence_map: dict[str, SectionEvidenceRefs] = Field(default_factory=dict)
    omitted_sections: dict[str, str] = Field(default_factory=dict)
    format: Literal["dashboard", "html", "pdf"] = "html"
    intent_emphasis: Optional[str] = None


class AudienceAdaptation(BaseModel):
    request_id: str
    audience_id: str
    tone: Optional[str] = None
    adapted_sections: dict = Field(default_factory=dict)


class GeneratedReportSection(BaseModel):
    section_id: str
    title: str
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    metric_points: list[MetricPoint] = Field(default_factory=list)
    comparison_points: list[ComparisonPoint] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)
    # Internal provenance only. Audience/layout/UI layers must preserve this
    # field but do not render claim IDs or quote linkage by default.
    grounded_claims: list[SynthesisClaim] = Field(default_factory=list)
    conclusions: list[SynthesisConclusion] = Field(default_factory=list)
    confidence: Optional[str] = None


class GeneratedReport(BaseModel):
    request_id: str
    sector_id: str
    audience_id: str
    purpose_id: str
    title: str
    executive_summary: str = ""
    sections: list[GeneratedReportSection] = Field(default_factory=list)
    source_count: int = 0
    unique_source_count: int = 0
    limitations: list[str] = Field(default_factory=list)
    generation_mode: Literal["rule_based", "openai"] = "rule_based"
    # Figures the report writer structured out of evidence prose that the
    # rule-based regex extractor had missed, already checked back against the
    # evidence text. The pipeline merges these into TrendSynthesis.metric_series
    # so the dashboard's chart/KPI/timeline blocks - which read the synthesis,
    # not the report - can finally see them. Empty on the rule_based path.
    extracted_metric_series: list[MetricPoint] = Field(default_factory=list)


class DashboardBlock(BaseModel):
    """Design-neutral handoff unit between Layout Generator and UI renderers.

    ``block_type`` is intentionally free text. The backend may later emit a
    known renderer type (table/chart/timeline/graph/etc.) or a new type from a
    finalized design without changing the pipeline contract first. Unknown
    types must be preserved and rendered through the generic fallback.
    """

    block_id: str
    section: str
    title: Optional[str] = None
    block_type: str = "auto"
    content: dict[str, Any] = Field(default_factory=dict)
    data: Any = None
    config: dict[str, Any] = Field(default_factory=dict)


class DynamicLayout(BaseModel):
    request_id: str
    format: str
    blocks: list[DashboardBlock] = Field(default_factory=list)
    render_target: Optional[str] = None
