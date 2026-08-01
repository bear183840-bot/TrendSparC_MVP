import json
import types

import pytest

from common.contracts import SourceDocument
from common.errors import PipelineStageError
from sectors.sk_hynix.adapter import analyzer as analyzer_module
from sectors.sk_hynix.adapter.analyzer import analyze


def _document() -> SourceDocument:
    return SourceDocument(
        doc_id="doc_1",
        source_id="SK하이닉스 뉴스룸",
        title="테스트 기사",
        url="https://example.com/article",
        content="테스트 기사 본문입니다.",
    )


def _make_response(
    summary,
    key_points,
    sentiment,
    relevant_to_question,
    refusal=None,
    business_impact="",
    risk="",
    opportunity="",
    recommended_actions=None,
    monitoring_indicators=None,
    evidence=None,
    action_level="insufficient_data",
    analysis_confidence="low",
):
    # Mirrors the real OpenAI Structured Outputs contract: _ANALYSIS_SCHEMA
    # marks all 12 fields "required" with strict=True, so a real response
    # always includes them — the test fixture must too, or _analyze_document's
    # data["field"] indexing raises KeyError before the test's actual
    # assertion is even reached.
    message = types.SimpleNamespace(
        content=json.dumps(
            {
                "summary": summary,
                "key_points": key_points,
                "sentiment": sentiment,
                "relevant_to_question": relevant_to_question,
                "business_impact": business_impact,
                "risk": risk,
                "opportunity": opportunity,
                "recommended_actions": recommended_actions or [],
                "monitoring_indicators": monitoring_indicators or [],
                "evidence": evidence or [],
                "action_level": action_level,
                "analysis_confidence": analysis_confidence,
            }
        ),
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


class _ErroringCompletions:
    def create(self, **kwargs):
        raise RuntimeError("simulated API failure")


class _ErroringChat:
    def __init__(self):
        self.completions = _ErroringCompletions()


class _ErroringOpenAI:
    def __init__(self, api_key):
        # analyze()'s `client = OpenAI(api_key=api_key)` isn't wrapped in a
        # try/except (only the .create() call inside _analyze_document is),
        # matching the real openai.OpenAI class — constructing it never makes
        # a network call, only an actual request can fail.
        self.chat = _ErroringChat()


def test_question_text_is_included_in_the_prompt_sent_to_the_model(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY", "test-key")
    response = _make_response("요약", ["포인트"], "neutral", True)
    fake_openai = _FakeOpenAI(response)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: fake_openai)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    analyze([_document()], "SK하이닉스 HBM 시장 전망은?")

    sent_messages = fake_openai.chat.completions.last_kwargs["messages"]
    user_message = next(m["content"] for m in sent_messages if m["role"] == "user")
    assert "SK하이닉스 HBM 시장 전망은?" in user_message


def test_relevant_document_is_parsed_correctly(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY", "test-key")
    response = _make_response("요약", ["포인트 1", "포인트 2"], "positive", True)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([_document()], "SK하이닉스 HBM 시장 전망은?")

    assert len(result) == 1
    assert result[0].relevant_to_question is True
    assert result[0].summary == "요약"
    assert result[0].key_points == ["포인트 1", "포인트 2"]


def test_irrelevant_document_is_still_returned_with_flag_set_false(monkeypatch):
    # analyze() itself doesn't drop anything — filtering happens centrally in
    # core/request_pipeline/pipeline.py, so the flag must survive intact here.
    monkeypatch.setenv("TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY", "test-key")
    response = _make_response("무관한 기사", [], "neutral", False)
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    result = analyze([_document()], "SK하이닉스 HBM 시장 전망은?")

    assert len(result) == 1
    assert result[0].relevant_to_question is False


def test_api_failure_still_raises_pipeline_stage_error(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY", "test-key")
    monkeypatch.setattr(analyzer_module, "OpenAI", _ErroringOpenAI)
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    with pytest.raises(PipelineStageError):
        analyze([_document()], "SK하이닉스 HBM 시장 전망은?")


def test_refusal_still_raises_pipeline_stage_error(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY", "test-key")
    response = _make_response("요약", [], "neutral", True, refusal="cannot help with that")
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "system prompt")

    with pytest.raises(PipelineStageError):
        analyze([_document()], "SK하이닉스 HBM 시장 전망은?")
