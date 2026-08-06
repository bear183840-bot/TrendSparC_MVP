"""SK Broadband sector collector.

Supports normal web sources through Firecrawl search, KOFIC PDF report
sources through the dedicated KOFIC download/parse helper, and any source
registered with collection_method "ai_gated_search" through the generic
AI-gated pattern (GPT judges whether the question is even in the source's
topic area, GPT drafts one search query phrased in that source's own
vocabulary, then Firecrawl runs a domain-restricted search + scrape) - see
the module-level comment by _AI_GATE_MODEL for the full pattern and how to
opt a future source into it without new code. It never fabricates a
SourceDocument: every returned document comes from a real source response.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from datetime import datetime
from queue import Queue
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions

from common.contracts import (
    PlannedSource,
    SourceDocument,
    SourcePlan,
    WebSearchContext,
    WebSearchHarnessResult,
)
from common.errors import PipelineStageError
from core.collection_progress import emit_collection_event
from core.source_planner.query_strategy import build_search_queries, build_source_search_terms
from sources.collectors.ai_search_harness import (
    HarnessConfig,
    run_question_search_harness_result,
)
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
# When enabled, collect() runs one bounded question-level search session and
# does not fall back to the legacy Firecrawl search. When disabled (the
# default), planned sources use the legacy per-source path unchanged.
_HARNESS_API_KEY_ENV_VAR = "TRENDSPARC_SK_BROADBAND_COLLECTOR_HARNESS_API_KEY"
_HARNESS_MODEL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_COLLECTOR_HARNESS_MODEL"
_HARNESS_DEFAULT_MODEL = "gpt-4o"
# Reusable "AI-gated Firecrawl collection" pattern: for any registered source
# whose content Firecrawl's generic search/scrape can reach but the harness's
# own web_search-based question session cannot discover well on its own (a
# fixed, non-negotiable board/URL like KOFIC's PDF board, a site with poor
# generic search coverage, etc.), the same three cheap gpt-4o-mini calls
# apply: (1) _ai_source_gate_relevant - is this question even in the source's
# declared topic area, so an off-topic question never triggers a real
# download/scrape; (2) _ai_select_relevant_candidates - given a list of
# (id, title) candidates from a listing page, which are genuinely relevant
# (only meaningful for listing-page-shaped sources like KOFIC; a plain search
# source skips straight to (3)); (3) _ai_generate_search_query - one short
# query phrased the way *that source's own site* describes the topic, not a
# generic keyword ladder. All three fail open/return None on a missing key,
# missing question, or any call error - a broken AI check must never make a
# working source silently disappear, and per an explicit decision NOT to
# retry a failed/empty AI query against the old rule-based term ladder (see
# _crawl_source_with_ai_gated_search / _discover_kofic_detail_urls_from_search),
# a query-generation failure means that discovery attempt returns no results
# rather than falling back to a lower-quality mechanical guess.
#
# KOFIC (_crawl_kofic_pdf_source) is the first user of this pattern and needs
# its own PDF-download plumbing on top (see sources/collectors/kofic_pdf.py).
# _crawl_source_with_ai_gated_search is the generic version for any future
# source that just needs plain Firecrawl search+scrape with the same
# gate-then-query steps in front of it - register it with collection_method
# "ai_gated_search" (see _AI_GATED_SEARCH_METHOD) to opt in, no new code
# needed per source.
_AI_GATE_MODEL = "gpt-4o-mini"
_AI_GATED_SEARCH_METHOD = "ai_gated_search"
_SPECIAL_COLLECTION_METHODS = {"kofic_pdf_post_download", _AI_GATED_SEARCH_METHOD}
_QUESTION_SEARCH_EVENT_NAME = "OpenAI 웹검색"
_QUESTION_HARNESS_MAX_DOCS = 7  # collect 6-7 relevant originals when the web has enough evidence
_QUESTION_HARNESS_TARGET_MIN_DOCS = 6
_MIN_REQUIRED_SOURCE_DOCUMENTS = 2
# Defensive cap on top of source_planner.select_top_sources()'s 6-source
# selection (6 sources * _MAX_RESULTS_PER_SOURCE = 12) — stops collection
# once reached even if a future config change lets more sources or results
# through, so the collector never hands the validator/analyzer an unbounded
# document set.
_MAX_COLLECTED_DOCUMENTS = 12
# Live-verified against kofic.or.kr (2026-08-06): the listing page's static
# HTML never contains a real, directly-usable detail-page URL. The only
# literal "selectBoardDetail.do?..." substring on the page is a JS template
# fragment inside the fn_detailPage() function *definition*
# ("selectBoardDetail.do?boardNumber=2", missing boardSeqNumber entirely) -
# matching that (the old behavior) produces a URL the server 420s on. The
# real per-post id only exists in each row's own onclick handler -
# fn_goDetailPage(<boardSeqNumber>, boardType, isPublic) on the title link,
# or equivalently fn_zipFileDownload('<boardNumber>','<boardSeqNumber>','1')
# on the download icon - never as a plain href.
_KOFIC_BOARD_SEQ_PATTERN = re.compile(
    r"fn_goDetailPage\(\s*(?P<seq_a>\d+)|fn_zipFileDownload\(\s*'[^']*'\s*,\s*'(?P<seq_b>\d+)'",
    re.IGNORECASE,
)
# Same fn_goDetailPage(...) onclick handler as above, but capturing the link
# text right after it too - only the title link carries a title (the
# zipFileDownload icon link doesn't), so this is a strict subset of
# _KOFIC_BOARD_SEQ_PATTERN's matches, used only when a title is needed to
# judge relevance before downloading anything.
_KOFIC_BOARD_SEQ_WITH_TITLE_PATTERN = re.compile(
    r"fn_goDetailPage\(\s*(?P<seq>\d+)[^)]*\)[^>]*>(?P<title>[^<]+)</a>",
    re.IGNORECASE,
)


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


def _extract_kofic_board_seq_numbers(html_or_markdown: str) -> list[str]:
    """Real per-post ids from a KOFIC listing page's onclick handlers (see
    _KOFIC_BOARD_SEQ_PATTERN) - deduped, page order preserved."""
    seq_numbers: list[str] = []
    for match in _KOFIC_BOARD_SEQ_PATTERN.finditer(html_or_markdown):
        seq = match.group("seq_a") or match.group("seq_b")
        if seq:
            seq_numbers.append(seq)
    return list(dict.fromkeys(seq_numbers))


def _extract_kofic_board_seq_and_titles(html_or_markdown: str) -> list[tuple[str, str]]:
    """(board_seq_number, title) pairs from a listing page's title links, page
    order, deduped by seq - lets a relevance judgment be made from the title
    text alone, before any detail page or PDF is ever fetched."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _KOFIC_BOARD_SEQ_WITH_TITLE_PATTERN.finditer(html_or_markdown):
        seq, title = match.group("seq"), match.group("title").strip()
        if seq and title and seq not in seen:
            seen.add(seq)
            pairs.append((seq, title))
    return pairs


