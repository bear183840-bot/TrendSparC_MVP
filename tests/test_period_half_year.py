"""Half-years must not collapse into their year.

`canonical_time_id` handled quarters and months but fell through for
상반기/하반기, so "2024년 하반기" became "2024년". `share_groups` keys on
that id, so one denominator's two half-year compositions merged into a
single group whose slices summed to 200%.
"""
from common.block_shapes import share_groups
from common.content_quality_validator import canonical_time_id
from common.contracts import MetricPoint
from common.metric_identity import canonical_period

WHOLE = "유료방송 가입자 전체"


def _slice(subject, value, period):
    return MetricPoint(label=f"{subject} 점유율", subject=subject, period=period,
                       value=value, unit="%", share_of=WHOLE, doc_id="d1")


# --------------------------------------------------- 5/6/7. period identity
def test_the_two_halves_of_a_year_are_different_periods():
    assert canonical_time_id("2024년 상반기") != canonical_time_id("2024년 하반기")


def test_a_year_is_not_one_of_its_halves():
    assert canonical_time_id("2024년") != canonical_time_id("2024년 상반기")
    assert canonical_time_id("2024년") == "2024년"


def test_spellings_of_one_half_year_agree():
    canonical = canonical_time_id("2024년 상반기")
    for written in ("2024 H1", "2024년 1H", "'24년 상반기", "2024년 상반기"):
        assert canonical_time_id(written) == canonical, written


def test_quarters_and_months_are_unaffected():
    assert canonical_time_id("2024년 1분기") == "2024년 1분기"
    assert canonical_time_id("2024 Q3") == "2024년 3분기"
    assert canonical_time_id("2024년 5월") == "2024년 5월"


def test_it_agrees_with_the_identity_side_normalizer():
    """Two spellings of one concept, not two parsers disagreeing."""
    for written in ("2024년 하반기", "2024 H2", "'24년 하반기"):
        assert canonical_time_id(written) == canonical_period(written)


# ------------------------------------------------ 8. compositions stay apart
def test_each_half_year_composition_stays_its_own_group():
    points = [
        _slice("IPTV", 58.60, "2024년 하반기"),
        _slice("SO", 33.75, "2024년 하반기"),
        _slice("위성", 7.65, "2024년 하반기"),
        _slice("IPTV", 59.11, "2025년 상반기"),
        _slice("SO", 33.38, "2025년 상반기"),
        _slice("위성", 7.51, "2025년 상반기"),
    ]

    groups = share_groups(points)

    assert len(groups) == 2
    for _, slices in groups:
        assert len(slices) == 3
        assert abs(sum(p.value for p in slices) - 100.0) < 0.05


def test_two_halves_of_the_same_year_do_not_merge_into_200_percent():
    """The exact failure this fix exists for."""
    points = [
        _slice("IPTV", 58.60, "2024년 상반기"),
        _slice("SO", 33.75, "2024년 상반기"),
        _slice("위성", 7.65, "2024년 상반기"),
        _slice("IPTV", 59.11, "2024년 하반기"),
        _slice("SO", 33.38, "2024년 하반기"),
        _slice("위성", 7.51, "2024년 하반기"),
    ]

    groups = share_groups(points)

    assert len(groups) == 2, "one year's two halves are two compositions"
    assert all(sum(p.value for p in slices) < 101 for _, slices in groups)


def test_a_year_digit_is_not_read_as_a_quarter():
    """"2024 Q3" contains "4 Q" - it used to be read as the 4th quarter."""
    assert canonical_time_id("2024 Q3") == "2024년 3분기"
    assert canonical_time_id("2023 Q1") == "2023년 1분기"
    assert canonical_time_id("2024년 3분기") == "2024년 3분기"
