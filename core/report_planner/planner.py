"""Build a ReportPlan from a TrendSynthesis and the target audience profile.

The section list and output format are derived from the audience profile's
declared focus/format_preference — no audience-name branching here either.
"""

from __future__ import annotations

from audience.contracts import load_audience_profile
from common.contracts import ReportPlan, TrendSynthesis

_BASE_SECTIONS = ["overview", "key_points"]


def plan_report(synthesis: TrendSynthesis, audience_id: str) -> ReportPlan:
    profile = load_audience_profile(audience_id)
    sections = _BASE_SECTIONS + list(profile.focus)

    return ReportPlan(
        request_id=synthesis.request_id,
        audience_id=profile.audience_id,
        sections=sections,
        format=profile.format_preference,
    )
