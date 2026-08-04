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


# When a section legitimately qualifies for more than one structured type
# (e.g. it has both a 2+ point metric series AND a SWOT split), the audience
# decides which one wins - see AudienceAdaptation.audience_id / the audience
# priority table in the feature plan (external -> big picture, practitioner
# -> detail, executive/management -> headline numbers).
_AUDIENCE_TYPE_PRIORITY: dict[str, list[str]] = {
    "external": ["matrix", "chart"],
    "practitioner": ["table", "list"],
    "executive": ["metrics", "list"],
    "management": ["metrics", "chart"],
}


def _candidate_content_types(content: dict) -> list[str]:
    """Which structured block_types this section's content actually supports.

    Never invents a type the content doesn't back - a "chart" only qualifies
    when 2+ distinct time periods are present, a "table" only when 2+ distinct
    entities are being compared, and "matrix" (SWOT) only when at least two of
    the four strength/weakness/risk/opportunity fields have real content.
    """
    candidates: list[str] = []
    metric_points = content.get("metric_points") or []
    periods = {point.get("period") for point in metric_points if isinstance(point, dict)}
    if len(periods) >= 2:
        candidates.append("chart")
    comparison_points = content.get("comparison_points") or []
    entities = {point.get("entity") for point in comparison_points if isinstance(point, dict)}
    if len(entities) >= 2:
        candidates.append("table")
    swot_fields = ("strengths", "weaknesses", "risks", "opportunities")
    if sum(1 for field in swot_fields if content.get(field)) >= 2:
        candidates.append("matrix")
    return candidates


def _block_type(section: str, content: dict, audience_id: str | None = None) -> str:
    """Choose a semantic UI slot from the section's actual structured content
    first; only fall back to the static per-section table when nothing
    structured exists. This deliberately inverts the old precedence (section
    name first) so a section never gets stuck as a text list just because its
    name isn't in the static table, and never gets a chart/table it has no
    real data to back."""
    candidates = _candidate_content_types(content)
    if len(candidates) > 1 and audience_id:
        for preferred in _AUDIENCE_TYPE_PRIORITY.get(audience_id, []):
            if preferred in candidates:
                return preferred
    if candidates:
        return candidates[0]
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
                block_type=_block_type(section, content, report_plan.audience_id),
                content=content,
            )
        )

    return DynamicLayout(
        request_id=report_plan.request_id,
        format=report_plan.format,
        blocks=blocks,
        render_target=report_plan.format,
    )
