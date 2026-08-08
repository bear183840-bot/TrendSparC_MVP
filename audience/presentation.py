"""Renderer-facing presentation policy derived only from audience profiles.

Purpose still decides which questions/slots a report contains.  This policy
changes how densely those same evidence-backed blocks are read and which of
them an audience sees first; it never removes a supported block or changes a
fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audience.contracts import AudienceProfile, load_audience_profile


@dataclass(frozen=True)
class AudiencePresentation:
    detail_level: str
    focus: tuple[str, ...]
    preferred_sections: tuple[str, ...]
    narrative_limit: int
    kpi_limit: int
    ranking_limit: int
    keyword_limit: int
    # The first screen is a decision surface, not the entire evidence dump.
    # Every remaining supported slot is still available in the collapsed
    # detail layer rendered below it.
    primary_slot_limit: int
    primary_group_limit: int
    timeline_limit: int
    summary_label: str


_DENSITY = {
    "full": (8, 6, 10, 10, "실무 요약"),
    "condensed": (4, 4, 7, 7, "의사결정 요약"),
    "highlight_only": (3, 3, 5, 5, "전략 요약"),
    "summary": (4, 4, 7, 7, "핵심 요약"),
}


def presentation_from_profile(profile: AudienceProfile) -> AudiencePresentation:
    narrative, kpi, ranking, keywords, label = _DENSITY.get(
        profile.detail_level, _DENSITY["summary"]
    )
    return AudiencePresentation(
        detail_level=profile.detail_level,
        focus=tuple(profile.focus),
        preferred_sections=tuple(profile.report_structure),
        narrative_limit=narrative,
        kpi_limit=kpi,
        ranking_limit=ranking,
        keyword_limit=keywords,
        primary_slot_limit=2,
        primary_group_limit=1,
        timeline_limit=5,
        summary_label=label,
    )


def load_audience_presentation(audience_id: str) -> AudiencePresentation:
    return presentation_from_profile(load_audience_profile(audience_id))


def order_slots_for_audience(slots: list[Any], policy: AudiencePresentation) -> list[Any]:
    """Stable profile-driven reading order; unsupported slots never appear.

    The summary remains first.  Other slots whose planned section occurs in
    the profile's registered ``report_structure`` move forward in that order.
    Unmatched purpose-specific slots retain their original relative order.
    """
    if not policy.preferred_sections:
        return list(slots)
    preferred = {section: index for index, section in enumerate(policy.preferred_sections)}

    def position(pair: tuple[int, Any]) -> tuple[int, int, int]:
        original, resolved = pair
        if getattr(resolved.slot, "slot_id", None) == "summary":
            return (-1, 0, original)
        section_ids = tuple(
            value for value in (
                getattr(resolved, "section_id", None),
                *getattr(resolved.slot, "sections", ()),
            ) if value
        )
        matches = [preferred[section] for section in section_ids if section in preferred]
        return (0, min(matches), original) if matches else (1, original, original)

    return [resolved for _, resolved in sorted(enumerate(slots), key=position)]
