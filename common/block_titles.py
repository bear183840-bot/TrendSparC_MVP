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
    "position": "Positioning",
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
