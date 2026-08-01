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

from pydantic import BaseModel

from audience.adapter import adapt_for_audience
from common.contracts import (
    AttachmentExtraction,
    AudienceAdaptation,
    DocumentAnalysis,
    DynamicLayout,
    EntityExtractionResult,
    GeneratedReport,
    ReportPlan,
    ReportPurposeClassification,
    SectorRoute,
    SourceDocument,
    SourcePlan,
    TrendSynthesis,
    UserRequest,
)
from common.errors import PipelineStageError, StageStatus, StageTrace
from core.attachments.extractor import build_question_context, extract_attachments
from core.entity.ai_based import extract_entities_ai
from core.entity.extractor import extract_entities
from core.entity.search_terms import build_search_terms
from core.layout_generator.generator import generate_layout
from core.report_planner.planner import plan_report
from core.report_generator.generator import generate_report
from core.report_purpose.classifier import classify_report_purpose
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
_DEFAULT_AUDIENCE_ID = "practitioner"


class PipelineResult(BaseModel):
    request_id: str
    trace: list[StageTrace] = []
    attachment_extractions: list[AttachmentExtraction] = []
    entities: Optional[EntityExtractionResult] = None
    sector_route: Optional[SectorRoute] = None
    source_plan: Optional[SourcePlan] = None
    report_purpose: Optional[ReportPurposeClassification] = None
    document_analyses: list[DocumentAnalysis] = []
    synthesis: Optional[TrendSynthesis] = None
    report_plan: Optional[ReportPlan] = None
    generated_report: Optional[GeneratedReport] = None
    audience_adaptation: Optional[AudienceAdaptation] = None
    layout: Optional[DynamicLayout] = None
    halted_at_stage: Optional[str] = None


def _call_sector_adapter_stage(sector_route: SectorRoute, role: str, *args):
    profile = sector_route.matched_profile
    module = importlib.import_module(f"{profile.pipeline_entrypoint}.{role}")
    func = getattr(module, _ADAPTER_ROLE_FUNCS[role])
    return func(*args)


def run_pipeline(
    request: UserRequest,
    dry_run: bool = True,
    requested_sector_id: Optional[str] = None,
    force_fail_stage: Optional[str] = None,
) -> PipelineResult:
    result = PipelineResult(request_id=request.request_id)
    requested_sector_id = requested_sector_id if requested_sector_id is not None else request.requested_sector_id

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
        rule_based_entities = extract_entities(contextual_request)
        result.entities = extract_entities_ai(contextual_request, rule_based_entities)
        result.trace.append(StageTrace(stage="entity", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("entity", exc.reason, exc.detail)
        return result

    # 2. sector_router
    try:
        _maybe_force_fail("sector_router")
        profiles = scan_sectors(SECTORS_DIR)
        result.sector_route = route_request(request.request_id, result.entities, profiles, requested_sector_id)
        result.trace.append(StageTrace(stage="sector_router", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("sector_router", exc.reason, exc.detail)
        return result

    if result.sector_route.status == "unsupported":
        for stage in ("report_purpose", "source_planner", "sector_adapter", "synthesis", "report_planner", "report_generator", "audience_adapter", "layout_generator"):
            result.trace.append(
                StageTrace(stage=stage, status=StageStatus.SKIPPED, reason="sector route is unsupported")
            )
        result.halted_at_stage = "sector_router"
        return result

    sector_id = result.sector_route.sector_id

    # 3. report_purpose
    try:
        _maybe_force_fail("report_purpose")
        result.report_purpose = classify_report_purpose(
            request.request_id,
            result.entities,
            result.sector_route,
        )
        result.trace.append(StageTrace(stage="report_purpose", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("report_purpose", exc.reason, exc.detail)
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
        )
        result.source_plan = select_top_sources(result.source_plan, result.entities.perspective)
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
                args = ([*documents, *attachment_documents], question_with_context)
            else:
                args = (documents,)
            output = _call_sector_adapter_stage(result.sector_route, role, *args)
            if role == "analyzer":
                relevant = [analysis for analysis in output if analysis.relevant_to_question is not False]
                for analysis in output:
                    if analysis.relevant_to_question is False:
                        print(
                            f"[synthesis] doc '{analysis.doc_id}' excluded: not relevant to the question",
                            file=sys.stderr,
                        )
                result.document_analyses = relevant
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
        result.synthesis = refine_synthesis_ai(rule_based_synthesis, question_with_context)
        result.trace.append(StageTrace(stage="synthesis", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("synthesis", exc.reason, exc.detail)
        return result

    audience_id = request.target_audience or _DEFAULT_AUDIENCE_ID

    # 6. report_planner
    try:
        _maybe_force_fail("report_planner")
        result.report_plan = plan_report(result.synthesis, audience_id, result.report_purpose)
        result.trace.append(StageTrace(stage="report_planner", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("report_planner", exc.reason, exc.detail)
        return result

    # 7. report_generator
    try:
        _maybe_force_fail("report_generator")
        result.generated_report = generate_report(request.question, result.synthesis, result.report_plan, audience_id)
        result.trace.append(StageTrace(stage="report_generator", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("report_generator", exc.reason, exc.detail)
        return result

    # 8. audience_adapter
    try:
        _maybe_force_fail("audience_adapter")
        result.audience_adaptation = adapt_for_audience(
            result.synthesis,
            result.report_plan,
            audience_id,
            result.generated_report,
        )
        result.trace.append(StageTrace(stage="audience_adapter", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("audience_adapter", exc.reason, exc.detail)
        return result

    # 9. layout_generator
    try:
        _maybe_force_fail("layout_generator")
        result.layout = generate_layout(result.report_plan, result.audience_adaptation)
        result.trace.append(StageTrace(stage="layout_generator", status=StageStatus.OK))
    except PipelineStageError as exc:
        _halt("layout_generator", exc.reason, exc.detail)
        return result

    return result
