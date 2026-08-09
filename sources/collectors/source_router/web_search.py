"""GPT-5 mini + web_search — search execution only, doc1 §5.

Deliberately does no judgment (no sufficiency/gap reasoning) — that split is
the core architectural difference from sources/collectors/ai_search_harness.py,
whose single round call both searches and judges. Only tool-grounded URLs
(url_citation annotations or web_search_call.action.sources) are trusted;
a URL the model's JSON reply invents without tool backing is dropped —
same hallucination guard as ai_search_harness.py's _grounded_candidates,
reimplemented locally so this package stays self-contained.

*** Timeout handling — live-verified 2026-08-09 ***
A `tool_choice="required"` web_search call does a real live search round-trip
before it can reply, so it routinely takes longer than a plain chat
completion. An earlier version of this module gave the OpenAI client a hard
`timeout=30` kwarg (a real HTTP client-side timeout that aborts the request);
a live run against 15 queries in a row saw 6/6 fail with "Request timed
out." ai_search_harness.py's `_run_with_timeout()` already solved this for
the exact same call shape (same nominal 30s) by never imposing a hard client
timeout at all — it runs the call in a background thread and simply stops
*waiting* after timeout_seconds, letting the request finish or fail on its
own instead of severing it mid-flight. Reused here verbatim (`_run_with_
timeout`) rather than reinvented, and the OpenAI client below is
deliberately constructed with no `timeout=` kwarg to match.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from queue import Queue

from openai import OpenAI

from common.ai_client import openai_client_kwargs
from sources.collectors.source_router.contracts import KeyFact, WebSearchResult

_API_KEY_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_MODEL"
_BASE_URL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_BASE_URL"
_DEFAULT_MODEL = "gpt-5-mini"

_DEFAULT_MAX_URLS_PER_QUERY = 2


def _run_with_timeout(func, timeout_seconds: int):
    """Same pattern as ai_search_harness.py's helper of the same name — runs
    `func` in a daemon thread and stops *waiting* after timeout_seconds
    rather than aborting the underlying HTTP request. Returns
    ("ok", result) | ("error", exception) | ("timeout", None)."""
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


def _system_prompt(max_urls: int) -> str:
    return (
        "You are a web search executor. Use the web_search tool to find "
        "evidence for the given query. Only report URLs actually retrieved "
        "through the tool - never fabricate a URL, title, date, or fact. "
        f"Return at most {max_urls} distinct URLs - the strongest, most "
        "on-topic evidence, not an exhaustive list. After searching, reply "
        "with exactly one JSON array on its own line, one object per "
        "distinct URL you found, shaped as: "
        '{"url": "...", "title": "...", "source_type": one of '
        '"official"/"research"/"independent"/"news"/"other", "summary": short '
        'summary of what this source says about the query, "key_facts": '
        '[{"text": "...", "metric": null-or-string, "value": null-or-number, '
        '"unit": null-or-string, "time": null-or-string, "value_type": null or '
        'one of "actual"/"estimate"/"forecast"/"target"/"guidance"}], '
        '"relevance": how this source answers the query}. Only populate a '
        "key_fact's metric/value/unit/time/value_type when the source text "
        "actually states it - never invent or estimate a number yourself. "
        "Prefer a short summary over an exhaustive one; put anything precise "
        "and checkable into key_facts instead."
    )


def _model(model_override: str | None) -> str:
    return model_override or os.environ.get(_MODEL_ENV_VAR, "").strip() or _DEFAULT_MODEL


def _grounded_urls(response) -> set[str]:
    urls: set[str] = set()
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            for block in getattr(item, "content", None) or []:
                for annotation in getattr(block, "annotations", None) or []:
                    if getattr(annotation, "type", None) == "url_citation":
                        url = getattr(annotation, "url", None)
                        if url:
                            urls.add(url)
        elif item_type == "web_search_call":
            action = getattr(item, "action", None)
            sources = getattr(action, "sources", None) or []
            for source in sources:
                url = source.get("url") if isinstance(source, dict) else getattr(source, "url", None)
                if url:
                    urls.add(url)
    return urls


def _coerce_value(raw) -> float | None:
    """KeyFact.value is a strict float, but the model sometimes writes an
    approximate figure as text instead of a bare number (live-verified:
    "약 500" crashed the whole search call with a pydantic ValidationError,
    killing every result from that round). Defensively extract the numeric
    part rather than let one malformed fact take down the entire response —
    falls back to None ("no clean number stated") rather than guessing when
    nothing numeric can be found, same spirit as coverage.py's _clamp."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(raw))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _parse_results(text: str, grounded: set[str]) -> list[WebSearchResult]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    results: list[WebSearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url or url not in grounded:
            continue  # hallucination guard — never trust a URL the tool didn't actually return
        key_facts = [
            KeyFact(
                text=str(fact.get("text", "")).strip(),
                metric=fact.get("metric") or None,
                value=_coerce_value(fact.get("value")),
                unit=fact.get("unit") or None,
                time=fact.get("time") or None,
                value_type=fact.get("value_type") or None,
            )
            for fact in item.get("key_facts", []) or []
            if isinstance(fact, dict) and str(fact.get("text", "")).strip()
        ]
        results.append(
            WebSearchResult(
                url=url,
                title=str(item.get("title", "")).strip(),
                source_type=item.get("source_type") or "other",
                summary=str(item.get("summary", "")).strip(),
                key_facts=key_facts,
                relevance=str(item.get("relevance", "")).strip(),
                evidence_depth="search_summary",
            )
        )
    return results


def execute_web_search(
    query: str,
    *,
    model_override: str | None = None,
    timeout_seconds: int = 30,
    max_urls: int = _DEFAULT_MAX_URLS_PER_QUERY,
) -> list[WebSearchResult]:
    """Run one query. Empty list on any failure or missing key — a search
    miss is not a crash; the router's own budget/loop logic decides what an
    empty round means.

    `max_urls` is both told to the model (fewer, stronger results requested)
    and enforced afterward in code (`_parse_results()[:max_urls]`) — the
    prompt alone is a request, not a guarantee, so a model that ignores it
    must not be able to blow up this call's cost or the accumulated
    `results` pool's size downstream in router.py."""
    query = query.strip()
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key or not query:
        return []

    # No `timeout=` kwarg here on purpose — see module docstring's "Timeout
    # handling" note. The client is free to take as long as it needs; only
    # how long we *wait* for it is bounded, by _run_with_timeout below.
    client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))

    def _call():
        return client.responses.create(
            model=_model(model_override),
            tools=[{"type": "web_search"}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            input=[
                {"role": "system", "content": _system_prompt(max_urls)},
                {"role": "user", "content": query},
            ],
        )

    status, payload = _run_with_timeout(_call, timeout_seconds)
    if status == "timeout":
        print(f"[source_router.web_search] search timed out after {timeout_seconds}s for {query!r}", file=sys.stderr)
        return []
    if status == "error":
        print(f"[source_router.web_search] search failed for {query!r}: {payload}", file=sys.stderr)
        return []
    response = payload
    grounded = _grounded_urls(response)
    text = getattr(response, "output_text", None) or ""
    return _parse_results(text, grounded)[:max_urls]
