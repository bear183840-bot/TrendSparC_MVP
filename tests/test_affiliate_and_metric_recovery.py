"""Fixes driven by the live "우리회사의 최근 매출과 영업이익 추이" run.

That run put SK텔레콤's operating profit in the KPI row of an SK브로드밴드
report, and left every one of the six SK브로드밴드 figures sitting in evidence
prose unextracted, so no chart could be drawn from data that was right there.
The sentences below are the ones the run actually produced.
"""

from __future__ import annotations

import pytest

from common.content_quality_validator import (
    extract_metric_points_from_evidence,
    has_renderable_content,
)
from common.contracts import MetricPoint
from core.report_generator.generator import _verified_ai_metric_points, normalize_metric_label
from core.sector_router.affiliates import (
    drop_other_affiliates_metrics,
    foreign_entity_names_for,
    names_another_company,
)
from reporting.dashboard_streamlit import components

# Verbatim from the live run.
LIVE_EVIDENCE = [
    "'24년 3분기 누적 연결 매출액은 3조 2,878억원(+2.9% YoY)",
    "SK브로드밴드는 2025년까지 매출 4조 5,406억원, 영업이익 3,005억 8,795만원",
    "2026년 1분기 SK브로드밴드의 매출은 1조 1,498억원으로 전년 동기 대비 3.2% 증가",
    "2026년 1분기 영업이익은 1166억원으로 전년 동기 대비 21.4% 증가",
    "IBK투자증권은 2026년 2분기 매출액을 1조1522억원으로 전년 동기 대비 2.9% 증가할 것으로 예상",
]


class _Synthesis:
    """Minimal stand-in - _verified_ai_metric_points only reads three lists."""

    def __init__(self, evidence):
        self.evidence = evidence
        self.key_points = []
        self.highlights = []


# --- [1] another affiliate's figure must never enter metric_series ---


def test_foreign_names_come_from_the_registry_not_a_hardcoded_list():
    foreign = foreign_entity_names_for("sk_broadband")

    assert any("텔레콤" in name for name in foreign)
    assert not any("브로드밴드" in name for name in foreign)
    # "SK" alone would match every affiliate including this one.
    assert "SK" not in foreign


def test_sk_telecom_operating_profit_is_dropped_from_an_sk_broadband_report():
    points = [
        MetricPoint(label="SK텔레콤 영업이익", period="2026년 1분기", value=5376, unit="억원"),
        MetricPoint(label="매출액", period="2026년 1분기", value=11498, unit="억원"),
    ]

    kept = drop_other_affiliates_metrics(points, "sk_broadband")

    assert [point.label for point in kept] == ["매출액"]


def test_a_figure_naming_both_companies_is_kept():
    """Dropping it would lose a real fact about this company."""
    points = [
        MetricPoint(label="SK텔레콤·SK브로드밴드 합산 매출", period="2025년", value=100, unit="억원")
    ]

    assert drop_other_affiliates_metrics(points, "sk_broadband") == points


def test_unlabelled_metrics_are_never_dropped():
    points = [MetricPoint(label="영업이익", period="2025년", value=3741, unit="억원")]
    assert drop_other_affiliates_metrics(points, "sk_broadband") == points


def test_names_another_company_ignores_text_naming_this_company():
    foreign, own = {"SK텔레콤"}, {"SK브로드밴드"}
    assert names_another_company("SK텔레콤 영업이익", foreign, own) is True
    assert names_another_company("SK브로드밴드 영업이익", foreign, own) is False
    assert names_another_company("영업이익", foreign, own) is False


# --- [1.5] AI extraction, verified against the evidence it claims to read ---


def test_ai_extracted_figure_absent_from_the_evidence_is_rejected():
    synthesis = _Synthesis(LIVE_EVIDENCE)
    raw = [
        {
            "label": "매출액", "period": "2027년", "value": 99999, "unit": "억원",
            "source_sentence": "2027년 매출액은 9조 9,999억원으로 전망된다",
        }
    ]

    assert _verified_ai_metric_points(raw, synthesis, set()) == []


