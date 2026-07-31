"""Build collector search terms from an EntityExtractionResult.

Every sector collector's `_query_term_counts()` takes the first 2 items of
whatever list it's handed as its primary (cheapest, tried-first) search
attempt. A flat concatenation of `organizations + technologies + keywords`
means that primary attempt is just whichever 2 items happen to land in
positions 0-1 — confirmed live to fail badly when `technologies` alone has
2+ items (e.g. two near-synonymous product names), which crowds out the
actual topic/framing keyword (e.g. "시장 현황") the question was actually
asking about.

Even after pairing one entity with one topic keyword, live-testing showed a
deeper issue: leading the search with a BRAND name at all tends to surface
that brand's own press-release/milestone coverage, regardless of which
topic word is paired with it — a company's own newsroom and most-indexed
coverage is inherently about itself, not the market it competes in. So when
`entities.perspective == "market_landscape"` (the question is about the
market/industry as a whole, not one company — see
`common/contracts.EntityExtractionResult.perspective`) and the routed
sector's `profile.json` has `market_keywords` registered, the anchor term
becomes a sector-level market term instead of a brand name.

Sector-agnostic — reads only fields already computed by the entity stage
plus the routed sector's own registered `market_keywords` (no sector-name
branching), no new API call.
"""

from __future__ import annotations

from common.contracts import EntityExtractionResult, SectorProfile

_INTENT_FRAMING_WORDS = {
    "current_status": "현황",
    "issue_response": "이슈",
    "future_business": "전망",
    "root_cause": "원인",
}

_MARKET_LANDSCAPE_PERSPECTIVE = "market_landscape"


def build_search_terms(
    entities: EntityExtractionResult, sector_profile: SectorProfile | None = None
) -> list[str]:
    all_terms = [*entities.organizations, *entities.technologies, *entities.keywords]

    use_market_keywords = (
        entities.perspective == _MARKET_LANDSCAPE_PERSPECTIVE
        and sector_profile is not None
        and bool(sector_profile.market_keywords)
    )

    if not all_terms and not use_market_keywords:
        return []

    anchor_primary = sector_profile.market_keywords[0] if use_market_keywords else next(iter(all_terms), None)

    anchor_topic = next((term for term in entities.keywords if term != anchor_primary), None)
    if anchor_topic is None:
        framing_word = _INTENT_FRAMING_WORDS.get(entities.primary_intent)
        if framing_word and framing_word != anchor_primary:
            anchor_topic = framing_word

    market_terms = sector_profile.market_keywords if use_market_keywords else []
    ordered = [term for term in (anchor_primary, anchor_topic) if term is not None] + market_terms + all_terms
    return list(dict.fromkeys(ordered))
