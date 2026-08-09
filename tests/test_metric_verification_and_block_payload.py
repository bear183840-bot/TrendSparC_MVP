"""Why a document full of figures produced no metric_points.

Diagnosed from a live run on the 방송미디어통신위원회 press release: the
evidence carried 36,226,100 / 21,414,521 / 59.11%, every section's
metric_points was [], and the sector analyzer - not synthesis - was discarding
them.
"""

from __future__ import annotations

import pytest

from sectors.sk_broadband.adapter.analyzer import (
    _load_analysis_json,
    _normalize_analysis_payload,
    _number_is_in_content,
    _recover_missing_metric_claims,
    _recovered_metric_points,
    _merge_metric_points,
    _displayable_metric_points,
    _verified_metric_points,
)


def test_solar_wrapped_json_and_missing_metadata_are_normalized_without_new_facts():
    raw = _load_analysis_json('```json\n{"grounded_claims": [{"claim_id": "c1", '
                              '"claim_type": "metric", "claim": "이용률 37.2%", '
                              '"evidence_quote": "이용률은 37.2%였다"}], '
                              '"metric_points": [{"label": "이용률", "period": "2025", '
                              '"value": 37.2, "evidence_claim_id": "c1"}]}\n```')
    normalized = _normalize_analysis_payload(raw)

    assert normalized["grounded_claims"][0]["evidence_passage_id"] is None
    assert normalized["grounded_claims"][0]["confidence"] == "low"
    assert normalized["metric_points"][0]["value"] == 37.2
    assert normalized["metric_points"][0]["value_origin"] == "source"
    assert normalized["metric_points"][0]["is_forecast"] is False
    assert normalized["comparison_points"] == []

_QUOTE = "올 상반기 유료방송 가입자 수는 36,226,100으로 작년 하반기 대비 138,546이 줄어"
_CLAIMS = [{"claim_id": "c1", "claim_type": "metric", "evidence_quote": _QUOTE}]


@pytest.mark.parametrize(
    "value, text",
    [
        (36226100.0, "가입자 수는 36,226,100으로"),
        (21414521.0, "IPTV 가입자 수는 21,414,521명"),
        (9123463.0, "KT가 912만3463명"[:0] + "KT는 9,123,463명"),
        (45406.0, "매출액은 45,406억원"),
        (84.9, "거실 TV(84.9%)에서"),
        (951.0, "영업이익 951억원"),
    ],
)
def test_a_figure_present_in_the_text_is_recognised(value, text):
    """`%g` switches to scientific notation at 7 significant digits, so
    36,226,100 was searched for as "3.62261e+07" and `str()` gave
    "36226100.0" - neither appears in any document. Every figure of a million
    or more was silently discarded, which is why subscriber counts never
    became metric_points while smaller revenue figures did."""
    assert _number_is_in_content(value, text) is True


def test_a_figure_absent_from_the_text_is_still_rejected():
    """The relaxation must not weaken the fabrication guard."""
    assert _number_is_in_content(36226100.0, "가입자 수는 35,000,000으로") is False
    assert _number_is_in_content(84.9, "점유율은 59.11%") is False


def test_a_figure_is_not_matched_inside_a_longer_number():
    assert _number_is_in_content(2141.0, "21,414,521명") is False


def test_a_million_scale_metric_survives_verification_end_to_end():
    point = {
        "label": "유료방송 가입자 수",
        "period": "올 상반기",
        "value": 36226100,
        "unit": "",
        "evidence_claim_id": "c1",
    }

    verified = _verified_metric_points({"metric_points": [point]}, _QUOTE, _CLAIMS)

    assert len(verified) == 1
    assert verified[0]["value"] == 36226100
    assert verified[0]["evidence_quote"] == _QUOTE


def test_a_metric_whose_number_is_not_in_its_quote_is_still_dropped():
    point = {
        "label": "유료방송 가입자 수",
        "period": "올 상반기",
        "value": 99999999,
        "unit": "",
        "evidence_claim_id": "c1",
    }
    assert _verified_metric_points({"metric_points": [point]}, _QUOTE, _CLAIMS) == []


def test_a_grounded_value_is_kept_when_only_the_period_is_not_local():
    quote = "숏폼 플랫폼별 이용률은 유튜브 쇼츠가 78.8%로 가장 많았다."
    claims = [{"claim_id": "c1", "claim_type": "metric", "evidence_quote": quote}]
    point = {
        "label": "유튜브 쇼츠 이용률", "subject": "유튜브 쇼츠",
        "period": "2024년", "value": 78.8, "unit": "%",
        "share_of": None, "is_forecast": False, "evidence_claim_id": "c1",
    }

    verified = _verified_metric_points({"metric_points": [point]}, quote, claims)

    assert len(verified) == 1
    assert verified[0]["period"] == "시점 미상"
    assert verified[0]["value"] == 78.8


