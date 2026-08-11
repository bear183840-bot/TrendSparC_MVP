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
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.document_media import detect_document_media_type
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    SearchPlan,
    SearchPlanQuery,
    SourceRouterResult,
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


def _simplify_query_for_retry(query: SearchPlanQuery) -> SearchPlanQuery | None:
    """Drop every key_term but the first, unquoting the rest in `query.query`.

    A direct query combining two quoted key_terms (e.g. `"롱폼" "숏폼" 미디어
    소비 현황`) asks web search to satisfy both exact phrases at once, which
    is exactly the shape live-verified to time out reliably (2026-08-11).
    Retrying the identical query would just time out again, so this keeps
    only the query's first key_term quoted and un-quotes the rest, leaving
    the rest of the query text intact - a strictly smaller ask, not a
    different one. Returns None when there is nothing to drop (0 or 1
    key_terms), so the caller knows a retry would be pointless."""
    if len(query.key_terms) < 2:
        return None
    kept, dropped = query.key_terms[0], query.key_terms[1:]
    simplified_text = query.query
    for term in dropped:
        simplified_text = simplified_text.replace(f'"{term}"', term)
    return query.model_copy(update={"query": simplified_text, "key_terms": [kept]})


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
        try:
            found = web_search_module.execute_web_search(
                query.query,
                model_override=config.search_model,
                timeout_seconds=config.call_timeout_seconds,
                max_urls=config.max_urls_per_query,
            )
        except web_search_module.WebSearchTimeoutError:
            found = []
            # Only direct queries get a retry: they're the planner's own
            # priority-1 angles (see planner.py's query_role assignment),
            # so losing one to a timeout is more costly than losing a
            # supporting query. One retry only - a second timeout is just
            # left as a miss, never a second retry.
            if query.query_role == "direct" and used < remaining_calls:
                simplified = _simplify_query_for_retry(query)
                if simplified is not None:
                    used += 1
                    try:
                        found = web_search_module.execute_web_search(
                            simplified.query,
                            model_override=config.search_model,
                            timeout_seconds=config.call_timeout_seconds,
                            max_urls=config.max_urls_per_query,
                        )
                        query = simplified
                    except web_search_module.WebSearchTimeoutError:
                        found = []
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


def _search_budget_terms(
    question: str, search_plan: SearchPlan, ceiling: int
) -> dict[str, int]:
    """Each term of the budget, so the trace can show the derivation.

    `ceiling` (config.max_web_search_calls) is only the cap; reading it as
    the budget is what made an exactly-met budget look like a premature
    stop.

    Every term below raised +10 (2026-08-11, temporary stopgap): a live run
    on "롱폼과 숏폼 미디어 소비 트랜드" scored only base+direct_query_bonus
    (6 total) because none of the comparison_temporal_bonus/strategy_bonus
    keyword lists recognize a question joining two parallel topics with "와/
    과" instead of "비교"/"vs"/"대비" - that budget was exhausted (2 of 6
    calls wasted on timed-out queries) before either topic got a verified
    source. This does not fix the keyword list's blind spot (see the plan's
    "다음 라운드 후보" note); it only buys more room while that's true.
    Every term then lowered -6 (2026-08-11, same day): the +10 stopgap
    over-corrected once eager direct-batch inspection (see
    SourceRouterConfig.max_auto_inspect_direct_results) started securing
    original-source evidence from the initial batch alone, so the gap loop
    needed less follow-up search budget than the stopgap assumed.

    `direct_query_bonus` reads `search_plan.queries` (the planner's own
    priority-1/`query_role="direct"` angles) rather than
    `search_plan.evidence_needs` - as of 2026-08-11 the router no longer
    depends on entity-derived answer_requirements/evidence_requirements at
    all (see planner.py/refiner-removal history), so `evidence_needs` is
    always empty now. Renamed from `evidence_needs_bonus` to match.
    """
    direct_query_count = len([
        query for query in search_plan.queries if query.query_role == "direct"
    ])
    return {
        "base": 8,
        "direct_query_bonus": 6 if direct_query_count >= 2 else 0,
        "comparison_temporal_bonus": 6 if any(
            token in question.casefold() for token in ("비교", "추이", "변화", "vs", "대비")
        ) else 0,
        "strategy_bonus": 6 if any(
            token in question for token in ("대응", "전략", "원인", "영향", "추천")
        ) else 0,
        "ceiling": ceiling,
    }


def _search_budget(question: str, search_plan: SearchPlan, ceiling: int) -> int:
    """Question/requirement-aware call budget; query count is not success."""
    terms = _search_budget_terms(question, search_plan, ceiling)
    budget = terms["base"] + sum(
        terms[key] for key in
        ("direct_query_bonus", "comparison_temporal_bonus", "strategy_bonus")
    )
    return min(ceiling, max(1, budget))


