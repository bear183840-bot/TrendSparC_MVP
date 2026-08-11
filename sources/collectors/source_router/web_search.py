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
completion. This module used to wait on it in a daemon thread and simply stop
*waiting* after timeout_seconds, which kept a slow-but-fine search from being
severed mid-flight - but an abandoned request is still a billed request, and
nothing stopped it from running to completion in the background.

The client now takes a real `timeout=` and `max_retries=0`: the timeout
closes the in-flight request rather than orphaning it, and no automatic retry
can silently double the cost of a call we already decided to give up on. The
timeout itself is generous (config.call_timeout_seconds) precisely because
this call shape is slow.
"""

from __future__ import annotations

import json
import os
import re
import sys

from openai import APIConnectionError, APITimeoutError, OpenAI

from common.ai_client import openai_client_kwargs
from sources.collectors.source_router.contracts import KeyFact, WebSearchResult

_API_KEY_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_MODEL"
_BASE_URL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_BASE_URL"
_DEFAULT_MODEL = "gpt-5-mini"

_DEFAULT_MAX_URLS_PER_QUERY = 2


class WebSearchTimeoutError(Exception):
    """Raised only when the call timed out, never for any other failure.

    A genuine zero-result search and a timed-out search both used to look
    identical to the caller (both returned `[]`) - `_run_queries()` needs to
    tell them apart so it can retry a *timed-out* direct query once with a
    simplified query, without treating an ordinary empty result the same
    way (retrying a query that legitimately found nothing would just waste
    another call)."""


def is_configured() -> bool:
    return bool(os.environ.get(_API_KEY_ENV_VAR, "").strip())


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


def _coerce_value_type(raw) -> str | None:
    """Keep malformed model labels from invalidating an entire search round.

    ``reported`` describes provenance, not a projection state, so it maps to
    the contract's evidence-stated ``actual`` value. Unknown labels are
    omitted rather than guessed.
    """
    normalized = str(raw or "").strip().casefold()
    if normalized == "reported":
        return "actual"
    return normalized if normalized in {"actual", "estimate", "forecast", "target", "guidance"} else None


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
                value_type=_coerce_value_type(fact.get("value_type")),
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
    """Run one query. Empty list on any failure or missing key, EXCEPT a
    timeout — a search miss is not a crash; the router's own budget/loop
    logic decides what an empty round means. A timeout raises
    `WebSearchTimeoutError` instead of returning `[]`, because `_run_queries()`
    treats a timed-out direct query differently from one that genuinely
    found nothing (see that class's docstring).

    `max_urls` is both told to the model (fewer, stronger results requested)
    and enforced afterward in code (`_parse_results()[:max_urls]`) — the
    prompt alone is a request, not a guarantee, so a model that ignores it
    must not be able to blow up this call's cost or the accumulated
    `results` pool's size downstream in router.py."""
    query = query.strip()
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key or not query:
        return []

    try:
        client = OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
            **openai_client_kwargs(_BASE_URL_ENV_VAR),
        )
        response = client.responses.create(
            model=_model(model_override),
            tools=[{"type": "web_search"}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            input=[
                {"role": "system", "content": _system_prompt(max_urls)},
                {"role": "user", "content": query},
            ],
        )
    except (APITimeoutError, APIConnectionError) as exc:
        print(f"[source_router.web_search] search TIMED OUT for {query!r}: {exc}", file=sys.stderr)
        raise WebSearchTimeoutError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - one query must not abort the router
        print(f"[source_router.web_search] search failed for {query!r}: {exc}", file=sys.stderr)
        return []
    grounded = _grounded_urls(response)
    text = getattr(response, "output_text", None) or ""
    return _parse_results(text, grounded)[:max_urls]
