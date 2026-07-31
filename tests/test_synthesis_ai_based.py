import json
import types

from common.contracts import TrendSynthesis
from core.synthesis import ai_based as synthesis_ai_module
from core.synthesis.ai_based import refine_synthesis_ai


def _rule_based_result(highlights: list[str]) -> TrendSynthesis:
    return TrendSynthesis(
        request_id="req_test",
        sector_id="sk_hynix",
        highlights=highlights,
        synthesis_text=None,
        source_count=len(highlights),
    )


def _make_response(highlights, synthesis_text, refusal=None):
    message = types.SimpleNamespace(
        content=json.dumps({"highlights": highlights, "synthesis_text": synthesis_text}),
        refusal=refusal,
    )
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class _FakeCompletions:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
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
    monkeypatch.delenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", raising=False)
    rule_based = _rule_based_result(["점 A", "점 B"])

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result == rule_based


def test_skips_api_call_when_no_highlights_to_refine(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", _ErroringOpenAI)  # would raise if ever called
    rule_based = _rule_based_result([])

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result == rule_based


def test_uses_ai_output_when_api_key_configured(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(["요약된 핵심 포인트"], "종합하면 이런 상황이다.")
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(["점 A", "점 A와 같은 말", "점 B"])

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result.highlights == ["요약된 핵심 포인트"]
    assert result.synthesis_text == "종합하면 이런 상황이다."
    # unrelated fields carried over unchanged from the rule-based result
    assert result.request_id == rule_based.request_id
    assert result.sector_id == rule_based.sector_id


def test_falls_back_to_rule_based_on_api_failure(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", _ErroringOpenAI)
    rule_based = _rule_based_result(["점 A", "점 B"])

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result == rule_based


def test_question_text_is_included_in_the_prompt_sent_to_the_model(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(["요약된 핵심 포인트"], "종합하면 이런 상황이다.")
    fake_openai = _FakeOpenAI(response)
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: fake_openai)
    rule_based = _rule_based_result(["점 A", "점 B"])

    refine_synthesis_ai(rule_based, "SKT AI 데이터센터 투자 현황은?")

    sent_messages = fake_openai.chat.completions.last_kwargs["messages"]
    user_message = next(m["content"] for m in sent_messages if m["role"] == "user")
    assert "SKT AI 데이터센터 투자 현황은?" in user_message


def test_falls_back_to_rule_based_on_refusal(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response([], "", refusal="cannot help with that")
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(["점 A", "점 B"])

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result == rule_based
