import json
import types

from common.contracts import EntityExtractionResult, SectorProfile, UserRequest
from core.entity import ai_based as entity_ai_module
from core.entity.ai_based import extract_entities_ai
from core.entity.extractor import extract_entities


def _rule_based_result(request_id: str) -> EntityExtractionResult:
    return EntityExtractionResult(
        request_id=request_id,
        primary_intent="current_status",
        perspective="company_update",
        organizations=["rule-based-org"],
        technologies=["rule-based-tech"],
        keywords=["rule-based-keyword"],
    )


def _make_response(
    primary_intent,
    organizations,
    technologies,
    keywords,
    refusal=None,
    perspective="company_update",
    sector_id="general",
    routing_confidence="medium",
):
    message = types.SimpleNamespace(
        content=json.dumps(
            {
                "primary_intent": primary_intent,
                "perspective": perspective,
                "organizations": organizations,
                "technologies": technologies,
                "keywords": keywords,
                "sector_id": sector_id,
                "routing_confidence": routing_confidence,
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

    assert result.primary_intent == rule_based.primary_intent
    assert result.organizations == rule_based.organizations
    assert result.extraction_method == "rule_fallback"
    assert "not configured" in result.extraction_error


def test_uses_ai_output_when_api_key_configured(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response(
        "future_business", ["SK하이닉스"], ["HBM"], ["HBM", "메모리 시장", "수요 전망"], perspective="market_landscape"
    )
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result.primary_intent == "future_business"
    assert result.perspective == "market_landscape"
    assert result.organizations == ["SK하이닉스"]
    assert result.technologies == ["HBM"]
    assert result.keywords == ["메모리 시장", "수요 전망"]
    assert result.sector_id == "general"
    assert result.routing_confidence == "medium"
    assert result.extraction_method == "ai"


def test_ai_prompt_explicitly_handles_dirty_language_and_general(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response("current_status", [], [], [], sector_id="general", routing_confidence="high")
    captured = {}

    class CapturingCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return response

    fake = _FakeOpenAI(response)
    fake.chat.completions = CapturingCompletions()
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: fake)

    request = UserRequest(request_id="req_prompt", question="오늘 점심 뭐먹지")
    extract_entities_ai(request, _rule_based_result(request.request_id))

    prompt = captured["messages"][0]["content"]
    assert "typos" in prompt
    assert "Never ask a follow-up question" in prompt
    assert 'sector_id="general"' in prompt
    assert '"우리"' in prompt
    assert "Do not invent a named competitor" in prompt
    assert "business performance" in prompt
    assert "canonical company/business name" in prompt
    schema = captured["response_format"]["json_schema"]["schema"]
    assert "general" in schema["properties"]["sector_id"]["enum"]


def test_falls_back_to_rule_based_on_api_failure(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    monkeypatch.setattr(entity_ai_module, "OpenAI", _ErroringOpenAI)

    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result.organizations == rule_based.organizations
    assert result.extraction_method == "rule_fallback"
    assert "simulated API failure" in result.extraction_error


def test_falls_back_to_rule_based_on_refusal(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response("current_status", [], [], [], refusal="cannot help with that")
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    request = UserRequest(request_id="req_test", question="SK하이닉스 HBM 시장 전망은?")
    rule_based = _rule_based_result(request.request_id)

    result = extract_entities_ai(request, rule_based)

    assert result.organizations == rule_based.organizations
    assert result.extraction_method == "rule_fallback"
    assert "cannot help" in result.extraction_error


def test_ai_cannot_erase_explicit_colloquial_comparison_signal(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response(
        "current_status", [], ["HBM4"], ["개발 현황"], perspective="company_update"
    )
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))
    request = UserRequest(request_id="req_compare", question="HBM4 다른 기업들은 어디까지 왔어?")
    rule_based = extract_entities(request)

    result = extract_entities_ai(request, rule_based)

    assert result.perspective == "competitor_comparison"


def test_explicit_sector_selection_overrides_a_wrong_ai_guess(monkeypatch):
    # Live-observed bug: a bare self-reference question ("우리회사") with the
    # sector already explicitly selected in the UI still let the model guess a
    # completely different SK affiliate. The UI selection must win regardless
    # of what the model returns.
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response(
        "current_status",
        [],  # model returned no organizations at all
        [],
        ["실적", "영업이익"],
        sector_id="sk_innovation",  # model guessed the wrong affiliate entirely
        perspective="company_update",
    )
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    profiles = {
        "sk_broadband": SectorProfile(
            sector_id="sk_broadband",
            display_name="SK브로드밴드 (SK Broadband)",
            status="active",
            canonical_name="SK브로드밴드",
            aliases=["SK Broadband", "SKB", "SK브로드밴드"],
        ),
    }
    request = UserRequest(request_id="req_override", question="요즘 우리회사 어때")

    result = extract_entities_ai(request, None, profiles, "sk_broadband")

    assert result.sector_id == "sk_broadband"
    assert result.organizations == ["SK브로드밴드"]


def test_ai_reclassifies_a_registered_brand_that_leaked_into_keywords(monkeypatch):
    # Live-observed bug (CLAUDE.md): the model puts named brands/products
    # like "OK캐쉬백"/"Syrup" into the generic keywords field instead of
    # organizations/technologies. Both are already registered as sk_planet
    # aliases, so this should be caught deterministically regardless of what
    # the model itself decided.
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response(
        "current_status",
        [],
        [],
        ["OK캐쉬백", "Syrup", "포인트 마케팅"],
        sector_id="sk_planet",
        perspective="company_update",
    )
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    profiles = {
        "sk_planet": SectorProfile(
            sector_id="sk_planet",
            display_name="SK플래닛 (SK Planet)",
            status="active",
            canonical_name="SK플래닛",
            aliases=["SK Planet", "SK플래닛", "OK캐쉬백", "Syrup", "시럽"],
        ),
    }
    request = UserRequest(request_id="req_brand", question="OK캐쉬백 시럽 포인트 마케팅 시장 현황은?")

    result = extract_entities_ai(request, None, profiles, "sk_planet")

    assert set(result.technologies) == {"OK캐쉬백", "Syrup"}
    assert result.keywords == ["포인트 마케팅"]


def test_ai_reclassifies_the_canonical_name_itself_into_organizations(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response(
        "current_status",
        [],
        [],
        ["SK플래닛", "실적"],
        sector_id="sk_planet",
        perspective="company_update",
    )
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    profiles = {
        "sk_planet": SectorProfile(
            sector_id="sk_planet",
            display_name="SK플래닛 (SK Planet)",
            status="active",
            canonical_name="SK플래닛",
            aliases=["SK Planet", "SK플래닛"],
        ),
    }
    request = UserRequest(request_id="req_canonical", question="SK플래닛 실적 어때")

    result = extract_entities_ai(request, None, profiles, "sk_planet")

    assert result.organizations == ["SK플래닛"]
    assert result.keywords == ["실적"]


def test_entity_ai_model_defaults_to_gpt4o_and_respects_env_override(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    monkeypatch.delenv("TRENDSPARC_ENTITY_AI_MODEL", raising=False)
    response = _make_response("current_status", [], [], [])
    captured = {}

    class CapturingCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return response

    fake = _FakeOpenAI(response)
    fake.chat.completions = CapturingCompletions()
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: fake)

    request = UserRequest(request_id="req_model", question="SK하이닉스 HBM 시장 전망은?")
    extract_entities_ai(request, _rule_based_result(request.request_id))

    assert captured["model"] == "gpt-4o"

    captured.clear()
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_MODEL", "gpt-4o-mini")
    extract_entities_ai(request, _rule_based_result(request.request_id))

    assert captured["model"] == "gpt-4o-mini"


def test_entity_ai_passes_base_url_to_the_client_only_when_the_env_var_is_set(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response("current_status", [], [], [])
    captured = {}

    def fake_openai_ctor(**kwargs):
        captured.update(kwargs)
        return _FakeOpenAI(response)

    monkeypatch.setattr(entity_ai_module, "OpenAI", fake_openai_ctor)
    request = UserRequest(request_id="req_base_url", question="테스트 질문")

    monkeypatch.delenv("TRENDSPARC_ENTITY_AI_BASE_URL", raising=False)
    extract_entities_ai(request, _rule_based_result(request.request_id))
    assert "base_url" not in captured

    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_BASE_URL", "https://api.upstage.ai/v1")
    extract_entities_ai(request, _rule_based_result(request.request_id))
    assert captured["base_url"] == "https://api.upstage.ai/v1"
    assert captured["api_key"] == "test-key"


def test_ai_removes_keywords_that_duplicate_canonical_entities(monkeypatch):
    monkeypatch.setenv("TRENDSPARC_ENTITY_AI_API_KEY", "test-key")
    response = _make_response(
        "current_status",
        ["SK브로드밴드"],
        [],
        ["브로드밴드", "매출", "사업 현황"],
        sector_id="sk_broadband",
        perspective="company_update",
    )
    monkeypatch.setattr(entity_ai_module, "OpenAI", lambda api_key: _FakeOpenAI(response))

    request = UserRequest(request_id="req_dedupe", question="요즘 브로드밴드 매출 어때")
    result = extract_entities_ai(request, None)

    assert result.organizations == ["SK브로드밴드"]
    assert result.keywords == ["매출", "사업 현황"]
