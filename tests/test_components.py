from common.contracts import ComparisonPoint, GeneratedReport, GeneratedReportSection, MetricPoint
from reporting.dashboard_streamlit import components
from reporting.dashboard_streamlit.components import prefer_audience_content, prefer_audience_content_raw


def _report(generation_mode: str, sections: list[GeneratedReportSection]) -> GeneratedReport:
    return GeneratedReport(
        request_id="req_1",
        sector_id="sk_broadband",
        audience_id="executive",
        purpose_id="issue_response",
        title="title",
        sections=sections,
        generation_mode=generation_mode,
    )


def test_prefers_openai_written_content_over_synthesis():
    report = _report(
        "openai",
        [GeneratedReportSection(section_id="issue", title="Issue", risks=["임원용으로 압축된 위험 [doc_id=a:1]"])],
    )

    result = prefer_audience_content(report, "risks", ["원본 위험 신호 [doc_id=a:1]"])

    assert result == ["임원용으로 압축된 위험"]


def test_falls_back_to_synthesis_when_rule_based():
    report = _report(
        "rule_based",
        [GeneratedReportSection(section_id="issue", title="Issue", risks=["규칙 기반 위험 [doc_id=a:1]"])],
    )

    result = prefer_audience_content(report, "risks", ["원본 위험 신호 [doc_id=a:1]"])

    assert result == ["원본 위험 신호"]


def test_falls_back_to_synthesis_when_openai_report_has_no_content_for_field():
    report = _report("openai", [GeneratedReportSection(section_id="issue", title="Issue")])

    result = prefer_audience_content(report, "risks", ["원본 위험 신호 [doc_id=a:1]"])

    assert result == ["원본 위험 신호"]


def test_falls_back_to_synthesis_when_report_is_none():
    result = prefer_audience_content(None, "risks", ["원본 위험 신호 [doc_id=a:1]"])

    assert result == ["원본 위험 신호"]


def test_merges_across_every_section():
    report = _report(
        "openai",
        [
            GeneratedReportSection(section_id="issue", title="Issue", opportunities=["기회 A [doc_id=a:1]"]),
            GeneratedReportSection(section_id="impact", title="Impact", opportunities=["기회 B [doc_id=b:1]"]),
        ],
    )

    result = prefer_audience_content(report, "opportunities", [])

    assert result == ["기회 A", "기회 B"]


def test_raw_variant_keeps_doc_id_markers_intact():
    report = _report(
        "openai",
        [GeneratedReportSection(section_id="response_actions", title="Action", actions=["실행안 A [doc_id=a:1]"])],
    )

    result = prefer_audience_content_raw(report, "actions", [])

    assert result == ["실행안 A [doc_id=a:1]"]


# --- KPI relevance / metric shape branching (render_kpi_row / render_metric_chart /
# render_metric_bar) - regression coverage for the req_cli_3093052e bug report:
# an irrelevant 채널 순위 metric crowding out 가입자 수, and 시청률's 2-point
# "도입 전"/"도입 후" series getting forced into a line chart. ---


def test_render_kpi_row_ranks_question_relevant_metric_first(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **kwargs: captured.append(body))

    metric_points = [
        MetricPoint(label="채널 순위", period="2024년", value=5.0, unit="위"),
        MetricPoint(label="IPTV 가입자 수", period="2024년", value=650.0, unit="만 명"),
    ]
    components.render_kpi_row(metric_points, question_terms=["가입자", "수"])

    output = captured[0]
    assert output.index("IPTV 가입자 수") < output.index("채널 순위")


def test_render_kpi_row_never_drops_a_low_relevance_metric_within_limit(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **kwargs: captured.append(body))

    metric_points = [
        MetricPoint(label="채널 순위", period="2024년", value=5.0, unit="위"),
        MetricPoint(label="IPTV 가입자 수", period="2024년", value=650.0, unit="만 명"),
    ]
    components.render_kpi_row(metric_points, question_terms=["가입자"])

    assert "채널 순위" in captured[0]


