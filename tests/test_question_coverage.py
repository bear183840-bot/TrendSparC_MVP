from common.contracts import DocumentAnalysis, MetricPoint
from core.question_coverage import (
    assess_question_coverage,
    coverage_safe_summary,
    derive_question_coverage,
)


def test_time_and_comparison_axes_are_derived_without_topic_hardcoding():
    requirement = derive_question_coverage(
        "지난 5년간 서비스 생태계의 변화 추이 (국내 vs 글로벌 비교)"
    )

    assert requirement.minimum_distinct_periods == 5
    assert requirement.comparison_anchors == ["국내", "글로벌"]
    assert requirement.forecast_required is False


def test_feedback_only_forecast_is_not_invented_as_a_question_requirement():
    assert derive_question_coverage("최근 3년 시장 변화").forecast_required is False
    assert derive_question_coverage("최근 3년 시장 변화와 향후 전망").forecast_required is True


def test_same_metric_across_requested_periods_satisfies_time_axis():
    points = [
        MetricPoint(label="가입자", period=str(year), value=year - 2010, unit="만 명")
        for year in range(2020, 2025)
    ]
    analysis = DocumentAnalysis(doc_id="d1", metric_points=points)
    requirement = derive_question_coverage("지난 5년 가입자 변화 추이")

    assert assess_question_coverage([analysis], requirement) == []


def test_many_unrelated_figures_do_not_fake_a_time_series():
    points = [
        MetricPoint(label=f"서로 다른 지표 {index}", period=str(2020 + index), value=index, unit="%")
        for index in range(5)
    ]
    gaps = assess_question_coverage(
        [DocumentAnalysis(doc_id="d1", metric_points=points)],
        derive_question_coverage("지난 5년 지표 변화 추이"),
    )

    assert gaps == ["동일 지표 시계열 5개 시점 (현재 최대 1개)"]


def test_whole_period_conclusion_is_withheld_when_series_is_missing():
    requirement = derive_question_coverage("지난 5년 시장 변화 추이")
    summary = "지난 5년간 시장 점유율이 상승했다. 현재 이용률은 57%다."

    guarded = coverage_safe_summary(
        summary, requirement, ["동일 지표 시계열 5개 시점 (현재 최대 1개)"],
    )

    assert "지난 5년간 시장 점유율이 상승했다" not in guarded
    assert "현재 이용률은 57%다" in guarded
    assert "기간 전체 추이는 확정할 수 없습니다" in guarded
