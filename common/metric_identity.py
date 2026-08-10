"""Canonical identity for a measured value, and merging by that identity.

Two documents restating one figure should be one reading with two sources,
not two readings. The existing `dedupe_structured_across_sections` compares
every field including `doc_id`, deliberately, so it never collapses across
documents - live-verified 2026-08-10, a 보도자료 that arrived as two
identical PDF chunks produced 184 metric points of which 92 were the same
fact twice.

What this module must never do is the opposite mistake. Two readings that
disagree are evidence of a conflict, and silently keeping one would hide it;
same identity with different values stays as separate points. Nothing here
infers a unit, a period or an entity - only forms that are the same string
written differently are brought together.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

_UNKNOWN_PERIODS = {"", "시점 미상", "미상", "unknown", "n/a", "-"}

# Written differently, identical in meaning. Scale is never touched: 억원 and
# 원 are different units, and "단말장치・단자" is never rewritten to "명".
_UNIT_ALIASES = {
    "％": "%",
    "percent": "%",
    "퍼센트": "%",
    "퍼센트포인트": "%p",
    "%P": "%p",
    "％P": "%p",
    "％p": "%p",
}

_HALF_YEAR_RE = re.compile(
    r"^(?P<year>\d{4})\s*년?\s*(?:(?P<half>상반기|하반기)|(?P<h>[12])\s*H|H\s*(?P<h2>[12]))$",
    re.IGNORECASE,
)
_QUARTER_RE = re.compile(
    r"^(?P<year>\d{4})\s*년?\s*(?:(?P<q>[1-4])\s*(?:Q|분기)|Q\s*(?P<q2>[1-4]))$",
    re.IGNORECASE,
)
_SHORT_YEAR_RE = re.compile(r"^['’]?(?P<yy>\d{2})\s*년(?P<rest>.*)$")


def canonical_text(value: object) -> str:
    """Whitespace and Unicode form only - never a rename."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:·")


def canonical_unit(unit: object) -> Optional[str]:
    """`unit=None` is a valid state and stays None.

    Only spelling variants collapse. A scale change (억원 -> 원) would alter
    the number's meaning, so it is not attempted here.
    """
    if unit is None:
        return None
    text = unicodedata.normalize("NFKC", str(unit)).strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    if compact in _UNIT_ALIASES:
        return _UNIT_ALIASES[compact]
    lowered = compact.casefold()
    if lowered in _UNIT_ALIASES:
        return _UNIT_ALIASES[lowered]
    # "억 원" and "억원" are the same unit written with and without a space;
    # "만 명" likewise. Collapsing inner whitespace is safe, renaming is not.
    return compact


def canonical_period(period: object) -> Optional[str]:
    """A stated period in one written form, or None when it is unknown.

    "2025 H1", "2025년 1H" and "2025년 상반기" name the same half-year.
    "2025년" does not - a whole year is not its first half, so it stays
    distinct and is never merged into one.
    """
    if period is None:
        return None
    text = unicodedata.normalize("NFKC", str(period)).strip()
    if not text or text.casefold() in _UNKNOWN_PERIODS:
        return None
    short = _SHORT_YEAR_RE.match(text)
    if short:
        # "'25년 상반기" - the century is the document's, not a guess: two
        # digit years in these sources are all 2000s.
        text = f"20{short.group('yy')}년{short.group('rest')}"
    compact = re.sub(r"\s+", " ", text).strip()
    half = _HALF_YEAR_RE.match(compact)
    if half:
        name = half.group("half")
        if not name:
            digit = half.group("h") or half.group("h2")
            name = "상반기" if digit == "1" else "하반기"
        return f"{half.group('year')}년 {name}"
    quarter = _QUARTER_RE.match(compact)
    if quarter:
        digit = quarter.group("q") or quarter.group("q2")
        return f"{quarter.group('year')}년 {digit}분기"
    return compact


def metric_identity(point: Any) -> tuple:
    """What makes two readings the same measurement.

    `value` is deliberately absent: two points that share an identity but
    disagree on the number are a conflict to surface, and putting the value
    in the key would make that conflict invisible by construction.
    """
    get = point.get if isinstance(point, dict) else lambda name: getattr(point, name, None)
    return (
        canonical_text(get("label")),
        canonical_text(get("subject")) or None,
        canonical_period(get("period")),
        canonical_unit(get("unit")),
        canonical_text(get("share_of")) or None,
    )


def _provenance(point: Any) -> tuple[Optional[str], Optional[str]]:
    get = point.get if isinstance(point, dict) else lambda name: getattr(point, name, None)
    return get("doc_id"), get("source_url")


