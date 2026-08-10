"""Shared retry wrapper for OpenAI calls used by every sector analyzer.

A 429 rate-limit response is transient - OpenAI's own error message usually
carries a sub-second retry hint (e.g. "Please try again in 228ms") - so one
rate-limited document shouldn't discard an entire analysis run's already
-collected documents and force a full, costly re-run. This retries only
rate limits and transient connection/server errors with exponential
backoff; a genuine bad request, auth failure, or refusal still raises
immediately since retrying those would never succeed.
"""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

T = TypeVar("T")

_RETRYABLE_ERRORS = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 1.0,
) -> T:
    """Call `fn`, retrying transient OpenAI errors with exponential backoff.

    Re-raises the last error once `max_attempts` is exhausted, or
    immediately for any non-retryable error.
    """

    for attempt in range(max_attempts):
        try:
            return fn()
        except _RETRYABLE_ERRORS:
            if attempt == max_attempts - 1:
                raise
            time.sleep(base_delay_seconds * (2**attempt))
    raise AssertionError("unreachable: loop always returns or raises")


def call_with_truncation_retry(
    make_call: Callable[[int], T],
    token_ceilings: list[int],
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 1.0,
) -> tuple[T, int]:
    """Escalate max_tokens only when a completed call was actually cut off.

    A structured-output analysis call can be genuinely too long for its
    token ceiling - live-verified 2026-08-10: two sk_broadband documents
    each returned response.choices[0].finish_reason == "length" at the
    4,500-token ceiling, producing an unparseable truncated JSON, and the
    whole document was silently skipped rather than retried. Pre-call
    density heuristics (e.g. counting explicit figures) can't catch every
    case - a document heavy in comparison entries rather than numbers can
    still overflow a "normal" ceiling. Detecting the actual overflow after
    the fact and escalating is more robust than guessing better upfront.

    `finish_reason == "length"` is the only trigger - a malformed-but-
    complete response (bad schema, hallucinated field) would fail the same
    way on a retry, so retrying it would only waste a call; that case is
    left to the caller's existing JSON-parsing error handling, unchanged.

    Each ceiling in `token_ceilings` is tried in order, largest last; each
    individual attempt still goes through `call_with_retry` for the usual
    transient-error resilience. Returns `(response, ceiling_used)` so the
    caller can log what ceiling actually produced the final response,
    rather than only the first one that was requested.
    """
    response: T | None = None
    for ceiling in token_ceilings:
        response = call_with_retry(
            lambda ceiling=ceiling: make_call(ceiling),
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
        )
        if getattr(response.choices[0], "finish_reason", None) != "length":
            return response, ceiling
    return response, token_ceilings[-1]
