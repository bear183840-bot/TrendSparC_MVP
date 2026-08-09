"""Small, provider-neutral telemetry for AI request budgets.

Only sizes, token counts, and outcomes are logged. Prompt text, document text,
API keys, and URLs are deliberately excluded so this can stay enabled in
normal runs without copying evidence or secrets into logs.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _usage_value(usage: Any, name: str) -> int | None:
    if usage is None:
        return None
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    return value if isinstance(value, int) else None


def emit_ai_usage(
    *,
    stage: str,
    model: str,
    system_content: str,
    user_content: str,
    schema: dict[str, Any] | None,
    requested_max_tokens: int,
    response: Any | None = None,
    outcome: str = "ok",
    error_type: str | None = None,
    counts: dict[str, int] | None = None,
) -> None:
    """Write one compact JSON record to stderr.

    OpenAI-compatible providers do not all expose token usage in exactly the
    same object shape, so missing usage is recorded as null rather than
    guessed from characters.
    """
    usage = getattr(response, "usage", None) if response is not None else None
    choices = getattr(response, "choices", None) if response is not None else None
    finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
    record = {
        "stage": stage,
        "model": model,
        "outcome": outcome,
        "system_chars": len(system_content),
        "user_chars": len(user_content),
        "schema_chars": len(json.dumps(schema, ensure_ascii=False)) if schema else 0,
        "requested_max_tokens": requested_max_tokens,
        "prompt_tokens": _usage_value(usage, "prompt_tokens"),
        "completion_tokens": _usage_value(usage, "completion_tokens"),
        "total_tokens": _usage_value(usage, "total_tokens"),
        # finish_reason == "length" means the response was cut off at
        # requested_max_tokens - the direct signal call_with_truncation_retry
        # (sources/openai_retry.py) acts on, surfaced here so a still-
        # truncated response is visible from the log alone, without having
        # to compare completion_tokens to requested_max_tokens by hand.
        "finish_reason": finish_reason,
    }
    if error_type:
        record["error_type"] = error_type
    if counts:
        record["counts"] = counts
    print(f"[ai-usage] {json.dumps(record, ensure_ascii=False, separators=(',', ':'))}", file=sys.stderr)
