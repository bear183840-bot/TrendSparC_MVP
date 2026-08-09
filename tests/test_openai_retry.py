"""Unit tests for sources/openai_retry.py — shared retry helpers used by
every sector analyzer. Previously untested; this file starts coverage with
call_with_truncation_retry (2026-08-10), added after a live pilot run showed
two sk_broadband documents lost entirely to a truncated (finish_reason ==
"length") analysis response with no retry at a higher token ceiling.
"""

from __future__ import annotations

import types

import pytest
from openai import APIConnectionError

from sources.openai_retry import call_with_retry, call_with_truncation_retry


def _response(finish_reason: str | None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(finish_reason=finish_reason)]
    )


def test_truncation_retry_returns_first_ceiling_when_not_truncated():
    calls: list[int] = []

    def make_call(max_tokens: int):
        calls.append(max_tokens)
        return _response("stop")

    response, used = call_with_truncation_retry(make_call, [4500, 7000])

    assert used == 4500
    assert calls == [4500]
    assert response.choices[0].finish_reason == "stop"


def test_truncation_retry_escalates_only_when_finish_reason_is_length():
    calls: list[int] = []

    def make_call(max_tokens: int):
        calls.append(max_tokens)
        return _response("length") if max_tokens == 4500 else _response("stop")

    response, used = call_with_truncation_retry(make_call, [4500, 7000])

    assert calls == [4500, 7000]
    assert used == 7000
    assert response.choices[0].finish_reason == "stop"


def test_truncation_retry_returns_last_response_when_still_truncated_at_ceiling():
    """No exception, no infinite escalation - the caller's existing JSON-
    parsing error handling is what decides what a still-truncated response
    means, unchanged from before this helper existed."""
    calls: list[int] = []

    def make_call(max_tokens: int):
        calls.append(max_tokens)
        return _response("length")

    response, used = call_with_truncation_retry(make_call, [4500, 7000])

    assert calls == [4500, 7000]
    assert used == 7000
    assert response.choices[0].finish_reason == "length"


def test_truncation_retry_does_not_escalate_a_malformed_but_complete_response():
    """A response that finishes normally (finish_reason != "length") but
    happens to be bad JSON is not this helper's concern - retrying it would
    only waste a call, since the same input would produce the same output."""
    calls: list[int] = []

    def make_call(max_tokens: int):
        calls.append(max_tokens)
        return _response("stop")

    _, used = call_with_truncation_retry(make_call, [4500, 7000])

    assert calls == [4500]
    assert used == 4500


def test_truncation_retry_single_rung_ladder_never_escalates():
    """sk_broadband's dense-content path already starts at the top ceiling -
    a one-element ladder means there is nowhere higher to go, matching
    behavior before this helper existed."""
    calls: list[int] = []

    def make_call(max_tokens: int):
        calls.append(max_tokens)
        return _response("length")

    response, used = call_with_truncation_retry(make_call, [7000])

    assert calls == [7000]
    assert used == 7000
    assert response.choices[0].finish_reason == "length"


def test_truncation_retry_still_retries_transient_errors_per_ceiling():
    """Each ceiling attempt still goes through call_with_retry - a
    transient connection error at one ceiling is retried, not mistaken for
    a truncation signal."""
    attempts = {"count": 0}

    def make_call(max_tokens: int):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise APIConnectionError(request=types.SimpleNamespace())
        return _response("stop")

    response, used = call_with_truncation_retry(
        make_call, [4500], base_delay_seconds=0
    )

    assert attempts["count"] == 2
    assert used == 4500
    assert response.choices[0].finish_reason == "stop"


def test_call_with_retry_reraises_non_retryable_errors_immediately():
    def make_call():
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        call_with_retry(make_call, base_delay_seconds=0)
