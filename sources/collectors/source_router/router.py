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
    StopReason,
    WebSearchResult,
)


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _cap_results(results: list[WebSearchResult], max_results: int) -> list[WebSearchResult]:
    """Bounds the pool resent in full on every check_coverage() call
    (coverage.py's payload has no truncation of its own — see
    SourceRouterConfig.max_results). original_source-depth entries are never
    dropped for budget: each one already cost an extra Firecrawl/Document
    Parse call plus a verify_evidence() call to obtain, so discarding one to
    make room for an untouched search-summary result would waste the
    already-spent cost for no benefit. Among search_summary entries, the
    most recently added are kept — later rounds are gap-targeted follow-ups
    (doc1 §19), strictly more likely to matter than an early broad sweep."""
    if len(results) <= max_results:
        return results
    original_source = [r for r in results if r.evidence_depth == "original_source"]
    search_summary = [r for r in results if r.evidence_depth != "original_source"]
    remaining = max(0, max_results - len(original_source))
    return original_source + search_summary[-remaining:] if remaining else original_source


def _merge_results(
    existing: list[WebSearchResult], new: list[WebSearchResult], max_results: int
) -> list[WebSearchResult]:
    """A re-inspected URL (original_source depth) overwrites its earlier
    search-summary-only version; everything else is additive, then capped."""
    by_url = {result.url: result for result in existing}
    for result in new:
        by_url[result.url] = result
    return _cap_results(list(by_url.values()), max_results)


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
                query,
                model_override=config.search_model,
                timeout_seconds=config.call_timeout_seconds,
                max_urls=config.max_urls_per_query,
            )
        )
    return results, used


def _summary_from_verification(verification, fallback_text: str) -> str:
    """Prefer the model's own confirmed facts (or, failing that, why the
    summary couldn't be verified) over a raw text excerpt — falls back to
    the excerpt only when verify_evidence produced nothing usable (no key,
    call failure, or a source with no relevant content)."""
    if verification.confirmed_facts:
        return " ".join(fact.fact for fact in verification.confirmed_facts[:3])
    if verification.summary_verification and verification.summary_verification.important_omissions:
        return "; ".join(verification.summary_verification.important_omissions[:3])
    return fallback_text[:500]


def _build_inspected_result(url: str, title: str, text: str, verification) -> WebSearchResult:
    return WebSearchResult(
        url=url,
        title=title,
        summary=_summary_from_verification(verification, text),
        key_facts=coverage_module.key_facts_from_verification(verification),
        relevance="original_source_inspection",
        evidence_depth="original_source",
        verification=verification,
    )


def _inspect_html(question: str, url: str, config: SourceRouterConfig) -> WebSearchResult | None:
    markdown = html_extractor.extract_html(url, timeout_seconds=config.call_timeout_seconds)
    if not markdown:
        return None
    verification = coverage_module.verify_evidence(
        question,
        markdown,
        url=url,
        max_chars=config.max_evidence_chars_for_coverage_check,
        model_override=config.planner_model,
        timeout_seconds=config.call_timeout_seconds,
    )
    return _build_inspected_result(url, "", markdown, verification)


