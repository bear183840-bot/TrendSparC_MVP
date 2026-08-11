"""entity_attribute_groups: two or more subjects, each with its OWN distinct
percentage attributes and no shared category between them - the shape
`grouped_bar_series` cannot draw (it requires the same categories measured
for every subject). Live case: "롱폼 콘텐츠: 깊이감 71.1%, 전문지식 68.4%"
beside "숏폼 콘텐츠: 가성비 구독 64.7%, 광고 요금제 34.8%" - two subjects
whose attributes don't overlap at all.
"""
from __future__ import annotations

from common.block_shapes import entity_attribute_groups, has_entity_attribute_bars
from common.contracts import MetricPoint


def _point(label: str, subject: str, value: float, unit: str = "%") -> MetricPoint:
    return MetricPoint(label=label, subject=subject, period="시점 미상", value=value, unit=unit)


def test_two_subjects_with_their_own_unrelated_attributes_group():
    points = [
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1),
        _point("전문 지식/정보 습득", "롱폼 콘텐츠", 68.4),
        _point("가성비 좋은 구독료", "숏폼 콘텐츠", 64.7),
        _point("광고 요금제 선택", "숏폼 콘텐츠", 34.8),
    ]

    groups = entity_attribute_groups(points)

    assert has_entity_attribute_bars(points)
    assert {subject for subject, _ in groups} == {"롱폼 콘텐츠", "숏폼 콘텐츠"}
    long_form = next(items for subject, items in groups if subject == "롱폼 콘텐츠")
    assert {point.label for point in long_form} == {"깊이감 있는 스토리 선호", "전문 지식/정보 습득"}


def test_a_single_subject_is_not_a_comparison():
    points = [
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1),
        _point("전문 지식/정보 습득", "롱폼 콘텐츠", 68.4),
    ]

    assert entity_attribute_groups(points) == []


def test_a_subject_with_only_one_attribute_is_excluded():
    points = [
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1),
        _point("가성비 좋은 구독료", "숏폼 콘텐츠", 64.7),
        _point("광고 요금제 선택", "숏폼 콘텐츠", 34.8),
        _point("만족도", "OTT 콘텐츠", 55.0),
        _point("재구독 의향", "OTT 콘텐츠", 40.0),
    ]

    groups = entity_attribute_groups(points)

    assert {subject for subject, _ in groups} == {"숏폼 콘텐츠", "OTT 콘텐츠"}


def test_a_subject_with_a_stated_shared_whole_is_excluded():
    """IPTV/SO/위성 style: the source explicitly framed these as slices of
    one named whole (`share_of` set) - a real composition, `share_groups`'s
    job, not unrelated attributes."""
    points = [
        MetricPoint(label="IPTV 비중", subject="유료방송", period="시점 미상",
                    value=59.6, unit="%", share_of="유료방송 전체"),
        MetricPoint(label="SO 비중", subject="유료방송", period="시점 미상",
                    value=33.0, unit="%", share_of="유료방송 전체"),
        _point("가성비 좋은 구독료", "숏폼 콘텐츠", 64.7),
        _point("광고 요금제 선택", "숏폼 콘텐츠", 34.8),
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1),
        _point("전문 지식/정보 습득", "롱폼 콘텐츠", 68.4),
    ]

    groups = entity_attribute_groups(points)

    assert {subject for subject, _ in groups} == {"숏폼 콘텐츠", "롱폼 콘텐츠"}


def test_a_coincidental_sum_near_100_is_not_excluded():
    """Two unrelated survey answers landing near 100% by chance (64.7 +
    34.8 = 99.5) must not be mistaken for a stated composition - nothing
    else will ever draw this pair as a donut since no `share_of` was
    stated, so excluding it here would just make the data disappear."""
    points = [
        _point("가성비 좋은 구독료", "숏폼 콘텐츠", 64.7),
        _point("광고 요금제 선택", "숏폼 콘텐츠", 34.8),
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1),
        _point("전문 지식/정보 습득", "롱폼 콘텐츠", 68.4),
    ]

    groups = entity_attribute_groups(points)

    assert {subject for subject, _ in groups} == {"숏폼 콘텐츠", "롱폼 콘텐츠"}


def test_non_percent_points_are_not_eligible():
    points = [
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1, unit="점"),
        _point("전문 지식/정보 습득", "롱폼 콘텐츠", 68.4, unit="점"),
        _point("가성비 좋은 구독료", "숏폼 콘텐츠", 64.7, unit="점"),
        _point("광고 요금제 선택", "숏폼 콘텐츠", 34.8, unit="점"),
    ]

    assert entity_attribute_groups(points) == []


def test_repeated_period_for_the_same_label_is_one_attribute_not_two():
    points = [
        _point("깊이감 있는 스토리 선호", "롱폼 콘텐츠", 71.1),
        MetricPoint(
            label="깊이감 있는 스토리 선호", subject="롱폼 콘텐츠",
            period="2024년", value=65.0, unit="%",
        ),
        _point("전문 지식/정보 습득", "롱폼 콘텐츠", 68.4),
        _point("가성비 좋은 구독료", "숏폼 콘텐츠", 64.7),
        _point("광고 요금제 선택", "숏폼 콘텐츠", 34.8),
    ]

    groups = entity_attribute_groups(points)

    long_form = next(items for subject, items in groups if subject == "롱폼 콘텐츠")
    assert len(long_form) == 2
    assert {point.label for point in long_form} == {"깊이감 있는 스토리 선호", "전문 지식/정보 습득"}
