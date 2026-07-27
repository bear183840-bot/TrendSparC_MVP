"""Build a DynamicLayout structural skeleton from a ReportPlan + AudienceAdaptation.

Produces block placement only (which section goes where, in what render
target) — never renders actual markup or content. Rendering is owned by
reporting/{dashboard_streamlit,html,pdf}.
"""

from __future__ import annotations

from common.contracts import AudienceAdaptation, DynamicLayout, ReportPlan


def generate_layout(report_plan: ReportPlan, adaptation: AudienceAdaptation) -> DynamicLayout:
    blocks = [
        {
            "section": section,
            "content": adaptation.adapted_sections.get(section, {}),
        }
        for section in report_plan.sections
    ]

    return DynamicLayout(
        request_id=report_plan.request_id,
        format=report_plan.format,
        blocks=blocks,
        render_target=report_plan.format,
    )
