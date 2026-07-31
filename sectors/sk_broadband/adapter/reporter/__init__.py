"""SK Broadband sector reporter helper."""

from __future__ import annotations

from common.contracts import ReportPlan, TrendSynthesis


def report(report_plan: ReportPlan, synthesis: TrendSynthesis) -> dict:
    return {
        "sector_id": synthesis.sector_id,
        "audience_id": report_plan.audience_id,
        "primary_intent": report_plan.primary_intent,
        "report_purpose": report_plan.report_purpose.purpose_id if report_plan.report_purpose else None,
        "sections": report_plan.sections,
        "source_count": synthesis.source_count,
        "synthesis_text": synthesis.synthesis_text,
        "highlights": synthesis.highlights,
    }
