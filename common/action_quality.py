"""Keep recommendations addressed to the company the report is for.

Source documents often contain another organisation's announced plan.  That
sentence remains useful evidence, but it is not automatically an action for
the routed SK affiliate.  These rules are deliberately sector- and topic-
agnostic: the owner comes from routing, never from an OTT/IPTV keyword.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


_DOC_ID_RE = re.compile(r"\s*\[doc_id=[^\]]+\]")
_KOREAN_SUBJECT_RE = re.compile(
    r"^\s*([가-힣A-Za-z0-9&.·()\- ]{1,50}?)(?:은|는|이|가)\s+"
)
_THIRD_PARTY_DECLARATION_RE = re.compile(
    r"예정|계획|방침|밝혔|발표|추진(?:했|한다|하고|할|\s*중)|"
    r"노력을?\s*(?:기울|이어)|운영(?:한다|하고|할)|제공(?:한다|하고|할)|"
    r"출시(?:했|한다|할)|도입(?:했|한다|할)|확대(?:했|한다|하고|할)",
    re.IGNORECASE,
)
_ENGLISH_DECLARATION_RE = re.compile(
    r"^\s*([A-Z][A-Za-z0-9&.()' -]{1,50}?)\s+"
    r"(?:will|plans?\s+to|intends?\s+to|announced|said\s+it\s+would|launched|operates?)\b",
    re.IGNORECASE,
)


def routed_action_owner(sector_route: Any) -> str | None:
    """Canonical company name selected by the sector router, if available."""
    profile = getattr(sector_route, "matched_profile", None)
    return (
        getattr(profile, "canonical_name", None)
        or getattr(profile, "display_name", None)
        or None
    )


def is_action_for_owner(action: str, owner: str | None) -> bool:
    """Reject a third party's declarative plan from the recommendation list.

    Subjectless proposals ("요금제를 재설계한다") remain valid proposals for
    the routed owner.  Named partners in an object phrase also remain valid.
    Only an explicit grammatical subject declaring its *own* activity is
    rejected, which avoids turning source news into our action plan.
    """
    if not owner:
        return True
    text = _DOC_ID_RE.sub("", action or "").strip()
    if not text:
        return False
    owner_key = re.sub(r"\s+", "", owner).casefold()
    match = _KOREAN_SUBJECT_RE.match(text)
    if match and _THIRD_PARTY_DECLARATION_RE.search(text):
        subject_key = re.sub(r"\s+", "", match.group(1)).casefold()
        return owner_key in subject_key or subject_key in owner_key
    english = _ENGLISH_DECLARATION_RE.match(text)
    if english:
        subject_key = re.sub(r"\s+", "", english.group(1)).casefold()
        return owner_key in subject_key or subject_key in owner_key
    return True


def actions_for_owner(actions: Iterable[str], owner: str | None) -> list[str]:
    """Stable de-duplication plus owner validation for recommended actions."""
    kept: list[str] = []
    seen: set[str] = set()
    for action in actions:
        key = _DOC_ID_RE.sub("", action or "").strip().casefold()
        if not key or key in seen or not is_action_for_owner(action, owner):
            continue
        seen.add(key)
        kept.append(action)
    return kept