def normalize_metric_points(points: list[Any]) -> list[Any]:
    """One point per (identity, value), carrying every source that stated it.

    Merging is by identity AND value, so a disagreement survives as two
    points rather than one arbitrary winner. The first occurrence keeps its
    own `doc_id`/`source_id`/`source_url` so existing readers are unchanged;
    the full set is added to `supporting_doc_ids`/`supporting_source_urls`.
    """
    merged: dict[tuple, Any] = {}
    doc_ids: dict[tuple, list[str]] = {}
    source_urls: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    for point in points:
        value = point.get("value") if isinstance(point, dict) else getattr(point, "value", None)
        key = (*metric_identity(point), value)
        if key not in merged:
            merged[key] = point
            doc_ids[key] = []
            source_urls[key] = []
            order.append(key)
        doc_id, source_url = _provenance(point)
        if doc_id and doc_id not in doc_ids[key]:
            doc_ids[key].append(doc_id)
        if source_url and source_url not in source_urls[key]:
            source_urls[key].append(source_url)

    result: list[Any] = []
    for key in order:
        point = merged[key]
        if isinstance(point, dict):
            point = dict(point)
            point["supporting_doc_ids"] = doc_ids[key]
            point["supporting_source_urls"] = source_urls[key]
        else:
            point = point.model_copy(update={
                "supporting_doc_ids": doc_ids[key],
                "supporting_source_urls": source_urls[key],
            })
        result.append(point)
    return result


def conflicting_metric_groups(points: list[Any]) -> list[list[Any]]:
    """Identities that carry more than one distinct value.

    Exposed so a caller can report a disagreement instead of discovering it
    as two near-identical cards; nothing in this module resolves one.
    """
    grouped: dict[tuple, list[Any]] = {}
    for point in points:
        grouped.setdefault(metric_identity(point), []).append(point)
    conflicts = []
    for group in grouped.values():
        values = {
            (item.get("value") if isinstance(item, dict) else getattr(item, "value", None))
            for item in group
        }
        if len(values) > 1:
            conflicts.append(group)
    return conflicts


def comparison_identity(point: Any) -> tuple:
    """What makes two comparison rows the same statement.

    Criterion and entity only. The period is already part of `criterion`
    for a table-recovered row (`"점유율(B) '25년 상반기"`), and
    ComparisonPoint has no period field of its own, so adding one here
    would key on something that does not exist. `value` is excluded for the
    same reason as in `metric_identity`: two sources disagreeing about
    KT's share is a conflict to keep, not a duplicate to drop.
    """
    get = point.get if isinstance(point, dict) else lambda name: getattr(point, name, None)
    return (
        canonical_text(get("criterion")),
        canonical_text(get("entity")),
    )


def normalize_comparison_points(points: list[Any]) -> list[Any]:
    """Merge the model's comparisons with the ones recovered from a table.

    Additive, not either/or: a model that stated one comparison used to
    suppress every deterministic one, so a 보도자료 whose table compared
    three operators on one shared 점유율 column contributed nothing. Rows
    that agree collapse and pool their sources; rows that disagree both
    survive, and a `level` row is treated exactly like a numeric one.
    """
    merged: dict[tuple, Any] = {}
    doc_ids: dict[tuple, list[str]] = {}
    source_urls: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    for point in points:
        get = point.get if isinstance(point, dict) else lambda name: getattr(point, name, None)
        key = (*comparison_identity(point), canonical_text(get("value")), get("level"))
        if key not in merged:
            merged[key] = point
            doc_ids[key] = []
            source_urls[key] = []
            order.append(key)
        doc_id, source_url = _provenance(point)
        if doc_id and doc_id not in doc_ids[key]:
            doc_ids[key].append(doc_id)
        if source_url and source_url not in source_urls[key]:
            source_urls[key].append(source_url)

    result: list[Any] = []
    for key in order:
        point = merged[key]
        if isinstance(point, dict):
            point = dict(point)
            point["supporting_doc_ids"] = doc_ids[key]
            point["supporting_source_urls"] = source_urls[key]
        else:
            point = point.model_copy(update={
                "supporting_doc_ids": doc_ids[key],
                "supporting_source_urls": source_urls[key],
            })
        result.append(point)
    return result


def conflicting_comparison_groups(points: list[Any]) -> list[list[Any]]:
    """Identities that carry more than one stated value."""
    grouped: dict[tuple, list[Any]] = {}
    for point in points:
        grouped.setdefault(comparison_identity(point), []).append(point)
    conflicts = []
    for group in grouped.values():
        values = {
            canonical_text(
                item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
            )
            for item in group
        }
        if len(values) > 1:
            conflicts.append(group)
    return conflicts