def test_year_suffix_and_percentage_point_notation_are_safe_equivalents():
    quote = "2024 아이엠 리포트에서 이용률은 전년보다 3.7%p 증가했다."
    claims = [{"claim_id": "c1", "claim_type": "metric", "evidence_quote": quote}]
    point = {
        "label": "이용률 증가폭", "subject": "모델이 덧붙인 주체",
        "period": "2024년", "value": 3.7, "unit": "p.p.",
        "share_of": "모델이 덧붙인 모집단", "is_forecast": False,
        "evidence_claim_id": "c1",
    }

    verified = _verified_metric_points({"metric_points": [point]}, quote, claims)

    assert len(verified) == 1
    assert verified[0]["period"] == "2024년"
    assert verified[0]["unit"] == "p.p."
    assert verified[0]["subject"] is None
    assert verified[0]["share_of"] is None


def test_verified_comparison_quote_recovers_every_literal_value():
    quote = "유튜브 쇼츠 78.8%, 인스타그램 릴스 46.2%, 틱톡 22.9% 순이다."
    claims = [{
        "claim_id": "c1", "claim_type": "comparison",
        "claim": "플랫폼별 이용률 비교", "evidence_quote": quote,
    }]

    recovered = _recovered_metric_points(claims)

    assert [point["value"] for point in recovered] == [78.8, 46.2, 22.9]
    assert all(point["unit"] == "%" for point in recovered)
    assert all(point["period"] == "시점 미상" for point in recovered)
    assert all(point["evidence_claim_id"] == "c1" for point in recovered)


def test_numeric_lists_become_separate_generic_series_without_domain_hardcoding():
    quote = (
        "주로 시청한 콘텐츠는 게임(63.9%), 음악·공연·댄스(50.6%), "
        "요리·먹방(먹는 방송, 40.6%) 등이고, 주로 이용하는 플랫폼은 "
        "인스타그램 릴스(37.2%), 유튜브(35.8%), 유튜브 쇼츠(16.5%), "
        "틱톡(8.0%), 네이버 클립(1.3%) 등의 순이었다."
    )
    claims = [{
        "claim_id": "c1", "claim_type": "metric",
        "claim": quote, "evidence_quote": quote,
    }]

    recovered = _recovered_metric_points(claims)
    content = recovered[:3]
    platforms = recovered[3:]

    assert {point["label"] for point in content} == {"주로 시청한 콘텐츠"}
    assert [point["subject"] for point in content] == [
        "게임", "음악·공연·댄스", "요리·먹방",
    ]
    assert [point["value"] for point in content] == [63.9, 50.6, 40.6]
    assert {point["label"] for point in platforms} == {"주로 이용하는 플랫폼"}
    assert [point["subject"] for point in platforms] == [
        "인스타그램 릴스", "유튜브", "유튜브 쇼츠", "틱톡", "네이버 클립",
    ]
    assert [point["value"] for point in platforms] == [37.2, 35.8, 16.5, 8.0, 1.3]


def test_numeric_list_grouping_is_vocabulary_free_for_company_comparisons():
    quote = "가입자 수는 A사(912만명), B사(682만명), C사(551만명) 순이다."
    claims = [{
        "claim_id": "c1", "claim_type": "comparison",
        "claim": quote, "evidence_quote": quote,
    }]

    recovered = _recovered_metric_points(claims)

    assert {point["label"] for point in recovered} == {"가입자 수"}
    assert [point["subject"] for point in recovered] == ["A사", "B사", "C사"]
    assert [point["value"] for point in recovered] == [912, 682, 551]


def test_recovery_never_turns_bare_years_or_united_numbers_into_metrics():
    claims = [{
        "claim_id": "c1", "claim_type": "metric",
        "claim": "표본 설명", "evidence_quote": "2024년 보고서는 표본 5000을 조사했다.",
    }]

    assert _recovered_metric_points(claims) == []


