"""collector for the sk_hynix sector adapter.

For each registered source, searches that source's own domain for whatever
content best matches the question (Firecrawl's `search` with
`include_domains` scoped to the source, ranked by Firecrawl's own
relevance ranking — not just "whatever's on today's front page"), and
requests the matched page's content in the same call via `scrape_options`.
This replaced an earlier "scrape the listing page, extract links, keyword
-match" approach: that could only ever find something published recently
enough to still be linked from the front page, so a source with no recent
coverage of the question's topic silently contributed nothing even when
the site's archive actually had a good match. Search looks across each
source's whole indexed history instead. Up to 3 documents may come back per
source (Firecrawl's own relevance order), and if the full-length query finds
nothing, progressively shorter/looser queries are retried before giving up
on that source — see _MAX_RESULTS_PER_SOURCE / _query_term_counts. A
document is only ever produced from a real Firecrawl response — nothing
here fabricates content, and no reliability_tier is invented (the registry
only carries a free-text reliability_reason, not a tier taxonomy, so the
field is left unset until one is defined).
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from datetime import datetime
from queue import Queue
from urllib.parse import urlparse

from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions

from common.contracts import PlannedSource, SourceDocument, SourcePlan
from common.errors import PipelineStageError
from core.collection_progress import emit_collection_event
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms
from sources.collectors.firecrawl_web import response_markdown

_API_KEY_ENV_VAR = "FIRECRAWL_API_KEY"
_SEARCH_TIMEOUT_SECONDS = 30
_STAGE = "sectors.sk_hynix.adapter.collector"
# Firecrawl's search treats a multi-term query as roughly an AND of every
# term, so a long query (esp. one with redundant Korean+English pairs for
# the same concept, e.g. "반도체 Semiconductors", or one mixing specific
# brand/product terms with generic filler words) can match nothing at all
# even when a short version of the same query returns good hits — confirmed
# live. Fewer terms are strictly more likely to match *something*, so
# _query_term_counts() below tries the short, specific combination FIRST
# (cheap and usually succeeds) and only escalates to the full-length query
# as a last resort if even a single term finds nothing — trying the
# longest/most-restrictive combination first would waste a call on the
# attempt least likely to succeed, for every single source, every time.
_PRIMARY_TERM_COUNT = 2
_LAST_RESORT_TERM_COUNT = 1
_MAX_QUERY_TERMS = 5
# Firecrawl's search already ranks by relevance; taking up to 2 (rather than
# just the single best) means a source still contributes something even
# when the top hit isn't a great match, and other sources return nothing.
_MAX_RESULTS_PER_SOURCE = 2
# Defensive cap on top of source_planner.select_top_sources()'s 6-source
# selection (6 sources * _MAX_RESULTS_PER_SOURCE = 12) — stops collection
# once reached even if a future config change lets more sources or results
# through, so the collector never hands the validator/analyzer an unbounded
# document set.
_MAX_COLLECTED_DOCUMENTS = 12


def _doc_id(source: PlannedSource, url: str) -> str:
    digest = hashlib.sha1(f"{source.name}:{url}".encode("utf-8")).hexdigest()[:16]
    return f"{source.name}:{digest}"


def _parse_published_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_with_timeout(func, timeout_seconds: int):
    """Run func() in a daemon thread and give up after timeout_seconds.

    Returns ("ok", result), ("error", exception), or ("timeout", None). A
    daemon thread (rather than concurrent.futures.ThreadPoolExecutor, whose
    context manager blocks on shutdown) lets us stop waiting without
    blocking process exit — the abandoned thread just gets dropped when the
    interpreter exits.
    """
    result: Queue = Queue(maxsize=1)

    def _run() -> None:
        try:
            result.put(("ok", func()))
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller via the queue
            result.put(("error", exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        return "timeout", None

    return result.get()


def _query_term_counts(available: int) -> list[int]:
    """Term counts to try, short/likely-to-match first, deduped and bounded
    by what's actually available. Escalating to more terms only happens
    when the previous (shorter, looser) attempt found zero results, so a
    query that already succeeds on the short form never pays for the
    longer, more-likely-to-fail attempt."""
    candidates = [_PRIMARY_TERM_COUNT, _LAST_RESORT_TERM_COUNT, min(available, _MAX_QUERY_TERMS)]
    counts: list[int] = []
    for count in candidates:
        if 1 <= count <= available and count not in counts:
            counts.append(count)
    return counts


def _search_source(client: Firecrawl, domain: str, deduped_keywords: list[str]):
    """Try progressively shorter queries until one returns results, a real
    error, or a timeout occurs. Returns ("ok", results-list), ("error", exc),
    or ("timeout", None) — mirrors _run_with_timeout's status values."""
    queries = build_search_queries(deduped_keywords)
    for query in queries:
        status, payload = _run_with_timeout(
            lambda: client.search(
                query,
                include_domains=[domain],
                limit=_MAX_RESULTS_PER_SOURCE,
                scrape_options=ScrapeOptions(formats=["markdown"]),
            ),
            _SEARCH_TIMEOUT_SECONDS,
        )
        if status != "ok":
            return status, payload
        results = payload.web or []
        if results:
            return "ok", results
    if queries:
        status, payload = _run_with_timeout(
            lambda: client.search(
                f"site:{domain} {queries[0]}", include_domains=[], limit=_MAX_RESULTS_PER_SOURCE,
                scrape_options=ScrapeOptions(formats=["markdown"]),
            ),
            _SEARCH_TIMEOUT_SECONDS,
        )
        if status != "ok":
            return status, payload
        results = [
            item for item in (payload.web or [])
            if (((item.metadata.url if item.metadata else None) or item.url)
                and urlparse((item.metadata.url if item.metadata else None) or item.url).netloc.endswith(domain))
        ]
        if results:
            return "ok", results
    return "ok", []


