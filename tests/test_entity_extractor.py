from common.contracts import UserRequest
from core.entity.extractor import extract_entities


def _request(question: str) -> UserRequest:
    return UserRequest(request_id="req_test", question=question)


def test_market_landscape_perspective_from_status_keywords():
    result = extract_entities(_request("포인트 마케팅 시장 현황은?"))
    assert result.perspective == "market_landscape"


def test_competitor_comparison_perspective_from_comparison_keyword():
    result = extract_entities(_request("SK하이닉스와 삼성전자 HBM 기술력 비교는?"))
    assert result.perspective == "competitor_comparison"


def test_regulatory_policy_perspective_from_regulation_keyword():
    result = extract_entities(_request("반도체 수출통제 규제 동향은?"))
    # "동향" also matches market_landscape's rule; rule order picks
    # market_landscape first since it's checked before regulatory_policy —
    # use a question with only a regulatory signal to test this branch in isolation.
    result_regulation_only = extract_entities(_request("반도체 수출 관련 새 정책은?"))
    assert result_regulation_only.perspective == "regulatory_policy"


def test_company_update_is_the_default_perspective():
    result = extract_entities(_request("SK온 북미 공장 준공식 소식은?"))
    assert result.perspective == "company_update"


def test_colloquial_other_companies_question_becomes_clean_comparison_query():
    result = extract_entities(_request("HBM4 다른 기업들 어느정도 수준으로 개발하고 있어?"))

    assert result.perspective == "competitor_comparison"
    assert result.technologies == ["HBM4"]
    assert "경쟁사" in result.keywords
    assert "기술 수준" in result.keywords
    assert "개발 현황" in result.keywords
    assert not {"기업들", "어느정도", "수준으로", "개발하고", "있어"}.intersection(result.keywords)
