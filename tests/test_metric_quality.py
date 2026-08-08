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
