"""The two blocks the delivered artwork has and the system didn't, plus the
multi-series trend the `subject` axis had been swallowing.
"""

from __future__ import annotations

from common.block_shapes import (
    grouped_bar_series,
    has_grouped_bars,
    has_status_levels,
    has_timeseries,
    status_levels,
)
from common.content_quality_validator import classify_metric_shape
from common.contracts import ComparisonPoint, MetricPoint


def _series(subject: str, periods: list[str], values: list[float], label="이용률", unit="%"):
    return [
        MetricPoint(label=label, subject=subject, period=period, value=value, unit=unit)
        for period, value in zip(periods, values)
    ]


# --- a subject split is not automatically a ranking ----------------------


def test_two_subjects_tracked_over_time_are_two_trends_not_a_ranking():
    """"국내 vs 글로벌 OTT 가입자, 5년치" drew five years of movement as a row
    of bars - the shape the question was about disappeared."""
    points = [
        *_series("국내", [f"{y}년" for y in range(2021, 2026)], [100, 140, 190, 230, 260], "가입자", "만명"),
        *_series("글로벌", [f"{y}년" for y in range(2021, 2026)], [900, 1200, 1600, 2000, 2300], "가입자", "만명"),
    ]

    assert classify_metric_shape(points) == "line"
    assert has_timeseries(points) is True


def test_two_subjects_measured_once_are_still_a_ranking():
    points = [*_series("KT", ["2025년"], [912], "가입자", "만명"),
              *_series("SKB", ["2025년"], [682], "가입자", "만명")]

    assert classify_metric_shape(points) == "comparison"


def test_each_subject_gets_its_own_line_rather_than_one_zigzag():
    """Grouping by label alone put both subjects on a single polyline, so it
    ran 국내 → 글로벌 → 국내 at every year."""
    from reporting.dashboard_streamlit.components import _metric_chart_svg

    points = [
        *_series("국내", [f"{y}년" for y in range(2021, 2026)], [100, 140, 190, 230, 260], "가입자", "만명"),
        *_series("글로벌", [f"{y}년" for y in range(2021, 2026)], [900, 1200, 1600, 2000, 2300], "가입자", "만명"),
    ]

    svg = _metric_chart_svg(points, "가입자")

    assert svg.count("<polyline") == 2
    assert "가입자 · 국내" in svg and "가입자 · 글로벌" in svg


# --- grouped bars: metric x subject x category ---------------------------


def test_grouped_bars_need_two_subjects_and_two_shared_categories():
    ages = ["20대", "30대", "40대"]
    points = [*_series("롱폼", ages, [62, 48, 35]), *_series("숏폼", ages, [38, 52, 65])]

    (label, categories, by_subject), = grouped_bar_series(points)

    assert label == "이용률"
    assert categories == ages
    assert sorted(by_subject) == ["롱폼", "숏폼"]


def test_a_category_only_one_subject_was_measured_on_is_dropped():
    """Otherwise the lone bar reads as "the others are zero"."""
    points = [
        *_series("롱폼", ["20대", "30대", "40대"], [62, 48, 35]),
        *_series("숏폼", ["20대", "30대"], [38, 52]),
    ]

    (_, categories, _), = grouped_bar_series(points)

    assert categories == ["20대", "30대"]


def test_one_subject_is_an_ordinary_bar_not_a_group():
    assert has_grouped_bars(_series("롱폼", ["20대", "30대"], [62, 48])) is False


def test_grouped_bars_scale_against_the_group_not_each_column(monkeypatch):
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    ages = ["20대", "30대"]
    components.render_grouped_bars([*_series("롱폼", ages, [50, 25]), *_series("숏폼", ages, [100, 75])])
    body = "".join(captured)

    assert "height:100.0%" in body and "height:50.0%" in body and "height:25.0%" in body


# --- status bar: graded standings ---------------------------------------


def _graded(entity: str, criterion: str, value: str, level):
    return ComparisonPoint(entity=entity, criterion=criterion, value=value, level=level)


def test_only_a_grade_the_source_stated_becomes_a_status():
    points = [
        _graded("B tv", "스포츠 중계", "3개 리그", "high"),
        _graded("B tv", "가격 경쟁력", "월 22,000원", None),
        _graded("B tv", "콘텐츠 다양성", "12만 편", "medium"),
    ]

    assert [criterion for criterion, _, _ in status_levels(points)] == ["스포츠 중계", "콘텐츠 다양성"]


def test_one_graded_item_is_not_a_status_row():
    assert has_status_levels([_graded("B tv", "스포츠 중계", "3개 리그", "high")]) is False


def test_the_grade_word_is_always_printed_beside_its_colour(monkeypatch):
    """Colour is a second channel, never the only one carrying the value."""
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_status_bar([
        _graded("B tv", "스포츠 중계", "3개 리그", "high"),
        _graded("B tv", "콘텐츠 다양성", "12만 편", "medium"),
    ])
    body = "".join(captured)

    assert "HIGH" in body and "MEDIUM" in body


# --- one block, several densities: the layout follows the data -----------


def test_a_short_timeline_reads_across_and_a_wordy_one_reads_down(monkeypatch):
    from reporting.dashboard_streamlit import components

    def render(evidence):
        captured: list[str] = []
        monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
        components.render_timeline(evidence, [], 2026, as_of_date="2026-08-01")
        return "".join(captured)

    short = render(["2024년 출시 완료", "2025년 확대 추진 중", "2027년 도입 예정"])
    wordy = render([
        "2024년 3분기 프로야구 중계권을 확보하며 스포츠 라인업을 크게 늘렸다.",
        "2025년 2분기 AI 셋톱박스 보급 확대를 전 지역으로 추진 중이다.",
    ])

    assert "ts-htimeline" in short
    assert "ts-htimeline" not in wordy and "ts-timeline-step" in wordy


