"""GPT-5 mini + web_search — search execution only, doc1 §5.

Deliberately does no judgment (no sufficiency/gap reasoning) — that split is
the core architectural difference from sources/collectors/ai_search_harness.py,
whose single round call both searches and judges. Only tool-grounded URLs
(url_citation annotations or web_search_call.action.sources) are trusted;
a URL the model's JSON reply invents without tool backing is dropped —
same hallucination guard as ai_search_harness.py's _grounded_candidates,
reimplemented locally so this package stays self-contained.
"""

from __future__ import annotations

import json
import os
import re
import sys

from openai import OpenAI

from common.ai_client import openai_client_kwargs
from sources.collectors.source_router.contracts import KeyFact, WebSearchResult

_API_KEY_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_MODEL"
_BASE_URL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_SEARCH_BASE_URL"
_DEFAULT_MODEL = "gpt-5-mini"

_SYSTEM_PROMPT = (
    "You are a web search executor. Use the web_search tool to find "
    "evidence for the given query. Only report URLs actually retrieved "
    "through the tool - never fabricate a URL, title, date, or fact. After "
    "searching, reply with exactly one JSON array on its own line, one "
    "object per distinct URL you found, shaped as: "
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
                value=fact.get("value"),
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
    query: str, *, model_override: str | None = None, timeout_seconds: int = 30
) -> list[WebSearchResult]:
    """Run one query. Empty list on any failure or missing key — a search
    miss is not a crash; the router's own budget/loop logic decides what an
    empty round means."""
    query = query.strip()
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key or not query:
        return []
    try:
        client = OpenAI(
            api_key=api_key, timeout=timeout_seconds, **openai_client_kwargs(_BASE_URL_ENV_VAR)
        )
        response = client.responses.create(
            model=_model(model_override),
            tools=[{"type": "web_search"}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.web_search] search failed for {query!r}: {exc}", file=sys.stderr)
        return []
    grounded = _grounded_urls(response)
    text = getattr(response, "output_text", None) or ""
    return _parse_results(text, grounded)