def _load_pdf_text(question: str, parsed, config: SourceRouterConfig) -> str:
    """doc1 §12-§14 Small/Large/Huge progressive narrowing."""
    if not parsed.sections:
        return parsed.full_text or ""
    size = pdf_parser.classify_size(parsed.token_count, config.pdf_small_max_tokens, config.pdf_large_max_tokens)
    if size == "small":
        return parsed.full_text or ""
    selected_sections_info = pdf_parser.select_sections(
        question, parsed.sections, model_override=config.planner_model, timeout_seconds=config.call_timeout_seconds
    )
    selected_ids = {item.section_id for item in selected_sections_info}
    selected_sections = [section for section in parsed.sections if section.section_id in selected_ids]
    if size == "large":
        return "\n\n".join(section.full_text or "" for section in selected_sections)
    # huge — narrow further into chunks per section (doc1 §14/§16)
    text_parts: list[str] = []
    for section in selected_sections:
        chunks = pdf_parser.build_chunk_map(section, chars_per_token_estimate=config.pdf_chars_per_token_estimate)
        if len(chunks) <= 1:
            text_parts.append(section.full_text or "")
            continue
        selected_chunks_info = pdf_parser.select_chunks(
            question, chunks, model_override=config.planner_model, timeout_seconds=config.call_timeout_seconds
        )
        selected_chunk_ids = {item.chunk_id for item in selected_chunks_info}
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
    verification = coverage_module.verify_evidence(
        question,
        text,
        url=url,
        max_chars=config.max_evidence_chars_for_coverage_check,
        model_override=config.planner_model,
        timeout_seconds=config.call_timeout_seconds,
    )
    return _build_inspected_result(url, parsed.document_title, text, verification)


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
    SourceRouterConfig for every bound this loop respects.

    stop_reason is one of 5 distinct values (contracts.StopReason) - split
    2026-08-09 from an earlier single "budget_exhausted" catch-all after a
    live run showed it couldn't distinguish "the model had nothing left to
    propose" (no_further_queries) from "we hit the numeric search-call cap"
    (search_call_budget_exhausted) from "every gap-loop round ran without
    ever reaching sufficient" (gap_loop_iterations_exhausted) - three
    genuinely different situations for whoever reads the result to reason
    about, previously indistinguishable."""
    config = config or SourceRouterConfig()
    search_plan: SearchPlan = planner_module.plan_searches(
        question, model_override=config.planner_model, timeout_seconds=config.call_timeout_seconds
    )

    search_call_count = 0
    priority1_queries = [query.query for query in search_plan.by_priority(1)][: config.max_priority1_queries]
    results, used = _run_queries(priority1_queries, config, config.max_web_search_calls - search_call_count)
    results = _cap_results(results, config.max_results)
    search_call_count += used

    coverage_history: list[CoverageDecision] = []
    inspected_urls: set[str] = set()

    def _finish(
        stop_reason: StopReason, *, rounds_completed: int, final_coverage: CoverageDecision | None
    ) -> SourceRouterResult:
        return SourceRouterResult(
            question=question,
            search_plan=search_plan,
            results=results,
            rounds_completed=rounds_completed,
            coverage_history=coverage_history,
            final_coverage=final_coverage,
            stop_reason=stop_reason,
            search_calls_used=search_call_count,
        )

    # Tracks whether `results` changed since the most recent check_coverage()
    # call — used below to detect the one case that used to go stale (see the
    # comment after the loop).
    results_changed_since_last_check = False

    for iteration in range(max(1, config.max_gap_loop_iterations)):
        decision = coverage_module.check_coverage(
            question,
            search_plan,
            results,
            model_override=config.planner_model,
            timeout_seconds=config.call_timeout_seconds,
        )
        coverage_history.append(decision)
        results_changed_since_last_check = False

        if decision.sufficient:
            return _finish("sufficient", rounds_completed=iteration + 1, final_coverage=decision)

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
                results = _merge_results(results, new_evidence, config.max_results)
                results_changed_since_last_check = True
                continue  # re-check coverage with the deepened evidence before spending more searches

        if not decision.next_queries:
            return _finish("no_further_queries", rounds_completed=iteration + 1, final_coverage=decision)
        if search_call_count >= config.max_web_search_calls:
            return _finish("search_call_budget_exhausted", rounds_completed=iteration + 1, final_coverage=decision)

        next_query_strings = [nq.query for nq in decision.next_queries[: config.max_priority2_queries]]
        new_results, used = _run_queries(
            next_query_strings,
            config,
            config.max_web_search_calls - search_call_count,
        )
        search_call_count += used
        if not new_results:
            return _finish("no_new_information", rounds_completed=iteration + 1, final_coverage=decision)
        results = _merge_results(results, new_results, config.max_results)
        results_changed_since_last_check = True

    # config.max_gap_loop_iterations rounds are used up. If the very last
    # round merged fresh evidence into `results` (via source inspection or a
    # new query round) but the loop ended before that evidence could be
    # re-assessed, coverage_history[-1] is stale — it is the *previous*
    # decision, not a judgment of the evidence actually gathered. Live-
    # verified 2026-08-09: a real run's final_coverage still listed two URLs
    # under sources_to_inspect that `results` already showed as successfully
    # inspected (evidence_depth="original_source"), because the inspection
    # that satisfied that request happened on the loop's last iteration and
    # was never re-checked. Do one more check_coverage() call here so
    # final_coverage always reflects the final results pool — this does not
    # consume another gap-loop iteration (max_gap_loop_iterations bounds how
    # many search/inspection rounds run, the actual cost driver per
    # config.py; this is a free re-read of evidence already paid for, not a
    # new search).
    if results_changed_since_last_check:
        final_decision = coverage_module.check_coverage(
            question,
            search_plan,
            results,
            model_override=config.planner_model,
            timeout_seconds=config.call_timeout_seconds,
        )
        coverage_history.append(final_decision)

    return _finish(
        "gap_loop_iterations_exhausted",
        rounds_completed=len(coverage_history),
        final_coverage=coverage_history[-1] if coverage_history else None,
    )