def test_question_relevant_numeric_sentence_becomes_an_exact_quote_claim():
    passages = [{
        "passage_id": "P007",
        "text": "숏폼 플랫폼 이용률은 93.2%였다. 조사 대상 표본 크기는 2000명이다.",
    }]

    claims = _recover_missing_metric_claims([], passages, "숏폼 이용률은?", [])

    assert len(claims) == 1
    assert claims[0]["claim_type"] == "metric"
    assert claims[0]["claim"] == claims[0]["evidence_quote"]
    assert claims[0]["evidence_quote"] == "숏폼 플랫폼 이용률은 93.2%였다."
    assert claims[0]["evidence_passage_id"] == "P007"
    assert _recovered_metric_points(claims)[0]["value"] == 93.2


def test_numeric_passage_without_a_question_term_is_not_promoted():
    passages = [{"passage_id": "P001", "text": "무관한 매출은 300억원이다."}]

    assert _recover_missing_metric_claims([], passages, "숏폼 이용률은?", []) == []


def test_deterministic_recovery_does_not_duplicate_a_verified_ai_point():
    verified = [{
        "label": "증가폭", "period": "지난해", "value": 3.7,
        "unit": "p.p.", "evidence_claim_id": "c1",
    }]
    recovered = [{
        "label": "증가폭", "period": "2024", "value": 3.7,
        "unit": "%p", "evidence_claim_id": "c1",
    }]

    assert _merge_metric_points(verified, recovered) == verified


def test_url_and_sentence_debris_never_become_dashboard_axes():
    points = [
        {"label": "com/User/abc%2Fdef", "subject": "path", "value": 1},
        {"label": "**가입자 수**", "subject": "▲ 국내", "value": 2},
        {"label": "근거 문장 전체를 축 이름으로 복사해서 단어가 열 개보다 훨씬 더 많아진 잘못된 지표 이름입니다", "value": 3},
    ]

    assert _displayable_metric_points(points) == [
        {"label": "가입자 수", "subject": "국내", "value": 2}
    ]


# --- block payloads carry only what the block type reads ----------------


def _layout_for(section: str, content: dict):
    from common.contracts import AudienceAdaptation, ReportPlan
    from core.layout_generator.generator import generate_layout

    plan = ReportPlan(
        request_id="r", audience_id="_default", primary_intent="current_status",
        sections=[section], format="dashboard",
    )
    adaptation = AudienceAdaptation(
        request_id="r", audience_id="_default", adapted_sections={section: content}
    )
    return generate_layout(plan, adaptation).blocks[0]


def test_an_action_block_does_not_ship_empty_metric_fields():
    """Every block used to carry the whole section dump - twelve keys, most of
    them [] - so a reader of the contract could not tell which fields a block
    type even uses."""
    block = _layout_for(
        "recommended_action",
        {"title": "Actions", "actions": ["대응한다"], "metric_points": [], "strengths": []},
    )

    assert block.block_type == "list"
    assert "actions" in block.content
    assert "metric_points" not in block.content
    assert "strengths" not in block.content


def test_a_table_block_keeps_its_comparison_points():
    block = _layout_for(
        "market_status",
        {
            "title": "Competitors",
            "comparison_points": [
                {"entity": "KT", "criterion": "가입자", "value": "912만"},
                {"entity": "SKB", "criterion": "가입자", "value": "669만"},
            ],
            "actions": [],
        },
    )

    assert block.block_type == "table"
    assert "comparison_points" in block.content
    assert "actions" not in block.content


def test_every_block_keeps_what_identifies_it():
    block = _layout_for("recommended_action", {"title": "Actions", "actions": ["대응한다"]})
    assert {"title"} <= set(block.content)


def test_an_unknown_block_type_keeps_the_full_content():
    """A new block type is never silently starved of its data."""
    from core.layout_generator.generator import _trim_content

    content = {"title": "t", "some_new_field": [1, 2]}
    assert _trim_content("brand_new_type", content) == content


# --- one claim per item, not one joined string per document -------------


def test_a_document_stating_three_risks_contributes_three_risks():
    """They survived in grounded_claims, but every field the report actually
    reads received "; ".join(...) - so a press release with a full results
    table contributed exactly as much as one with a single remark."""
    from common.contracts import DocumentAnalysis, GroundedClaim
    from core.synthesis.synthesizer import synthesize

    claims = [
        GroundedClaim(claim_id=f"c{index}", claim_type=claim_type, claim=text,
                      evidence_quote=text, confidence="high")
        for index, (claim_type, text) in enumerate(
            [("risk", "케이블TV 가입자 감소"), ("risk", "OTT 대체 심화"),
             ("risk", "위성방송 감소"), ("opportunity", "IPTV 점유율 확대"),
             ("strength", "3사 중 2위"), ("weakness", "SO 점유율 하락"),
             ("business_impact", "ARPU 압박"), ("business_impact", "결합매출 하방")],
            1,
        )
    ]
    synthesis = synthesize(
        "r", "sk_broadband",
        [DocumentAnalysis(doc_id="d:1", source_id="s", grounded_claims=claims)],
    )

    assert len(synthesis.risks) == 3
    assert len(synthesis.business_impacts) == 2
    assert len(synthesis.opportunities) == 1
    assert not any("; " in risk for risk in synthesis.risks)
    # Each still carries its own provenance marker.
    assert all("[doc_id=d:1]" in risk for risk in synthesis.risks)