def test_three_or_more_compared_items_are_drawn_as_columns(monkeypatch):
    from reporting.dashboard_streamlit import components

    def render(subjects):
        captured: list[str] = []
        monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
        components.render_metric_bar([
            MetricPoint(label="가입자", subject=subject, period="2025년", value=value, unit="만명")
            for subject, value in subjects
        ])
        return "".join(captured)

    three = render([("KT", 912), ("SKB", 682), ("LGU+", 551)])
    two = render([("KT", 912), ("SKB", 682)])

    assert "ts-gbar single" in three
    # A pair is a before/after and stays horizontal, where it reads as one change.
    assert "ts-gbar" not in two and "ts-bar-compare" in two


def test_one_or_two_figures_use_the_row_layout_not_a_four_up_grid(monkeypatch):
    """Two figures in a grid leave two empty tracks, which reads as missing
    data rather than as a short list."""
    from reporting.dashboard_streamlit import components

    def render(count):
        captured: list[str] = []
        monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
        components.render_kpi_row([
            MetricPoint(label=f"지표 {i}", period="2025년", value=10 * i, unit="%")
            for i in range(1, count + 1)
        ])
        return "".join(captured)

    assert 'class="ts-kpi-row rows"' in render(2)
    assert 'class="ts-kpi-row"' in render(4)


def test_a_three_level_chain_keeps_its_middle_layer():
    """Flattening the third level up would attribute a second-order effect
    directly to the root cause."""
    from common.block_shapes import cause_forest
    from common.contracts import SynthesisClaim

    def claim(claim_id, parent=None):
        return SynthesisClaim(
            synthesis_claim_id=claim_id, claim_id=claim_id, claim_type="risk", claim=claim_id,
            evidence_quote="q", confidence="high", doc_id="d1", source_id="s1",
            parent_synthesis_claim_id=parent,
        )

    (tree,) = cause_forest([
        claim("가입자 감소"), claim("OTT 이용 증가", "가입자 감소"),
        claim("요금제 다양화", "OTT 이용 증가"), claim("4단계", "요금제 다양화"),
    ])

    branch, = tree["children"]
    leaf, = branch["children"]
    assert branch["claim"].claim == "OTT 이용 증가"
    assert leaf["claim"].claim == "요금제 다양화"
    # Depth stops at three: the fourth link is dropped, not raised.
    assert leaf["children"] == []


# --- Landscape: two blocks in one card, neither derived from the other ---


def test_landscape_needs_both_halves_to_stand_on_their_own():
    from common.block_shapes import has_landscape

    trend = [MetricPoint(label="HBM 시장 규모", period=f"202{y}년", value=v, unit="조원")
             for y, v in zip(range(3, 8), [12, 21, 32, 43, 57])]
    split = [MetricPoint(label="구성비", subject=s, period="2025년", value=v, unit="%",
                         share_of="HBM 수요")
             for s, v in (("AI GPU", 48), ("AI Server", 25), ("Cloud CSP", 12))]

    assert has_landscape(trend) is False
    assert has_landscape(split) is False
    assert has_landscape([*trend, *split]) is True


# --- competitor panels: only what is attributable to one competitor ------


def _graded_point(entity: str, criterion: str, value: str, level=None):
    from common.contracts import ComparisonPoint

    return ComparisonPoint(entity=entity, criterion=criterion, value=value, level=level)


def test_a_competitor_needs_two_kinds_of_fact_to_earn_a_panel():
    """One fact is a row in the comparison table, and it stays there."""
    from common.block_shapes import competitor_panels

    points = [
        _graded_point("B tv", "AI 추천", "자체 엔진", "medium"),
        _graded_point("B tv", "스포츠 중계", "3개 리그", "medium"),
        _graded_point("Netflix", "AI 추천", "고도화", "high"),
        _graded_point("Netflix", "스포츠 중계", "없음", "low"),
        _graded_point("TVING", "AI 추천", "보통", "medium"),
    ]

    assert [entity for entity, _, _, _ in competitor_panels(points, [])] == ["B tv", "Netflix"]


def test_a_panel_only_carries_figures_measured_for_that_competitor():
    from common.block_shapes import competitor_panels

    points = [_graded_point("B tv", "AI 추천", "자체 엔진", "medium"),
              _graded_point("KT", "AI 추천", "고도화", "high")]
    figures = [
        MetricPoint(label="가입자", subject="B tv", period="2025년", value=682, unit="만명"),
        MetricPoint(label="가입자", subject="KT", period="2025년", value=912, unit="만명"),
        MetricPoint(label="시장 규모", period="2025년", value=5, unit="조원"),
    ]

    panels = dict((entity, figures) for entity, _, figures, _ in competitor_panels(points, figures))

    assert [point.subject for point in panels["B tv"]] == ["B tv"]
    assert [point.subject for point in panels["KT"]] == ["KT"]


def test_one_competitor_is_not_a_panel_set():
    from common.block_shapes import has_competitor_panels

    points = [_graded_point("B tv", "AI 추천", "자체 엔진", "medium"),
              _graded_point("B tv", "스포츠", "3개 리그", "high")]

    assert has_competitor_panels(points, []) is False
