"""Shared "Solar Pro 3" JSON-chat helper.

doc1 assigns Search Planning, Coverage/Gap Check, and PDF Section/Chunk
Selection all to the same model role ("Solar Pro 3") — this module is the one
place that resolves the API key/model/base_url and makes the call, so
planner.py, coverage.py, and pdf_parser.py's selection functions share one
env-var surface and one fallback behavior instead of four copies of it.

Uses the same escape-hatch pattern as the rest of this repo
(common/ai_client.py's openai_client_kwargs) so pointing this role at Upstage
Solar is just setting TRENDSPARC_SOURCE_ROUTER_PLANNER_BASE_URL, exactly like
every other AI-calling stage.

Every caller must have its own deterministic fallback for `call_json`
returning None (missing key, call failure, bad JSON) — this module never
raises out of `call_json`, matching the repo-wide silent-fallback contract
(core/entity/ai_based.py, core/synthesis/ai_based.py).

*** Timeout handling ***
This module backs all 5 "Solar Pro 3" role call sites (planner, coverage's
check_coverage/verify_evidence, pdf_parser's select_sections/select_chunks) -
including check_coverage(), which resends the accumulated results pool every
round and is the largest-payload call in the router.

It went through both extremes. A hard client timeout that was too short
killed calls that would have succeeded; waiting in a background thread
instead never severed anything, but an abandoned request is still a billed
request and nothing stopped it running to completion unheard. What it uses
now is a real `timeout=` that is *generous* (config.call_timeout_seconds),
plus `max_retries=0` so a call we already gave up on cannot be billed twice
behind the router's own budget policy.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from openai import OpenAI

from common.ai_client import openai_client_kwargs

API_KEY_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_PLANNER_API_KEY"
MODEL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_PLANNER_MODEL"
BASE_URL_ENV_VAR = "TRENDSPARC_SOURCE_ROUTER_PLANNER_BASE_URL"
_DEFAULT_UPSTAGE_MODEL = "solar-pro3"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def api_key() -> str:
    return os.environ.get(API_KEY_ENV_VAR, "").strip()


def model() -> str:
    override = os.environ.get(MODEL_ENV_VAR, "").strip()
    if override:
        return override
    if os.environ.get(BASE_URL_ENV_VAR, "").strip():
        return _DEFAULT_UPSTAGE_MODEL
    return _DEFAULT_OPENAI_MODEL


def call_json(
    system_prompt: str,
    payload: dict[str, Any],
    *,
    caller: str,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any] | None:
    """One JSON-mode chat completion. Returns None on missing key, call
    failure, or unparsable JSON — never raises."""
    key = api_key()
    if not key:
        return None
    try:
        # The SDK/httpx timeout closes the in-flight request; the earlier
        # daemon-thread version only stopped waiting while the paid call kept
        # running. max_retries=0 keeps a timed-out request from being billed
        # again behind the router's own budget policy. Client construction
        # stays inside this try/except because a bad base_url/kwarg
        # combination raises here, before there is a call to time-box.
        client = OpenAI(
            api_key=key,
            timeout=timeout_seconds,
            max_retries=0,
            **openai_client_kwargs(BASE_URL_ENV_VAR),
        )
        response = client.chat.completions.create(
            model=model_override or model(),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        print(f"[source_router.{caller}] Solar call failed, falling back: {exc}", file=sys.stderr)
        return None
