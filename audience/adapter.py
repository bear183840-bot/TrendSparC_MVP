"""Adapt a TrendSynthesis + ReportPlan into an AudienceAdaptation.

Driven entirely by the audience's registered profile — never by comparing
audience_id against a literal name.
"""

from __future__ import annotations

from audience.contracts import load_audience_profile
from common.contracts import AudienceAdaptation, ReportPlan, TrendSynthesis


def adapt_for_audience(
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
) -> AudienceAdaptation:
    profile = load_audience_profile(audience_id)

    adapted_sections = {
        section: {
            "detail_level": profile.detail_level,
            "focus": profile.focus,
            "highlights": synthesis.highlights,
        }
        for section in report_plan.sections
    }

    return AudienceAdaptation(
        request_id=report_plan.request_id,
        audience_id=profile.audience_id,
        tone=profile.tone,
        adapted_sections=adapted_sections,
    )
