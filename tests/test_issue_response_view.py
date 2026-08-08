from types import SimpleNamespace

from common.contracts import DocumentAnalysis, GeneratedReport, GeneratedReportSection, PlannedSource, SourcePlan, TrendSynthesis
from reporting.dashboard_streamlit import issue_response_view as view


def _result():
    competitor = PlannedSource(
        name="KT 뉴스룸",
        url="https://example.com/kt",
        role="competitor_official",
    )
    market = PlannedSource(
        name="시장 보고서",
        url="https://example.com/market",
        role="market_analysis",
    )
    return SimpleNamespace(
        source_plan=SourcePlan(
            request_id="req_ui",
            sector_id="sk_broadband",
            planned_sources=[competitor, market],
        ),
        document_analyses=[
            DocumentAnalysis(
                doc_id="kt:1",
                source_id="KT 뉴스룸",
                summary="경쟁 서비스가 개인화를 강화했다.",
                key_points=["경쟁 서비스의 AI 추천 기능이 확대됐다."],
                analysis_confidence="high",
            ),
            DocumentAnalysis(
                doc_id="market:1",
                source_id="시장 보고서",
                summary="OTT 이용이 증가했다.",
                key_points=["OTT 이용시간 증가가 확인됐다."],
                analysis_confidence="medium",
            ),
        ],
        synthesis=TrendSynthesis(
            request_id="req_ui",
            sector_id="sk_broadband",
            synthesis_text="IPTV 경쟁력 방어를 위한 대응이 필요하다.",
            source_count=2,
            unique_source_count=2,
            risks=["가입자 이탈 위험 [doc_id=kt:1]"],
            opportunities=["AI 추천 강화 기회 [doc_id=market:1]"],
            recommended_actions=["추천 서비스를 고도화한다. [doc_id=kt:1]"],
            business_impacts=["가입자 유지율 개선 가능성"],
            evidence=["경쟁 서비스의 개인화 확대 [doc_id=kt:1]"],
            monitoring_indicators=["월별 해지율"],
        ),
        generated_report=None,
    )


def test_competitor_and_market_cards_only_use_matching_registered_source_roles():
    result = _result()

    competitor_rows = view._points_for_roles(result, {"competitor_official"})
    market_rows = view._points_for_roles(result, {"market_analysis"})

    assert competitor_rows[0][0] == "KT 뉴스룸"
    assert "AI 추천" in competitor_rows[0][1]
    assert market_rows[0][0] == "시장 보고서"


def test_action_evidence_link_resolves_from_doc_id_to_registered_source_url():
    result = _result()

    assert view._evidence_url("추천 서비스를 고도화한다. [doc_id=kt:1]", result) == "https://example.com/kt"


def test_dashboard_does_not_invent_reference_mockup_scores_or_time_series(monkeypatch):
    captured = []
    monkeypatch.setattr(view.st, "markdown", lambda body, **kwargs: captured.append(body))

    view.render_issue_response_dashboard(
        _result(),
        "IPTV와 OTT 경쟁 심화의 영향은?",
        "SK브로드밴드",
        "경영진",
        "이슈 대응",
    )

    output = "\n".join(captured)
    assert "SWOT" in output
    assert "실행 제안" in output
    assert "Medium" not in output
    assert "2025E" not in output
    assert "https://example.com/kt" in output


def test_dashboard_prefers_audience_tailored_generated_report_over_raw_synthesis(monkeypatch):
    """Once report_generator.py's OpenAI pass actually writes audience-tailored
    risks/opportunities/actions, the dashboard should show that writing, not
    the raw audience-agnostic synthesis list it was built from - proves the
    audience-content wiring actually reaches the rendered page, not just the
    unread audience_adaptation/layout debug dump."""
    captured = []
    monkeypatch.setattr(view.st, "markdown", lambda body, **kwargs: captured.append(body))

    result = _result()
    result.generated_report = GeneratedReport(
        request_id="req_ui",
        sector_id="sk_broadband",
        audience_id="executive",
        purpose_id="issue_response",
        title="경영진 보고서",
        generation_mode="openai",
        sections=[
            GeneratedReportSection(
                section_id="issue",
                title="Issue",
                risks=["경영진 관점 압축 위험 서술 [doc_id=kt:1]"],
                opportunities=["경영진 관점 압축 기회 서술 [doc_id=market:1]"],
                actions=["경영진 관점 실행안 [doc_id=kt:1]"],
            ),
        ],
    )

    view.render_issue_response_dashboard(
        result,
        "IPTV와 OTT 경쟁 심화의 영향은?",
        "SK브로드밴드",
        "경영진",
        "이슈 대응",
    )

    output = "\n".join(captured)
    assert "경영진 관점 압축 위험 서술" in output
    assert "경영진 관점 압축 기회 서술" in output
    assert "경영진 관점 실행안" in output
    assert "가입자 이탈 위험" not in output
    assert "AI 추천 강화 기회" not in output
    assert "추천 서비스를 고도화한다" not in output
