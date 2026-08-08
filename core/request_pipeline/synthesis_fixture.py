"""Load a saved synthesis so the report half of the pipeline can be re-run.

A fixture is a TrendSynthesis dump plus the three things the collection half
would otherwise have decided: the question, the audience, and the report
purpose. Those live alongside the synthesis fields in the same JSON file
rather than in CLI flags, so one file fully describes one reproducible run.

Development-only. Nothing here fabricates evidence - the fixture must already
contain whatever a real run produced, and a run driven from one is marked as
such in the pipeline trace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.contracts import CorroboratedPoint, ReportPurposeClassification, TrendSynthesis
from core.report_purpose.classifier import recommended_sections_for
from core.request_pipeline.pipeline import DEFAULT_AUDIENCE_ID

# Fields that describe the *run*, not the synthesis itself. Stripped before
# TrendSynthesis validation so a fixture stays a single self-contained file.
_RUN_FIELDS = ("question", "audience_id", "purpose_id")

# Same default the live pipeline uses - see DEFAULT_AUDIENCE_ID there. These
# were "_default" and "practitioner" respectively, so a fixture that omitted
# audience_id silently produced a different report than the live path would.
_DEFAULT_AUDIENCE_ID = DEFAULT_AUDIENCE_ID
_DEFAULT_PURPOSE_ID = "current_status"


_CORROBORATED_POINT_FIELDS = ("corroborated_points", "uncorroborated_points")


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept the shorthand a hand-written fixture naturally uses.

    `corroborated_points`/`uncorroborated_points` are both lists of
    CorroboratedPoint in the contract, but a fixture written by hand states
    the claim as a bare string. Promoting it here keeps fixtures readable
    without loosening the contract itself - the supporting doc/source ids
    stay empty rather than being invented.
    """
    normalized = {key: value for key, value in payload.items() if not key.startswith("_")}
    for field in _CORROBORATED_POINT_FIELDS:
        points = normalized.get(field)
        if isinstance(points, list):
            normalized[field] = [
                {"claim": point} if isinstance(point, str) else point for point in points
            ]
    return normalized


def load_synthesis_fixture(path: str | Path) -> tuple[TrendSynthesis, str, str, ReportPurposeClassification]:
    """Return (synthesis, question, audience_id, report_purpose) from a fixture."""
    payload = _normalize(json.loads(Path(path).read_text(encoding="utf-8")))
    question = payload.get("question") or ""
    audience_id = payload.get("audience_id") or _DEFAULT_AUDIENCE_ID
    purpose_id = payload.get("purpose_id") or _DEFAULT_PURPOSE_ID

    synthesis = TrendSynthesis.model_validate(
        {key: value for key, value in payload.items() if key not in _RUN_FIELDS}
    )
    purpose = ReportPurposeClassification(
        request_id=synthesis.request_id,
        purpose_id=purpose_id,
        display_name=purpose_id,
        # Same recipe the live classifier would apply for this purpose, so a
        # fixture run exercises the real section structure rather than a
        # hand-listed one that could drift away from it.
        recommended_sections=recommended_sections_for(purpose_id),
    )
    return synthesis, question, audience_id, purpose


def validate_purpose_id(purpose_id: str) -> bool:
    return bool(recommended_sections_for(purpose_id))
