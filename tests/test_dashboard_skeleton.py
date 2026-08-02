from common.contracts import AudienceAdaptation, DashboardBlock, ReportPlan
from core.layout_generator.generator import generate_layout
from reporting.dashboard_streamlit.renderer import normalized_block_type


def test_layout_generator_emits_purpose_specific_semantic_blocks():
    plan = ReportPlan(
        request_id="req_dashboard",
        audience_id="executive",
        primary_intent="issue_response",
        sections=["overview", "issue", "impact", "response_actions"],
        format="dashboard",
    )
    adaptation = AudienceAdaptation(
        request_id="req_dashboard",
        audience_id="executive",
        adapted_sections={
            "executive_summary": {"title": "요약", "summary": "핵심 결론"},
            "overview": {"title": "Overview", "summary": "전체 맥락"},
            "issue": {"title": "Issue", "risks": ["위험"]},
            "impact": {"title": "Impact", "key_points": ["영향"]},
            "response_actions": {"title": "Action", "actions": ["대응"]},
        },
    )

    layout = generate_layout(plan, adaptation)

    assert [block.section for block in layout.blocks] == [
        "executive_summary", "overview", "issue", "impact", "response_actions",
    ]
    assert [block.block_type for block in layout.blocks] == [
        "text", "text", "matrix", "metrics", "list",
    ]
    assert all(block.data is None and block.config == {} for block in layout.blocks)
    assert layout.blocks[0].block_id == "01_executive_summary"


def test_dashboard_block_accepts_future_visualization_payloads_without_contract_change():
    chart = DashboardBlock(
        block_id="market_trend",
        section="market_status",
        block_type="chart",
        data={"rows": [{"period": "2026-Q1", "value": 10}]},
        config={"x": "period", "y": "value"},
    )
    future_unknown = DashboardBlock(
        block_id="future_component",
        section="opportunity",
        block_type="design_component_v2",
        data={"anything": True},
    )

    assert normalized_block_type(chart) == "chart"
    assert normalized_block_type(future_unknown) == "custom"
    assert future_unknown.block_type == "design_component_v2"
