"""Block types the live dashboard can draw, and the data shapes that earn them.

The old block registry (reporting/dashboard_streamlit/blocks/) offered a wide
range of block types but read them from `block.data["rows"]`, which no pipeline
stage writes - so none of them could ever draw anything. These tests pin the
replacements to contracts the pipeline actually fills, and check that two
genuinely different analyses produce two genuinely different block mixes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.contracts import (
    ActionImpact,
    ComparisonPoint,
    DocumentAnalysis,
    MetricPoint,
    ReportPurposeClassification,
)
from core.report_generator.generator import generate_report
from core.report_planner.planner import plan_report
from core.report_purpose.classifier import recommended_sections_for
from core.synthesis.synthesizer import synthesize
from reporting.dashboard_streamlit import components

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def markup(monkeypatch):
    """Collect whatever the renderer hands to st.markdown."""
    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
    return captured


def _metric(label: str, period: str, value: float, unit: str = "억원") -> MetricPoint:
    return MetricPoint(label=label, period=period, value=value, unit=unit)


# --- radar: only when every plotted entity has a stated level on 3+ shared axes ---


def _three_axis_points() -> list[ComparisonPoint]:
    return [
        ComparisonPoint(entity=entity, criterion=criterion, value=value, level=level)
        for entity, criterion, value, level in [
            ("B tv", "AI 추천", "보통", "medium"),
            ("B tv", "콘텐츠", "보통", "medium"),
            ("B tv", "가격", "결합할인", "high"),
            ("Netflix", "AI 추천", "최고 수준", "high"),
            ("Netflix", "콘텐츠", "오리지널 다수", "high"),
            ("Netflix", "가격", "구독료 인상", "low"),
        ]
    ]


def test_radar_needs_three_shared_axes():
    assert components.has_radar(_three_axis_points()) is True
    assert components.has_radar(_three_axis_points()[:2]) is False


def test_radar_axis_dropped_when_one_entity_lacks_a_level():
    points = _three_axis_points()
    # Netflix has no stated level on 가격 - plotting it would read as zero.
    points = [p for p in points if not (p.entity == "Netflix" and p.criterion == "가격")]
    assert "가격" not in components.radar_axes(points)


def test_radar_ignores_points_with_no_level():
    points = _three_axis_points() + [
        ComparisonPoint(entity="TVING", criterion="AI 추천", value="제한적")
    ]
    assert "TVING" not in "".join(components.radar_axes(points))


def test_render_radar_draws_one_polygon_per_entity(markup):
    components.render_radar(_three_axis_points())
    body = "".join(markup)
    assert "<svg" in body
    # 3 grid rings + 2 entity shapes.
    assert body.count("<polygon") == 5
    assert "B tv" in body and "Netflix" in body


def test_render_radar_silent_below_three_axes(markup):
    components.render_radar(_three_axis_points()[:2])
    assert markup == []


# --- item comparison: several metrics sharing a unit at one period ---


def test_metric_comparison_needs_two_labels_in_the_same_unit_and_period():
    same_period = [_metric("매출", "2025년", 45406), _metric("영업이익", "2025년", 3741)]
    assert components.has_metric_comparison(same_period) is True

    # Same metric over time is a trend, not an item comparison.
    over_time = [_metric("매출", "2024년", 32878), _metric("매출", "2025년", 45406)]
    assert components.has_metric_comparison(over_time) is False


def test_metric_comparison_does_not_mix_units():
    mixed = [_metric("매출", "2025년", 45406, "억원"), _metric("영업이익률", "2025년", 8.2, "%")]
    assert components.has_metric_comparison(mixed) is False


def test_metric_comparison_rejects_unknown_period_and_ranking_subjects():
    unknown = [_metric("이용률", "시점 미상", 89, "%"), _metric("선호도", "시점 미상", 91, "%")]
    ranked = [
        MetricPoint(label="플랫폼 이용률", subject=name, period="2025년", value=value, unit="%")
        for name, value in (("A", 50), ("B", 30), ("C", 20))
    ]

    assert components.has_metric_comparison(unknown) is False
    assert components.has_metric_comparison(ranked) is False


def test_render_metric_comparison_bar_length_is_the_real_ratio(markup):
    components.render_metric_comparison(
        "2025년", [_metric("매출", "2025년", 100), _metric("영업이익", "2025년", 25)]
    )
    body = "".join(markup)
    assert "--pct:100.0%" in body
    assert "--pct:25.0%" in body


def test_render_metric_comparison_scales_large_shared_unit_values(markup):
    """Live gap: this renderer used to print raw 8-digit values instead of
    routing through the shared number_format helpers everything else uses."""
    components.render_metric_comparison(
        "2025년",
        [_metric("가입자", "2025년", 21_535_256, "명"), _metric("해지자", "2025년", 1_200_000, "명")],
    )
    body = "".join(markup)
    assert "21,535,256" not in body
    assert "2,154만" in body


def test_render_metric_comparison_scales_each_row_independently_when_units_differ(markup):
    components.render_metric_comparison(
        "2025년",
        [_metric("가입자", "2025년", 21_535_256, "명"), _metric("점유율", "2025년", 59.1, "%")],
    )
    body = "".join(markup)
    assert "21,535,256" not in body
    assert "2,154만" in body
    assert "59.1%" in body


# --- grouped bars: one metric, several subjects, several shared categories ---


def test_render_grouped_bars_scales_large_values_in_tooltip_and_note(markup):
    points = [
        MetricPoint(label="가입자", subject=subject, period=period, value=value, unit="명")
        for subject, period, value in [
            ("KT", "20대", 21_535_256), ("KT", "30대", 18_000_000),
            ("LGU+", "20대", 15_200_000), ("LGU+", "30대", 12_400_000),
        ]
    ]
    components.render_grouped_bars(points)
    body = "".join(markup)
    assert "21,535,256" not in body
    assert "2,154만" in body
    assert "단위: 만명" in body


# --- competitor panels: per-entity facts, each attributable to that entity ---


def test_render_competitor_panels_scales_each_figure(markup):
    comparisons = [
        ComparisonPoint(entity=entity, criterion=criterion, value=value)
        for entity in ("KT", "SK브로드밴드")
        for criterion, value in [("가격", "결합할인"), ("콘텐츠", "오리지널 다수")]
    ]
    metrics = [
        MetricPoint(label="가입자 수", subject="KT", period="2025년",
                    value=21_535_256, unit="명"),
    ]
    components.render_competitor_panels(comparisons, metrics)
    body = "".join(markup)
    assert "21,535,256" not in body
    assert "2,154만" in body


# --- action list: a bar only where the source stated a size ---


def test_render_action_list_scales_the_impact_bar(markup):
    components.render_action_list([
        (
            "요금제 개편",
            ActionImpact(
                action="요금제 개편", expected_impact="가입자 30만명 순증",
                evidence_quote="가입자 30만명 순증 예상",
                impact_value=300_000, impact_unit="명",
            ),
            "",
        ),
        (
            "프로모션 확대",
            ActionImpact(
                action="프로모션 확대", expected_impact="대규모 가입자 순증 전망",
                evidence_quote="대규모 가입자 순증이 전망됨",
                impact_value=21_535_256, impact_unit="명",
            ),
            "",
        ),
    ])
    body = "".join(markup)
    # The raw magnitude must appear nowhere - not even the impact bar's own
    # title/label - only the scaled form.
    assert "21,535,256" not in body
    assert "2,154만" in body


# --- timeline: dated evidence + metric periods, chronologically ---


def test_timeline_orders_entries_chronologically():
    entries = components.timeline_entries(
        ["2026년 1분기에 신규 요금제를 출시했다", "2024년 3분기 가입자가 감소했다"],
        [_metric("매출", "2025년", 45406)],
    )
    assert [period for period, _ in entries] == ["2024년 3분기", "2026년 1분기"]


def test_timeline_excludes_undated_prose():
    assert components.has_timeline(["가입자 이탈이 이어지고 있다"], []) is False


def test_render_timeline_caps_entries(markup):
    evidence = [f"20{10 + i}년 지표가 변동했다" for i in range(9)]
    components.render_timeline(evidence, [], limit=4)
    body = "".join(markup)
    # Short labels take the horizontal rail, long ones the vertical one - the
    # cap under test applies to both.
    assert body.count("ts-htimeline-step") + body.count("ts-timeline-step") == 4


# --- cause map: three honest columns, no invented edges ---


def test_cause_map_needs_two_of_three_columns():
    assert components.has_cause_map(["위험"], ["영향"], []) is True
    assert components.has_cause_map(["위험"], [], []) is False


def test_render_cause_map_draws_no_edges_between_items(markup):
    components.render_cause_map(["위험 A", "위험 B"], ["영향 A"], ["대응 A"])
    body = "".join(markup)
    assert "ts-cause-col" in body
    # Nothing in the data says which risk produced which impact, so no
    # connector may be drawn between individual items.
    assert "<line" not in body and "→" not in body


def test_render_cause_map_marks_an_empty_column_rather_than_hiding_it(markup):
    components.render_cause_map(["위험 A"], ["영향 A"], [])
    assert "확인된 근거 없음" in "".join(markup)


# --- end to end: two analyses, two different block mixes ---


def _blocks_for(fixture_name: str, purpose_id: str) -> tuple[list[str], dict[str, int]]:
    data = json.loads((_FIXTURES / f"{fixture_name}.json").read_text(encoding="utf-8"))
    data.pop("_note", None)
    synthesis = synthesize("req_1", "sk_broadband", [DocumentAnalysis(**data)])
    purpose = ReportPurposeClassification(
        request_id="req_1",
        purpose_id=purpose_id,
        display_name=purpose_id,
        recommended_sections=recommended_sections_for(purpose_id),
    )
    plan = plan_report(synthesis, "practitioner", purpose)
    report = generate_report("질문", synthesis, plan, "practitioner")

    blocks = []
    if components.has_timeseries(synthesis.metric_series):
        blocks.append("chart")
    if components.bar_metric_groups(synthesis.metric_series):
        blocks.append("bar")
    if components.has_metric_comparison(synthesis.metric_series):
        blocks.append("metric_comparison")
    if components.has_timeline(synthesis.evidence, synthesis.metric_series):
        blocks.append("timeline")
    if components.has_comparison(synthesis.comparison_points):
        blocks.append("table")
    if components.has_radar(synthesis.comparison_points):
        blocks.append("radar")
    if synthesis.recommended_actions:
        blocks.append("action_list")
    structured = {
        "metric_points": sum(len(section.metric_points) for section in report.sections),
        "comparison_points": sum(len(section.comparison_points) for section in report.sections),
    }
    return blocks, structured


def test_mixed_annual_and_quarterly_revenue_does_not_draw_a_false_trend():
    blocks, structured = _blocks_for("analysis_revenue_trend", "current_status")

    # Q3 cumulative, full-year and Q1 revenue are different time bases. They
    # remain available as quantitative blocks, but must not share one line.
    assert "chart" not in blocks
    assert "bar" in blocks
    assert "timeline" in blocks
    assert "metric_comparison" in blocks
    # Purely quantitative evidence - no entity-vs-entity comparison to draw.
    assert "table" not in blocks and "radar" not in blocks
    # The figures reach a report section rather than staying in evidence prose.
    assert structured["metric_points"] == 5


def test_iptv_competition_fixture_draws_the_qualitative_blocks():
    blocks, structured = _blocks_for("analysis_iptv_competition", "issue_response")

    assert "table" in blocks
    assert "radar" in blocks
    assert "action_list" in blocks
    # No figures in this analysis, so no chart may be drawn.
    assert "chart" not in blocks and "metric_comparison" not in blocks
    assert structured["comparison_points"] > 0


def test_the_two_fixtures_do_not_produce_the_same_layout():
    revenue, _ = _blocks_for("analysis_revenue_trend", "current_status")
    iptv, _ = _blocks_for("analysis_iptv_competition", "issue_response")
    assert set(revenue) != set(iptv)
