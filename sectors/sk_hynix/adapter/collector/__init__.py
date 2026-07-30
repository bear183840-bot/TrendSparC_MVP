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
# Firecrawl's search already ranks by relevance; taking up to 3 (rather than
# just the single best) means a source still contributes something even
# when the top hit isn't a great match, and other sources return nothing.
_MAX_RESULTS_PER_SOURCE = 3


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
    for term_count in _query_term_counts(len(deduped_keywords)):
        query = " ".join(deduped_keywords[:term_count])
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
        if not item.markdown:
            continue
        metadata = item.metadata
        article_url = (metadata.url if metadata else None) or item.url
        documents.append(
            SourceDocument(
                doc_id=_doc_id(source, article_url),
                source_id=source.name,
                title=(metadata.title if metadata else None) or item.title,
                url=article_url,
                published_at=_parse_published_at(metadata.published_time if metadata else None),
                content=item.markdown,
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
        print(f"[{index + 1}/{total}] {source.name} 검색중...", file=sys.stderr)
        try:
            source_documents = _crawl_source(client, source, source_plan.question_keywords)
            documents.extend(source_documents)
            print(f"[{index + 1}/{total}] {source.name} 완료 ({len(source_documents)}건)", file=sys.stderr)
        except PipelineStageError as exc:
            # One source failing (rate limit, network error, etc.) must not
            # discard whatever was already collected from the others — skip
            # it and keep going, regardless of how many sources are registered.
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc.reason}", file=sys.stderr)

    return documents