def _ai_source_gate_relevant(question: str, source: PlannedSource, openai_api_key: str | None) -> bool:
    """Cheap upfront check: is this question even in `source`'s declared
    subject area at all? Runs before any discovery/download so an off-topic
    question never spends a real fetch/scrape or a full analyzer pass on
    content nobody asked about. Source-agnostic - works for KOFIC's PDF board
    or any other "ai_gated_search" registered source. Fails open (True) on a
    missing key, no registered topics to judge against, or any call error -
    see module-level comment by _AI_GATE_MODEL."""
    if not question.strip() or not openai_api_key or not source.topics:
        return True
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=_AI_GATE_MODEL,
            max_tokens=20,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only with a JSON object {\"relevant\": true/false}. A "
                        "registered source covers only the listed topics. Judge whether "
                        "the user's question is meaningfully related to any of those "
                        "topics - a topic a document from this source could plausibly "
                        "help answer, not just a superficial keyword overlap."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "source_name": source.name, "source_topics": source.topics},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ai_source_relevance_gate",
                    "schema": {
                        "type": "object",
                        "properties": {"relevant": {"type": "boolean"}},
                        "required": ["relevant"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        return bool(json.loads(response.choices[0].message.content)["relevant"])
    except Exception as exc:  # noqa: BLE001
        print(f"[{source.name}] relevance gate call failed, proceeding unconditionally: {exc}", file=sys.stderr)
        return True


def _ai_select_relevant_candidates(
    question: str, posts: list[tuple[str, str]], openai_api_key: str | None
) -> list[str] | None:
    """Ask which of a listing page's (id, title) candidates are genuinely
    relevant evidence for the question, replacing "just grab the newest N
    regardless of title". Source-agnostic - `posts` can come from any
    listing-page-shaped source (KOFIC's board today, any future
    "ai_gated_search" listing source). Returns None (never []) on a missing
    key, no question, or any call failure, so the caller can fall back to
    its own blind newest-N behavior instead of a working source silently
    returning zero documents because of a broken selection call. An empty
    list IS a meaningful result here (the call succeeded and genuinely found
    nothing relevant) - only None means "couldn't judge, fall back"."""
    if not question.strip() or not openai_api_key or not posts:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=_AI_GATE_MODEL,
            max_tokens=200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Given a question and a list of document titles (each with an "
                        "id), return the ids of titles that are genuinely relevant "
                        "evidence for answering the question - not just loosely on the "
                        "same general subject. Return an empty list if none qualify. "
                        "Never pick a title just because it looks recent - judge only "
                        "from what the title itself says."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question,
                            "titles": [{"id": seq, "title": title} for seq, title in posts],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ai_candidate_selection",
                    "schema": {
                        "type": "object",
                        "properties": {"relevant_ids": {"type": "array", "items": {"type": "string"}}},
                        "required": ["relevant_ids"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        data = json.loads(response.choices[0].message.content)
        valid_seqs = {seq for seq, _ in posts}
        return [seq for seq in data["relevant_ids"] if seq in valid_seqs]
    except Exception as exc:  # noqa: BLE001
        print(f"[AI candidate selection] post-selection call failed, falling back to newest posts: {exc}", file=sys.stderr)
        return None


def _build_kofic_detail_url(source_url: str, board_seq_number: str) -> str | None:
    """The registered source.url is the *listing* page
    (.../selectBoardList.do?boardNumber=<N>) - boardNumber identifies which
    board/category (e.g. "2" = 보도자료), taken from there rather than
    hardcoded, so this stays correct if the registry ever points at a
    different KOFIC board. boardSeqNumber is the specific post, only ever
    discoverable via _extract_kofic_board_seq_numbers."""
    parsed = urlparse(source_url)
    board_number = parse_qs(parsed.query).get("boardNumber", [None])[0]
    if not board_number:
        return None
    detail_path = parsed.path.replace("selectBoardList.do", "selectBoardDetail.do")
    return f"{parsed.scheme}://{parsed.netloc}{detail_path}?boardNumber={board_number}&boardSeqNumber={board_seq_number}"


def _kofic_urls_from_search_items(items, source_url: str) -> list[str]:
    urls: list[str] = []
    for item in items:
        candidate = _item_url(item)
        if candidate and "selectBoardDetail.do" in candidate and "boardSeqNumber=" in candidate:
            urls.append(_normalize_kofic_detail_url(candidate, source_url))
        markdown = getattr(item, "markdown", None) or ""
        for seq in _extract_kofic_board_seq_numbers(markdown):
            built = _build_kofic_detail_url(source_url, seq)
            if built:
                urls.append(built)
    return list(dict.fromkeys(urls))


def _ai_generate_search_query(question: str, source: PlannedSource, openai_api_key: str | None) -> str | None:
    """Ask the model for one short search query phrased the way `source`'s
    own site would describe the topic, instead of a generic role-based term
    ladder - e.g. a question about "IPTV 가입자 수" is better searched on
    kofic.or.kr as "IPTV VOD 이용 건수" (KOFIC's own vocabulary, see its
    registered topics), which a generic keyword concatenation wouldn't know
    to produce. Source-agnostic - the same call works for any registered
    source with declared topics, not just KOFIC. Returns None on a missing
    key/question/topics or any call failure. By design there is no
    rule-based-ladder fallback here: a caller that gets None is expected to
    treat that discovery attempt as empty rather than retry with a lower-
    quality mechanical query (an explicit decision - see
    _crawl_source_with_ai_gated_search and
    _discover_kofic_detail_urls_from_search)."""
    if not question.strip() or not openai_api_key or not source.topics:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=_AI_GATE_MODEL,
            max_tokens=40,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Given a question and a source's declared topics, write ONE short "
                        "Korean search query (2-5 words) that would find this specific "
                        "source's own content relevant to the question - phrase it the way "
                        "this source's own site/documents would describe the topic (see its "
                        "topics), not necessarily the user's exact wording. Answer only with "
                        'JSON {"query": "..."}.'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "source_name": source.name, "source_topics": source.topics},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ai_search_query",
                    "schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        query = json.loads(response.choices[0].message.content)["query"].strip()
        return query or None
    except Exception as exc:  # noqa: BLE001
        print(f"[{source.name}] search-query generation failed: {exc}", file=sys.stderr)
        return None


def _discover_kofic_detail_urls_from_search(
    client: Firecrawl,
    source: PlannedSource,
    keywords: list[str],
    question: str = "",
    openai_api_key: str | None = None,
) -> list[str]:
    """GPT-only discovery: no rule-based term-ladder fallback here anymore -
    if the model can't produce a query (or its query finds nothing), this
    returns [] and _crawl_kofic_pdf_source's listing-page path (which has
    its own GPT title-selection, then its own blind-newest fallback) is what
    actually catches that, not a second search attempt in this function."""
    if not source.url or not keywords:
        return []
    domain = urlparse(source.url).netloc
    if not domain:
        return []
    gpt_query = _ai_generate_search_query(question, source, openai_api_key)
    if not gpt_query:
        return []
    status, payload = _run_with_timeout(
        lambda: client.search(
            gpt_query,
            include_domains=[domain],
            limit=_MAX_RESULTS_PER_SOURCE,
            scrape_options=ScrapeOptions(formats=["markdown"]),
        ),
        _SEARCH_TIMEOUT_SECONDS,
    )
    if status != "ok":
        return []
    return _kofic_urls_from_search_items(payload.web or [], source.url)[:_MAX_RESULTS_PER_SOURCE]


def _discover_kofic_detail_urls_from_listing(
    source: PlannedSource, question: str = "", openai_api_key: str | None = None
) -> list[str]:
    if not source.url:
        return []
    try:
        response = requests.get(source.url, headers={"User-Agent": "Mozilla/5.0"}, timeout=_LISTING_TIMEOUT_SECONDS)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
    except Exception:  # noqa: BLE001
        return []
    posts = _extract_kofic_board_seq_and_titles(response.text)
    selected_seqs = _ai_select_relevant_candidates(question, posts, openai_api_key)
    if selected_seqs is None:
        # No question context, or the selection call couldn't run/failed -
        # fall back to the original "newest N regardless of title" behavior.
        seq_numbers = _extract_kofic_board_seq_numbers(response.text)
    else:
        seq_numbers = selected_seqs
    urls = [
        built
        for seq in seq_numbers
        if (built := _build_kofic_detail_url(source.url, seq)) is not None
    ]
    return list(dict.fromkeys(urls))[:_MAX_RESULTS_PER_SOURCE]


def _crawl_kofic_pdf_source(
    client: Firecrawl,
    source: PlannedSource,
    api_key: str,
    keywords: list[str],
    question: str = "",
    openai_api_key: str | None = None,
) -> list[SourceDocument]:
    if not _ai_source_gate_relevant(question, source, openai_api_key):
        print(
            f"[KOFIC] question judged unrelated to '{source.name}' topics {source.topics} - "
            "skipping collection entirely",
            file=sys.stderr,
        )
        return []
    detail_urls = _discover_kofic_detail_urls_from_search(client, source, keywords, question, openai_api_key)
    if not detail_urls:
        detail_urls = _discover_kofic_detail_urls_from_listing(source, question, openai_api_key)
    if not detail_urls:
        # Never a silent "0건" - distinguish "genuinely nothing new posted"
        # from "discovery itself found no candidate post ids", visible in
        # both the terminal log and (via the caller's emit_collection_event)
        # the in-app 실행 기록 panel, so a recurring failure here doesn't
        # quietly look identical to a normal empty result.
        print(
            f"[KOFIC] no post ids discovered for '{source.name}' from search results or the "
            "listing page - either the site's markup changed again or there's genuinely nothing "
            "new; see _extract_kofic_board_seq_numbers",
            file=sys.stderr,
        )
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


def _crawl_source_with_ai_gated_search(
    client: Firecrawl,
    source: PlannedSource,
    question: str = "",
    openai_api_key: str | None = None,
) -> list[SourceDocument]:
    """Generic version of the KOFIC pattern (see the module-level comment by
    _AI_GATE_MODEL) for any source registered with collection_method
    "ai_gated_search": (1) gate on whether the question is even in this
    source's declared topic area, (2) ask the model for one short query
    phrased the way this source's own site would describe the topic,
    (3) Firecrawl domain-restricted search + scrape. Unlike
    _crawl_kofic_pdf_source there is no listing-page/PDF plumbing here - this
    is the plain-web-article case. No rule-based query ladder: if the gate
    says no, or the model can't produce a query, or the query finds nothing,
    this returns [] rather than retrying with a lower-quality mechanical
    guess (same explicit decision as _discover_kofic_detail_urls_from_search)."""
    if not source.url:
        return []
    if not _ai_source_gate_relevant(question, source, openai_api_key):
        print(
            f"[{source.name}] question judged unrelated to topics {source.topics} - "
            "skipping collection entirely",
            file=sys.stderr,
        )
        return []
    domain = urlparse(source.url).netloc
    if not domain:
        return []
    query = _ai_generate_search_query(question, source, openai_api_key)
    if not query:
        return []
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
        return []
    documents: list[SourceDocument] = []
    for item in (payload.web or [])[:_MAX_RESULTS_PER_SOURCE]:
        url = _item_url(item)
        if not url:
            continue
        markdown = getattr(item, "markdown", None)
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


def _crawl_special_source(
    client: Firecrawl,
    source: PlannedSource,
    api_key: str,
    keywords: list[str],
    question: str = "",
    openai_api_key: str | None = None,
) -> list[SourceDocument]:
    """Dispatches a registered "special" source (collection_method in
    _SPECIAL_COLLECTION_METHODS) to its dedicated collector. Adding a new
    special collection method later means adding one branch here and to
    _SPECIAL_COLLECTION_METHODS - no other call site needs to change."""
    methods = set(source.collection_method)
    if "kofic_pdf_post_download" in methods:
        return _crawl_kofic_pdf_source(
            client, source, api_key, keywords, question=question, openai_api_key=openai_api_key
        )
    if _AI_GATED_SEARCH_METHOD in methods:
        return _crawl_source_with_ai_gated_search(
            client, source, question=question, openai_api_key=openai_api_key
        )
    return []


def _crawl_source(
    client: Firecrawl,
    source: PlannedSource,
    api_key: str,
    keywords: list[str],
    all_sources: tuple[PlannedSource, ...] = (),
    search_context: WebSearchContext | None = None,
) -> WebSearchHarnessResult:
    methods = set(source.collection_method)
    if "kofic_pdf_post_download" in methods:
        return _crawl_kofic_pdf_source(client, source, api_key, keywords)
    if _AI_GATED_SEARCH_METHOD in methods:
        question = search_context.question if search_context else ""
        return _crawl_source_with_ai_gated_search(
            client, source, question, os.environ.get(_HARNESS_API_KEY_ENV_VAR)
        )
    return _crawl_web_source(client, source, keywords)


def _run_question_ai_harness(
    client: Firecrawl,
    registered_sources: list[PlannedSource],
    keywords: list[str],
    api_key: str,
    search_context: WebSearchContext | None,
) -> list[SourceDocument]:
    try:
        from openai import OpenAI

        openai_client = OpenAI(api_key=api_key)
        model = os.environ.get(_HARNESS_MODEL_ENV_VAR) or _HARNESS_DEFAULT_MODEL
        return run_question_search_harness_result(
            openai_client,
            client,
            registered_sources,
            keywords,
            HarnessConfig(
                model=model,
                target_docs=_QUESTION_HARNESS_MAX_DOCS,
                assess_scraped_evidence=True,
                # Six relevant originals are enough to finish successfully;
                # seven is the bounded collection cap. The collector still
                # permits a corroborated partial result of two documents after
                # exhausting the search budget.
                min_scraped_docs_for_sufficient=_QUESTION_HARNESS_TARGET_MIN_DOCS,
                # One extra round beyond the default 3, specifically to give
                # a gap-driven follow-up query (see run loop's next_queries)
                # a real shot at covering an information need the first few
                # rounds missed, before we accept a partial result below.
                max_rounds=4,
                # Raised from the module default of 2 -> more raw source
                # documents considered per round, not just the first couple
                # of grounded hits. max_total_scrape_calls raised to match
                # (5 candidates/round * 4 rounds * up to 2 attempts each with
                # the default 1 retry) so this budget, not the scrape-call
                # ceiling, is what actually bounds each round.
                max_candidates_per_round=5,
                max_total_scrape_calls=40,
            ),
            search_context=search_context,
        )
    except Exception as exc:  # noqa: BLE001
        raise PipelineStageError(
            stage=_STAGE,
            reason="question-level ai_search_harness call failed",
            detail=str(exc),
        ) from exc


def _collect_with_question_harness(
    client: Firecrawl,
    source_plan: SourcePlan,
    firecrawl_api_key: str,
    harness_api_key: str,
) -> list[SourceDocument]:
    """One OpenAI search session plus any registry-declared special collectors."""
    registered_sources = source_plan.registered_sources or source_plan.planned_sources
    special_sources = [
        source
        for source in registered_sources
        if source.url and set(source.collection_method) & _SPECIAL_COLLECTION_METHODS
    ]
    total = 1 + len(special_sources)
    documents: list[SourceDocument] = []
    search_result: WebSearchHarnessResult | None = None

    emit_collection_event(_QUESTION_SEARCH_EVENT_NAME, 1, total, "started")
    print(f"[1/{total}] {_QUESTION_SEARCH_EVENT_NAME} 수집 중...", file=sys.stderr)
    try:
        search_result = _run_question_ai_harness(
            client,
            list(registered_sources),
            source_plan.question_keywords,
            harness_api_key,
            source_plan.search_context,
        )
        documents.extend(search_result.documents)
        detail = (
            f"rounds={search_result.rounds_completed}, "
            f"scrape_calls={search_result.scrape_call_count}, "
            f"covered={search_result.covered_information_needs}, "
            f"missing={search_result.missing_information_needs}"
        )
        emit_collection_event(
            _QUESTION_SEARCH_EVENT_NAME,
            1,
            total,
            "completed" if len(search_result.documents) >= _MIN_REQUIRED_SOURCE_DOCUMENTS else "failed",
            document_count=len(search_result.documents),
            detail=detail,
        )
    except PipelineStageError as exc:
        emit_collection_event(
            _QUESTION_SEARCH_EVENT_NAME, 1, total, "failed", detail=exc.detail or exc.reason
        )
        print(f"[1/{total}] {_QUESTION_SEARCH_EVENT_NAME} 실패: {exc.reason}", file=sys.stderr)

    for index, source in enumerate(special_sources, start=2):
        emit_collection_event(source.name, index, total, "started")
        try:
            found = _crawl_special_source(
                client,
                source,
                firecrawl_api_key,
                build_source_search_terms(source, source_plan.question_keywords),
                question=(source_plan.search_context.question if source_plan.search_context else ""),
                openai_api_key=harness_api_key,
            )
            documents.extend(found)
            emit_collection_event(source.name, index, total, "completed", document_count=len(found))
        except Exception as exc:  # noqa: BLE001
            detail = exc.detail or exc.reason if isinstance(exc, PipelineStageError) else str(exc)
            emit_collection_event(source.name, index, total, "failed", detail=detail)
            print(f"[{index}/{total}] {source.name} 실패: {detail}", file=sys.stderr)
    # Not all-or-nothing: a real, corroborated core of evidence (>= 2
    # documents from >= 2 independent sources) is required, but the harness
    # is not required to have covered every single information_need before
    # we proceed - a need it genuinely couldn't find evidence for after its
    # full round budget is left empty and surfaced honestly as a report
    # limitation downstream (see pipeline.py's report_generator call),
    # rather than fabricated or used to block the whole report.
    #
    # This must count the *combined* `documents` list (harness + KOFIC/other
    # special sources), not just search_result.documents - otherwise a
    # question that the harness alone couldn't fully cover gets rejected
    # even when a special source (e.g. KOFIC) already supplied real,
    # independent corroborating evidence.
    independent_sources = {document.source_id for document in documents}
    if len(documents) < _MIN_REQUIRED_SOURCE_DOCUMENTS or len(independent_sources) < _MIN_REQUIRED_SOURCE_DOCUMENTS:
        raise PipelineStageError(
            stage=_STAGE,
            reason=(
                "insufficient relevant evidence after bounded collection "
                f"(documents={len(documents)}, independent_sources={len(independent_sources)})"
            ),
            detail="At least two question-relevant documents from independent sources are required.",
        )
    if search_result and search_result.missing_information_needs:
        print(
            f"[{_STAGE}] proceeding with partial coverage - no grounded evidence found for: "
            f"{search_result.missing_information_needs}",
            file=sys.stderr,
        )
    if len(documents) > _QUESTION_HARNESS_MAX_DOCS:
        # Special collectors are registered, purpose-built evidence paths.
        # Reserve their successfully collected documents before trimming the
        # web-harness overflow so the total still stays within the requested
        # 6-7 originals without silently discarding the special source.
        special_source_ids = {source.name for source in special_sources}
        special_documents = [
            document for document in documents if document.source_id in special_source_ids
        ]
        web_documents = [
            document for document in documents if document.source_id not in special_source_ids
        ]
        documents = [*special_documents, *web_documents]
    return documents[:_QUESTION_HARNESS_MAX_DOCS]


def collect(source_plan: SourcePlan) -> list[SourceDocument]:
    if not source_plan.planned_sources:
        raise PipelineStageError(stage=_STAGE, reason="no sources registered for sk_broadband")
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"{_API_KEY_ENV_VAR} is not configured")
    client = Firecrawl(api_key=api_key)
    harness_key = os.environ.get(_HARNESS_API_KEY_ENV_VAR)
    if harness_key:
        return _collect_with_question_harness(client, source_plan, api_key, harness_key)
    total = len(source_plan.planned_sources)
    documents: list[SourceDocument] = []
    for index, source in enumerate(source_plan.planned_sources):
        if not source.url:
            continue
        emit_collection_event(source.name, index + 1, total, "started")
        print(f"[{index + 1}/{total}] {source.name} 수집 중...", file=sys.stderr)
        try:
            crawl_args = (
                client,
                source,
                api_key,
                build_source_search_terms(source, source_plan.question_keywords),
                tuple(source_plan.planned_sources),
            )
            if source_plan.search_context is None:
                source_documents = _crawl_source(*crawl_args)
            else:
                source_documents = _crawl_source(
                    *crawl_args,
                    search_context=source_plan.search_context,
                )
            documents.extend(source_documents)
            emit_collection_event(
                source.name, index + 1, total, "completed", document_count=len(source_documents)
            )
            print(f"[{index + 1}/{total}] {source.name} 완료 ({len(source_documents)}건)", file=sys.stderr)
        except PipelineStageError as exc:
            emit_collection_event(
                source.name, index + 1, total, "failed", detail=exc.detail or exc.reason
            )
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc.reason}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            emit_collection_event(source.name, index + 1, total, "failed", detail=str(exc))
            print(f"[{index + 1}/{total}] {source.name} 실패: {exc}", file=sys.stderr)
        if len(documents) >= _MAX_COLLECTED_DOCUMENTS:
            break
    return documents[:_MAX_COLLECTED_DOCUMENTS]
