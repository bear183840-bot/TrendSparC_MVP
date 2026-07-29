import json
import types

from common.contracts import EntityExtractionResult, UserRequest
from core.entity import ai_based as entity_ai_module
from core.entity.ai_based import extract_entities_ai


def _rule_based_result(request_id: str) -> EntityExtractionResult:
    return EntityExtractionResult(
        request_id=request_id,
        primary_intent="current_status",
        organizations=["rule-based-org"],
        technologies=["rule-based-tech"],
        keywords=["rule-based-keyword"],
    )


def _make_response(primary_intent, organizations, technologies, keywords, refusal=None):
    message = types.SimpleNamespace(
        content=json.dumps(
            {
                "primary_intent": primary_intent,
                "organizations": organizations,
                "technologies": technologies,
                "keywords": keywords,
            }
        ),
        refusal=refusal,
    )
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class _FakeCompletions:
    def __init__(self, response):
        self._response = response

    def create(self, **kwargs):
        return self._response


class _FakeChat:
    def __init__(self, response):
        self.completions = _FakeCompletions(response)


class _FakeOpenAI:
    def __init__(self, response):
        self.chat = _FakeChat(response)


class _ErroringOpenAI:
    def __init__(self, api_key):
        raise RuntimeError("simulated API failure")


def test_falls_back_to_rule_based_when_no_api_key(monkeypatch):
    monkeypatch.delenv("TRENDSPARC_ENTITY_AI_API_KEY", raising=False)
    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result == rule_based


def test_uses_ai_output_when_api_key_configured(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response("future_business", ["SK하이닉스"], ["HBM"], ["HBM", "메모리 시장", "수요 전망"])
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result.primary_intent == "future_business"
    assert result.organizations == ["SK하이닉스"]
    assert result.technologies == ["HBM"]
    assert result.keywords == ["HBM", "메모리 시장", "수요 전망"]


def test_falls_back_to_rule_based_on_api_failure(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    monkeypatch.setattr(entity_ai_module, "OpenAI", _ErroringOpenAI)

    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result == rule_based


def test_falls_back_to_rule_based_on_refusal(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response("current_status", [], [], [], refusal="cannot help with that")
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result == rule_based
