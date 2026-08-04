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
