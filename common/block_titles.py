"""Every heading the dashboard draws, in one table.

Titles used to live wherever the thing was drawn: a slot's own `title`
field in `purpose_slots.py`, a hard-coded string inside a renderer in
`components.py`, a heading assembled in the view. Changing what a card is
called meant finding all three.

Headings are English; the content under them stays in the language of the
evidence. That split is deliberate - a heading names a fixed role the report
always has ("Market Analysis" is the same slot in every sector, purpose and
audience), while the body is quoting and summarising Korean sources and must
not be machine-translated into a second voice.

Nothing here is sector- or question-specific by construction: the keys are
slot ids and block types, both of which are fixed vocabulary.
"""
from __future__ import annotations

# Keyed by `Slot.slot_id`. Two purposes can share an id (`segments`,
# `problem`, `cause`) and mean the same thing by it, which is why one table
# covers all four skeletons.
SLOT_TITLES: dict[str, str] = {
    # 현황파악
    "summary": "Executive Summary",
    "ranking": "Ranking",
    "market": "Market Analysis",
    "metrics": "Key Metrics",
    "snapshot": "Key Metrics",
    "comparison": "Key Comparisons",
    "position": "SWOT",
    "competitor": "Competitive Landscape",
    "factors": "Key Drivers",
    "segments": "Audience Segments",
    "keywords": "Recurring Terms",
    "response": "Recommended Actions",
    # 이슈대응
    "problem": "Problem",
    "cause": "Root Cause",
    "impact": "Impact",
    "options": "Options",
    "recommendation": "Recommended Actions",
    # 미래사업
    "market_shift": "Market Shift",
    "opportunity": "Opportunity",
    "capability": "Required Capabilities",
    "roadmap": "Roadmap",
    "risk": "Risks",
    # 원인분석
    "drivers": "Drivers",
    # Was "Improvement" - live-verified 2026-08-11: this is the same
    # action-recommendation slot every other purpose titles "Recommended
    # Actions" (see "response"/"recommendation" above), just under
    # root_cause's own slot id. One heading for one role, regardless of
    # which purpose's skeleton reaches it.
    "improvement": "Recommended Actions",
    # _STRATEGY_NARRATIVE (question-first skeleton) - live-verified
    # 2026-08-11: these 5 slot_ids had no SLOT_TITLES entry, so `slot_title()`
    # fell back to each Slot's own Korean `title` argument verbatim
    # ("현재 위치", "미래 변화", ...), the only Korean headers left once every
    # purpose skeleton's own slots were mapped. Named by what each slot's own
    # candidates/fields actually draw, not by literal translation of the
    # Korean title:
    "current_position": "Key Metrics",  # kpi_grid/benchmark_table of the company's own current standing
    "future_change": "Market Analysis",  # landscape/chart/timeline of market & tech direction - same content as "market" above
    "competitive_fit": "Competitive Landscape",  # benchmark_table/radar of us vs competitors - same content as "competitor" above
    "strategic_choice": "Key Comparisons",  # matrix/benchmark_table/table comparing candidate directions
    "execution": "Recommended Actions",  # action_list/timeline of what to do next - same role as "recommendation"/"roadmap" above
    # _RECOMMEND (question-first "추천" skeleton) - live-verified
    # 2026-08-11: same gap as _STRATEGY_NARRATIVE above, just a different
    # skeleton nobody had exercised yet ("타깃"/"후보" stayed Korean). Same
    # rule: named by what the slot's own candidates/fields actually draw.
    "target": "Key Metrics",  # kpi_grid/segment_table of the target audience's own stats (a single-stat card, not literally "a target")
    "candidates": "Key Comparisons",  # item_bar/ranking_list/table enumerating the candidate options
    "fit": "SWOT",  # matrix/level_matrix/driver_bars assessing suitability - same SWOT-shaped content as "position"/"matrix" above
    "evidence": "Evidence",  # table/narrative_list of supporting detail - same name the "Evidence & Sources" panel already uses elsewhere
}

# Headings a renderer draws *inside* a card, keyed by block type. Separate
# from `SLOT_TITLES` because one slot's card can hold two blocks, and the
# inner heading names the picture rather than the section.
BLOCK_TITLES: dict[str, str] = {
    "cause_tree": "Causal Structure",
    "driver_bars": "Ranked by Relevance",
    "landscape": "Market Trend & Composition",
    "chart": "Trend",
    "timeline": "Timeline",
    "action_list": "Recommended Actions",
    "share_split": "Composition",
    "composition_breakdown": "Composition",
    # A SWOT quadrant grid's meaning doesn't depend on which slot's
    # candidate list happened to include "matrix" - `_matrix()` always
    # draws from the full strengths/weaknesses/opportunities/risks pool,
    # so its card is always "SWOT" regardless of the slot's own narrower
    # title. See generic_dashboard.py's `_render_slot`, which applies this
    # even when `matrix` is the lead block (every other block type only
    # gets a BLOCK_TITLES lookup as a companion).
    "matrix": "SWOT",
}


def slot_title(slot_id: str | None, fallback: str = "") -> str:
    """The heading for a section, falling back to whatever the caller had.

    A fallback rather than a KeyError: an unregistered slot id is a slot
    someone added without a heading, and a report that renders with its
    Korean working title is better than one that raises.
    """
    return SLOT_TITLES.get(slot_id or "", fallback or (slot_id or ""))


def block_title(block_type: str | None, fallback: str = "") -> str:
    return BLOCK_TITLES.get(block_type or "", fallback or (block_type or ""))
