"""collector for the sk_planet sector adapter.

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
source's whole indexed history instead. Up to 2 documents may come back per
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
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms

_API_KEY_ENV_VAR = "FIRECRAWL_API_KEY"
_SEARCH_TIMEOUT_SECONDS = 30
_STAGE = "sectors.sk_planet.adapter.collector"

# Firecrawl의 search는 다중 검색어를 AND 조건으로 처리하는 경향이 있어, 너무 긴
# 검색어(예: 국문/영문 혼용, 혹은 브랜드명과 "포인트"/"마케팅"/"현황" 같은 흔한
# 단어가 섞인 조합)는 검색 결과를 내지 못할 수 있습니다. 검색어가 적을수록 뭔가
# 매칭될 확률이 높으므로, _query_term_counts()는 짧고 구체적인 조합을 먼저
# 시도하고(비용도 적고 대체로 성공함), 그래도 안 되면 최후 수단으로 전체 검색어를
# 시도합니다 — 가장 실패 확률이 높은 긴 검색어를 매번 먼저 시도하면 소스마다
# 낭비되는 호출이 생기고, Firecrawl의 분당 호출 한도에 걸리기 쉬워집니다.
_PRIMARY_TERM_COUNT = 2
_LAST_RESORT_TERM_COUNT = 1
_MAX_QUERY_TERMS = 5
# Firecrawl은 이미 관련도 순으로 정렬해서 반환하므로, 1건이 아니라 최대 2건까지
# 받아오면 1등 결과가 애매하거나 다른 소스가 전부 0건일 때도 뭔가는 건질 수 있음.
_MAX_RESULTS_PER_SOURCE = 2
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
    """짧고 구체적인 검색어부터 시도할 검색어 개수 목록을 반환합니다. 이전 시도
    (더 짧고 느슨한 검색어)가 0건일 때만 더 긴 검색어로 확대하므로, 짧은
    검색어에서 이미 성공하면 실패 확률 높은 긴 검색어 호출 비용이 안 듭니다."""
    candidates = [_PRIMARY_TERM_COUNT, _LAST_RESORT_TERM_COUNT, min(available, _MAX_QUERY_TERMS)]
    counts: list[int] = []
    for count in candidates:
        if 1 <= count <= available and count not in counts:
            counts.append(count)
    return counts


def _search_source(client: Firecrawl, domain: str, deduped_keywords: list[str]):
    """결과가 나올 때까지, 혹은 실제 에러/타임아웃이 날 때까지 검색어를 점점
    줄여가며 재시도합니다. ("ok", 결과리스트) / ("error", 예외) / ("timeout", None)
    중 하나를 반환 — _run_with_timeout의 상태값 규칙과 동일합니다."""
    for query in build_search_queries(deduped_keywords):
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
    deduped_keywords = list(dict.fromkeys(keywords))  # 중복 제거 및 입력 순서 유지

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
    """SK플래닛 소스 플랜에 따라 등록된 도메인별 키워드 검색을 실행하여 문서를 수집합니다."""
    if not source_plan.planned_sources:
        raise PipelineStageError(
            stage=_STAGE,
            reason="template_only: no sources registered for sk_planet",
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
            source_documents = _crawl_source(client, source, build_source_search_terms(source, source_plan.question_keywords))
            documents.extend(source_documents)
            print(f"[{index + 1}/{total}] {source.name} 완료 ({len(source_documents)}건)", file=sys.stderr)
        except PipelineStageError as exc:
            # 특정 소스에서 수집 오류가 발생하더라도 다른 소스 수집에 영향을 주지 않도록 개별 스킵 처리
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc.reason}", file=sys.stderr)
        if len(documents) >= _MAX_COLLECTED_DOCUMENTS:
            break

    return documents[:_MAX_COLLECTED_DOCUMENTS]
