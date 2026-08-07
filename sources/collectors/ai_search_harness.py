"""AI-driven grounded search harness for a question or registered source.

Uses OpenAI's Responses API `web_search` tool to find candidate URLs — not
restricted to the triggering source's own domain, since a registered source's
domain can itself mix unrelated content (e.g. a shared corporate newsroom
tag page) that keyword/domain filtering alone can't separate. Only URLs
returned as `url_citation` annotations or grounded
`web_search_call.action.sources` are trusted (never text the model states
without tool backing — the hallucination guard). Each grounded URL is then
scraped via Firecrawl into markdown and attributed to whichever registered
source's domain it actually matches (or left unattributed, honestly, if it
matches none — never a fabricated reliability tier).

Runs a bounded number of rounds. The question-level mode evaluates the
successfully scraped Firecrawl text with Structured Outputs after each round,
then uses missing evidence categories to generate the next query. Search-result
snippets alone cannot end that mode. A deterministic fallback query exists
only when the assessment offers nothing usable, so the loop always terminates.

The detailed question-level result records sufficiency, covered/missing needs,
round count, and scrape calls. The sector collector still owns the final policy
for whether an insufficient result halts its pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from dataclasses import dataclass, replace as dataclass_replace
from queue import Queue
from urllib.parse import urlparse

from common.contracts import (
    EvidenceCoverageAssessment,
    PlannedSource,
    SourceDocument,
    WebSearchContext,
    WebSearchHarnessResult,
)
from common.content_quality_validator import strip_company_from_query
from core.source_planner.query_strategy import build_source_search_terms
from sources.collectors.document_media import detect_document_media_type
from sources.collectors.firecrawl_web import response_markdown

_SYSTEM_PROMPT = (
    "You are a grounded web-search assistant working in rounds. Use the "
    "web_search tool to find the strongest currently accessible evidence "
    "anywhere on the web for the user's original question. Evidence may "
    "include news articles, official announcements, regulatory documents, "
    "IR materials, statistical reports, technical documents, and industry "
    "analysis. Treat suggested terms as hints, not a query that must be "
    "copied verbatim. Only report URLs actually retrieved "
    "through the tool — never fabricate a URL, title, or date.\n"
    "When search_context.company_name is present, that is the specific "
    "company/organization this question is about — resolve any generic "
    "self-reference in the question (\"우리회사\", \"our company\", \"we\", "
    "\"the company\") to that name and include it (or an unambiguous synonym) "
    "in every search query for a round tagged company_specific_round.\n"
    "search_context.needs_generic_topic_round marks a question that cannot be "
    "answered from this company's own coverage alone - it needs general "
    "industry knowledge applied to the company (media-mix research by age "
    "bracket, component price trends, industry cost structures). For a round "
    "tagged generic_topic_round, search the SUBJECT ONLY and leave the company "
    "name out entirely, so broad research that never names this company can "
    "surface. Do not add the company name back into a generic_topic_round "
    "query; the company context is gathered by the company_specific_round.\n"
    "Use the supplied as_of_date and the question's requested time range. "
    "For current-status questions prefer the newest reliable evidence, while "
    "keeping older material only when it is necessary historical context.\n"
    "Never return a URL listed in search_context.excluded_urls, and never "
    "return a URL on any domain listed in search_context.excluded_domains "
    "(those sites cannot currently be retrieved, so citing them wastes the "
    "round) - find the same facts on another site instead. Use any "
    "validation_feedback to replace documents rejected by downstream checks.\n"
    "When registered_source_hints are supplied, prefer relevant documents from "
    "those registered domains. Do not force an inaccessible or off-topic registered "
    "source: use other grounded web sources as fallbacks, and keep the result set "
    "diverse across independent domains.\n"
    "STRICT RELEVANCE RULE: only cite an article if it is substantively "
    "ABOUT the query's core subject. Do not cite an article that merely "
    "mentions the subject in passing while primarily covering something "
    "else (e.g. do not cite a general SK텔레콤 corporate-news article just "
    "because it briefly references SK브로드밴드).\n"
    "After presenting your citations, end your reply with exactly one JSON "
    "object on its own line, judging THIS round only: "
    '{"sufficient": true/false, "next_queries": ["...", ...] or []}. '
    "sufficient=true if you found enough strictly on-topic articles "
    "(target: up to N, see below). If not sufficient, propose 2-3 DIFFERENT "
    "candidate follow-up queries covering different angles (broader, "
    "narrower, a different synonym/angle, a related sub-topic) — ordered by "
    "how promising you think each is. Empty list if you genuinely have no "
    "better query to try."
)


@dataclass(frozen=True)
class HarnessConfig:
    model: str = "gpt-4o"
    max_rounds: int = 3
    target_docs: int = 2  # mirrors _MAX_RESULTS_PER_SOURCE convention
    # Optional hard retention cap. When omitted, legacy behavior uses
    # target_docs as both the stopping target and final cap.
    max_collected_docs: int | None = None
    min_content_length: int = 250  # mirrors validator._MIN_CONTENT_LENGTH
    search_context_size: str = "medium"
    call_timeout_seconds: int = 30
    max_candidates_per_round: int = 2
    # 2 candidates/round * 3 rounds * (initial attempt + one error retry).
    max_total_scrape_calls: int = 12
    max_scrape_retries_per_url: int = 1
    min_scraped_docs_for_sufficient: int = 2
    min_independent_sources_for_sufficient: int = 2
    assess_scraped_evidence: bool = False
    max_evidence_chars_per_document: int = 8_000


@dataclass(frozen=True)
class _Citation:
    url: str
    title: str | None


def _doc_id(attributed_source_id: str, url: str) -> str:
    digest = hashlib.sha1(f"{attributed_source_id}:{url}".encode("utf-8")).hexdigest()[:16]
    return f"{attributed_source_id}:{digest}"


def _run_with_timeout(func, timeout_seconds: int):
    result: Queue = Queue(maxsize=1)

    def _run() -> None:
        try:
            result.put(("ok", func()))
        except Exception as exc:  # noqa: BLE001
            result.put(("error", exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        return "timeout", None
    return result.get()


def _initial_query(
    source: PlannedSource | None,
    question_keywords: list[str],
    search_context: WebSearchContext | None = None,
) -> str | None:
    if search_context and search_context.question.strip():
        question = search_context.question.strip()
        company_name = (search_context.company_name or "").strip()
        # Defense in depth alongside the system-prompt instruction: a vague
        # self-reference ("우리회사"/"our company") in the raw question text
        # shouldn't rely solely on the model reading company_name out of the
        # structured payload every round - anchor round 1's literal query
        # string to the company explicitly whenever it isn't already there.
        if company_name and company_name not in question:
            return f"{company_name} {question}"
        return question
    terms = (
        build_source_search_terms(source, question_keywords)
        if source is not None
        else question_keywords
    )
    query = " ".join(dict.fromkeys(term.strip() for term in terms if term and term.strip()))
    return query or None


GENERIC_TOPIC_ROUND = "generic_topic_round"
COMPANY_SPECIFIC_ROUND = "company_specific_round"


def plan_round_kinds(search_context: WebSearchContext | None, max_rounds: int) -> list[str]:
    """Which kind of query each round runs, decided up front.

    Live-observed: for "브랜드 이미지 개선에 맞는 연령층별 광고 매체 및 모델
    추천" every one of three rounds searched "SK브로드밴드 …", so the results
    were all SK브로드밴드's own coverage and none of the age-bracket media
    research a person would have found first. Leaving the mix to the model
    meant it happened to never drop the company name; planning the kinds here
    guarantees at least one of each whenever the question needs both.

    Company-specific goes first: it anchors what the question is actually
    about, and the generic round then widens rather than wanders.
    """
    if max_rounds <= 0:
        return []
    if search_context is None or not search_context.needs_generic_topic_round:
        return [COMPANY_SPECIFIC_ROUND] * max_rounds
    if not (search_context.company_name or "").strip():
        # No company to strip - every round is already a topic search.
        return [GENERIC_TOPIC_ROUND] * max_rounds
    if max_rounds == 1:
        return [COMPANY_SPECIFIC_ROUND]
    kinds = [COMPANY_SPECIFIC_ROUND, GENERIC_TOPIC_ROUND]
    # Remaining rounds alternate, so a third round widens the topic again
    # rather than re-asking the company the same way.
    while len(kinds) < max_rounds:
        kinds.append(kinds[len(kinds) % 2])
    return kinds[:max_rounds]


def query_for_round_kind(query: str, kind: str, search_context: WebSearchContext | None) -> str:
    """The query as-is, or with the company name removed for a generic round."""
    if kind != GENERIC_TOPIC_ROUND or search_context is None:
        return query
    stripped = strip_company_from_query(query, search_context.company_name)
    # Never return an empty query just because the company name was the whole
    # of it - fall back to the original rather than searching for nothing.
    return stripped or query


def _fallback_next_query(
    source: PlannedSource | None, question_keywords: list[str], tried_queries: list[str]
) -> str | None:
    topics = [topic.strip() for topic in source.topics if topic and topic.strip()] if source else []
    fallback_terms = topics if topics else [term for term in question_keywords[:2] if term]
    query = " ".join(dict.fromkeys(fallback_terms))
    if not query or query in tried_queries:
        return None
    return query


def _diversity_follow_up_query(
    search_context: WebSearchContext | None,
    tried_queries: list[str],
) -> str | None:
    """Build a bounded fallback when evidence is sound but still too sparse."""
    if search_context is None:
        return None
    anchor = (search_context.company_name or search_context.question).strip()
    if not anchor:
        return None
    for angle in (
        "공식 발표 통계",
        "산업 분석 경쟁사 비교",
        "시장 전망 대응 전략",
    ):
        query = f"{anchor} {angle}"
        if query not in tried_queries:
            return query
    return None


def _parse_round_judgment(response) -> tuple[bool, list[str]]:
    """Gracefully extract {"sufficient": ..., "next_queries": [...]} from the
    round's free-text reply. Tries the last non-empty line first (the model
    was asked to put the JSON there), then falls back to scanning the whole
    text for any flat {...} block. Returns (False, []) on any parse failure —
    the caller falls back to `_fallback_next_query`, never crashes."""
    text = getattr(response, "output_text", None) or ""
    candidates: list[str] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        candidates.append(lines[-1])
    candidates.extend(re.findall(r"\{[^{}]*\}", text, re.DOTALL))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "sufficient" in data:
            sufficient = bool(data.get("sufficient"))
            next_queries = [
                query.strip()
                for query in (data.get("next_queries") or [])
                if isinstance(query, str) and query.strip()
            ]
            return sufficient, next_queries
    return False, []


def _extract_url_citations(response) -> list[_Citation]:
    """Only `url_citation` annotations are trusted — `response.output_text`
    is never read for URLs, since prose can restate a URL the tool never
    actually returned."""
    citations: list[_Citation] = []
    seen: set[str] = set()
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", None) or []:
            for annotation in getattr(block, "annotations", None) or []:
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                url = getattr(annotation, "url", None)
                if not url or url in seen:
                    continue
                seen.add(url)
                citations.append(_Citation(url=url, title=getattr(annotation, "title", None)))
    return citations


def _field(value, name: str):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _extract_tool_sources(response) -> list[_Citation]:
    """Extract grounded candidates returned by the web-search tool itself.

    Responses API returns these only when the request includes
    ``web_search_call.action.sources``.  They are lower-priority candidates
    than explicit message citations, but unlike URLs in model prose they are
    still tool-grounded and safe to consider for scraping.
    """
    sources: list[_Citation] = []
    seen: set[str] = set()
    for item in getattr(response, "output", None) or []:
        if _field(item, "type") != "web_search_call":
            continue
        action = _field(item, "action")
        for source in _field(action, "sources") or []:
            url = _field(source, "url")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(_Citation(url=url, title=_field(source, "title")))
    return sources


def _grounded_candidates(response) -> list[_Citation]:
    """Return explicit citations first, then any additional tool sources."""
    candidates = [*_extract_url_citations(response), *_extract_tool_sources(response)]
    deduped: list[_Citation] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        deduped.append(candidate)
    return deduped


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_excluded_domain(url: str, excluded_domains: list[str]) -> bool:
    """True when the URL sits on (or under) a registry-blocked domain - see
    SectorProfile.blocked_scrape_domains. Subdomain-aware, so blocking
    "example.com" also blocks "www.example.com" and "corp.example.com"."""
    netloc = _domain(url)
    for excluded in excluded_domains:
        normalized = excluded.strip().lower()
        if not normalized:
            continue
        if netloc == normalized or netloc.endswith("." + normalized):
            return True
    return False


def _registered_source_index(url: str, all_sources: list[PlannedSource]) -> int | None:
    """Return registry order for a matching domain, or ``None`` when unregistered."""
    netloc = urlparse(url).netloc.lower()
    for index, source in enumerate(all_sources):
        candidate_domain = urlparse(source.url or "").netloc.lower()
        if candidate_domain and (
            netloc == candidate_domain or netloc.endswith("." + candidate_domain)
        ):
            return index
    return None


def _prioritize_candidates(
    candidates: list[_Citation],
    all_sources: list[PlannedSource],
    existing_documents: list[SourceDocument],
    limit: int,
    desired_total: int | None = None,
) -> list[_Citation]:
    """Prefer registered domains and diversity, with a bounded fallback.

    Two documents per domain is the normal ceiling. Only when that leaves the
    collection below ``desired_total`` do we admit a third document from a
    domain; the fallback never permits a fourth.
    """
    if limit <= 0:
        return []

    indexed = [
        (position, candidate, _registered_source_index(candidate.url, all_sources))
        for position, candidate in enumerate(candidates)
    ]
    ranked = sorted(
        indexed,
        key=lambda item: (
            item[2] is None,
            item[2] if item[2] is not None else len(all_sources),
            item[0],
        ),
    )
    existing_domain_counts: dict[str, int] = {}
    for document in existing_documents:
        domain = urlparse(document.url or "").netloc.lower()
        if domain:
            existing_domain_counts[domain] = existing_domain_counts.get(domain, 0) + 1

    selected: list[_Citation] = []
    selected_domains: set[str] = set()
    for _, candidate, _ in ranked:
        domain = urlparse(candidate.url).netloc.lower()
        if not domain or existing_domain_counts.get(domain, 0) >= 2 or domain in selected_domains:
            continue
        selected.append(candidate)
        selected_domains.add(domain)
        if len(selected) >= limit:
            return selected

    for _, candidate, _ in ranked:
        if candidate in selected:
            continue
        domain = urlparse(candidate.url).netloc.lower()
        selected_from_domain = sum(
            1
            for selected_candidate in selected
            if urlparse(selected_candidate.url).netloc.lower() == domain
        )
        if not domain or existing_domain_counts.get(domain, 0) + selected_from_domain >= 2:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break

    target = desired_total if desired_total is not None else len(existing_documents) + limit
    if len(existing_documents) + len(selected) >= target:
        return selected

    for _, candidate, _ in ranked:
        if candidate in selected:
            continue
        domain = urlparse(candidate.url).netloc.lower()
        selected_from_domain = sum(
            1
            for selected_candidate in selected
            if urlparse(selected_candidate.url).netloc.lower() == domain
        )
        if not domain or existing_domain_counts.get(domain, 0) + selected_from_domain >= 3:
            continue
        selected.append(candidate)
        if len(selected) >= limit or len(existing_documents) + len(selected) >= target:
            break
    return selected


def _maximum_documents(config: HarnessConfig) -> int:
    return config.max_collected_docs or config.target_docs


def _attribute_source(url: str, all_sources: list[PlannedSource]) -> tuple[str, str | None]:
    """Match a grounded URL's domain against every registered source in this
    pipeline run (not just the one that triggered this search round) and
    return (source_id, reliability_tier). No domain match -> the URL's own
    netloc as source_id and reliability_tier=None — never an invented tier
    for an unregistered source."""
    netloc = urlparse(url).netloc.lower()
    for candidate in all_sources:
        if not candidate.url:
            continue
        candidate_domain = urlparse(candidate.url).netloc.lower()
        if not candidate_domain:
            continue
        if netloc == candidate_domain or netloc.endswith("." + candidate_domain):
            return candidate.name, candidate.reliability_tier
    return netloc, None


def _scrape_candidate(
    firecrawl_client,
    citation: _Citation,
    all_sources: list[PlannedSource],
    config: HarnessConfig,
) -> tuple[SourceDocument | None, int]:
    attempts = 0
    payload = None
    max_attempts = 1 + max(0, config.max_scrape_retries_per_url)
    while attempts < max_attempts:
        attempts += 1
        status, payload = _run_with_timeout(
            lambda: firecrawl_client.scrape(citation.url, formats=["markdown"]),
            config.call_timeout_seconds,
        )
        if status == "ok":
            break
    if payload is None or status != "ok":
        detail = payload if status == "error" else "timed out"
        print(
            f"[ai_search_harness] scrape failed for {citation.url} "
            f"after {attempts} attempt(s): {detail}",
            file=sys.stderr,
        )
        return None, attempts
    markdown = response_markdown(payload)
    if not markdown or len(markdown.strip()) < config.min_content_length:
        length = len(markdown.strip()) if markdown else 0
        print(
            f"[ai_search_harness] scraped content too short for {citation.url} "
            f"({length} < {config.min_content_length} chars)",
            file=sys.stderr,
        )
        return None, attempts
    source_id, reliability_tier = _attribute_source(citation.url, all_sources)
    return (
        SourceDocument(
            doc_id=_doc_id(source_id, citation.url),
            source_id=source_id,
            title=citation.title or "Untitled",
            url=citation.url,
            content=markdown,
            media_type=detect_document_media_type(
                citation.url, citation.title, payload
            ),
            reliability_tier=reliability_tier,
        ),
        attempts,
    )


def _call_round(
    openai_client,
    source: PlannedSource | None,
    all_sources: list[PlannedSource],
    query: str,
    config: HarnessConfig,
    search_context: WebSearchContext | None = None,
    round_kind: str = COMPANY_SPECIFIC_ROUND,
):
    tool = {
        "type": "web_search",
        "search_context_size": config.search_context_size,
        "external_web_access": True,
    }
    if search_context and search_context.country_code:
        tool["user_location"] = {
            "type": "approximate",
            "country": search_context.country_code,
        }
    context_payload = search_context.model_dump() if search_context else {
        "question": query,
        "suggested_terms": [query],
    }
    request_payload = {
        "search_context": context_payload,
        "current_round_query": query,
        # Tagged so the model knows whether to keep the company name in this
        # round's query or deliberately leave it out - see plan_round_kinds.
        "round_kind": round_kind,
        "target_relevant_documents": _maximum_documents(config),
        "minimum_relevant_documents_for_target": config.min_scraped_docs_for_sufficient,
        "instructions": (
            "Search anywhere on the live web. Return up to "
            f"{config.max_candidates_per_round} distinct, strictly on-topic evidence URLs "
            "for this round. Prefer relevant registered sources first, then use other "
            "grounded web sources to fill evidence gaps. Favor independent domains and "
            "different evidence types over near-duplicate coverage."
        ),
        "registered_source_hints": [
            {
                "name": registered_source.name,
                "url": registered_source.url,
                "role": registered_source.role or "unspecified",
                "reliability_tier": registered_source.reliability_tier,
                "topics": registered_source.topics,
            }
            for registered_source in all_sources
            if registered_source.url
        ],
    }
    if source is not None:
        request_payload["registered_source_hint"] = {
            "name": source.name,
            "role": source.role or "unspecified",
            "topics": source.topics,
        }
    return openai_client.responses.create(
        model=config.model,
        tools=[tool],
        tool_choice="required",
        include=["web_search_call.action.sources"],
        input=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(request_payload, ensure_ascii=False),
            },
        ],
    )


def _evidence_excerpt(document: SourceDocument, terms: list[str], max_chars: int) -> str:
    content = document.content or ""
    if len(content) <= max_chars:
        return content
    first_chunk = content[: min(2_000, max_chars)]
    chunks = [first_chunk]
    remaining = max_chars - len(first_chunk)
    lowered = content.lower()
    seen_positions: list[int] = []
    for term in terms:
        normalized = term.strip().lower()
        if len(normalized) < 2:
            continue
        position = lowered.find(normalized)
        if position < 0 or any(abs(position - seen) < 500 for seen in seen_positions):
            continue
        seen_positions.append(position)
        start = max(0, position - 500)
        chunk = content[start : start + min(1_500, remaining)]
        if chunk:
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n\n[...관련 구간...]\n\n".join(chunks)[:max_chars]


def _assess_scraped_evidence(
    openai_client,
    documents: list[SourceDocument],
    question_keywords: list[str],
    config: HarnessConfig,
    search_context: WebSearchContext | None,
) -> EvidenceCoverageAssessment | None:
    if not documents or search_context is None:
        return None
    terms = list(dict.fromkeys([*search_context.suggested_terms, *question_keywords]))
    payload = {
        "question": search_context.question,
        "perspective": search_context.perspective,
        "report_purpose_id": search_context.report_purpose_id,
        "required_information_needs": search_context.information_needs,
        "minimum_relevant_document_count": config.min_scraped_docs_for_sufficient,
        "documents": [
            {
                "doc_id": document.doc_id,
                "source_id": document.source_id,
                "title": document.title,
                "url": document.url,
                "content_excerpt": _evidence_excerpt(
                    document, terms, config.max_evidence_chars_per_document
                ),
            }
            for document in documents
        ],
    }
    status, response = _run_with_timeout(
        lambda: openai_client.responses.parse(
            model=config.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Evaluate only the supplied Firecrawl source text. Mark a document relevant "
                        "only when it contains substantive evidence for the original question, not a "
                        "passing mention. Identify which required information needs are actually covered. "
                        "Set sufficient=true only when the evidence can support a defensible answer and "
                        "the supplied minimum_relevant_document_count is met. "
                        "If evidence is missing, propose 1-3 focused web queries targeting only those gaps."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            text_format=EvidenceCoverageAssessment,
        ),
        config.call_timeout_seconds,
    )
    if status != "ok" or response is None:
        return None
    parsed = getattr(response, "output_parsed", None)
    return parsed if isinstance(parsed, EvidenceCoverageAssessment) else None


def _validate_assessment(
    assessment: EvidenceCoverageAssessment,
    documents: list[SourceDocument],
    config: HarnessConfig,
    information_needs: list[str],
) -> EvidenceCoverageAssessment:
    document_by_id = {document.doc_id: document for document in documents}
    relevant_doc_ids = [
        doc_id for doc_id in dict.fromkeys(assessment.relevant_doc_ids) if doc_id in document_by_id
    ]
    relevant_sources = {document_by_id[doc_id].source_id for doc_id in relevant_doc_ids}
    required_needs = list(dict.fromkeys(information_needs))
    covered = [need for need in required_needs if need in assessment.covered_information_needs]
    missing = [need for need in required_needs if need not in covered]
    sufficient = (
        assessment.sufficient
        and len(relevant_doc_ids) >= config.min_scraped_docs_for_sufficient
        and len(relevant_sources) >= config.min_independent_sources_for_sufficient
        and not missing
    )
    return assessment.model_copy(
        update={
            "sufficient": sufficient,
            "relevant_doc_ids": relevant_doc_ids,
            "covered_information_needs": covered,
            "missing_information_needs": missing,
        }
    )


def _run_search_harness_result(
    openai_client,
    firecrawl_client,
    source: PlannedSource | None,
    all_sources: list[PlannedSource],
    question_keywords: list[str],
    config: HarnessConfig = HarnessConfig(),
    search_context: WebSearchContext | None = None,
) -> WebSearchHarnessResult:
    query = _initial_query(source, question_keywords, search_context)
    if not query:
        return WebSearchHarnessResult()

    tried_queries: list[str] = []
    pending_queries: list[str] = []
    documents: list[SourceDocument] = []
    attempted_urls: set[str] = set(search_context.excluded_urls) if search_context else set()
    # Domains that already failed to scrape earlier in *this* run (timeout,
    # proxy/tunnel error, etc.) - live-observed against skbroadband.com's own
    # press pages repeatedly failing via Firecrawl across multiple rounds
    # while other candidates the model already found went untried. Only
    # deprioritizes (never excludes outright): a domain that failed once
    # this run is unlikely to succeed moments later, so other already-found
    # candidates are a better use of the remaining scrape budget, but if
    # nothing else is available the domain still gets a fair try.
    failed_domains: set[str] = set()
    excluded_domains = list(search_context.excluded_domains) if search_context else []
    scrape_call_count = 0
    rounds_completed = 0
    final_sufficient = False
    final_documents: list[SourceDocument] = []
    accepted_doc_ids: set[str] = set()
    covered_information_needs: list[str] = []
    missing_information_needs = list(search_context.information_needs) if search_context else []
    maximum_documents = _maximum_documents(config)
    round_kinds = plan_round_kinds(search_context, config.max_rounds)

    for round_index in range(config.max_rounds):
        round_kind = (
            round_kinds[round_index] if round_index < len(round_kinds) else COMPANY_SPECIFIC_ROUND
        )
        query = query_for_round_kind(query, round_kind, search_context)
        tried_queries.append(query)
        print(
            f"[ai_search] round {round_index + 1}/{config.max_rounds} "
            f"[{round_kind}] query={query!r}",
            file=sys.stderr,
        )
        try:
            response = _call_round(
                openai_client, source, all_sources, query, config, search_context, round_kind
            )
        except Exception as exc:  # noqa: BLE001
            label = source.name if source is not None else "question"
            print(f"[ai_search_harness] round call failed for '{label}': {exc}", file=sys.stderr)
            break
        rounds_completed += 1

        candidates = _grounded_candidates(response)
        new_candidates = [candidate for candidate in candidates if candidate.url not in attempted_urls]
        # Hard guard for registry-blocked domains: the system prompt already
        # asks the model to avoid them, but a model instruction is not an
        # enforcement mechanism, so drop them here regardless.
        blocked = [candidate for candidate in new_candidates if _is_excluded_domain(candidate.url, excluded_domains)]
        if blocked:
            print(
                f"[ai_search_harness] skipped {len(blocked)} candidate(s) on registry-blocked "
                f"domain(s): {sorted({_domain(candidate.url) for candidate in blocked})}",
                file=sys.stderr,
            )
        new_candidates = [candidate for candidate in new_candidates if candidate not in blocked]
        # Prefer domains that haven't already failed to scrape in this run,
        # but never drop them outright - a failed domain is only held back
        # behind fresher options, and still gets picked up below when there
        # isn't enough else to fill the round. Registered-source priority and
        # per-domain diversity are applied within each group.
        candidate_limit = max(0, config.max_candidates_per_round)
        fresh_candidates = [c for c in new_candidates if _domain(c.url) not in failed_domains]
        stale_candidates = [c for c in new_candidates if _domain(c.url) in failed_domains]
        round_candidates = _prioritize_candidates(
            fresh_candidates,
            all_sources,
            documents,
            candidate_limit,
            desired_total=config.min_scraped_docs_for_sufficient,
        )
        if len(round_candidates) < candidate_limit and stale_candidates:
            round_candidates = round_candidates + _prioritize_candidates(
                stale_candidates,
                all_sources,
                documents,
                candidate_limit - len(round_candidates),
                desired_total=config.min_scraped_docs_for_sufficient,
            )
        label = source.name if source is not None else "question"
        print(
            f"[ai_search_harness] round {round_index + 1} for '{label}' query='{query}': "
            f"{len(candidates)} grounded candidate(s), {len(round_candidates)} selected",
            file=sys.stderr,
        )
        for citation in round_candidates:
            remaining_calls = config.max_total_scrape_calls - scrape_call_count
            if remaining_calls <= 0:
                break
            attempted_urls.add(citation.url)
            per_url_config = dataclass_replace(
                config,
                max_scrape_retries_per_url=min(
                    config.max_scrape_retries_per_url,
                    max(0, remaining_calls - 1),
                ),
            )
            document, attempts = _scrape_candidate(
                firecrawl_client, citation, all_sources, per_url_config
            )
            scrape_call_count += attempts
            if document is not None:
                documents.append(document)
            else:
                failed_domains.add(_domain(citation.url))
            if len(documents) >= maximum_documents:
                break

        sufficient, next_queries = _parse_round_judgment(response)
        if config.assess_scraped_evidence:
            try:
                assessment = _assess_scraped_evidence(
                    openai_client, documents, question_keywords, config, search_context
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[ai_search_harness] evidence assessment failed: {exc}", file=sys.stderr)
                assessment = None
            if assessment is not None:
                assessment = _validate_assessment(
                    assessment,
                    documents,
                    config,
                    search_context.information_needs if search_context else [],
                )
                relevant_ids = set(assessment.relevant_doc_ids)
                accepted_doc_ids.update(relevant_ids)
                final_documents = [
                    document for document in documents
                    if document.doc_id in accepted_doc_ids
                ]
                # Retain good evidence across rounds while allowing weak pages
                # to be replaced instead of consuming the target-doc budget.
                documents = list(final_documents)
                covered_information_needs = assessment.covered_information_needs
                missing_information_needs = assessment.missing_information_needs
                sufficient = assessment.sufficient
                next_queries = assessment.next_queries
                if (
                    len(final_documents) < config.min_scraped_docs_for_sufficient
                    and not next_queries
                ):
                    diversity_query = _diversity_follow_up_query(
                        search_context, tried_queries
                    )
                    if diversity_query:
                        next_queries = [diversity_query]
            else:
                sufficient = False
                next_queries = []
            if sufficient:
                final_sufficient = True
                break
        else:
            final_documents = list(documents)
            if len(documents) >= config.target_docs:
                final_sufficient = True
                break
            if sufficient and len(documents) >= config.min_scraped_docs_for_sufficient:
                final_sufficient = True
                break
        if len(documents) >= maximum_documents:
            break
        if scrape_call_count >= config.max_total_scrape_calls:
            break
        if (
            not new_candidates
            and round_index > 0
            and (not config.assess_scraped_evidence or not next_queries)
        ):
            break

        pending_queries = [q for q in next_queries if q not in tried_queries] or pending_queries
        if pending_queries:
            query = pending_queries.pop(0)
        else:
            fallback_query = _fallback_next_query(source, question_keywords, tried_queries)
            if fallback_query is None:
                break
            query = fallback_query
        if query in tried_queries:
            break

    return WebSearchHarnessResult(
        documents=final_documents[:maximum_documents],
        sufficient=final_sufficient,
        covered_information_needs=covered_information_needs,
        missing_information_needs=missing_information_needs,
        rounds_completed=rounds_completed,
        scrape_call_count=scrape_call_count,
    )


def _run_search_harness(
    openai_client,
    firecrawl_client,
    source: PlannedSource | None,
    all_sources: list[PlannedSource],
    question_keywords: list[str],
    config: HarnessConfig = HarnessConfig(),
    search_context: WebSearchContext | None = None,
) -> list[SourceDocument]:
    return _run_search_harness_result(
        openai_client, firecrawl_client, source, all_sources, question_keywords, config, search_context
    ).documents


def run_question_search_harness_result(
    openai_client,
    firecrawl_client,
    registered_sources: list[PlannedSource],
    question_keywords: list[str],
    config: HarnessConfig = HarnessConfig(),
    search_context: WebSearchContext | None = None,
) -> WebSearchHarnessResult:
    return _run_search_harness_result(
        openai_client,
        firecrawl_client,
        None,
        registered_sources,
        question_keywords,
        config,
        search_context,
    )


def run_question_search_harness(
    openai_client,
    firecrawl_client,
    registered_sources: list[PlannedSource],
    question_keywords: list[str],
    config: HarnessConfig = HarnessConfig(),
    search_context: WebSearchContext | None = None,
) -> list[SourceDocument]:
    """Backward-compatible list-only wrapper around the detailed result."""
    return run_question_search_harness_result(
        openai_client,
        firecrawl_client,
        registered_sources,
        question_keywords,
        config,
        search_context,
    ).documents


def run_ai_search_harness(
    openai_client,
    firecrawl_client,
    source: PlannedSource,
    all_sources: list[PlannedSource],
    question_keywords: list[str],
    config: HarnessConfig = HarnessConfig(),
    search_context: WebSearchContext | None = None,
) -> list[SourceDocument]:
    """Backward-compatible source-hinted entrypoint for legacy callers."""
    return _run_search_harness(
        openai_client,
        firecrawl_client,
        source,
        all_sources,
        question_keywords,
        config,
        search_context,
    )