def test_the_legacy_single_string_path_still_works():
    """Analyzers that have not adopted grounded claims carry one string per
    field, so there is only ever one item to pass on."""
    from common.contracts import DocumentAnalysis
    from core.synthesis.synthesizer import synthesize

    synthesis = synthesize(
        "r", "sk_broadband",
        [DocumentAnalysis(doc_id="d:1", source_id="s", risk="단일 리스크", opportunity="단일 기회")],
    )

    assert len(synthesis.risks) == 1
    assert len(synthesis.opportunities) == 1


# --- KPI: "latest" must mean latest in time -----------------------------


def test_kpi_uses_the_latest_period_not_the_last_one_emitted(monkeypatch):
    """Grouping preserves input order, so points[-1] was whichever the
    analyzer happened to emit last. An out-of-order series showed the wrong
    figure as current and inverted the delta."""
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_kpi_row([
        MetricPoint(label="매출", period="2026년", value=300, unit="억원"),
        MetricPoint(label="매출", period="2024년", value=100, unit="억원"),
        MetricPoint(label="매출", period="2025년", value=200, unit="억원"),
    ])
    body = "".join(captured)

    assert "300억원" in body
    assert "+200억원 (2024년→2026년)" in body


def test_a_non_time_axis_gets_no_delta(monkeypatch):
    """A "change" between two age brackets is meaningless."""
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_kpi_row([
        MetricPoint(label="TV 도달률", period="20대", value=22, unit="%"),
        MetricPoint(label="TV 도달률", period="50대 이상", value=68, unit="%"),
    ])
    body = "".join(captured)

    assert "2개 대상 비교" in body
    assert "+46" not in body


def test_a_sparkline_needs_three_points_in_time(monkeypatch):
    """Two points are already fully described by the delta, and a line between
    two dots implies a path the evidence never described."""
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit import components

    def render(points):
        captured: list[str] = []
        monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
        components.render_kpi_row(points)
        return "".join(captured)

    two = [MetricPoint(label="매출", period=f"202{i}년", value=100 * i, unit="억원") for i in (4, 5)]
    three = two + [MetricPoint(label="매출", period="2026년", value=300, unit="억원")]

    assert "ts-kpi-spark" not in render(two)
    assert "ts-kpi-spark" in render(three)


# --- The subject axis: who a figure was measured for --------------------


def test_one_metric_across_companies_is_a_comparison_not_a_trend():
    """Three companies' subscriber counts, all dated the same real quarter,
    used to classify as a trend because only `period` distinguished them and
    the entity had to be smuggled in there. With `subject` carrying the
    entity, the periods are identical and the shape is decided by the axis
    that actually varies."""
    from common.contracts import MetricPoint
    from common.content_quality_validator import classify_metric_shape

    points = [
        MetricPoint(label="IPTV 가입자 수", subject=name, period="2025년 2분기", value=value, unit="만명")
        for name, value in (("KT", 912), ("SK브로드밴드", 682), ("LG유플러스", 551))
    ]

    assert classify_metric_shape(points) == "comparison"


def test_a_real_trend_is_still_a_trend_when_one_subject_is_named():
    """One company over three quarters must not become a comparison just
    because `subject` is filled in."""
    from common.contracts import MetricPoint
    from common.content_quality_validator import classify_metric_shape

    points = [
        MetricPoint(label="IPTV 가입자 수", subject="SK브로드밴드", period=f"2025년 {q}분기", value=v, unit="만명")
        for q, v in ((1, 680), (2, 682), (3, 690))
    ]

    assert classify_metric_shape(points) == "line"


def test_subject_bars_are_labelled_by_subject_not_by_a_repeated_period():
    from common.block_shapes import metric_axis_labels
    from common.contracts import MetricPoint

    points = [
        MetricPoint(label="IPTV 가입자 수", subject=name, period="2025년 2분기", value=value, unit="만명")
        for name, value in (("KT", 912), ("SK브로드밴드", 682))
    ]

    assert metric_axis_labels(points) == ["KT", "SK브로드밴드"]


