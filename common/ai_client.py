"""Optional per-stage escape hatch to an OpenAI-API-compatible alternative
provider (e.g. Upstage Solar, which serves its own models behind an
OpenAI-SDK-compatible endpoint at base_url="https://api.upstage.ai/v1").

Deliberately NOT a client-construction wrapper. Every AI call site still
constructs `OpenAI(...)` directly, by name, in its own module - that is what
keeps `monkeypatch.setattr(<module>, "OpenAI", ...)` working exactly as it
does today across every existing test. This only supplies one extra kwarg,
and only when the stage's own env var is actually set:

    client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))

When the env var is unset (the default, and every case in the test suite),
this returns {} and the call is byte-for-byte OpenAI(api_key=api_key) exactly
as before this module existed - switching providers is opt-in per stage,
never a behavior change for anyone who hasn't set the var.

The model name itself is a separate, already-existing per-stage env var
(each call site's own _MODEL_ENV_VAR) - the two are set together to actually
switch a stage to a different provider's model.
"""

from __future__ import annotations

import os


def openai_client_kwargs(base_url_env_var: str) -> dict[str, str]:
    """{"base_url": ...} if the given env var is set, else {}."""
    base_url = os.environ.get(base_url_env_var)
    return {"base_url": base_url} if base_url else {}


def resolve_model(
    model_env_var: str,
    base_url_env_var: str,
    *,
    default_openai_model: str,
    default_upstage_model: str = "solar-pro3",
) -> str:
    """The model name to request, matching whichever provider base_url
    actually points at.

    An explicit *_MODEL env var always wins. Otherwise an Upstage base_url
    (api.upstage.ai) selects `default_upstage_model`; anything else
    (including unset) selects `default_openai_model`. Without this, a stage
    whose model name is a bare hardcoded constant sends that literal name to
    whichever provider base_url points at regardless of whether that
    provider actually has a model by that name - live-verified 2026-08-11,
    sk_innovation's hardcoded "gpt-4o" sent to an Upstage base_url failed
    with Upstage's own "requested model is invalid" error, since gpt-4o
    isn't an Upstage model. sk_broadband already did this per-stage by hand;
    this is that same logic made shared so every stage gets it.
    """
    configured = os.environ.get(model_env_var)
    if configured:
        return configured
    base_url = os.environ.get(base_url_env_var, "")
    return default_upstage_model if "upstage.ai" in base_url else default_openai_model
