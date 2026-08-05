"""Declarative purpose -> section -> block_type templates.

This is config, not code: a `PURPOSE_TEMPLATES` entry only lists which
registered `block_type` string(s) suit a section for a given
`primary_intent`/purpose. Nothing in the pipeline reads this yet - actual
block_type selection still happens dynamically in
`core/layout_generator/generator.py`'s `_block_type()` (content-shape-first,
sector/audience-agnostic). This file exists so that adding a new block_type
to the registry (see `blocks/__init__.py`'s checklist) also gives it a place
to be referenced by a purpose template, without touching `registry.py` or
`renderer.py`.

Values are copied from two places that already encode this same mapping as
plain Python logic - source of truth stays there; this file will drift if
those change and nobody updates it, which is fine as long as nothing depends
on it yet:
  - `core/layout_generator/generator.py`'s `_SECTION_BLOCK_TYPES` (the
    section -> single block_type table used for the full issue_response-style
    report shape).
  - `reporting/dashboard_streamlit/generic_dashboard.py`'s
    `_panel_definitions()` (the 3-panel layout used for future_business /
    root_cause / default purposes).
"""

from __future__ import annotations

from typing import TypedDict


class SectionTemplate(TypedDict):
    section: str
    blocks: list[str]


_ISSUE_RESPONSE_SECTIONS: list[SectionTemplate] = [
    {"section": "executive_summary", "blocks": ["text"]},
    {"section": "overview", "blocks": ["text"]},
    {"section": "current_situation", "blocks": ["metrics"]},
    {"section": "market_status", "blocks": ["chart"]},
    {"section": "near_term_outlook", "blocks": ["timeline"]},
    {"section": "issue", "blocks": ["matrix"]},
    {"section": "impact", "blocks": ["metrics"]},
    {"section": "response_actions", "blocks": ["list"]},
    {"section": "trend", "blocks": ["chart"]},
    {"section": "opportunity", "blocks": ["matrix"]},
    {"section": "investment_signal", "blocks": ["metrics"]},
    {"section": "strategic_recommendation", "blocks": ["list"]},
    {"section": "problem", "blocks": ["text"]},
    {"section": "root_cause", "blocks": ["graph"]},
    {"section": "improvement_plan", "blocks": ["list"]},
    {"section": "key_implication", "blocks": ["text"]},
    {"section": "risk_and_opportunity", "blocks": ["matrix"]},
    {"section": "recommended_action", "blocks": ["list"]},
    {"section": "key_metrics", "blocks": ["metrics"]},
    {"section": "timeline", "blocks": ["timeline"]},
    {"section": "decision_required", "blocks": ["list"]},
    {"section": "risk", "blocks": ["matrix"]},
    {"section": "sources", "blocks": ["evidence"]},
]

_FUTURE_BUSINESS_SECTIONS: list[SectionTemplate] = [
    {"section": "trend_drivers", "blocks": ["chart", "list"]},
    {"section": "opportunity_map", "blocks": ["matrix", "list"]},
    {"section": "investment_signals", "blocks": ["metrics", "timeline"]},
    # "radar" added 2026-08 purely to prove the registry is extensible: one
    # new block file (blocks/radar.py) + this one line, no registry.py or
    # renderer.py edits. Fits here because a capability-comparison radar is
    # itself a competitor/positioning signal, same as this section's other
    # block choices.
    {"section": "capability_comparison", "blocks": ["radar", "table"]},
]

_ROOT_CAUSE_SECTIONS: list[SectionTemplate] = [
    {"section": "problem_definition", "blocks": ["text", "list"]},
    {"section": "cause_map", "blocks": ["graph", "list"]},
    {"section": "improvement_plan", "blocks": ["list"]},
]

_DEFAULT_SECTIONS: list[SectionTemplate] = [
    {"section": "current_snapshot", "blocks": ["text", "list"]},
    {"section": "market_signals", "blocks": ["metrics", "timeline"]},
    {"section": "near_term_outlook", "blocks": ["timeline", "matrix"]},
]

PURPOSE_TEMPLATES: dict[str, list[SectionTemplate]] = {
    "issue_response": _ISSUE_RESPONSE_SECTIONS,
    "future_business": _FUTURE_BUSINESS_SECTIONS,
    "root_cause": _ROOT_CAUSE_SECTIONS,
    "default": _DEFAULT_SECTIONS,
}