def test_labels_name_both_axes_when_both_vary():
    """Otherwise two rows for the same company in different quarters collide
    into one indistinguishable label."""
    from common.block_shapes import metric_axis_labels
    from common.contracts import MetricPoint

    points = [
        MetricPoint(label="가입자", subject="KT", period="2024년", value=900, unit="만명"),
        MetricPoint(label="가입자", subject="KT", period="2025년", value=912, unit="만명"),
        MetricPoint(label="가입자", subject="SKB", period="2025년", value=682, unit="만명"),
    ]

    assert metric_axis_labels(points) == ["KT (2024년)", "KT (2025년)", "SKB (2025년)"]


def test_a_kpi_reports_no_delta_between_two_different_companies(monkeypatch):
    """Both periods are real dates, so the chronological branch would have
    fired and printed a "+230만명 change" that is really the gap between two
    competitors."""
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_kpi_row([
        MetricPoint(label="가입자", subject="SK브로드밴드", period="2025년", value=682, unit="만명"),
        MetricPoint(label="가입자", subject="KT", period="2025년", value=912, unit="만명"),
    ])
    body = "".join(captured)

    assert "2개 대상 비교" in body
    assert "+230" not in body


# --- The claim behind a chart -------------------------------------------


def _claim(claim_id: str, text: str):
    from common.contracts import SynthesisClaim

    return SynthesisClaim(
        synthesis_claim_id=claim_id, claim_id="c1", claim_type="metric", claim=text,
        evidence_quote=text, confidence="high", doc_id="d1", source_id="s1",
        source_url="https://example.com/a",
    )


def test_a_chart_carries_the_claim_its_figures_came_from(monkeypatch):
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    points = [
        MetricPoint(label="가입자", period=f"202{y}년", value=v, unit="만명",
                    evidence_synthesis_claim_id="d1:c1")
        for y, v in ((3, 700), (4, 690), (5, 682))
    ]
    components.render_metric_chart(points, grounded_claims=[_claim("d1:c1", "가입자 감소가 3년째 이어졌다")])

    assert "가입자 감소가 3년째 이어졌다" in "".join(captured)


def test_an_unlinked_series_gets_no_caption_rather_than_a_written_one():
    from common.block_shapes import metric_insight
    from common.contracts import MetricPoint

    points = [MetricPoint(label="가입자", period="2025년", value=682, unit="만명")]

    assert metric_insight(points, [_claim("d1:c1", "무관한 문장")]) is None


# --- A projection is not history ----------------------------------------


def test_a_forecast_flag_is_only_honoured_when_the_source_marks_one():
    from core.report_generator.generator import _is_stated_forecast

    assert _is_stated_forecast(
        {"is_forecast": True, "period": "2026년 2분기(전망)", "source_sentence": "2분기 매출 1조를 전망했다"}
    )
    # The model calling a plainly reported figure a forecast is not enough.
    assert not _is_stated_forecast(
        {"is_forecast": True, "period": "2025년 2분기", "source_sentence": "2분기 매출은 1조였다"}
    )
    assert not _is_stated_forecast({"is_forecast": False, "period": "2026년(전망)"})


def test_a_kpi_headline_is_the_latest_observed_figure_not_the_projection(monkeypatch):
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_kpi_row([
        MetricPoint(label="매출", period="2024년", value=100, unit="억원"),
        MetricPoint(label="매출", period="2025년", value=120, unit="억원"),
        MetricPoint(label="매출", period="2026년", value=200, unit="억원", is_forecast=True),
    ])
    body = "".join(captured)

    assert "120억원" in body
    assert "200억원" not in body
    assert "+20억원 (2024년→2025년)" in body


def test_the_forecast_leg_of_a_chart_is_drawn_dashed():
    from common.contracts import MetricPoint
    from reporting.dashboard_streamlit.components import _metric_chart_svg

    svg = _metric_chart_svg([
        MetricPoint(label="매출", period="2023년", value=90, unit="억원"),
        MetricPoint(label="매출", period="2024년", value=100, unit="억원"),
        MetricPoint(label="매출", period="2025년", value=120, unit="억원"),
        MetricPoint(label="매출", period="2026년", value=200, unit="억원", is_forecast=True),
    ], "매출")

    assert "stroke-dasharray" in svg
    assert "전망(출처 제시)" in svg
