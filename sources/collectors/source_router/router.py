"""Source Router orchestrator — doc1 (final_research_router.md) §21 pseudocode,
implemented against this package's own planner/web_search/coverage/
html_extractor/pdf_parser modules.

This is the production collection engine. `integration.collect()` calls
`research()` from the pipeline's collector boundary, and `adapter.py` converts
the result into the SourceDocument list the existing processor/validator/
analyzer already consume — so the verified original text of every inspected
source travels downstream rather than stopping here.

Two deferrals from the standalone build are now closed: the registry is
consulted for attribution (`adapter.match_registry_source`) and the router's
output crosses into common/contracts.py at the adapter. The package keeps its
own Pydantic shapes internally on purpose; only the adapter translates.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

from sources.collectors.source_router import coverage as coverage_module
from sources.collectors.source_router import html_extractor
from sources.collectors.source_router import pdf_parser
from sources.collectors.source_router import planner as planner_module
from sources.collectors.source_router import refiner as refiner_module
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.document_media import detect_document_media_type
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    SearchPlan,
    SearchPlanQuery,
    SourceRouterResult,
    SourceToInspect,
    StopReason,
    WebSearchResult,
)


def _is_direct_verification(verification) -> bool:
    return any(fact.evidence_strength == "direct" for fact in verification.confirmed_facts)


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
        previous = by_url.get(result.url)
        if previous is None:
            by_url[result.url] = result
            continue
        preferred = result if result.evidence_depth == "original_source" else previous
        by_url[result.url] = preferred.model_copy(update={
            "query_role": (
                "direct" if "direct" in {previous.query_role, result.query_role}
                else "supporting"
            ),
            "evidence_need_ids": list(dict.fromkeys([
                *previous.evidence_need_ids,
                *result.evidence_need_ids,
            ])),
            "search_query": preferred.search_query or previous.search_query or result.search_query,
        })
    return _cap_results(list(by_url.values()), max_results)


def _run_queries(
    queries: list[SearchPlanQuery],
    config: SourceRouterConfig,
    remaining_calls: int,
    *,
    excluded_urls: set[str] | None = None,
    excluded_domains: set[str] | None = None,
) -> tuple[list[WebSearchResult], int]:
    """Runs at most `remaining_calls` queries (doc1 §27 cost-aware budget).
    Returns (results, calls_actually_used)."""
    results: list[WebSearchResult] = []
    used = 0
    for query in queries:
        if used >= remaining_calls:
            break
        used += 1
        found = web_search_module.execute_web_search(
            query.query,
            model_override=config.search_model,
            timeout_seconds=config.call_timeout_seconds,
            max_urls=config.max_urls_per_query,
        )
        for result in found:
            domain = (urlparse(result.url).hostname or "").casefold()
            if result.url in (excluded_urls or set()):
                continue
            if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in (excluded_domains or set())):
                continue
            results.append(result.model_copy(update={
                "search_query": query.query,
                "query_role": query.query_role,
                "evidence_need_ids": list(query.evidence_need_ids),
            }))
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


def _build_inspected_result(
    source: WebSearchResult,
    text: str,
    verification,
    *,
    title: str = "",
    media_type: str | None = None,
) -> WebSearchResult:
    return source.model_copy(update={
        "title": title or source.title,
        "summary": _summary_from_verification(verification, text),
        "key_facts": coverage_module.key_facts_from_verification(verification),
        "relevance": "original_source_inspection",
        "evidence_depth": "original_source",
        "verification": verification,
        "original_content": text,
        "media_type": media_type,
        "retrieval_metadata": {
            "original_character_count": len(text),
            "verification_status": "direct" if _is_direct_verification(verification) else "contextual",
        },
    })


def _inspect_html(
    question: str, source: WebSearchResult, config: SourceRouterConfig
) -> WebSearchResult | None:
    markdown = html_extractor.extract_html(source.url, timeout_seconds=config.call_timeout_seconds)
    if not markdown:
        return None
    verification = coverage_module.verify_evidence(
        question,
        markdown,
        url=source.url,
        max_chars=config.max_evidence_chars_for_coverage_check,
        model_override=config.planner_model,
        timeout_seconds=config.call_timeout_seconds,
    )
    if len(markdown.strip()) < config.min_content_length and not _is_direct_verification(verification):
        return None
    return _build_inspected_result(
        source,
        markdown,
        verification,
        media_type="text/markdown",
    )


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


def _inspect_pdf(
    question: str, source: WebSearchResult, config: SourceRouterConfig
) -> WebSearchResult | None:
    try:
        response = requests_get(source.url, timeout=config.call_timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.router] PDF download failed for {source.url}: {exc}", file=sys.stderr)
        return None
    if response is None:
        return None
    parsed = pdf_parser.parse_pdf(
        response, source_url=source.url, chars_per_token_estimate=config.pdf_chars_per_token_estimate
    )
    if parsed is None:
        return None
    text = _load_pdf_text(question, parsed, config)
    if not text.strip():
        return None
    verification = coverage_module.verify_evidence(
        question,
        text,
        url=source.url,
        max_chars=config.max_evidence_chars_for_coverage_check,
        model_override=config.planner_model,
        timeout_seconds=config.call_timeout_seconds,
    )
    if len(text.strip()) < config.min_content_length and not _is_direct_verification(verification):
        return None
    return _build_inspected_result(
        source,
        text,
        verification,
        title=parsed.document_title,
        media_type="application/pdf",
    )


def requests_get(url: str, *, timeout: int) -> bytes | None:
    """Thin wrapper kept as a free function so tests can monkeypatch it
    without pulling `requests` into every test module."""
    import requests

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _inspect_source(
    question: str, source: WebSearchResult, config: SourceRouterConfig
) -> WebSearchResult | None:
    """HTML → Firecrawl or PDF → Upstage Document Parse, doc1 §9-§17.
    Returns an original_source-depth WebSearchResult, or None on any
    failure — the caller just keeps the search-summary version in that case."""
    media_type = detect_document_media_type(source.url, source.title)
    if media_type == "application/pdf":
        return _inspect_pdf(question, source, config)
    return _inspect_html(question, source, config)


def _search_budget(question: str, search_plan: SearchPlan, ceiling: int) -> int:
    """Question/requirement-aware call budget; query count is not success."""
    budget = 4
    if len(search_plan.evidence_needs) >= 2:
        budget += 2
    if any(token in question.casefold() for token in ("비교", "추이", "변화", "vs", "대비")):
        budget += 2
    if any(token in question for token in ("대응", "전략", "원인", "영향", "추천")):
        budget += 2
    return min(ceiling, max(1, budget))


def _enforce_direct_original_sources(
    decision: CoverageDecision,
    search_plan: SearchPlan,
    results: list[WebSearchResult],
    inspected_urls: set[str],
) -> CoverageDecision:
    """A search summary can never satisfy an explicit direct requirement."""
    direct_ids = {
        need.evidence_need_id
        for need in search_plan.evidence_needs
        if need.requirement_type == "direct"
    }
    if not direct_ids:
        return decision
    verified_ids = {
        need_id
        for result in results
        if result.evidence_depth == "original_source"
        and result.original_content
        and result.verification is not None
        and _is_direct_verification(result.verification)
        for need_id in result.evidence_need_ids
    }
    missing = direct_ids - verified_ids
    if not missing:
        return decision
    candidates = [
        SourceToInspect(
            url=result.url,
            reason="DIRECT requirement needs verified original source",
            target_information=sorted(missing & set(result.evidence_need_ids)),
        )
        for result in results
        if result.evidence_depth != "original_source"
        and result.url not in inspected_urls
        and result.query_role == "direct"
        and (not result.evidence_need_ids or missing & set(result.evidence_need_ids))
    ]
    existing = {item.url for item in decision.sources_to_inspect}
    combined = [*decision.sources_to_inspect]
    combined.extend(item for item in candidates if item.url not in existing)
    return decision.model_copy(update={
        "sufficient": False,
        "structural_sufficient": False,
        "needs_full_text": bool(combined),
        "sources_to_inspect": combined,
        "missing": list(dict.fromkeys([
            *decision.missing,
            *(f"verified original source for {need_id}" for need_id in sorted(missing)),
        ])),
        "reason": "DIRECT requirements are not linked to verified original source text",
    })


def research(
    question: str,
    config: SourceRouterConfig | None = None,
    *,
    answer_requirements: list[str] | None = None,
    evidence_requirements: list[str] | None = None,
    purpose_id: str | None = None,
    excluded_urls: list[str] | None = None,
    excluded_domains: list[str] | None = None,
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
    search_plan = refiner_module.refine_search_plan(
        question,
        search_plan,
        answer_requirements or (),
        evidence_requirements or (),
        purpose_id=purpose_id,
        max_total_queries=config.max_planned_queries,
        model_override=config.planner_model,
        timeout_seconds=config.call_timeout_seconds,
    )
    total_search_budget = _search_budget(question, search_plan, config.max_web_search_calls)

    search_call_count = 0
    direct_queries = [
        query for query in search_plan.queries if query.query_role == "direct"
    ][: config.max_priority1_queries]
    pending_supporting = [
        query for query in search_plan.queries if query.query_role != "direct"
    ][: config.max_priority2_queries]
    excluded_url_set = set(excluded_urls or ())
    excluded_domain_set = {
        value.casefold().removeprefix("www.") for value in (excluded_domains or ()) if value
    }
    results, used = _run_queries(
        direct_queries,
        config,
        total_search_budget - search_call_count,
        excluded_urls=excluded_url_set,
        excluded_domains=excluded_domain_set,
    )
    results = _merge_results([], results, config.max_results)
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
        decision = _enforce_direct_original_sources(
            decision, search_plan, results, inspected_urls
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
                candidate = next((result for result in results if result.url == source.url), None)
                if candidate is None:
                    continue
                inspected = _inspect_source(question, candidate, config)
                if inspected is not None:
                    new_evidence.append(inspected)
            if new_evidence:
                results = _merge_results(results, new_evidence, config.max_results)
                results_changed_since_last_check = True
                continue  # re-check coverage with the deepened evidence before spending more searches

        if not decision.next_queries and not pending_supporting:
            return _finish("no_further_queries", rounds_completed=iteration + 1, final_coverage=decision)
        if search_call_count >= total_search_budget:
            return _finish("search_call_budget_exhausted", rounds_completed=iteration + 1, final_coverage=decision)

        next_queries = list(pending_supporting)
        pending_supporting = []
        next_queries.extend(SearchPlanQuery(
            query=nq.query,
            angle="coverage_gap",
            purpose=nq.purpose,
            priority=2,
            query_role="supporting",
        ) for nq in decision.next_queries[: config.max_priority2_queries])
        new_results, used = _run_queries(
            next_queries,
            config,
            total_search_budget - search_call_count,
            excluded_urls=excluded_url_set,
            excluded_domains=excluded_domain_set,
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
        final_decision = _enforce_direct_original_sources(
            final_decision, search_plan, results, inspected_urls
        )
        coverage_history.append(final_decision)

    return _finish(
        "gap_loop_iterations_exhausted",
        rounds_completed=len(coverage_history),
        final_coverage=coverage_history[-1] if coverage_history else None,
    )