def research(
    question: str,
    config: SourceRouterConfig | None = None,
    *,
    purpose_id: str | None = None,
    purpose_confidence: str | None = None,
    audience: str | None = None,
    as_of_date: str | None = None,
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
    about, previously indistinguishable.

    No entity-derived input (answer_requirements/evidence_requirements)
    reaches this function as of 2026-08-11 — the router judges its own gap
    coverage entirely from `question` + the accumulated `results`, via
    coverage.py's check_coverage(), matching this package's original design
    (cc7d4da) before the entity-coupled refiner.py/
    _enforce_direct_original_sources hard gate (69704a6) was layered on top
    and then removed again. `as_of_date` is the one exception: it is not
    entity-derived (it is `request.created_at`, see common/contracts.py),
    and is still threaded through so freshness-sensitive queries anchor on
    the real current date."""
    config = config or SourceRouterConfig()
    search_plan: SearchPlan = planner_module.plan_searches(
        question,
        audience=audience,
        purpose_id=purpose_id,
        purpose_confidence=purpose_confidence,
        as_of_date=as_of_date,
        model_override=config.planner_model,
        timeout_seconds=config.call_timeout_seconds,
    )
    budget_basis = _search_budget_terms(question, search_plan, config.max_web_search_calls)
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

    inspected_urls: set[str] = set()
    # Eagerly inspect the direct-priority batch's own real text, rather than
    # waiting on coverage.py's needs_full_text request - see
    # SourceRouterConfig.max_auto_inspect_direct_results for why (bounded to
    # this one batch, not every round, to respect Firecrawl's rate limit).
    # A failed/None inspection just leaves that result at search_summary
    # depth, same as if this loop never ran - not a hard requirement.
    for candidate in [
        result for result in results
        if result.query_role == "direct" and result.evidence_depth != "original_source"
    ][:config.max_auto_inspect_direct_results]:
        inspected_urls.add(candidate.url)
        inspected = _inspect_source(question, candidate, config)
        if inspected is not None:
            results = _merge_results(results, [inspected], config.max_results)

    coverage_history: list[CoverageDecision] = []
    # Accumulates every round's CoverageDecision.rejected_claims so the next
    # check_coverage() call can remind the model what it already fabricated
    # once (2026-08-11) - the payload otherwise carries no memory between
    # calls, so an ungrounded claim could otherwise repeat every round.
    rejected_claims_so_far: list[str] = []

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
            search_budget=total_search_budget,
            search_budget_basis=budget_basis,
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
            previously_rejected_claims=rejected_claims_so_far,
            model_override=config.planner_model,
            timeout_seconds=config.call_timeout_seconds,
        )
        coverage_history.append(decision)
        rejected_claims_so_far.extend(decision.rejected_claims)
        results_changed_since_last_check = False

        if decision.sufficient:
            return _finish("sufficient", rounds_completed=iteration + 1, final_coverage=decision)

        if decision.needs_full_text and decision.sources_to_inspect:
            new_evidence: list[WebSearchResult] = []
            # Select first, THEN cap (2026-08-11) - the cap used to slice
            # decision.sources_to_inspect before the already-inspected/not-in-
            # pool entries were skipped, so those entries consumed budget
            # without ever producing a scrape. That was harmless while the cap
            # was 15 (== max_results, so it never bound), but the eager direct
            # batch now pre-fills inspected_urls with up to
            # max_auto_inspect_direct_results URLs, and coverage tends to list
            # the most relevant sources first - exactly the ones already
            # inspected. Filtering first makes the cap mean "this many NEW
            # sources", which is what it reads as.
            selected: list[WebSearchResult] = []
            for source in decision.sources_to_inspect:
                if len(selected) >= config.max_sources_to_inspect:
                    break
                if source.url in inspected_urls:
                    continue
                candidate = next((result for result in results if result.url == source.url), None)
                if candidate is None:
                    continue
                # Marked here, not after the attempt, so a failed inspection
                # isn't retried next round (unchanged behavior) and a URL
                # listed twice in one decision is only inspected once.
                inspected_urls.add(source.url)
                selected.append(candidate)
            for candidate in selected:
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
            previously_rejected_claims=rejected_claims_so_far,
            model_override=config.planner_model,
            timeout_seconds=config.call_timeout_seconds,
        )
        coverage_history.append(final_decision)

    return _finish(
        "gap_loop_iterations_exhausted",
        rounds_completed=len(coverage_history),
        final_coverage=coverage_history[-1] if coverage_history else None,
    )
