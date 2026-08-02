import pytest

from common.contracts import EntityExtractionResult, UserRequest
from common.errors import StageStatus
from core.request_pipeline import pipeline as pipeline_module
from core.request_pipeline.pipeline import run_pipeline


CASES = [
    ("하이닉스 hbm 요즘 어떰?", "sk_hynix"),
    (
        "요즘 회사에서 자꾸 AI 데이터센터 얘기 나오는데 SKT가 하는거 "
        "잘되고있나요 갑자기 궁금해서요",
        "sk_telecom",
    ),
    ("오케캐시백 시럽 요새 반응 어떰", "sk_planet"),
    ("sk온 배터리 요즘 잘 팔림?", "sk_innovation"),
    ("비티비 콘텐츠 어때", "sk_broadband"),
    ("오늘 점심 뭐먹지", "general"),
]


def _mock_ai(request, rule_based_result, profiles, requested_sector_id=None):
    base = rule_based_result or EntityExtractionResult(
        request_id=request.request_id,
        primary_intent="current_status",
        perspective="company_update",
    )
    if "SKT" in request.question:
        sector_id = "sk_telecom"
        organizations = ["SK텔레콤"]
        technologies = ["AI 데이터센터"]
        keywords = ["데이터센터", "사업 현황"]
    elif "점심" in request.question:
        sector_id = "general"
        organizations = []
        technologies = []
        keywords = ["점심 메뉴"]
    else:
        mappings = {
            "하이닉스": ("sk_hynix", ["SK하이닉스"], ["HBM"], ["개발 현황"]),
            "오케캐시백": ("sk_planet", ["SK플래닛"], ["OK캐쉬백", "Syrup"], ["이용자 반응"]),
            "sk온": ("sk_innovation", ["SK온"], ["전기차 배터리"], ["판매 현황"]),
            "비티비": ("sk_broadband", ["SK브로드밴드"], ["B tv"], ["콘텐츠 반응"]),
        }
        matched = next((value for marker, value in mappings.items() if marker in request.question), None)
        if matched is None:
            raise AssertionError(f"unexpected delegated question: {request.question}")
        sector_id, organizations, technologies, keywords = matched
    return base.model_copy(
        update={
            "organizations": organizations,
            "technologies": technologies,
            "keywords": keywords,
            "sector_id": sector_id,
            "routing_confidence": "high",
            "routing_reason": "test AI route",
            "needs_ai_routing": False,
        }
    )


@pytest.mark.parametrize(("question", "expected_sector"), CASES)
def test_dirty_natural_language_routes_to_expected_sector(monkeypatch, question, expected_sector):
    monkeypatch.setattr(pipeline_module, "extract_entities_ai", _mock_ai)

    result = run_pipeline(UserRequest(request_id="req_robust", question=question), dry_run=True)

    assert result.sector_route.sector_id == expected_sector
    # dry_run=True skips every sector's adapter stages uniformly (including
    # general, which is now a real — if unconfigured — sector like any other),
    # so no sector should ever halt here.
    assert result.halted_at_stage is None


def test_general_reports_template_only_without_configured_api_key(monkeypatch):
    # general is a real sector now (reuses sk_telecom's generic web collector,
    # see sectors/general/adapter/collector/__init__.py) so it SHOULD attempt
    # collection like any other real sector — it just can't succeed without a
    # configured FIRECRAWL_API_KEY, same as sk_hynix/sk_planet/etc. would report
    # in this same unconfigured test environment. It must not crash or fabricate.
    monkeypatch.setattr(pipeline_module, "extract_entities_ai", _mock_ai)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    result = run_pipeline(
        UserRequest(request_id="req_general", question="오늘 점심 뭐먹지"),
        dry_run=False,
    )

    assert result.sector_route.sector_id == "general"
    assert result.sector_route.matched_profile.status == "active"
    assert result.halted_at_stage is None
    collector_trace = next(trace for trace in result.trace if trace.stage == "sector_adapter.collector")
    assert collector_trace.status == StageStatus.TEMPLATE_ONLY


def test_ai_market_classification_is_used_without_rule_override(monkeypatch):
    def ai_result(request, rule_based_result, profiles, requested_sector_id=None):
        return EntityExtractionResult(
            request_id=request.request_id,
            primary_intent="current_status",
            perspective="market_landscape",
            sector_id="sk_broadband",
            organizations=["SK브로드밴드"],
            keywords=["시장 점유율"],
        )

    monkeypatch.setattr(pipeline_module, "extract_entities_ai", ai_result)
    result = run_pipeline(
        UserRequest(request_id="req_market_guard", question="비티비 시장 점유율 현황"),
        dry_run=True,
    )

    assert result.sector_route.sector_id == "sk_broadband"
    assert result.entities.perspective == "market_landscape"
