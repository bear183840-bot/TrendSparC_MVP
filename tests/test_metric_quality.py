from common.contracts import MetricPoint
from common.metric_quality import display_metric_points


def test_display_filter_keeps_values_but_drops_unchartable_dimensions():
    points = [
        MetricPoint(label="com/User/Process%2Fstate", period="2025", value=2026, unit="%"),
        MetricPoint(label="**이용률**", subject="▲ 국내", period="2025", value=57, unit="%"),
    ]

    assert display_metric_points(points) == [
        MetricPoint(label="이용률", subject="국내", period="2025", value=57, unit="%")
    ]


def test_display_filter_drops_encoded_paths_and_value_fragments():
    points = [
        MetricPoint(label="kr/tag/%EA%B4%91%EA%B3%A0", period="미상", value=91, unit="%"),
        MetricPoint(label="지난 2024년말 680만3000명", period="2024", value=3000, unit="명"),
        MetricPoint(label="온라인 광고 비중", period="2025", value=60, unit="%"),
    ]

    assert display_metric_points(points) == [points[2]]


def test_display_filter_drops_suffix_of_korean_compound_count():
    suffix = MetricPoint(
        label="시장 1위 KT",
        period="2025",
        value=9000,
        unit="명",
        evidence_quote="가입자는 944만9000명이다.",
    )
    assert display_metric_points([suffix]) == []
