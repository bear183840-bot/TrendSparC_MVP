from common.ai_client import openai_client_kwargs


def test_openai_client_kwargs_empty_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_ENTITY_AI_BASE_URL", raising=False)

    assert openai_client_kwargs("TRENDSPARC_ENTITY_AI_BASE_URL") == {}


def test_openai_client_kwargs_carries_base_url_when_set(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_BASE_URL", "https://api.upstage.ai/v1")

    assert openai_client_kwargs("TRENDSPARC_ENTITY_AI_BASE_URL") == {
        "base_url": "https://api.upstage.ai/v1"
    }


def test_openai_client_kwargs_treats_empty_string_as_unset(monkeypatch):
    # A .env file with a trailing `KEY=` (no value) sets the var to "", not
    # absent - must behave the same as unset, not send base_url="" to the SDK.
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_BASE_URL", "")

    assert openai_client_kwargs("TRENDSPARC_ENTITY_AI_BASE_URL") == {}
