import json
import types

from common.contracts import SynthesisClaim, TrendSynthesis
from core.synthesis import ai_based as synthesis_ai_module
from core.synthesis.ai_based import refine_synthesis_ai


def _rule_based_result(
    highlights: list[str],
    doc_source_map: dict[str, str] | None = None,
    **kwargs,
) -> TrendSynthesis:
    return TrendSynthesis(
        request_id="req_test",
        sector_id="sk_hynix",
        highlights=highlights,
        synthesis_text=None,
        source_count=len(highlights),
        doc_source_map=doc_source_map or {},
        **kwargs,
    )


def _make_response(highlights, synthesis_text, refusal=None, claim_groups=None, contradictions=None):
    message = types.SimpleNamespace(
        content=json.dumps(
            {
                "highlights": highlights,
                "synthesis_text": synthesis_text,
                "claim_groups": claim_groups or [],
                "contradictions": contradictions or [],
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
    grounded_claim = SynthesisClaim(
        synthesis_claim_id="doc1:c1",
        claim_id="c1",
        claim_type="key_point",
        claim="검증된 주장",
        evidence_quote="검증된 원문",
        confidence="high",
        doc_id="doc1",
        source_id="출처1",
    )
    rule_based = _rule_based_result(
        ["점 A", "점 A와 같은 말", "점 B"],
        grounded_claims=[grounded_claim],
        covered_information_needs=["현황"],
    )

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result.highlights == ["요약된 핵심 포인트"]
    assert result.synthesis_text == "종합하면 이런 상황이다."
    # unrelated fields carried over unchanged from the rule-based result
    assert result.request_id == rule_based.request_id
    assert result.sector_id == rule_based.sector_id
    assert result.grounded_claims == [grounded_claim]
    assert result.covered_information_needs == ["현황"]


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


def test_corroborated_points_require_two_distinct_independent_sources(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(
        ["점 A"], "요약",
        claim_groups=[{"claim": "SK브로드밴드 IPTV 가입자 감소", "doc_ids": ["doc1", "doc2"]}],
    )
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(
        ["점 A", "점 B"], doc_source_map={"doc1": "전자신문", "doc2": "SK브로드밴드 뉴스룸"}
    )

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert len(result.corroborated_points) == 1
    assert result.corroborated_points[0].claim == "SK브로드밴드 IPTV 가입자 감소"
    assert set(result.corroborated_points[0].supporting_source_ids) == {"전자신문", "SK브로드밴드 뉴스룸"}
    assert result.uncorroborated_points == []


def test_same_source_two_documents_does_not_count_as_corroboration(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(
        ["점 A"], "요약",
        claim_groups=[{"claim": "SK브로드밴드 IPTV 가입자 감소", "doc_ids": ["doc1", "doc2"]}],
    )
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(
        ["점 A", "점 B"], doc_source_map={"doc1": "전자신문", "doc2": "전자신문"}
    )

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result.corroborated_points == []
    assert result.uncorroborated_points == ["SK브로드밴드 IPTV 가입자 감소"]


def test_claim_group_with_unknown_doc_id_only_is_ignored(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(
        ["점 A"], "요약",
        claim_groups=[{"claim": "존재하지 않는 문서 클레임", "doc_ids": ["doc_does_not_exist"]}],
    )
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(["점 A"], doc_source_map={"doc1": "전자신문"})

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result.corroborated_points == []
    assert result.uncorroborated_points == []  # no known doc_id backed it at all


def test_contradiction_with_unknown_doc_id_is_dropped(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(
        ["점 A"], "요약",
        contradictions=[
            {
                "topic": "가입자 수",
                "conflicting_claims": [
                    {"claim": "670만명", "doc_id": "doc1"},
                    {"claim": "700만명", "doc_id": "doc_does_not_exist"},
                ],
            }
        ],
    )
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(["점 A", "점 B"], doc_source_map={"doc1": "전자신문"})

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result.contradictions == []  # only 1 of 2 claims had a real doc_id -> whole item dropped


def test_contradiction_with_two_known_doc_ids_is_kept(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    response = _make_response(
        ["점 A"], "요약",
        contradictions=[
            {
                "topic": "가입자 수",
                "conflicting_claims": [
                    {"claim": "670만명", "doc_id": "doc1"},
                    {"claim": "700만명", "doc_id": "doc2"},
                ],
            }
        ],
    )
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    rule_based = _rule_based_result(
        ["점 A", "점 B"], doc_source_map={"doc1": "전자신문", "doc2": "SK브로드밴드 뉴스룸"}
    )

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert len(result.contradictions) == 1
    assert result.contradictions[0].topic == "가입자 수"
    assert len(result.contradictions[0].conflicting_claims) == 2
    assert result.contradictions[0].conflicting_claims[0].source_id == "전자신문"


def test_new_synthesis_fields_stay_empty_when_ai_refinement_fails(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_SYNTHESIS_AI_API_KEY", "test-key")
    monkeypatch.setattr(synthesis_ai_module, "OpenAI", _ErroringOpenAI)
    rule_based = _rule_based_result(["점 A", "점 B"], doc_source_map={"doc1": "전자신문"})

    result = refine_synthesis_ai(rule_based, "테스트 질문")

    assert result.corroborated_points == []
    assert result.uncorroborated_points == []
    assert result.contradictions == []
    assert result.doc_source_map == {"doc1": "전자신문"}  # unchanged rule-based data preserved