def test_render_metric_chart_only_plots_line_shaped_series(monkeypatch):
    captured_chart: list = []
    monkeypatch.setattr(components.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(components.st, "line_chart", lambda data, **kwargs: captured_chart.append(data))

    metric_points = [
        MetricPoint(label="IPTV 가입자 수", period="2022년", value=520.0, unit="만 명"),
        MetricPoint(label="IPTV 가입자 수", period="2023년", value=610.0, unit="만 명"),
        MetricPoint(label="IPTV 가입자 수", period="2024년", value=650.0, unit="만 명"),
        MetricPoint(label="시청률", period="도입 전", value=3.2, unit="%"),
        MetricPoint(label="시청률", period="도입 후", value=4.1, unit="%"),
    ]
    components.render_metric_chart(metric_points)

    assert len(captured_chart) == 1
    plotted = captured_chart[0]
    assert "IPTV 가입자 수" in plotted.columns
    assert "시청률" not in plotted.columns


def test_render_metric_chart_is_a_no_op_when_nothing_is_line_shaped(monkeypatch):
    captured_chart: list = []
    monkeypatch.setattr(components.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(components.st, "line_chart", lambda data, **kwargs: captured_chart.append(data))

    metric_points = [
        MetricPoint(label="시청률", period="도입 전", value=3.2, unit="%"),
        MetricPoint(label="시청률", period="도입 후", value=4.1, unit="%"),
    ]
    components.render_metric_chart(metric_points)

    assert captured_chart == []


def test_render_metric_bar_shows_both_periods_of_a_two_point_label(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **kwargs: captured.append(body))

    components.render_metric_bar(
        [
            MetricPoint(label="시청률", period="도입 전", value=3.2, unit="%"),
            MetricPoint(label="시청률", period="도입 후", value=4.1, unit="%"),
        ]
    )

    output = captured[0]
    assert "도입 전" in output
    assert "도입 후" in output
    assert "시청률" in output


def test_render_metric_bar_is_a_no_op_for_a_single_point(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **kwargs: captured.append(body))

    components.render_metric_bar([MetricPoint(label="채널 순위", period="2024년", value=5.0, unit="위")])

    assert captured == []


def test_has_timeseries_and_has_bar_metrics_split_by_label_shape():
    metric_points = [
        MetricPoint(label="IPTV 가입자 수", period="2022년", value=520.0, unit="만 명"),
        MetricPoint(label="IPTV 가입자 수", period="2023년", value=610.0, unit="만 명"),
        MetricPoint(label="IPTV 가입자 수", period="2024년", value=650.0, unit="만 명"),
        MetricPoint(label="시청률", period="도입 전", value=3.2, unit="%"),
        MetricPoint(label="시청률", period="도입 후", value=4.1, unit="%"),
    ]
    assert components.has_timeseries(metric_points) is True
    assert components.has_bar_metrics(metric_points) is True
    groups = components.bar_metric_groups(metric_points)
    assert len(groups) == 1
    assert {point.label for point in groups[0]} == {"시청률"}


# --- Comparison table shared-axis filtering (problem 3) ---


def test_has_comparison_false_when_entities_share_no_criterion():
    points = [
        ComparisonPoint(entity="자사", criterion="국내 월간 이용자 수", value="200만 명"),
        ComparisonPoint(entity="KT", criterion="해외 진출 현황", value="없음"),
    ]
    assert components.has_comparison(points) is False


def test_comparison_points_to_table_drops_unshared_criterion_columns():
    points = [
        ComparisonPoint(entity="자사", criterion="요금제 가격", value="9,900원"),
        ComparisonPoint(entity="KT", criterion="요금제 가격", value="10,900원"),
        ComparisonPoint(entity="자사", criterion="국내 월간 이용자 수", value="200만 명"),
    ]
    headers, _rows = components.comparison_points_to_table(points)
    assert headers == ["요금제 가격"]


# --- SWOT empty-state wording (problem 4) ---


def test_render_swot_empty_state_names_which_quadrant_lacks_evidence():
    markup = components.render_swot(strengths=[], weaknesses=[], opportunities=[], threats=[])
    assert "관련 데이터 수집 필요 (강점 근거 미확인)" in markup
    assert "관련 데이터 수집 필요 (약점 근거 미확인)" in markup
