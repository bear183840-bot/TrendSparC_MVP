"""Request pipeline orchestration skeleton.

Runs every stage in a fixed order, records a StageTrace per stage, and halts
with a clearly identified failing stage if any stage raises a
PipelineStageError that isn't an expected "template_only" signal from a
not-yet-implemented sector adapter.

`dry_run=True` (the default) never invokes sector adapter code at all — the
collector/processor/validator/analyzer stages are recorded as SKIPPED by
design, so the pipeline can be exercised end-to-end (contracts validated at
every boundary) with zero sector implementation and zero external calls.
Setting `dry_run=False` attempts to actually call into the routed sector's
adapter, which today always reports itself as template_only since no sector
is active yet.

`force_fail_stage` is a test hook: pass a stage id exactly as it appears in
the trace (e.g. "entity", "sector_router", "sector_adapter.collector") to
make that stage raise deliberately, to prove failure traceability.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from audience.adapter import adapt_for_audience
from common.contracts import (
    AttachmentExtraction,
    AudienceAdaptation,
    BlockDeliveryTrace,
    BlockPriorityPlan,
    DocumentAnalysis,
    DynamicLayout,
    EntityExtractionResult,
    GeneratedReport,
    ReportPlan,
    ReportPurposeClassification,
    QuestionCoverageRequirement,
    SectorRoute,
    SourceCollectionResult,
    SourceDocument,
    SourceCollectionEvent,
    SourcePlan,
    TrendSynthesis,
    UserRequest,
    WebSearchContext,
)
from common.content_quality_validator import needs_generic_topic_search
from common.errors import PipelineStageError, StageStatus, StageTrace
from core.attachments.extractor import build_question_context, extract_attachments
from core.block_priority_planner.planner import plan_block_priorities
from core.block_delivery_trace import build_block_delivery_trace
from core.collection_progress import bind_collection_events, reset_collection_events
from core.entity.ai_based import extract_entities_ai
from core.entity.search_terms import build_search_terms
from core.layout_generator.generator import generate_layout
from core.report_planner.planner import plan_report
from core.report_generator.generator import generate_report
from core.question_coverage import (
    assess_question_coverage,
    derive_answer_and_evidence_requirements,
    derive_question_coverage,
)
from core.report_purpose.classifier import classify_report_purpose
from core.run_archive import archive_run
from core.request_pipeline.direct_response import direct_response_for
from core.sector_router.router import route_request, scan_sectors
from core.source_planner.planner import plan_sources, select_top_sources
from core.synthesis.ai_based import refine_synthesis_ai
from core.synthesis.synthesizer import synthesize

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SECTORS_DIR = PROJECT_ROOT / "sectors"
SOURCE_REGISTRY_DIR = PROJECT_ROOT / "sources" / "registry"

_ADAPTER_ROLE_FUNCS = {
    "collector": "collect",
    "processor": "process",
    "validator": "validate",
    "analyzer": "analyze",
}
_ADAPTER_ROLE_ORDER = ("collector", "processor", "validator", "analyzer")
# The audience used when a request names none. Exported (no leading underscore
# alias below) because the fixture loader has to answer the same question and
# had drifted to "practitioner", so a fixture without an explicit audience got
# a different report shape than the identical live request would.
DEFAULT_AUDIENCE_ID = "_default"
_DEFAULT_AUDIENCE_ID = DEFAULT_AUDIENCE_ID


def _enrich_document_analyses(
    analyses: list[DocumentAnalysis],
    source_documents: list[SourceDocument],
) -> list[DocumentAnalysis]:
    document_by_id = {document.doc_id: document for document in source_documents}
    enriched: list[DocumentAnalysis] = []
    for analysis in analyses:
        document = document_by_id.get(analysis.doc_id)
        if document is not None:
            analysis = analysis.model_copy(
                update={
                    "source_id": document.source_id,
                    "source_title": document.title,
                    "source_url": document.url,
                    "reliability_tier": document.reliability_tier,
                }
            )
        enriched.append(analysis)
    return enriched


def _usable_analyses(analyses: list[DocumentAnalysis]) -> list[DocumentAnalysis]:
    return [
        analysis
        for analysis in analyses
        if analysis.relevant_to_question is not False
        and analysis.usable_for_synthesis is not False
    ]


def _missing_analysis_needs(
    analyses: list[DocumentAnalysis],
    information_needs: list[str],
) -> list[str]:
    covered = {
        need
        for analysis in analyses
        for need in analysis.covered_information_needs
    }
    return [need for need in information_needs if need not in covered]


class PipelineResult(BaseModel):
    request_id: str
    # Persist the user's actual question with the result.  The archive also
    # stores it, but uploaded/full result JSON must remain self-describing
    # even when its small archive record is not present on this machine.
    question: Optional[str] = None
    question_coverage: Optional[QuestionCoverageRequirement] = None
    question_coverage_gaps: list[str] = Field(default_factory=list)
    trace: list[StageTrace] = []
    attachment_extractions: list[AttachmentExtraction] = []
    entities: Optional[EntityExtractionResult] = None
    sector_route: Optional[SectorRoute] = None
    source_plan: Optional[SourcePlan] = None
    collection_events: list[SourceCollectionEvent] = Field(default_factory=list)
    source_collection: Optional[SourceCollectionResult] = None
    report_purpose: Optional[ReportPurposeClassification] = None
    block_priority_plan: Optional[BlockPriorityPlan] = None
    # Raw documents exactly as returned by the sector collector, before the
    # processor strips boilerplate or the validator drops documents. Kept so
    # operators can audit the actual Firecrawl markdown behind a report.
    collected_source_documents: list[SourceDocument] = Field(default_factory=list)
    document_analyses: list[DocumentAnalysis] = []
    synthesis: Optional[TrendSynthesis] = None
    report_plan: Optional[ReportPlan] = None
    generated_report: Optional[GeneratedReport] = None
    audience_adaptation: Optional[AudienceAdaptation] = None
    layout: Optional[DynamicLayout] = None
    block_delivery_trace: Optional[BlockDeliveryTrace] = None
    halted_at_stage: Optional[str] = None
    direct_answer: Optional[str] = None


def _normalize_collection_output(output) -> SourceCollectionResult:
    if isinstance(output, SourceCollectionResult):
        return output
    return SourceCollectionResult(documents=list(output))


def _call_sector_adapter_stage(sector_route: SectorRoute, role: str, *args):
    if role == "collector":
        # Search and original-source retrieval have one production engine.
        # Sector adapters continue to own processing, validation and analysis.
        from sources.collectors.source_router.integration import collect

        return collect(*args)
    profile = sector_route.matched_profile
    module = importlib.import_module(f"{profile.pipeline_entrypoint}.{role}")
    func = getattr(module, _ADAPTER_ROLE_FUNCS[role])
    return func(*args)


def run_pipeline(
    request: UserRequest,
    dry_run: bool = True,
    requested_sector_id: Optional[str] = None,
    force_fail_stage: Optional[str] = None,
    progress_sink: Optional[list[SourceCollectionEvent]] = None,
    archive: bool = True,
) -> PipelineResult:
    """Run the pipeline and, unless `archive=False`, record what happened.

    The archive is a small per-run JSON under storage/requests/ (see
    core/run_archive.py). It exists so questions about how the system behaves
    across many runs can be answered from real history rather than from
    whichever runs someone happened to keep. Tests pass `archive=False` to
    avoid writing thousands of files.
    """
    result = _run_pipeline_stages(
        request, dry_run, requested_sector_id, force_fail_stage, progress_sink
    )
    if archive:
        archive_run(result, request.question, request.target_audience)
    return result


def _run_pipeline_stages(
    request: UserRequest,
    dry_run: bool = True,
    requested_sector_id: Optional[str] = None,
    force_fail_stage: Optional[str] = None,
    progress_sink: Optional[list[SourceCollectionEvent]] = None,
) -> PipelineResult:
    result = PipelineResult(
        request_id=request.request_id,
        question=request.question,
        question_coverage=derive_question_coverage(request.question),
    )
    if progress_sink is not None:
        # Let a caller (e.g. the Streamlit UI, polling this list from another
        # thread while run_pipeline is still executing) observe collection
        # progress live instead of only after the whole call returns - same
        # list object throughout, no separate accumulate-then-copy step.
        result.collection_events = progress_sink
    requested_sector_id = requested_sector_id if requested_sector_id is not None else request.requested_sector_id
    profiles = scan_sectors(SECTORS_DIR)
    # Resolved once up front (not down at synthesis, where this used to be
    # computed) so the source_planner stage's WebSearchContext can carry it
    # into query generation - the report's audience shouldn't only matter
    # after evidence is already collected.
    audience_id = request.target_audience or _DEFAULT_AUDIENCE_ID

    direct_answer = direct_response_for(request.question)
    if direct_answer is not None:
        result.direct_answer = direct_answer
        result.trace.append(
            StageTrace(stage="direct_response", status=StageStatus.OK, reason="conversational input")
        )
        return result

    def _maybe_force_fail(stage: str) -> None:
        if force_fail_stage == stage:
            raise PipelineStageError(stage=stage, reason="forced failure for testing")

    def _halt(stage: str, reason: str, detail: Optional[str] = None) -> None:
        result.trace.append(StageTrace(stage=stage, status=StageStatus.FAILED, reason=reason, detail=detail))
        result.halted_at_stage = stage

    # Attachments are first-class evidence: extract them before entity and intent
    # classification, then analyze them beside collected web documents.
    try:
        _maybe_force_fail("attachment_extractor")
        attachment_documents, result.attachment_extractions = extract_attachments(request.attachments)
        question_with_context = build_question_context(request.question, attachment_documents)
        contextual_request = request.model_copy(update={"question": question_with_context})
        result.trace.append(StageTrace(stage="attachment_extractor", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("attachment_extractor", exc.reason, exc.detail)
        return result

    # 1. entity (also classifies primary_intent, see core/entity)
    try:
        _maybe_force_fail("entity")
        result.entities = extract_entities_ai(contextual_request, None, profiles, requested_sector_id)
        result.trace.append(StageTrace(stage="entity", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("entity", exc.reason, exc.detail)
        return result

    if result.entities.response_mode == "direct_answer":
        result.direct_answer = result.entities.direct_answer or "무엇을 도와드릴까요?"
        result.trace.append(
            StageTrace(stage="direct_response", status=StageStatus.OK, reason="AI classified conversational input")
        )
        for stage in (
            "sector_router", "report_purpose", "block_priority_planner", "source_planner",
            "sector_adapter", "synthesis", "report_planner", "report_generator",
            "audience_adapter", "layout_generator",
        ):
            result.trace.append(StageTrace(stage=stage, status=StageStatus.SKIPPED, reason="direct response"))
        return result

    # 2. sector_router
    try:
        _maybe_force_fail("sector_router")
        result.sector_route = route_request(
            request.request_id,
            result.entities,
            profiles,
            requested_sector_id,
            question=request.question,
        )
        result.trace.append(StageTrace(stage="sector_router", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("sector_router", exc.reason, exc.detail)
        return result

    if result.sector_route.status == "unsupported":
        for stage in ("report_purpose", "block_priority_planner", "source_planner", "sector_adapter", "synthesis", "report_planner", "report_generator", "audience_adapter", "layout_generator"):
            result.trace.append(
                StageTrace(stage=stage, status=StageStatus.SKIPPED, reason="sector route is unsupported")
            )
        result.halted_at_stage = "sector_router"
        return result

    sector_id = result.sector_route.sector_id

    # Profiles marked template_only are recognized routes, but must never enter
    # an adapter. This is currently how the explicit general fallback reports
    # that classification succeeded while report generation is not implemented.
    if result.sector_route.matched_profile.status == "template_only":
        reason = f"template_only: sector '{sector_id}' report pipeline is not implemented"
        result.trace.append(StageTrace(stage="sector_adapter", status=StageStatus.TEMPLATE_ONLY, reason=reason))
        for stage in (
            "report_purpose", "block_priority_planner", "source_planner", "synthesis",
            "report_planner", "report_generator", "audience_adapter", "layout_generator",
        ):
            result.trace.append(StageTrace(stage=stage, status=StageStatus.SKIPPED, reason=reason))
        result.halted_at_stage = "sector_adapter"
        return result

    # 3. report_purpose
    try:
        _maybe_force_fail("report_purpose")
        result.report_purpose = classify_report_purpose(
            request.request_id,
            result.entities,
            result.sector_route,
            request.question,
        )
        result.trace.append(StageTrace(stage="report_purpose", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("report_purpose", exc.reason, exc.detail)
        return result

    # 3.5 block_priority_planner - pure lookup against common.purpose_slots,
    # no API call, so failure here should never actually happen in practice.
    try:
        _maybe_force_fail("block_priority_planner")
        result.block_priority_plan = plan_block_priorities(
            request.request_id, result.report_purpose.purpose_id,
            result.report_purpose.question_answer_type,
        )
        answer_requirements, evidence_requirements = derive_answer_and_evidence_requirements(
            request.question,
            result.report_purpose.question_answer_type,
            result.entities.answer_requirements,
            result.entities.evidence_requirements,
        )
        result.entities = result.entities.model_copy(update={
            "answer_requirements": answer_requirements,
            "evidence_requirements": evidence_requirements,
        })
        result.trace.append(StageTrace(stage="block_priority_planner", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("block_priority_planner", exc.reason, exc.detail)
        return result

    # 4. source_planner
    try:
        _maybe_force_fail("source_planner")
        search_terms = build_search_terms(result.entities, result.sector_route.matched_profile)
        result.source_plan = plan_sources(
            request.request_id,
            sector_id,
            SOURCE_REGISTRY_DIR,
            search_terms,
            result.entities.perspective,
            result.entities.information_needs,
            WebSearchContext(
                question=request.question,
                company_name=(
                    result.sector_route.matched_profile.canonical_name
                    or result.sector_route.matched_profile.display_name
                ),
                perspective=result.entities.perspective,
                needs_generic_topic_round=needs_generic_topic_search(
                    request.question, result.entities.perspective
                ),
                report_purpose_id=result.report_purpose.purpose_id,
                purpose_confidence=result.report_purpose.confidence,
                audience=audience_id,
                information_needs=result.entities.information_needs,
                answer_requirements=result.entities.answer_requirements,
                evidence_requirements=result.entities.evidence_requirements,
                question_coverage=result.question_coverage,
                suggested_terms=search_terms,
                as_of_date=request.created_at.date().isoformat(),
                excluded_domains=list(result.sector_route.matched_profile.blocked_scrape_domains),
            ),
        )
        if not result.sector_route.matched_profile.skip_source_narrowing:
            result.source_plan = select_top_sources(
                result.source_plan,
                result.entities.perspective,
                result.report_purpose.purpose_id,
            )
        result.trace.append(StageTrace(stage="source_planner", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("source_planner", exc.reason, exc.detail)
        return result

    # 4. sector adapter: collector -> processor -> validator -> analyzer
    documents: list[SourceDocument] = []
    stopped_at_template_only = False
    for role in _ADAPTER_ROLE_ORDER:
        stage_name = f"sector_adapter.{role}"

        if dry_run:
            result.trace.append(
                StageTrace(stage=stage_name, status=StageStatus.SKIPPED, reason="dry_run: sector adapter stage not invoked")
            )
            continue
        if stopped_at_template_only:
            result.trace.append(
                StageTrace(stage=stage_name, status=StageStatus.SKIPPED, reason="upstream sector adapter stage is template_only")
            )
            continue

        try:
            _maybe_force_fail(stage_name)
            if role == "collector":
                args = (result.source_plan,)
            elif role == "analyzer":
                args = (
                    [*documents, *attachment_documents],
                    question_with_context,
                    result.source_plan.information_needs,
                    result.source_plan.evidence_requirements,
                )
            elif role == "validator":
                args = (documents, result.source_plan.search_context)
            else:
                args = (documents,)
            if role == "collector":
                progress_token = bind_collection_events(result.collection_events)
                try:
                    output = _call_sector_adapter_stage(result.sector_route, role, *args)
                finally:
                    reset_collection_events(progress_token)
            else:
                output = _call_sector_adapter_stage(result.sector_route, role, *args)
            if role == "collector":
                result.source_collection = _normalize_collection_output(output)
                output = list(result.source_collection.documents)
                result.collected_source_documents = list(output)
            if role == "validator":
                profile = result.sector_route.matched_profile
                minimum = (
                    result.source_collection.minimum_validated_documents
                    if result.source_collection
                    and result.source_collection.minimum_validated_documents is not None
                    else profile.min_validated_documents
                )
                max_recollections = profile.max_validation_recollection_attempts
                recollection_attempt = 0
                while minimum > 0 and len(output) < minimum and recollection_attempt < max_recollections:
                    recollection_attempt += 1
                    retained_documents = list(output)
                    excluded_urls = list(
                        dict.fromkeys(
                            document.url
                            for document in result.collected_source_documents
                            if document.url
                        )
                    )
                    previous_context = result.source_plan.search_context
                    if previous_context is None:
                        raise PipelineStageError(
                            stage=stage_name,
                            reason="validation recollection requires search context",
                        )
                    feedback = [
                        *previous_context.validation_feedback,
                        (
                            f"Validation retained {len(retained_documents)} of {len(documents)} documents; "
                            f"find replacement evidence so at least {minimum} valid documents remain."
                        ),
                    ]
                    retry_context = previous_context.model_copy(
                        update={
                            "excluded_urls": list(
                                dict.fromkeys([*previous_context.excluded_urls, *excluded_urls])
                            ),
                            "validation_feedback": feedback,
                        }
                    )
                    retry_plan = result.source_plan.model_copy(update={"search_context": retry_context})

                    progress_token = bind_collection_events(result.collection_events)
                    try:
                        retry_raw = _call_sector_adapter_stage(
                            result.sector_route, "collector", retry_plan
                        )
                    finally:
                        reset_collection_events(progress_token)
                    retry_collection = _normalize_collection_output(retry_raw)
                    retry_raw = list(retry_collection.documents)
                    result.collected_source_documents.extend(retry_raw)
                    if result.source_collection is not None:
                        result.source_collection = result.source_collection.model_copy(
                            update={"documents": list(result.collected_source_documents)}
                        )
                    result.trace.append(
                        StageTrace(stage="sector_adapter.collector.recollection", status=StageStatus.OK)
                    )

                    # Retained documents already passed processor + validator.
                    # Process only newly collected raw pages, then validate the
                    # combined evidence set.
                    retry_processed = _call_sector_adapter_stage(
                        result.sector_route,
                        "processor",
                        retry_raw,
                    )
                    result.trace.append(
                        StageTrace(stage="sector_adapter.processor.recollection", status=StageStatus.OK)
                    )
                    output = _call_sector_adapter_stage(
                        result.sector_route,
                        "validator",
                        [*retained_documents, *retry_processed],
                        retry_context,
                    )
                    result.trace.append(
                        StageTrace(stage="sector_adapter.validator.recollection", status=StageStatus.OK)
                    )
                    documents = [*retained_documents, *retry_processed]
                    result.source_plan = retry_plan

                if minimum > 0 and len(output) < minimum:
                    raise PipelineStageError(
                        stage=stage_name,
                        reason=(
                            "insufficient documents after validation and bounded recollection "
                            f"({len(output)} < {minimum})"
                        ),
                    )
            if role == "analyzer":
                analysis_documents = [*documents, *attachment_documents]
                output = _enrich_document_analyses(output, analysis_documents)
                usable = _usable_analyses(output)
                profile = result.sector_route.matched_profile
                minimum = profile.min_analyzed_documents
                target = max(minimum, profile.target_analyzed_documents)
                # The collection mode used to decide this: a `source_router`
                # run got 0 attempts, on the assumption that the router's own
                # gap loop had already collected everything it was going to.
                # That assumption fails exactly when the router stops for a
                # reason unrelated to coverage. Live-verified 2026-08-10
                # (storage/requests/req_cli_8452ace0): the router halted on
                # `search_call_budget_exhausted` with three of its nine
                # planned queries never run, delivered 2 documents, and the
                # analyzer then reported "insufficient usable analyses after
                # bounded recollection (2 < 3)" - where the bounded
                # recollection had run zero times and the profile's own
                # allowance of 1 was unreachable.
                #
                # The retry path is mode-agnostic: it re-invokes whichever
                # collector the sector registered, with the same
                # `search_context` widened by `excluded_urls` and the gaps
                # folded into `evidence_requirements`, and source_router
                # honours both (integration.py:34 -> router.py:414,422,504).
                max_recollections = profile.max_analysis_recollection_attempts
                recollection_attempt = 0
                structural_gaps = assess_question_coverage(
                    usable, result.question_coverage or QuestionCoverageRequirement()
                )

                while (
                    ((target > 0 and len(usable) < target) or structural_gaps)
                    and recollection_attempt < max_recollections
                ):
                    recollection_attempt += 1
                    previous_context = result.source_plan.search_context
                    if previous_context is None:
                        raise PipelineStageError(
                            stage=stage_name,
                            reason="analysis recollection requires search context",
                        )
                    excluded_urls = list(
                        dict.fromkeys(
                            document.url
                            for document in result.collected_source_documents
                            if document.url
                        )
                    )
                    missing_needs = _missing_analysis_needs(
                        usable,
                        result.source_plan.information_needs,
                    )
                    retry_context = previous_context.model_copy(
                        update={
                            "excluded_urls": list(
                                dict.fromkeys([*previous_context.excluded_urls, *excluded_urls])
                            ),
                            "validation_feedback": [
                                *previous_context.validation_feedback,
                                (
                                    f"Analyzer retained {len(usable)} usable documents; "
                                    f"collect toward the target of {target} usable documents "
                                    f"with replacement evidence for missing needs: {missing_needs}; "
                                    f"missing question axes: {structural_gaps}."
                                ),
                            ],
                        }
                    )
                    # validation_feedback above is human-readable audit trail only -
                    # nothing in source_router reads it (the old ai_search_harness.py
                    # prompt did; that path was dropped when Source Router replaced it
                    # as the collector, PR #23). missing_needs/structural_gaps are
                    # already short, concrete requirement phrases, so folding them
                    # into evidence_requirements is what actually makes the retry's
                    # search gap-specific instead of re-running the first round's
                    # query with only excluded_urls grown.
                    retry_plan = result.source_plan.model_copy(update={
                        "search_context": retry_context,
                        "evidence_requirements": list(dict.fromkeys([
                            *result.source_plan.evidence_requirements,
                            *missing_needs,
                            *structural_gaps,
                        ])),
                    })

                    progress_token = bind_collection_events(result.collection_events)
                    try:
                        retry_raw = _call_sector_adapter_stage(
                            result.sector_route,
                            "collector",
                            retry_plan,
                        )
                    finally:
                        reset_collection_events(progress_token)
                    retry_collection = _normalize_collection_output(retry_raw)
                    retry_raw = list(retry_collection.documents)
                    result.collected_source_documents.extend(retry_raw)
                    if result.source_collection is not None:
                        result.source_collection = result.source_collection.model_copy(
                            update={"documents": list(result.collected_source_documents)}
                        )
                    result.trace.append(
                        StageTrace(stage="sector_adapter.collector.analysis_recollection", status=StageStatus.OK)
                    )

                    retry_processed = _call_sector_adapter_stage(
                        result.sector_route,
                        "processor",
                        retry_raw,
                    )
                    result.trace.append(
                        StageTrace(stage="sector_adapter.processor.analysis_recollection", status=StageStatus.OK)
                    )
                    retry_validated = _call_sector_adapter_stage(
                        result.sector_route,
                        "validator",
                        retry_processed,
                        retry_context,
                    )
                    result.trace.append(
                        StageTrace(stage="sector_adapter.validator.analysis_recollection", status=StageStatus.OK)
                    )
                    try:
                        retry_output = _call_sector_adapter_stage(
                            result.sector_route,
                            "analyzer",
                            retry_validated,
                            question_with_context,
                            retry_plan.information_needs,
                            retry_plan.evidence_requirements,
                        )
                    except PipelineStageError as exc:
                        # Recollection is an optional depth pass.  It must not
                        # erase analyses that already cleared grounding and
                        # relevance gates in the initial pass.
                        result.trace.append(StageTrace(
                            stage="sector_adapter.analyzer.recollection",
                            status=StageStatus.FAILED,
                            reason=exc.reason,
                            detail=exc.detail,
                        ))
                        print(
                            "[analyzer] analysis recollection failed; preserving "
                            f"{len(usable)} previously usable analysis(es): {exc.reason}",
                            file=sys.stderr,
                        )
                        documents.extend(retry_validated)
                        result.source_plan = retry_plan
                        break
                    retry_output = _enrich_document_analyses(retry_output, retry_validated)
                    result.trace.append(
                        StageTrace(stage="sector_adapter.analyzer.recollection", status=StageStatus.OK)
                    )
                    output = [*output, *retry_output]
                    usable_by_doc_id = {
                        analysis.doc_id: analysis
                        for analysis in _usable_analyses(output)
                    }
                    usable = list(usable_by_doc_id.values())
                    structural_gaps = assess_question_coverage(
                        usable, result.question_coverage or QuestionCoverageRequirement()
                    )
                    documents.extend(retry_validated)
                    result.source_plan = retry_plan

                result.question_coverage_gaps = structural_gaps

                if minimum > 0 and len(usable) < minimum:
                    raise PipelineStageError(
                        stage=stage_name,
                        reason=(
                            "insufficient usable analyses after bounded recollection "
                            f"({len(usable)} < {minimum})"
                        ),
                    )
                if target > 0 and len(usable) < target:
                    print(
                        "[synthesis] proceeding below analyzer target after bounded "
                        f"recollection ({len(usable)} < {target}); minimum {minimum} satisfied",
                        file=sys.stderr,
                    )

                for analysis in output:
                    if analysis not in usable:
                        exclusion_reason = (
                            "not relevant to the question"
                            if analysis.relevant_to_question is False
                            else f"analysis grounding status={analysis.analysis_validation_status}"
                        )
                        print(
                            f"[synthesis] doc '{analysis.doc_id}' excluded: {exclusion_reason}",
                            file=sys.stderr,
                        )
                result.document_analyses = usable
            else:
                documents = output
            result.trace.append(StageTrace(stage=stage_name, status=StageStatus.OK))
        except PipelineStageError as exc:
            if exc.reason.startswith("template_only"):
                if role == "collector" and attachment_documents:
                    result.trace.append(
                        StageTrace(
                            stage=stage_name,
                            status=StageStatus.SKIPPED,
                            reason="collector unavailable; continuing with extracted attachment evidence",
                        )
                    )
                else:
                    result.trace.append(StageTrace(stage=stage_name, status=StageStatus.TEMPLATE_ONLY, reason=exc.reason))
                    stopped_at_template_only = True
            else:
                _halt(stage_name, exc.reason, exc.detail)
                return result

    # 5. synthesis (also de-dupes/ranks/summarizes via AI, see core/synthesis/ai_based.py)
    try:
        _maybe_force_fail("synthesis")
        rule_based_synthesis = synthesize(request.request_id, sector_id, result.document_analyses)
        rule_based_synthesis.as_of_date = request.created_at.date().isoformat()
        result.synthesis = refine_synthesis_ai(rule_based_synthesis, question_with_context)
        result.trace.append(StageTrace(stage="synthesis", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("synthesis", exc.reason, exc.detail)
        return result

    _run_report_stages(result, request, audience_id, _maybe_force_fail, _halt)
    return result


def _merge_extracted_metrics(result: PipelineResult) -> None:
    """Fold the report writer's evidence-verified figures into the synthesis.

    Also re-runs the planner afterwards when the merge added something: a
    section like key_metrics may have been omitted for "검증된 수치 자료가
    없음" on the strength of the regex extractor alone, and that reason no
    longer holds. Re-planning is a pure function over the synthesis - free,
    no API call - and the generated sections are left untouched.
    """
    report, synthesis = result.generated_report, result.synthesis
    if not report or not synthesis:
        return
    seen_metrics = {
        (point.label, point.period, point.value, point.unit) for point in synthesis.metric_series
    }
    added_metrics = [
        point for point in report.extracted_metric_series
        if (point.label, point.period, point.value, point.unit) not in seen_metrics
    ]
    seen_comparisons = {
        (point.entity, point.criterion, point.value) for point in synthesis.comparison_points
    }
    added_comparisons = [
        point for point in report.extracted_comparison_points
        if (point.entity, point.criterion, point.value) not in seen_comparisons
    ]
    if not added_metrics and not added_comparisons:
        return
    print(
        f"[report_generator] recovered {len(added_metrics)} metric(s) and "
        f"{len(added_comparisons)} comparison(s) from evidence prose that the "
        f"rule-based extractors missed",
        file=sys.stderr,
    )
    synthesis.metric_series = [*synthesis.metric_series, *added_metrics]
    synthesis.comparison_points = [*synthesis.comparison_points, *added_comparisons]
    if result.report_plan is not None:
        result.report_plan = plan_report(
            synthesis, result.report_plan.audience_id, result.report_purpose
        )
    # The sections were assembled before this extraction existed, so without
    # this they stay empty while the synthesis holds the data - which is
    # exactly what "전 섹션의 metric_points가 빈 배열" was. Fill the sections
    # that own each kind, keeping the single-ownership rule.
    result.generated_report = _apply_structured_to_sections(report, synthesis)


_METRIC_OWNER_SECTIONS = ("key_metrics", "investment_signal", "impact", "current_situation",
                          "market_status")
_COMPARISON_OWNER_SECTIONS = ("root_cause", "market_status", "issue", "problem", "impact",
                              "current_situation")


def _apply_structured_to_sections(report: GeneratedReport, synthesis: TrendSynthesis) -> GeneratedReport:
    """Give the newly extracted points to the first section that should own them.

    Ownership order mirrors report_generator's: the section whose subject the
    data is, not whichever comes first in the plan.
    """
    present = {section.section_id for section in report.sections}
    metric_owner = next((s for s in _METRIC_OWNER_SECTIONS if s in present), None)
    comparison_owner = next((s for s in _COMPARISON_OWNER_SECTIONS if s in present), None)
    sections = []
    for section in report.sections:
        updates = {}
        if section.section_id == metric_owner and not section.metric_points:
            updates["metric_points"] = list(synthesis.metric_series)
        if section.section_id == comparison_owner and not section.comparison_points:
            updates["comparison_points"] = list(synthesis.comparison_points)
        sections.append(section.model_copy(update=updates) if updates else section)
    return report.model_copy(update={"sections": sections})


def _run_report_stages(
    result: PipelineResult,
    request: UserRequest,
    audience_id: str,
    maybe_force_fail,
    halt,
) -> None:
    """Stages 6-9: everything downstream of a finished synthesis.

    Split out from the collection half so it can be driven from a saved
    synthesis as well as a live one (see `run_pipeline_from_synthesis`) -
    these four stages are pure transforms over `result.synthesis`, and
    re-running them shouldn't require paying for collection again.
    """
    # Recommendations are owned by the company selected by sector routing.
    # A source organisation's announced plan remains in claims/evidence, but
    # must not become that company's action merely because an analyzer put it
    # in recommended_actions.
    from common.action_quality import actions_for_owner, routed_action_owner

    action_owner = routed_action_owner(result.sector_route)
    result.synthesis = result.synthesis.model_copy(update={
        "recommended_actions": actions_for_owner(
            result.synthesis.recommended_actions, action_owner
        )
    })
    # 6. report_planner
    try:
        maybe_force_fail("report_planner")
        result.report_plan = plan_report(result.synthesis, audience_id, result.report_purpose)
        result.trace.append(StageTrace(stage="report_planner", status=StageStatus.OK))
    except PipelineStageError as exc:
        halt("report_planner", exc.reason, exc.detail)
        result.block_delivery_trace = build_block_delivery_trace(result, audience_id)
        return

    # 7. report_generator
    try:
        maybe_force_fail("report_generator")
        # What's left after best-effort collection/analysis (including the
        # recollection loops above) - never fabricated to fill these, just
        # disclosed honestly in the report's limitations (see
        # report_generator._missing_needs_limitation).
        still_missing = _missing_analysis_needs(
            result.document_analyses,
            result.source_plan.information_needs if result.source_plan else [],
        )
        still_missing = list(dict.fromkeys([*still_missing, *result.question_coverage_gaps]))
        # A fixture run starts at report_planner, so the entity stage never
        # ran and there are no canonical entities to normalize names against.
        entities = result.entities
        canonical_entities = (
            [*entities.organizations, *entities.technologies] if entities else []
        )
        result.generated_report = generate_report(
            request.question,
            result.synthesis,
            result.report_plan,
            audience_id,
            canonical_entities=canonical_entities,
            missing_information_needs=still_missing,
            target_company=action_owner,
        )
        # The dashboard's chart/KPI/timeline blocks read
        # TrendSynthesis.metric_series, not the report's sections, so figures
        # the report writer structured out of evidence prose have to be merged
        # back or they would be extracted and then never drawn.
        _merge_extracted_metrics(result)
        result.trace.append(StageTrace(stage="report_generator", status=StageStatus.OK))
    except PipelineStageError as exc:
        halt("report_generator", exc.reason, exc.detail)
        result.block_delivery_trace = build_block_delivery_trace(result, audience_id)
        return

    # 8. audience_adapter
    try:
        maybe_force_fail("audience_adapter")
        result.audience_adaptation = adapt_for_audience(
            result.synthesis,
            result.report_plan,
            audience_id,
            result.generated_report,
        )
        result.trace.append(StageTrace(stage="audience_adapter", status=StageStatus.OK))
    except PipelineStageError as exc:
        halt("audience_adapter", exc.reason, exc.detail)
        result.block_delivery_trace = build_block_delivery_trace(result, audience_id)
        return

    # 9. layout_generator
    try:
        maybe_force_fail("layout_generator")
        result.layout = generate_layout(
            result.report_plan,
            result.audience_adaptation,
            result.synthesis.doc_source_map,
            result.synthesis.doc_url_map,
        )
        result.trace.append(StageTrace(stage="layout_generator", status=StageStatus.OK))
    except PipelineStageError as exc:
        halt("layout_generator", exc.reason, exc.detail)
    result.block_delivery_trace = build_block_delivery_trace(result, audience_id)


# Stages a fixture run replaces rather than executes - recorded as SKIPPED so
# the trace still shows the full pipeline shape and nobody mistakes a fixture
# run's output for a report built from freshly collected evidence.
_FIXTURE_SKIPPED_STAGES = (
    "attachment_extractor", "entity", "sector_router", "source_planner",
    "sector_adapter", "synthesis",
)



def run_pipeline_from_documents(
    result: PipelineResult,
    question: str,
    audience_id: str,
    force_fail_stage: Optional[str] = None,
) -> PipelineResult:
    """Re-run analysis onward over documents a previous run already collected.

    Collection is the expensive half - search rounds and a scrape per page -
    and it is also the half that doesn't change when the bug was downstream of
    it. A run that halted in the analyzer therefore left five perfectly good
    documents on disk and no way to use them without paying to fetch them
    again. This takes that saved result and restarts at the analyzer.

    Not free: the analyzer is an AI stage, and so are synthesis's refinement
    pass and the report writer. But the searching and scraping are not
    repeated, which is where most of a run's cost and all of its rate-limit
    pressure sit.

    The stages before the analyzer keep the statuses they had in the saved
    run, so the trace still shows what actually happened rather than implying
    those stages ran again.
    """
    result.question = question
    result.question_coverage = derive_question_coverage(question)
    answer_requirements, evidence_requirements = derive_answer_and_evidence_requirements(
        question,
        result.report_purpose.question_answer_type if result.report_purpose else None,
        result.entities.answer_requirements if result.entities else (),
        result.entities.evidence_requirements if result.entities else (),
    )
    if result.entities is not None:
        result.entities = result.entities.model_copy(update={
            "answer_requirements": answer_requirements,
            "evidence_requirements": evidence_requirements,
        })
    if result.source_plan is not None:
        search_context = result.source_plan.search_context
        if search_context is not None:
            search_context = search_context.model_copy(update={
                "question": question,
                "answer_requirements": answer_requirements,
                "evidence_requirements": evidence_requirements,
                "target_block_shapes": [],
                "question_coverage": result.question_coverage,
            })
        result.source_plan = result.source_plan.model_copy(update={
            "answer_requirements": answer_requirements,
            "evidence_requirements": evidence_requirements,
            "search_context": search_context,
        })
    documents = list(result.collected_source_documents or [])
    if not documents:
        raise PipelineStageError(
            stage="sector_adapter.analyzer",
            reason="saved run has no collected documents to resume from",
        )
    if result.sector_route is None:
        raise PipelineStageError(
            stage="sector_adapter.analyzer", reason="saved run has no sector route"
        )

    request = UserRequest(
        request_id=result.request_id, question=question, target_audience=audience_id
    )
    # Drop the failed analyzer entry and everything the halt skipped: those
    # statuses describe the run being replaced, not this one.
    _RESUMED_FROM = {"sector_adapter.analyzer", "synthesis", "report_planner",
                     "report_generator", "audience_adapter", "layout_generator"}
    result.trace = [trace for trace in result.trace if trace.stage not in _RESUMED_FROM]
    result.halted_at_stage = None

    def _maybe_force_fail(stage: str) -> None:
        if force_fail_stage == stage:
            raise PipelineStageError(stage=stage, reason="forced failure for testing")

    def _halt(stage: str, reason: str, detail: Optional[str] = None) -> None:
        result.trace.append(StageTrace(stage=stage, status=StageStatus.FAILED, reason=reason, detail=detail))
        result.halted_at_stage = stage

    try:
        _maybe_force_fail("sector_adapter.analyzer")
        analyses = _call_sector_adapter_stage(
            result.sector_route, "analyzer", documents, question,
            result.source_plan.information_needs if result.source_plan else [],
            result.source_plan.evidence_requirements if result.source_plan else [],
        )
        # Same relevance gate the live path applies: a document search matched
        # is not a document that answers the question.
        usable = [
            analysis for analysis in analyses
            if analysis.relevant_to_question is not False
            and analysis.analysis_validation_status != "failed"
        ]
        for analysis in analyses:
            if analysis not in usable:
                print(f"[synthesis] doc '{analysis.doc_id}' excluded on resume", file=sys.stderr)
        result.document_analyses = usable
        result.question_coverage_gaps = assess_question_coverage(
            usable, result.question_coverage
        )
        result.trace.append(StageTrace(stage="sector_adapter.analyzer", status=StageStatus.OK,
                                       reason="resumed from saved documents"))
    except PipelineStageError as exc:
        _halt("sector_adapter.analyzer", exc.reason, exc.detail)
        return result

    try:
        _maybe_force_fail("synthesis")
        rule_based = synthesize(result.request_id, result.sector_route.sector_id, result.document_analyses)
        rule_based.as_of_date = request.created_at.date().isoformat()
        result.synthesis = refine_synthesis_ai(rule_based, question)
        result.trace.append(StageTrace(stage="synthesis", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("synthesis", exc.reason, exc.detail)
        return result

    _run_report_stages(result, request, audience_id, _maybe_force_fail, _halt)
    return result

def run_pipeline_from_synthesis(
    question: str,
    synthesis: TrendSynthesis,
    audience_id: str,
    report_purpose: ReportPurposeClassification,
    force_fail_stage: Optional[str] = None,
) -> PipelineResult:
    """Development entrypoint: run only the report half, from a saved synthesis.

    Everything up to and including synthesis costs Firecrawl and OpenAI calls,
    so iterating on planner/generator/adapter/layout behaviour used to mean
    paying to re-collect evidence that hadn't changed. This takes a
    TrendSynthesis straight off disk instead. No collector, analyzer, entity
    or synthesis AI pass runs on this path.
    """
    result = PipelineResult(
        request_id=synthesis.request_id,
        question=question,
        question_coverage=derive_question_coverage(question),
    )
    result.synthesis = synthesis
    result.report_purpose = report_purpose
    for stage in _FIXTURE_SKIPPED_STAGES:
        result.trace.append(
            StageTrace(stage=stage, status=StageStatus.SKIPPED, reason="synthesis loaded from fixture")
        )
    result.trace.append(
        StageTrace(stage="report_purpose", status=StageStatus.OK, reason="purpose taken from fixture")
    )

    def _maybe_force_fail(stage: str) -> None:
        if force_fail_stage == stage:
            raise PipelineStageError(stage=stage, reason="forced failure for testing")

    def _halt(stage: str, reason: str, detail: Optional[str] = None) -> None:
        result.trace.append(StageTrace(stage=stage, status=StageStatus.FAILED, reason=reason, detail=detail))
        result.halted_at_stage = stage

    request = UserRequest(
        request_id=synthesis.request_id, question=question, target_audience=audience_id
    )
    _run_report_stages(result, request, audience_id, _maybe_force_fail, _halt)
    return result
