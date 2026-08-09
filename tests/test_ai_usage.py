import json
import types

from common.ai_usage import emit_ai_usage


def test_ai_usage_logs_sizes_and_provider_usage_without_prompt_text(capsys):
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(prompt_tokens=123, completion_tokens=45, total_tokens=168)
    )

    emit_ai_usage(
        stage="entity",
        model="solar-pro3",
        system_content="secret system prompt",
        user_content="secret user question",
        schema={"type": "object"},
        requested_max_tokens=500,
        response=response,
        counts={"keywords": 3},
    )

    line = capsys.readouterr().err.removeprefix("[ai-usage] ")
    record = json.loads(line)
    assert record["prompt_tokens"] == 123
    assert record["total_tokens"] == 168
    assert record["system_chars"] == len("secret system prompt")
    assert record["counts"] == {"keywords": 3}
    assert "secret" not in line


def test_ai_usage_logs_finish_reason_from_response_choices(capsys):
    """2026-08-10: added so a truncated response (finish_reason == "length")
    is visible directly from the log, without comparing completion_tokens to
    requested_max_tokens by hand - see call_with_truncation_retry."""
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=4500, total_tokens=4501),
        choices=[types.SimpleNamespace(finish_reason="length")],
    )

    emit_ai_usage(
        stage="sectors.sk_broadband.adapter.analyzer",
        model="solar-pro3",
        system_content="s",
        user_content="u",
        schema=None,
        requested_max_tokens=4500,
        response=response,
        outcome="invalid_response",
    )

    record = json.loads(capsys.readouterr().err.removeprefix("[ai-usage] "))
    assert record["finish_reason"] == "length"


def test_ai_usage_finish_reason_none_when_response_has_no_choices(capsys):
    response = types.SimpleNamespace(usage=None)
    # No `choices` attribute at all - must not raise (missing usage already
    # tolerated the same way, see test_ai_usage_accepts_missing_usage below).
    emit_ai_usage(
        stage="entity", model="m", system_content="s", user_content="u",
        schema=None, requested_max_tokens=1, response=response,
    )

    record = json.loads(capsys.readouterr().err.removeprefix("[ai-usage] "))
    assert record["finish_reason"] is None


def test_ai_usage_accepts_missing_usage(capsys):
    emit_ai_usage(
        stage="synthesis",
        model="solar-pro3",
        system_content="system",
        user_content="user",
        schema=None,
        requested_max_tokens=1500,
        outcome="failed",
        error_type="ValueError",
    )

    record = json.loads(capsys.readouterr().err.removeprefix("[ai-usage] "))
    assert record["prompt_tokens"] is None
    assert record["outcome"] == "failed"
    assert record["error_type"] == "ValueError"
