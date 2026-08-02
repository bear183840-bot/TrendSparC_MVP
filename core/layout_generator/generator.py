"""Build a DynamicLayout structural skeleton from a ReportPlan + AudienceAdaptation.

Produces block placement only (which section goes where, in what render
target) — never renders actual markup or content. Rendering is owned by
reporting/{dashboard_streamlit,html,pdf}.
"""

from __future__ import annotations

from common.contracts import AudienceAdaptation, DashboardBlock, DynamicLayout, ReportPlan


_SECTION_BLOCK_TYPES = {
    "executive_summary": "text",
    "overview": "text",
    "current_situation": "metrics",
    "market_status": "chart",
    "near_term_outlook": "timeline",
    "issue": "matrix",
    "impact": "metrics",
    "response_actions": "list",
    "trend": "chart",
    "opportunity": "matrix",
    "investment_signal": "metrics",
    "strategic_recommendation": "list",
    "problem": "text",
    "root_cause": "graph",
    "improvement_plan": "list",
    "key_implication": "text",
    "risk_and_opportunity": "matrix",
    "recommended_action": "list",
    "key_metrics": "metrics",
    "timeline": "timeline",
    "decision_required": "list",
    "risk": "matrix",
    "sources": "evidence",
}


def _block_type(section: str, content: dict) -> str:
    """Choose a semantic UI slot without inventing chart data."""
    if section in _SECTION_BLOCK_TYPES:
        return _SECTION_BLOCK_TYPES[section]
    if content.get("actions"):
        return "list"
    if content.get("evidence"):
        return "evidence"
    return "auto"


def _block_title(section: str, content: dict) -> str:
    return content.get("title") or section.replace("_", " ").title()


def generate_layout(report_plan: ReportPlan, adaptation: AudienceAdaptation) -> DynamicLayout:
    section_order = list(report_plan.sections)
    if "executive_summary" in adaptation.adapted_sections:
        section_order.insert(0, "executive_summary")
    blocks = []
    for index, section in enumerate(section_order):
        content = adaptation.adapted_sections.get(section, {})
        blocks.append(
            DashboardBlock(
                block_id=f"{index + 1:02d}_{section}",
                section=section,
                title=_block_title(section, content),
                block_type=_block_type(section, content),
                content=content,
            )
        )

    return DynamicLayout(
        request_id=report_plan.request_id,
        format=report_plan.format,
        blocks=blocks,
        render_target=report_plan.format,
    )
