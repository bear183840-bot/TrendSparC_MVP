from core.question_coverage import coverage_safe_summary, minimum_drawable_periods
from common.contracts import QuestionCoverageRequirement


def test_five_period_request_draws_from_three_real_periods_without_claiming_all_five():
    requirement = QuestionCoverageRequirement(minimum_distinct_periods=5)
    summary = coverage_safe_summary(
        "지난 5년간 시장이 성장했습니다.",
        requirement,
        ["동일 지표 시계열 5개 시점 (현재 최대 3개)"],
    )
    assert minimum_drawable_periods(5) == 3
    assert "확보된 동일 지표 3개 시점의 추이는 제시" in summary
    assert "5개 시점 전체로 확대 해석할 수 없습니다" in summary
