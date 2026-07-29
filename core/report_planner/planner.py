"""Build a ReportPlan from a TrendSynthesis, the target audience profile,
and the question's classified intent.

The section list and output format are derived from the audience profile's
declared focus/format_preference — no audience-name branching here either.
`primary_intent` is carried onto the ReportPlan and, if a matching file
exists under prompts/report_structures/, its (currently template-only)
content is attached as `intent_emphasis` — this is a structural extension
point only: no per-intent differentiation logic exists yet. The team will
design what each report type should actually emphasize and fill in those
files later; an unrecognized or not-yet-authored intent value is not an
error, it just means no extra emphasis is attached.
"""

from __future__ import annotations

from pathlib import Path

from audience.contracts import load_audience_profile
from common.contracts import ReportPlan, TrendSynthesis

_BASE_SECTIONS = ["overview", "key_points"]
_REPORT_STRUCTURES_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "report_structures"


def _load_intent_emphasis(primary_intent: str) -> str | None:
    path = _REPORT_STRUCTURES_DIR / f"{primary_intent}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def plan_report(synthesis: TrendSynthesis, audience_id: str, primary_intent: str) -> ReportPlan:
    profile = load_audience_profile(audience_id)
    sections = _BASE_SECTIONS + list(profile.focus)

    return ReportPlan(
        request_id=synthesis.request_id,
        audience_id=profile.audience_id,
        primary_intent=primary_intent,
        sections=sections,
        format=profile.format_preference,
        intent_emphasis=_load_intent_emphasis(primary_intent),
    )