def _crawl_source(client: Firecrawl, source: PlannedSource, keywords: list[str]) -> list[SourceDocument]:
    if not keywords:
        return []

    domain = urlparse(source.url).netloc
    deduped_keywords = list(dict.fromkeys(keywords))  # de-dupe, keep first-seen order

    status, payload = _search_source(client, domain, deduped_keywords)

    if status == "timeout":
        return []
    if status == "error":
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"failed to search source '{source.name}'",
            detail=str(payload),
        ) from payload

    documents: list[SourceDocument] = []
    for item in payload[:_MAX_RESULTS_PER_SOURCE]:
        metadata = getattr(item, "metadata", None)
        article_url = getattr(metadata, "url", None) or getattr(item, "url", None)
        markdown = getattr(item, "markdown", None)
        if not markdown and article_url:
            scrape_status, scrape_payload = _run_with_timeout(
                lambda: client.scrape(article_url, formats=["markdown"]),
                _SEARCH_TIMEOUT_SECONDS,
            )
            if scrape_status == "ok":
                markdown = response_markdown(scrape_payload)
        if not markdown or not article_url:
            continue
        documents.append(
            SourceDocument(
                doc_id=_doc_id(source, article_url),
                source_id=source.name,
                title=getattr(metadata, "title", None) or getattr(item, "title", None),
                url=article_url,
                published_at=_parse_published_at(getattr(metadata, "published_time", None)),
                content=markdown,
                # Only carried through when the registry itself sets a tier
                # (see PlannedSource.reliability_tier) — never invented here.
                reliability_tier=source.reliability_tier,
            )
        )
    return documents


def collect(source_plan: SourcePlan) -> list[SourceDocument]:
    if not source_plan.planned_sources:
        raise PipelineStageError(
            stage=_STAGE,
            reason="template_only: no sources registered for sk_hynix",
        )

    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"template_only: {_API_KEY_ENV_VAR} is not configured",
        )

    client = Firecrawl(api_key=api_key)
    total = len(source_plan.planned_sources)
    documents: list[SourceDocument] = []
    for index, source in enumerate(source_plan.planned_sources):
        if not source.url:
            continue
        emit_collection_event(source.name, index + 1, total, "started")
        print(f"[{index + 1}/{total}] {source.name} 검색중...", file=sys.stderr)
        try:
            source_documents = _crawl_source(client, source, build_source_search_terms(source, source_plan.question_keywords))
            documents.extend(source_documents)
            emit_collection_event(
                source.name, index + 1, total, "completed", document_count=len(source_documents)
            )
            print(f"[{index + 1}/{total}] {source.name} 완료 ({len(source_documents)}건)", file=sys.stderr)
        except PipelineStageError as exc:
            # One source failing (rate limit, network error, etc.) must not
            # discard whatever was already collected from the others — skip
            # it and keep going, regardless of how many sources are registered.
            emit_collection_event(
                source.name, index + 1, total, "failed", detail=exc.detail or exc.reason
            )
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc.reason}", file=sys.stderr)
        if len(documents) >= _MAX_COLLECTED_DOCUMENTS:
            break

    return documents[:_MAX_COLLECTED_DOCUMENTS]
