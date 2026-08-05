"""AI-driven grounded search harness for one registered source.

Uses OpenAI's Responses API `web_search` tool to find candidate URLs — not
restricted to the triggering source's own domain, since a registered source's
domain can itself mix unrelated content (e.g. a shared corporate newsroom
tag page) that keyword/domain filtering alone can't separate. Only URLs
actually returned as `url_citation` annotations are trusted (never text the
model states without one — the hallucination guard, and now the *only* one
since there's no domain filter to fall back on). Each grounded URL is then
scraped via Firecrawl into markdown and attributed to whichever registered
source's domain it actually matches (or left unattributed, honestly, if it
matches none — never a fabricated reliability tier).

Runs a bounded number of rounds: after each round the model judges whether
it found enough strictly on-topic results and, if not, proposes several
candidate follow-up queries — genuine gap-driven re-search, not a fixed
query ladder. A small deterministic fallback query exists only for when the
model's judgment can't be parsed or offers nothing new, so the loop always
terminates.

This module never decides whether its output is "enough" for a caller's
purposes and never falls back to anything itself — it returns whatever valid
documents it found (0 to `HarnessConfig.target_docs`) and lets the caller (a
sector collector) apply its own sufficiency threshold and fallback policy.
This keeps the module a pure, reusable building block, not a sk_broadband-
specific policy — see sectors/sk_broadband/adapter/collector/__init__.py for
that sector's policy on top of it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from dataclasses import dataclass
from queue import Queue
from urllib.parse import urlparse

from common.contracts import PlannedSource, SourceDocument
from core.source_planner.query_strategy import build_source_search_terms
from sources.collectors.firecrawl_web import response_markdown

_SYSTEM_PROMPT = (
    "You are a grounded web-search assistant working in rounds. Use the "
    "web_search tool to find real, currently-live news articles anywhere on "
    "the web matching the query. Only report URLs actually retrieved "
    "through the tool — never fabricate a URL, title, or date.\n"
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
    min_content_length: int = 250  # mirrors validator._MIN_CONTENT_LENGTH
    search_context_size: str = "medium"
    call_timeout_seconds: int = 30


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


def _initial_query(source: PlannedSource, question_keywords: list[str]) -> str | None:
    terms = build_source_search_terms(source, question_keywords)
    query = " ".join(dict.fromkeys(term.strip() for term in terms if term and term.strip()))
    return query or None


def _fallback_next_query(
    source: PlannedSource, question_keywords: list[str], tried_queries: list[str]
) -> str | None:
    topics = [topic.strip() for topic in source.topics if topic and topic.strip()]
    fallback_terms = topics if topics else [term for term in question_keywords[:2] if term]
    query = " ".join(dict.fromkeys(fallback_terms))
    if not query or query in tried_queries:
        return None
    return query


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
) -> SourceDocument | None:
    status, payload = _run_with_timeout(
        lambda: firecrawl_client.scrape(citation.url, formats=["markdown"]),
        config.call_timeout_seconds,
    )
    if status != "ok":
        return None
    markdown = response_markdown(payload)
    if not markdown or len(markdown.strip()) < config.min_content_length:
        return None
    source_id, reliability_tier = _attribute_source(citation.url, all_sources)
    return SourceDocument(
        doc_id=_doc_id(source_id, citation.url),
        source_id=source_id,
        title=citation.title or "Untitled",
        url=citation.url,
        content=markdown,
        reliability_tier=reliability_tier,
    )


def _call_round(openai_client, source: PlannedSource, query: str, config: HarnessConfig):
    return openai_client.responses.create(
        model=config.model,
        tools=[{"type": "web_search", "search_context_size": config.search_context_size}],
        tool_choice="auto",
        input=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Search query: {query}\n"
                    f"Context: this query is being run for the registered source "
                    f"\"{source.name}\" (role: {source.role or 'unspecified'}), but "
                    f"you are not restricted to that source's own site — search "
                    f"anywhere. Target: up to {config.target_docs} distinct, "
                    f"strictly on-topic article URLs."
                ),
            },
        ],
    )


def run_ai_search_harness(
    openai_client,
    firecrawl_client,
    source: PlannedSource,
    all_sources: list[PlannedSource],
    question_keywords: list[str],
    config: HarnessConfig = HarnessConfig(),
) -> list[SourceDocument]:
    query = _initial_query(source, question_keywords)
    if not query:
        return []

    tried_queries: list[str] = []
    pending_queries: list[str] = []
    documents: list[SourceDocument] = []
    seen_urls: set[str] = set()

    for round_index in range(config.max_rounds):
        tried_queries.append(query)
        try:
            response = _call_round(openai_client, source, query, config)
        except Exception as exc:  # noqa: BLE001
            print(f"[ai_search_harness] round call failed for '{source.name}': {exc}", file=sys.stderr)
            break

        citations = _extract_url_citations(response)
        new_citations = [citation for citation in citations if citation.url not in seen_urls]
        for citation in new_citations:
            seen_urls.add(citation.url)
            document = _scrape_candidate(firecrawl_client, citation, all_sources, config)
            if document is not None:
                documents.append(document)

        sufficient, next_queries = _parse_round_judgment(response)
        if sufficient or len(documents) >= config.target_docs:
            break
        if not new_citations and round_index > 0:
            break  # diminishing returns — round 1 finding nothing isn't compared yet

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

    return documents[: config.target_docs]
