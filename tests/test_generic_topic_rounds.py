"""Company-free topic rounds alongside company-specific ones.

Live-observed on "브랜드 이미지 개선에 맞는 연령층별 광고 매체 및 모델 추천":
all three rounds searched "SK브로드밴드 …", so every result was the company's
own coverage and none of the age-bracket media research a person would have
found by searching the topic alone. The system prompt actually forbade it -
"Never search generically once company_name is given".
"""

from __future__ import annotations

import pytest

from common.content_quality_validator import (
    needs_generic_topic_search,
    strip_company_from_query,
)
from common.contracts import WebSearchContext
from sources.collectors.ai_search_harness import (
    COMPANY_SPECIFIC_ROUND,
    GENERIC_TOPIC_ROUND,
    plan_round_kinds,
    query_for_round_kind,
)

_BRAND = "SK브로드밴드 브랜드 이미지 개선에 맞는 연령층별 광고 매체 및 모델 추천"
_CHIP = "칩플레이션이 셋톱박스 업계에 미치는 영향"
_COMPANY_FACT = "우리회사의 최근 매출과 영업이익 추이는 어떻게 되고 있어?"


def _context(question: str, needs_generic: bool, company: str | None = "SK브로드밴드"):
    return WebSearchContext(
        question=question, company_name=company, needs_generic_topic_round=needs_generic
    )


@pytest.mark.parametrize(
    "question, expected",
    [
        (_BRAND, True),
        (_CHIP, True),
        ("업계 표준 원가 구조는 어떻게 되나요?", True),
        ("경쟁사 대비 요금 비교", True),
        (_COMPANY_FACT, False),
        ("2026년 1분기 가입자 수는?", False),
    ],
)
def test_which_questions_need_a_company_free_round(question, expected):
    assert needs_generic_topic_search(question) is expected


def test_market_perspective_alone_is_enough():
    """The entity stage already classifies this; don't re-derive it lexically."""
    assert needs_generic_topic_search("가입자 수는?", "market_landscape") is True
    assert needs_generic_topic_search("가입자 수는?", "company_update") is False


def test_applied_knowledge_question_gets_one_of_each_round_kind():
    kinds = plan_round_kinds(_context(_BRAND, True), 3)

    assert GENERIC_TOPIC_ROUND in kinds
    assert COMPANY_SPECIFIC_ROUND in kinds
    # Company first: it anchors the subject before the generic round widens.
    assert kinds[0] == COMPANY_SPECIFIC_ROUND


def test_company_fact_question_keeps_every_round_company_specific():
    kinds = plan_round_kinds(_context(_COMPANY_FACT, False), 3)
    assert set(kinds) == {COMPANY_SPECIFIC_ROUND}


def test_a_single_round_stays_company_specific():
    """With one round there is no budget to spend on widening."""
    assert plan_round_kinds(_context(_BRAND, True), 1) == [COMPANY_SPECIFIC_ROUND]


def test_sector_with_no_company_name_is_all_topic_rounds():
    kinds = plan_round_kinds(_context(_BRAND, True, company=None), 3)
    assert set(kinds) == {GENERIC_TOPIC_ROUND}


def test_generic_round_drops_the_company_name_from_the_query():
    context = _context(_BRAND, True)

    generic = query_for_round_kind(_BRAND, GENERIC_TOPIC_ROUND, context)
    company = query_for_round_kind(_BRAND, COMPANY_SPECIFIC_ROUND, context)

    assert "SK브로드밴드" not in generic
    assert generic.startswith("브랜드 이미지")
    assert company == _BRAND


def test_a_query_that_is_only_the_company_name_is_left_alone():
    """Stripping it would leave nothing to search for."""
    context = _context("SK브로드밴드", True)
    assert query_for_round_kind("SK브로드밴드", GENERIC_TOPIC_ROUND, context) == "SK브로드밴드"


def test_strip_company_collapses_the_gap_it_leaves():
    assert strip_company_from_query("A SK브로드밴드 B", "SK브로드밴드") == "A B"


def test_chipflation_question_splits_into_both_angles():
    context = _context(_CHIP, True)
    kinds = plan_round_kinds(context, 3)
    queries = [query_for_round_kind(_CHIP, kind, context) for kind in kinds]

    assert any("SK브로드밴드" not in query for query in queries)
    assert "칩플레이션" in queries[kinds.index(GENERIC_TOPIC_ROUND)]
