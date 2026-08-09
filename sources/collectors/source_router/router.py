"""Source Router orchestrator — doc1 (final_research_router.md) §21 pseudocode,
implemented against this package's own planner/web_search/coverage/
html_extractor/pdf_parser modules.

Standalone by design: not wired into core/request_pipeline/pipeline.py or any
sector adapter, and does not import or modify
sources/collectors/ai_search_harness.py (the existing sk_broadband harness
stays untouched — this is a deliberate parallel build, not a replacement).
See C:\\Users\\noogs\\.claude\\plans\\query-gentle-sketch.md for the tracked,
non-blocking warnings this defers (no common/contracts.py reuse, no
sources/registry integration, no pipeline wiring, no AGENTS.md §8-5
enforcement) — none of that matters yet because nothing downstream consumes
this module's output.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

from sources.collectors.source_router import coverage as coverage_module
from sources.collectors.source_router import html_extractor
from sources.collectors.source_router import pdf_parser
from sources.collectors.source_router import planner as planner_module
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    SearchPlan,
    SourceRouterResult,
    WebSearchResult,
)


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _merge_results(
    existing: list[WebSearchResult], new: list[WebSearchResult]
) -> list[WebSearchResult]:
    """A re-inspected URL (original_source depth) overwrites its earlier
    search-summary-only version; everything else is additive."""
    by_url = {result.url: result for result in existing}
    for result in new:
        by_url[result.url] = result
    return list(by_url.values())


def _run_queries(
    queries: list[str], config: SourceRouterConfig, remaining_calls: int
) -> tuple[list[WebSearchResult], int]:
    """Runs at most `remaining_calls` queries (doc1 §27 cost-aware budget).
    Returns (results, calls_actually_used)."""
    results: list[WebSearchResult] = []
    used = 0
    for query in queries:
        if used >= remaining_calls:
            break
        used += 1
        results.extend(
            web_search_module.execute_web_search(
                query, model_override=config.search_model, timeout_seconds=config.call_timeout_seconds
            )
        )
    return results, used


def _inspect_html(question: str, url: str, config: SourceRouterConfig) -> WebSearchResult | None:
    markdown = html_extractor.extract_html(url, timeout_seconds=config.call_timeout_seconds)
    if not markdown:
        return None
    key_facts = coverage_module.extract_key_facts(
        question, markdown, max_chars=config.max_evidence_chars_for_coverage_check, model_override=config.planner_model
    )
    return WebSearchResult(
        url=url,
        summary=markdown[:500],
        key_facts=key_facts,
        relevance="original_source_inspection",
        evidence_depth="original_source",
    )


def _load_pdf_text(question: str, parsed, config: SourceRouterConfig) -> str:
    """doc1 §12-§14 Small/Large/Huge progressive narrowing."""
    if not parsed.sections:
        return parsed.full_text or ""
    size = pdf_parser.classify_size(parsed.token_count, config.pdf_small_max_tokens, config.pdf_large_max_tokens)
    if size == "small":
        return parsed.full_text or ""
    selected_section_ids = pdf_parser.select_sections(
        question, parsed.sections, model_override=config.planner_model
    )
    selected_sections = [section for section in parsed.sections if section.section_id in selected_section_ids]
    if size == "large":
        return "\n\n".join(section.full_text or "" for section in selected_sections)
    # huge — narrow further into chunks per section (doc1 §14/§16)
    text_parts: list[str] = []
    for section in selected_sections:
        chunks = pdf_parser.build_chunk_map(section, chars_per_token_estimate=config.pdf_chars_per_token_estimate)
        if len(chunks) <= 1:
            text_parts.append(section.full_text or "")
            continue
        selected_chunk_ids = pdf_parser.select_chunks(question, chunks, model_override=config.planner_model)
        text_parts.extend(chunk.text or "" for chunk in chunks if chunk.chunk_id in selected_chunk_ids)
    return "\n\n".join(text_parts)


def _inspect_pdf(question: str, url: str, config: SourceRouterConfig) -> WebSearchResult | None:
    try:
        response = requests_get(url, timeout=config.call_timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.router] PDF download failed for {url}: {exc}", file=sys.stderr)
        return None
    if response is None:
        return None
    parsed = pdf_parser.parse_pdf(
        response, source_url=url, chars_per_token_estimate=config.pdf_chars_per_token_estimate
    )
    if parsed is None:
        return None
    text = _load_pdf_text(question, parsed, config)
    if not text.strip():
        return None
    key_facts = coverage_module.extract_key_facts(
        question, text, max_chars=config.max_evidence_chars_for_coverage_check, model_override=config.planner_model
    )
    return WebSearchResult(
        url=url,
        title=parsed.document_title,
        summary=text[:500],
        key_facts=key_facts,
        relevance="original_source_inspection",
        evidence_depth="original_source",
    )


def requests_get(url: str, *, timeout: int) -> bytes | None:
    """Thin wrapper kept as a free function so tests can monkeypatch it
    without pulling `requests` into every test module."""
    import requests

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _inspect_source(question: str, url: str, config: SourceRouterConfig) -> WebSearchResult | None:
    """HTML → Firecrawl or PDF → Upstage Document Parse, doc1 §9-§17.
    Returns an original_source-depth WebSearchResult, or None on any
    failure — the caller just keeps the search-summary version in that case."""
    if _is_pdf_url(url):
        return _inspect_pdf(question, url, config)
    return _inspect_html(question, url, config)


def research(
    question: str, config: SourceRouterConfig | None = None
) -> SourceRouterResult:
    """doc1 §21 pseudocode, implemented. Always terminates within
    `config.max_gap_loop_iterations` / `config.max_web_search_calls` — see
    SourceRouterConfig for every bound this loop respects."""
    config = config or SourceRouterConfig()
    search_plan: SearchPlan = planner_module.plan_searches(question, model_override=config.planner_model)

    search_call_count = 0
    priority1_queries = [query.query for query in search_plan.by_priority(1)][: config.max_priority1_queries]
    results, used = _run_queries(priority1_queries, config, config.max_web_search_calls - search_call_count)
    search_call_count += used

    coverage_history: list[CoverageDecision] = []
    inspected_urls: set[str] = set()

    for iteration in range(max(1, config.max_gap_loop_iterations)):
        decision = coverage_module.check_coverage(
            question, search_plan, results, model_override=config.planner_model
        )
        coverage_history.append(decision)

        if decision.sufficient:
            return SourceRouterResult(
                question=question,
                search_plan=search_plan,
                results=results,
                rounds_completed=iteration + 1,
                coverage_history=coverage_history,
                final_coverage=decision,
                stop_reason="sufficient",
            )

        if decision.needs_full_text and decision.sources_to_inspect:
            new_evidence: list[WebSearchResult] = []
            for source in decision.sources_to_inspect[: config.max_sources_to_inspect]:
                if source.url in inspected_urls:
                    continue
                inspected_urls.add(source.url)
                inspected = _inspect_source(question, source.url, config)
                if inspected is not None:
                    new_evidence.append(inspected)
            if new_evidence:
                results = _merge_results(results, new_evidence)
                continue  # re-check coverage with the deepened evidence before spending more searches

        if not decision.next_queries or search_call_count >= config.max_web_search_calls:
            break

        new_results, used = _run_queries(
            decision.next_queries[: config.max_priority2_queries],
            config,
            config.max_web_search_calls - search_call_count,
        )
        search_call_count += used
        if not new_results:
            return SourceRouterResult(
                question=question,
                search_plan=search_plan,
                results=results,
                rounds_completed=iteration + 1,
                coverage_history=coverage_history,
                final_coverage=decision,
                stop_reason="no_new_information",
            )
        results = _merge_results(results, new_results)

    return SourceRouterResult(
        question=question,
        search_plan=search_plan,
        results=results,
        rounds_completed=len(coverage_history),
        coverage_history=coverage_history,
        final_coverage=coverage_history[-1] if coverage_history else None,
        stop_reason="budget_exhausted",
    )
