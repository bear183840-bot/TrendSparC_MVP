"""Direct unit coverage for common/recency.py's question-sensitive recency
window — extracted from sk_broadband's validator (behavior-preserving) and
now also consumed by source_router's planner. Some branches below were
previously only reachable indirectly through the validator's `validate()`
and had no direct test at all (ranged-years/months regex, the as_of_date
year-in-question branch, and the bare current_status-purpose branch) —
those are called out explicitly.
"""

from common.recency import format_recency_hint, max_age_days, requires_verified_published_at


def test_max_age_days_no_question_returns_default():
    assert max_age_days(None) == 730


def test_max_age_days_ranged_years_regex():
    # Previously untested branch.
    assert max_age_days("최근 3년간 시장 동향은?") == max(365, 3 * 366)


def test_max_age_days_ranged_years_regex_floor():
    # N=1 should still floor at 365, not 366.
    assert max_age_days("지난 1년간 트렌드는?") == 366
    assert max_age_days("지난 1년간 트렌드는?") == max(365, 366)


def test_max_age_days_ranged_months_regex():
    # Previously untested branch.
    assert max_age_days("최근 2개월 이슈는?") == max(30, 2 * 31)


def test_max_age_days_ranged_months_regex_floor():
    assert max_age_days("지난 1개월 이슈는?") == max(30, 31)


def test_max_age_days_historical_terms_are_unbounded():
    assert max_age_days("이 산업의 역사는 어떻게 되나?") is None
    assert max_age_days("도입 배경이 궁금합니다") is None
    assert max_age_days("장기 추이를 알려줘") is None


def test_max_age_days_strong_latest_terms_cap_at_30():
    assert max_age_days("오늘 발표된 내용은?") == 30
    assert max_age_days("가장 최신 소식 알려줘") == 30


def test_max_age_days_latest_term_caps_at_90():
    assert max_age_days("최신 동향이 궁금해") == 90


def test_max_age_days_recent_terms_cap_at_180():
    assert max_age_days("현재 상황은 어떤가요?") == 180
    assert max_age_days("요즘 이슈는?") == 180


def test_max_age_days_as_of_date_year_in_question_branch():
    # Previously untested: no other trigger term, but the as_of_date's year
    # literally appears in the question text.
    assert max_age_days("2026년 실적 발표 내용은?", as_of_date="2026-08-11") == 365


def test_max_age_days_bare_current_status_purpose_branch():
    # Previously untested: no keyword trigger at all, purpose alone decides.
    assert (
        max_age_days("경쟁사 동향 비교해줘", as_of_date=None, report_purpose_id="current_status")
        == 365
    )


def test_max_age_days_default_fallback_when_nothing_matches():
    assert max_age_days("이 기술의 원리를 설명해줘") == 730


def test_requires_verified_published_at():
    assert requires_verified_published_at("오늘 나온 뉴스는?") is True
    assert requires_verified_published_at("방금 발표된 자료") is True
    assert requires_verified_published_at("최근 3년간 동향은?") is False
    assert requires_verified_published_at(None) is False


def test_format_recency_hint():
    assert format_recency_hint(None) == "특별한 기간 제약 없음"
    assert format_recency_hint(90) == "최근 90일 이내"
