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
