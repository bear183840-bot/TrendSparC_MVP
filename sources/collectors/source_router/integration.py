"""Production collection boundary for the single Source Router engine."""

from __future__ import annotations

from common.contracts import SourceCollectionResult, SourcePlan
from common.errors import PipelineStageError
from core.collection_progress import emit_collection_event
from sources.collectors.source_router.adapter import source_router_result_to_collection
from sources.collectors.source_router.router import research
from sources.collectors.source_router.web_search import is_configured as search_is_configured


def collect(source_plan: SourcePlan) -> SourceCollectionResult:
    context = source_plan.search_context
    if context is None or not context.question.strip():
        raise PipelineStageError(
            stage="sector_adapter.collector",
            reason="Source Router requires question search context",
        )
    if not search_is_configured():
        raise PipelineStageError(
            stage="sector_adapter.collector",
            reason="template_only: Source Router web-search API key is not configured",
        )
    emit_collection_event("Source Router", 1, 1, "started")
    try:
        router_result = research(
            context.question,
            answer_requirements=list(source_plan.answer_requirements),
            evidence_requirements=list(source_plan.evidence_requirements),
            purpose_id=context.report_purpose_id,
            excluded_urls=list(context.excluded_urls),
            excluded_domains=list(context.excluded_domains),
        )
        collection = source_router_result_to_collection(router_result, source_plan)
    except PipelineStageError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize boundary failures
        emit_collection_event("Source Router", 1, 1, "failed", detail=f"{type(exc).__name__}: {exc}")
        raise PipelineStageError(
            stage="sector_adapter.collector",
            reason=f"Source Router failed: {type(exc).__name__}: {exc}",
        ) from exc
    detail = (
        f"search_calls={router_result.search_calls_used}, "
        f"stop_reason={router_result.stop_reason}"
    )
    if router_result.results and not collection.documents:
        # Search found pages but not one of them could be read as an original
        # source, so there is nothing verified to analyse. Failing here names
        # the retrieval layer; returning an empty collection instead would
        # surface three stages later as "no evidence" and point at the wrong
        # thing. The usual cause is the HTML/PDF fetch layer being down or out
        # of credit, which otherwise only shows up in stderr.
        attempted = len(router_result.results)
        emit_collection_event("Source Router", 1, 1, "failed", detail=detail)
        raise PipelineStageError(
            stage="sector_adapter.collector",
            reason=(
                f"Source Router found {attempted} search result(s) but retrieved 0 original "
                "sources — check the HTML (Firecrawl) / PDF (Upstage) retrieval credentials "
                "and remaining credit"
            ),
            detail=detail,
        )
    emit_collection_event(
        "Source Router",
        1,
        1,
        "completed",
        document_count=len(collection.documents),
        detail=detail,
    )
    return collection
