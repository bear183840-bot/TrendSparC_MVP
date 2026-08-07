"""Build a DynamicLayout structural skeleton from a ReportPlan + AudienceAdaptation.

Produces block placement only (which section goes where, in what render
target) — never renders actual markup or content. Rendering is owned by
reporting/{dashboard_streamlit,html,pdf}.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from common.content_quality_validator import dated_items, is_time_period
from common.contracts import AudienceAdaptation, DashboardBlock, DynamicLayout, ReportPlan

_LOGGER = logging.getLogger("trendsparc.layout_generator")
_DOC_ID_RE = re.compile(r"\[doc_id=([^\]]+)\]")

# Candidate new block_type detections - logged only, never used to pick a
# type automatically ("detect, don't auto-generate" - a human decides whether
# a section's unrecognized structured field is worth a real block; see
# reporting/dashboard_streamlit/blocks/'s registration checklist). Kept local
# to core/ rather than importing reporting/dashboard_streamlit's block
# registry, since core must stay renderer-agnostic (this module's docstring:
# rendering is owned by reporting/{dashboard_streamlit,html,pdf}, not core).
SUGGESTED_BLOCK_TYPES: list[dict[str, Any]] = []

_KNOWN_CONTENT_KEYS = {
    "title", "section_id", "summary", "highlights", "key_points", "evidence",
    "risks", "opportunities", "strengths", "weaknesses", "actions",
    "metric_points", "comparison_points", "monitoring_indicators",
    "business_impacts", "source_count", "unique_source_count", "limitations",
    "grounded_claims", "conclusions", "label", "value", "delta", "items",
}


def _suggest_new_block_type(section: str, content: dict) -> None:
    unknown_keys = sorted(
        key
        for key, value in content.items()
        if key not in _KNOWN_CONTENT_KEYS
        and isinstance(value, list)
        and value
        and all(isinstance(item, dict) for item in value)
    )
    if not unknown_keys:
        return
    entry = {"section": section, "content_keys": unknown_keys}
    SUGGESTED_BLOCK_TYPES.append(entry)
    _LOGGER.info(
        "candidate new block type for section '%s': unrecognized structured field(s) %s", section, unknown_keys
    )


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
# (e.g. it has both a 2+ point metric series AND a SWOT split), the report's
# *purpose* breaks the tie, from the block hints its recipe already declares
# (core/report_purpose/classifier.py). This used to be keyed on audience,
# which meant asking the same question as an executive rather than a
# practitioner silently changed the report's block structure - audience is
# supposed to decide tone and detail, purpose decides shape. Hints that don't
# name a real block_type (e.g. "issue_summary") simply never match, and the
# data-shape ordering below stands.
def _purpose_preferred_types(report_purpose) -> list[str]:
    return list(getattr(report_purpose, "dashboard_block_hints", None) or [])


def _candidate_content_types(content: dict) -> list[str]:
    """Which structured block_types this section's content actually supports.

    Never invents a type the content doesn't back - a "chart" only qualifies
    when a single metric has 2+ distinct time periods (two *different*
    metrics each contributing one period is not a trend, it's two unrelated
    numbers that would render as a disjointed, unreadable chart - see
    reporting/dashboard_streamlit/components.py's has_timeseries()), a
    "table" only when 2+ distinct entities are being compared, and "matrix"
    (SWOT) only when at least two of the four
    strength/weakness/risk/opportunity fields have real content.
    """
    candidates: list[str] = []
    metric_points = content.get("metric_points") or []
    periods_by_label: dict[Any, set] = {}
    time_periods_by_label: dict[Any, set] = {}
    for point in metric_points:
        if isinstance(point, dict):
            label, period = point.get("label"), point.get("period")
            periods_by_label.setdefault(label, set()).add(period)
            if is_time_period(period):
                time_periods_by_label.setdefault(label, set()).add(period)
    # Same thresholds the live path uses (content_quality_validator
    # .classify_metric_shape): 3+ points in time is a line, exactly 2 is a
    # before/after bar, and 2+ points that are *not* times are an item
    # comparison - also a bar. The same metric measured against two age
    # brackets ("20대" vs "50대 이상") is not a movement over time, and this
    # module used to call both of those cases "chart" while the dashboard
    # called them "bar", so the two disagreed about identical data.
    if any(len(periods) >= 3 for periods in time_periods_by_label.values()):
        candidates.append("chart")
    elif any(len(periods) >= 2 for periods in periods_by_label.values()):
        candidates.append("bar")
    comparison_points = content.get("comparison_points") or []
    entities = {point.get("entity") for point in comparison_points if isinstance(point, dict)}
    if len(entities) >= 2:
        candidates.append("table")
    swot_fields = ("strengths", "weaknesses", "risks", "opportunities")
    if sum(1 for field in swot_fields if content.get(field)) >= 2:
        candidates.append("matrix")
    return candidates


# block_types the static per-section table assigns purely by section name
# that also make an implicit claim about the content's *shape* - never
# trust these without checking, since a section named "market_status"/
# "near_term_outlook" doesn't guarantee its content is actually chartable
# or chronologically ordered.
_MIN_TIMELINE_DATED_ITEMS = 2


def _has_genuine_timeline_data(content: dict) -> bool:
    """"timeline" is only earned by >= 2 distinct dated items (key_points/
    evidence carrying a concrete year/quarter/date marker, see
    content_quality_validator.dated_items) - a single-period metric or
    undated prose isn't a real timeline, just a section that happens to be
    *named* one."""
    candidate_items = [*(content.get("key_points") or []), *(content.get("evidence") or [])]
    return len(dated_items(candidate_items)) >= _MIN_TIMELINE_DATED_ITEMS


def _block_type(section: str, content: dict, preferred_types: list[str] | None = None) -> str:
    """Choose a semantic UI slot from the section's actual structured content
    first; only fall back to the static per-section table when nothing
    structured exists. This deliberately inverts the old precedence (section
    name first) so a section never gets stuck as a text list just because its
    name isn't in the static table, and never gets a chart/table it has no
    real data to back."""
    candidates = _candidate_content_types(content)
    if len(candidates) > 1:
        for preferred in preferred_types or []:
            if preferred in candidates:
                return preferred
    if candidates:
        return candidates[0]
    static_type = _SECTION_BLOCK_TYPES.get(section)
    if static_type == "chart":
        # _candidate_content_types() above is the one true test for "chart"
        # (2+ distinct periods for one metric label) and already didn't
        # qualify, or we wouldn't have reached this fallback - never assign
        # it just because the section is *named* market_status/trend.
        static_type = None
    elif static_type == "timeline" and not _has_genuine_timeline_data(content):
        static_type = None
    if static_type:
        return static_type
    if content.get("actions"):
        return "list"
    # Prose bullets are a text block. Without this, any section whose static
    # type was withdrawn for lack of qualifying data (e.g. "trend", mapped to
    # chart but holding only narrative key_points) fell all the way through to
    # "auto" - which means "no idea what this is" and asks for a new block
    # type, when plain text was the right answer all along.
    if content.get("key_points") or content.get("opportunities") or content.get("risks"):
        return "text"
    if content.get("evidence"):
        return "evidence"
    _suggest_new_block_type(section, content)
    return "auto"


# What each block type actually reads. A DashboardBlock used to carry the
# whole GeneratedReportSection dump, so an action list shipped empty
# metric_points/comparison_points/strengths/weaknesses and a KPI block shipped
# empty actions - twelve keys on every block, most of them [] - and a reader
# of the contract could not tell which fields a block type even uses.
#
# Anything not listed falls back to the full content, so a new block type is
# never silently starved; add it here when you add the type.
_ALWAYS_KEPT = ("section_id", "title", "summary", "confidence")
_BLOCK_CONTENT_FIELDS: dict[str, tuple[str, ...]] = {
    "text": ("key_points", "evidence", "grounded_claims", "conclusions"),
    "metrics": ("metric_points", "evidence", "monitoring_indicators"),
    "chart": ("metric_points", "evidence"),
    "bar": ("metric_points", "evidence"),
    "table": ("comparison_points", "evidence"),
    "matrix": ("strengths", "weaknesses", "opportunities", "risks"),
    "timeline": ("key_points", "evidence"),
    "list": ("actions", "monitoring_indicators", "evidence"),
    "graph": ("risks", "key_points", "evidence"),
    "evidence": ("evidence", "source_count", "unique_source_count", "limitations"),
}


def _trim_content(block_type: str, content: dict) -> dict:
    """Keep only the fields this block type reads, plus what identifies it."""
    fields = _BLOCK_CONTENT_FIELDS.get(block_type)
    if fields is None:
        return content
    keep = {*_ALWAYS_KEPT, *fields}
    return {key: value for key, value in content.items() if key in keep}


def _block_title(section: str, content: dict) -> str:
    return content.get("title") or section.replace("_", " ").title()


def _structure_evidence(
    evidence: list,
    doc_source_map: dict[str, str],
    doc_url_map: dict[str, str] | None = None,
) -> list[dict]:
    """Turn raw '[doc_id=...]'-tagged evidence strings into {"text", "source_id"}
    entries so the debug sources block exposes an actual source instead of raw
    markup - the live UI already resolves real source links elsewhere
    (reporting/dashboard_streamlit/components.py's evidence_url); this only
    brings the debug-only layout.blocks JSON up to the same standard."""
    structured = []
    for item in evidence:
        if not isinstance(item, str):
            continue
        match = _DOC_ID_RE.search(item)
        doc_id = match.group(1) if match else None
        structured.append({
            "text": _DOC_ID_RE.sub("", item).strip(),
            "source_id": doc_source_map.get(doc_id) if doc_id else None,
            "source_url": (doc_url_map or {}).get(doc_id) if doc_id else None,
        })
    return structured


def generate_layout(
    report_plan: ReportPlan,
    adaptation: AudienceAdaptation,
    doc_source_map: dict[str, str] | None = None,
    doc_url_map: dict[str, str] | None = None,
) -> DynamicLayout:
    section_order = list(report_plan.sections)
    if "executive_summary" in adaptation.adapted_sections:
        section_order.insert(0, "executive_summary")
    preferred_types = _purpose_preferred_types(report_plan.report_purpose)
    blocks = []
    for index, section in enumerate(section_order):
        content = adaptation.adapted_sections.get(section, {})
        if section == "sources" and content.get("evidence"):
            content = {
                **content,
                "evidence": _structure_evidence(
                    content["evidence"], doc_source_map or {}, doc_url_map or {}
                ),
            }
        block_type = _block_type(section, content, preferred_types)
        blocks.append(
            DashboardBlock(
                block_id=f"{index + 1:02d}_{section}",
                section=section,
                title=_block_title(section, content),
                block_type=block_type,
                content=_trim_content(block_type, content),
            )
        )

    return DynamicLayout(
        request_id=report_plan.request_id,
        format=report_plan.format,
        blocks=blocks,
        render_target=report_plan.format,
    )
