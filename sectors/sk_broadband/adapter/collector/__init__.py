"""SK Broadband sector collector.

Supports normal web sources through Firecrawl search and KOFIC PDF report
sources through the dedicated KOFIC download/parse helper. It never fabricates a
SourceDocument: every returned document comes from a real source response.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import threading
from datetime import datetime
from queue import Queue
from urllib.parse import urljoin, urlparse

import requests
from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions

from common.contracts import PlannedSource, SourceDocument, SourcePlan
from common.errors import PipelineStageError
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms
from sources.collectors.ai_search_harness import HarnessConfig, run_ai_search_harness
from sources.collectors.kofic_pdf import collect_pdf_markdown_from_detail_url
from sources.collectors.firecrawl_web import response_markdown

_API_KEY_ENV_VAR = "FIRECRAWL_API_KEY"
_SEARCH_TIMEOUT_SECONDS = 30
_LISTING_TIMEOUT_SECONDS = 20
_STAGE = "sectors.sk_broadband.adapter.collector"
_PRIMARY_TERM_COUNT = 2
_LAST_RESORT_TERM_COUNT = 1
_MAX_QUERY_TERMS = 5
_MAX_RESULTS_PER_SOURCE = 2
# AI search harness (grounded web_search + Firecrawl scrape, see
# sources/collectors/ai_search_harness.py) — optional, opt-in via env var.
# When enabled, a source uses the harness ONLY: insufficient/failed results
# raise PipelineStageError instead of falling back to the legacy Firecrawl
# search below, since retrying with a lower-quality method after already
# spending harness tokens wastes money for little chance of success. When
# disabled (the default), sources use the legacy Firecrawl search unchanged.
_HARNESS_API_KEY_ENV_VAR = "TRENDSPARC_SK_BROADBAND_COLLECTOR_HARNESS_API_KEY"
_HARNESS_MODEL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_COLLECTOR_HARNESS_MODEL"
_HARNESS_DEFAULT_MODEL = "gpt-4o"
_HARNESS_MIN_DOCS_PER_SOURCE = 1
# Defensive cap on top of source_planner.select_top_sources()'s 6-source
# selection (6 sources * _MAX_RESULTS_PER_SOURCE = 12) — stops collection
# once reached even if a future config change lets more sources or results
# through, so the collector never hands the validator/analyzer an unbounded
# document set.
_MAX_COLLECTED_DOCUMENTS = 12
_KOFIC_DETAIL_PATTERN = re.compile(r"selectBoardDetail\.do\?[^\"'<>\s]+", re.IGNORECASE)


def _doc_id(source: PlannedSource, url: str, suffix: str = "") -> str:
    digest = hashlib.sha1(f"{source.name}:{url}:{suffix}".encode("utf-8")).hexdigest()[:16]
    return f"{source.name}:{digest}"


def _parse_published_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _query_term_counts(available: int) -> list[int]:
    candidates = [_PRIMARY_TERM_COUNT, _LAST_RESORT_TERM_COUNT, min(available, _MAX_QUERY_TERMS)]
    counts: list[int] = []
    for count in candidates:
        if 1 <= count <= available and count not in counts:
            counts.append(count)
    return counts


def _search_source(client: Firecrawl, domain: str, deduped_keywords: list[str]):
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
                f"site:{domain} {queries[0]}",
                include_domains=[],
                limit=_MAX_RESULTS_PER_SOURCE,
                scrape_options=ScrapeOptions(formats=["markdown"]),
            ),
            _SEARCH_TIMEOUT_SECONDS,
        )
        if status != "ok":
            return status, payload
        results = [
            item for item in (payload.web or [])
            if _item_url(item) and urlparse(_item_url(item)).netloc.endswith(domain)
        ]
        if results:
            return "ok", results
    return "ok", []


def _item_url(item) -> str | None:
    metadata = getattr(item, "metadata", None)
    metadata_url = getattr(metadata, "url", None) if metadata else None
    return metadata_url or getattr(item, "url", None)


def _item_title(item) -> str:
    metadata = getattr(item, "metadata", None)
    metadata_title = getattr(metadata, "title", None) if metadata else None
    return metadata_title or getattr(item, "title", None) or "Untitled"


def _item_published_time(item) -> str | None:
    metadata = getattr(item, "metadata", None)
    return getattr(metadata, "published_time", None) if metadata else None


def _crawl_web_source(client: Firecrawl, source: PlannedSource, keywords: list[str]) -> list[SourceDocument]:
    if not keywords or not source.url:
        return []
    domain = urlparse(source.url).netloc
    if not domain:
        return []
    deduped_keywords = list(dict.fromkeys(keyword for keyword in keywords if keyword))
    if not deduped_keywords:
        return []
    status, payload = _search_source(client, domain, deduped_keywords)
    if status == "timeout":
        return []
    if status == "error":
        raise PipelineStageError(stage=_STAGE, reason=f"failed to search source '{source.name}'", detail=str(payload)) from payload
    documents: list[SourceDocument] = []
    for item in payload[:_MAX_RESULTS_PER_SOURCE]:
        markdown = getattr(item, "markdown", None)
        url = _item_url(item)
        if not url:
            continue
        if not markdown:
            scrape_status, scrape_payload = _run_with_timeout(
                lambda: client.scrape(url, formats=["markdown"]),
                _SEARCH_TIMEOUT_SECONDS,
            )
            if scrape_status == "ok":
                markdown = response_markdown(scrape_payload)
        if not markdown:
            continue
        documents.append(
            SourceDocument(
                doc_id=_doc_id(source, url),
                source_id=source.name,
                title=_item_title(item),
                url=url,
                published_at=_parse_published_at(_item_published_time(item)),
                content=markdown,
                reliability_tier=source.reliability_tier,
            )
        )
    return documents


def _normalize_kofic_detail_url(raw_url: str, base_url: str) -> str:
    return urljoin(base_url, raw_url.replace("&amp;", "&").strip())


def _discover_kofic_detail_urls_from_search(client: Firecrawl, source: PlannedSource, keywords: list[str]) -> list[str]:
    if not source.url or not keywords:
        return []
    domain = urlparse(source.url).netloc
    if not domain:
        return []
    status, payload = _search_source(client, domain, list(dict.fromkeys(keywords)))
    if status != "ok":
        return []
    urls: list[str] = []
    for item in payload:
        candidate = _item_url(item)
        if candidate and "selectBoardDetail.do" in candidate:
            urls.append(_normalize_kofic_detail_url(candidate, source.url))
        markdown = getattr(item, "markdown", None) or ""
        for match in _KOFIC_DETAIL_PATTERN.findall(markdown):
            urls.append(_normalize_kofic_detail_url(match, source.url))
    return list(dict.fromkeys(urls))[:_MAX_RESULTS_PER_SOURCE]


def _discover_kofic_detail_urls_from_listing(source: PlannedSource) -> list[str]:
    if not source.url:
        return []
    try:
        response = requests.get(source.url, headers={"User-Agent": "Mozilla/5.0"}, timeout=_LISTING_TIMEOUT_SECONDS)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
    except Exception:  # noqa: BLE001
        return []
    urls = [_normalize_kofic_detail_url(match, source.url) for match in _KOFIC_DETAIL_PATTERN.findall(response.text)]
    return list(dict.fromkeys(urls))[:_MAX_RESULTS_PER_SOURCE]


def _crawl_kofic_pdf_source(client: Firecrawl, source: PlannedSource, api_key: str, keywords: list[str]) -> list[SourceDocument]:
    detail_urls = _discover_kofic_detail_urls_from_search(client, source, keywords)
    if not detail_urls:
        detail_urls = _discover_kofic_detail_urls_from_listing(source)
    documents: list[SourceDocument] = []
    for detail_url in detail_urls[:_MAX_RESULTS_PER_SOURCE]:
        try:
            parsed = collect_pdf_markdown_from_detail_url(detail_url, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"[KOFIC] PDF parse skipped: {detail_url} ({exc})", file=sys.stderr)
            continue
        documents.append(
            SourceDocument(
                doc_id=_doc_id(source, detail_url, parsed.attachment.download_name),
                source_id=source.name,
                title=parsed.attachment.download_name,
                url=detail_url,
                content=parsed.markdown,
                reliability_tier=source.reliability_tier,
            )
        )
    return documents


def _run_ai_harness(
    client: Firecrawl,
    source: PlannedSource,
    all_sources: list[PlannedSource],
    keywords: list[str],
    api_key: str,
) -> list[SourceDocument]:
    """The only path taken when the harness is enabled for this source —
    insufficient/failed results raise PipelineStageError instead of falling
    back to legacy Firecrawl search. collect()'s existing per-source
    try/except catches this, logs the source as failed, and moves on."""
    try:
        from openai import OpenAI

        openai_client = OpenAI(api_key=api_key)
        model = os.environ.get(_HARNESS_MODEL_ENV_VAR) or _HARNESS_DEFAULT_MODEL
        docs = run_ai_search_harness(
            openai_client,
            client,
            source,
            all_sources,
            keywords,
            HarnessConfig(model=model),
        )
    except Exception as exc:  # noqa: BLE001
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"ai_search_harness call failed for '{source.name}'",
            detail=str(exc),
        ) from exc
    if len(docs) < _HARNESS_MIN_DOCS_PER_SOURCE:
        raise PipelineStageError(
            stage=_STAGE,
            reason=(
                f"ai_search_harness found insufficient documents for "
                f"'{source.name}' ({len(docs)} < {_HARNESS_MIN_DOCS_PER_SOURCE})"
            ),
        )
    return docs


def _crawl_source(
    client: Firecrawl,
    source: PlannedSource,
    api_key: str,
    keywords: list[str],
    all_sources: tuple[PlannedSource, ...] = (),
) -> list[SourceDocument]:
    if "kofic_pdf_post_download" in set(source.collection_method):
        return _crawl_kofic_pdf_source(client, source, api_key, keywords)
    harness_key = os.environ.get(_HARNESS_API_KEY_ENV_VAR)
    if not harness_key:
        return _crawl_web_source(client, source, keywords)  # harness disabled — legacy is the default
    return _run_ai_harness(client, source, list(all_sources), keywords, harness_key)  # enabled — never falls back


def collect(source_plan: SourcePlan) -> list[SourceDocument]:
    if not source_plan.planned_sources:
        raise PipelineStageError(stage=_STAGE, reason="no sources registered for sk_broadband")
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"{_API_KEY_ENV_VAR} is not configured")
    client = Firecrawl(api_key=api_key)
    total = len(source_plan.planned_sources)
    documents: list[SourceDocument] = []
    for index, source in enumerate(source_plan.planned_sources):
        if not source.url:
            continue
        print(f"[{index + 1}/{total}] {source.name} 수집 중...", file=sys.stderr)
        try:
            source_documents = _crawl_source(
                client,
                source,
                api_key,
                build_source_search_terms(source, source_plan.question_keywords),
                tuple(source_plan.planned_sources),
            )
            documents.extend(source_documents)
            print(f"[{index + 1}/{total}] {source.name} 완료 ({len(source_documents)}건)", file=sys.stderr)
        except PipelineStageError as exc:
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc.reason}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc}", file=sys.stderr)
        if len(documents) >= _MAX_COLLECTED_DOCUMENTS:
            break
    return documents[:_MAX_COLLECTED_DOCUMENTS]
