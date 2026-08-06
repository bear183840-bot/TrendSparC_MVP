"""Persist a compact record of every pipeline run.

Diagnosing "the dashboard keeps showing the same thing" previously meant
reconstructing runs from whatever happened to be pasted into a chat, because
nothing was kept on disk. This module writes one small JSON file per run so
questions like "how often does a section get omitted for lack of evidence?"
or "how many numeric facts never reach metric_series?" can be answered from
real history instead of a handful of remembered cases.

Deliberately records *shape*, not content: counts, ids, section names and
stage statuses, plus the question itself. Full document markdown is left out
- it is large, it is the bulk of what makes a run heavy, and none of the
questions above need it. Archiving never affects the run: any failure here is
swallowed with a note to stderr, because losing a diagnostic record must not
cost the user their report.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = _PROJECT_ROOT / "storage" / "requests"


def _metric_shape_counts(metric_series: list[Any]) -> dict[str, int]:
    """How many distinct periods each metric label spans - the thing that
    decides whether a metric can be a chart, a before/after bar, or only a
    single KPI figure."""
    periods_by_label: dict[str, set[str]] = {}
    for point in metric_series:
        if point.label:
            periods_by_label.setdefault(point.label, set()).add(point.period or "")
    return {label: len(periods) for label, periods in periods_by_label.items()}


def build_run_record(result: Any, question: str, audience_id: str | None = None) -> dict:
    synthesis = result.synthesis
    plan = result.report_plan
    report = result.generated_report
    return {
        "request_id": result.request_id,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "audience_id": audience_id or (plan.audience_id if plan else None),
        "sector_id": result.sector_route.sector_id if result.sector_route else None,
        "purpose_id": result.report_purpose.purpose_id if result.report_purpose else None,
        "secondary_purpose_id": (
            result.report_purpose.secondary_purpose_id if result.report_purpose else None
        ),
        "halted_at_stage": result.halted_at_stage,
        "trace": [
            {"stage": trace.stage, "status": trace.status.value, "reason": trace.reason}
            for trace in result.trace
        ],
        "collection": {
            "events": [
                {
                    "source": event.source_name,
                    "status": event.status,
                    "documents": event.document_count,
                    "detail": event.detail,
                }
                for event in result.collection_events
            ],
            "collected_document_count": len(result.collected_source_documents),
        },
        "analysis": {
            "analyzed_document_count": len(result.document_analyses),
            "source_count": synthesis.source_count if synthesis else 0,
            "unique_source_count": synthesis.unique_source_count if synthesis else 0,
        },
        # The numbers this diagnosis actually turns on: how much structured,
        # chartable evidence a question ended up with.
        "structured_evidence": {
            "metric_point_count": len(synthesis.metric_series) if synthesis else 0,
            "metric_periods_by_label": _metric_shape_counts(synthesis.metric_series) if synthesis else {},
            "comparison_point_count": len(synthesis.comparison_points) if synthesis else 0,
            "grounded_claim_count": len(synthesis.grounded_claims) if synthesis else 0,
            "evidence_sentence_count": len(synthesis.evidence) if synthesis else 0,
        },
        "report": {
            "sections": list(plan.sections) if plan else [],
            "omitted_sections": dict(plan.omitted_sections) if plan else {},
            "generation_mode": report.generation_mode if report else None,
            "limitations": list(report.limitations) if report else [],
        },
        "layout_block_types": (
            [block.block_type for block in result.layout.blocks] if result.layout else []
        ),
    }


def archive_run(result: Any, question: str, audience_id: str | None = None) -> Path | None:
    """Write the run record. Returns the path, or None if archiving failed."""
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        path = ARCHIVE_DIR / f"{result.request_id}.json"
        record = build_run_record(result, question, audience_id)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001
        print(f"[run_archive] could not archive {result.request_id}: {exc}", file=sys.stderr)
        return None