def test_ai_extracted_figure_present_in_the_evidence_is_accepted():
    synthesis = _Synthesis(LIVE_EVIDENCE)
    raw = [
        {
            "label": "매출액", "period": "2026년 1분기", "value": 11498, "unit": "억원",
            "source_sentence": LIVE_EVIDENCE[2],
        }
    ]

    points = _verified_ai_metric_points(raw, synthesis, set())

    assert len(points) == 1
    # "매출액" normalizes to "매출" so it groups with the other revenue points.
    assert (points[0].label, points[0].period, points[0].value) == ("매출", "2026년 1분기", 11498.0)


def test_ai_extraction_also_drops_another_affiliates_figure():
    synthesis = _Synthesis([*LIVE_EVIDENCE, "SK텔레콤 영업이익은 5,376억원을 기록했다"])
    raw = [
        {
            "label": "SK텔레콤 영업이익", "period": "2026년 1분기", "value": 5376, "unit": "억원",
            "source_sentence": "SK텔레콤 영업이익은 5,376억원을 기록했다",
        }
    ]

    assert _verified_ai_metric_points(raw, synthesis, {"SK텔레콤"}) == []


def test_regex_extractor_remains_as_the_fallback_and_still_covers_what_it_did():
    """The regex path is the safety net when no key is set, so it must keep
    working - but this run is also the record of how much it misses on its
    own, which is why the AI pass exists."""
    recovered = extract_metric_points_from_evidence(LIVE_EVIDENCE)
    assert len(recovered) < len(LIVE_EVIDENCE)


# --- [2] empty sections are dropped, not filled with an apology ---


@pytest.mark.parametrize(
    "groups, expected",
    [
        (([],), False),
        ((["", "   "],), False),
        ((None,), False),
        ((["실제 신호"],), True),
        (([], ["두 번째 그룹에만 내용"]), True),
        (([MetricPoint(label="매출", period="2025년", value=1.0)],), True),
    ],
)
def test_has_renderable_content(groups, expected):
    assert has_renderable_content(*groups) is expected


# --- [4] timeline: year required, chronological, no restatements ---


def test_bare_quarter_takes_the_year_from_its_own_sentence():
    entries = components.timeline_entries([LIVE_EVIDENCE[4]], [])
    assert entries == [("2026년 2분기", entries[0][1])]


def test_apostrophe_year_is_expanded():
    entries = components.timeline_entries([LIVE_EVIDENCE[0]], [])
    assert entries[0][0] == "2024년 3분기"


def test_quarter_with_no_year_anywhere_is_left_out_rather_than_misplaced():
    assert components.timeline_entries(["2분기 매출액을 1조1522억원으로 예상"], []) == []


def test_live_evidence_timeline_is_in_chronological_order():
    periods = [period for period, _ in components.timeline_entries(LIVE_EVIDENCE, [])]

    assert periods == sorted(periods, key=components.period_sort_key)
    assert periods[0].startswith("2024")
    assert periods[-1].startswith("2026")


def test_the_same_fact_restated_appears_once():
    entries = components.timeline_entries(
        [
            "2026년 1분기 영업이익이 5376억원을 기록했다",
            "2026년 1분기 영업이익은 5,376억원으로 집계됐다",
        ],
        [],
    )

    assert len(entries) == 1


# --- label normalization: what actually turns 3 figures into 1 trend line ---


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("누적 연결 매출액", "매출"),
        ("2026년 1분기 매출", "매출"),
        ("2026년 2분기 매출 예상", "매출"),
        ("2026년 1분기 영업이익", "영업이익"),
        ("'24년 3분기 누적 매출액", "매출"),
        ("IPTV 가입자 수", "IPTV 가입자 수"),
    ],
)
def test_normalize_metric_label(raw, expected):
    assert normalize_metric_label(raw) == expected


def test_normalized_labels_turn_the_live_figures_into_a_chartable_series():
    """The whole point of the normalization.

    The model returned this run's three revenue figures under three different
    labels, so they grouped as three unrelated one-off numbers and no trend
    line could be drawn - which is exactly what the user saw.
    """
    raw = [
        ("누적 연결 매출액", "2024년 3분기", 32878),
        ("2026년 1분기 매출", "2026년 1분기", 11498),
        ("2026년 2분기 매출 예상", "2026년 2분기", 11522),
    ]
    points = [
        MetricPoint(label=normalize_metric_label(label), period=period, value=value, unit="억원")
        for label, period, value in raw
    ]

    assert {point.label for point in points} == {"매출"}
    assert components.has_timeseries(points) is True
