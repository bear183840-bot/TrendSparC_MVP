"""Which visual shape a piece of evidence honestly supports.

Pure predicates over the synthesis contracts - no Streamlit, no HTML. They
answer "is this drawable as X", never "should we draw X here", which is the
slot templates' job (reporting/dashboard_streamlit/purpose_slots.py).

These used to live in components.py, next to the renderers that call them.
That made every consumer of a data question import the whole rendering layer
(and Streamlit with it) - purpose_slots.py needed seven predicates and pulled
in the entire dashboard to get them. Keeping the judgement here and the
drawing there means a decision about data never depends on a UI module.
"""

from __future__ import annotations

import re
from typing import Any

from common.content_quality_validator import (
    _RELATIVE_YEAR_OFFSETS,
    classify_metric_shape,
    has_relative_period,
    resolve_relative_period,
    dated_items,
    filter_shared_comparison_axis,
    group_metric_points_by_label,
    is_duplicate_statement,
    is_time_period,
    period_sort_key,
)

# A radar plots the document-stated low/medium/high ordinal, never an invented
# continuous score; the palette that draws it stays in the rendering layer.
LEVEL_RADIUS_FRACTION = {"low": 0.4, "medium": 0.7, "high": 1.0}
_LEVEL_RADIUS_FRACTION = LEVEL_RADIUS_FRACTION
RADAR_MIN_AXES = 3
RADAR_MAX_ENTITIES = 3
_RADAR_MIN_AXES = RADAR_MIN_AXES
_RADAR_MAX_ENTITIES = RADAR_MAX_ENTITIES

# A full year+quarter/month label, a bare year, and an apostrophe year
# ("'24년" - standard in Korean financial copy) all pin a point in time.
_FULL_PERIOD_RE = re.compile(r"(?:20\d{2}|'\d{2})\s*년(?:\s*(?:[1-4]\s*분기|\d{1,2}\s*월))?")
_BARE_QUARTER_RE = re.compile(r"[1-4]\s*분기")
_DOC_ID_RE = re.compile(r"\s*\[doc_id=([^\]]+)\]")


def clean_citation(value: str | None) -> str:
    """Strip the internal `[doc_id=...]` provenance marker from display text."""
    return _DOC_ID_RE.sub("", value or "").strip()


def _format_number(value: float) -> str:
    """Trailing-zero-free rendering of a metric value."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.1f}"


def has_timeseries(metric_points: list[Any]) -> bool:
    """True only when at least one label is genuinely line-chart-shaped (3+
    distinct periods - see `classify_metric_shape`). A label with exactly 2
    periods is a before/after comparison, not a trend - see
    `has_bar_metrics`/`render_metric_bar` for that case instead of forcing
    two dots into a line chart."""
    by_label = group_metric_points_by_label(metric_points)
    return any(classify_metric_shape(points) == "line" for points in by_label.values())


def has_bar_metrics(metric_points: list[Any]) -> bool:
    """True when at least one label has exactly 2 distinct periods - a real
    before/after change worth a bar comparison (`render_metric_bar`), even
    though it's not enough points for a line chart."""
    by_label = group_metric_points_by_label(metric_points)
    return any(classify_metric_shape(points) == "bar" for points in by_label.values())


def bar_metric_groups(metric_points: list[Any]) -> list[list[Any]]:
    """Every label worth drawing as bars, one list per label.

    Covers both bar shapes: a before/after pair over two points in time, and
    one metric measured across several *subjects* ("SK브로드밴드" / "KT" /
    "LG유플러스"), which is an item comparison. The second used to be
    misclassified as a line and drawn as a trend running between companies;
    excluding it outright would have been the opposite mistake, dropping a
    real three-way comparison to prose bullets.
    """
    by_label = group_metric_points_by_label(metric_points)
    return [
        points for points in by_label.values()
        if classify_metric_shape(points) in {"bar", "comparison"}
    ]


def has_comparison(comparison_points: list[Any]) -> bool:
    """True only when 2+ entities share a real common criterion - two
    entities that each only state a *different* metric (no overlap) don't
    make a comparable table, just two unrelated facts side by side."""
    shared = filter_shared_comparison_axis(comparison_points)
    return len({point.entity for point in shared}) >= 2


def radar_axes(comparison_points: list[Any]) -> list[str]:
    """Criteria every compared entity has a stated `level` for. A radar with
    a missing vertex misreads as a zero, so an axis only counts when all
    plotted entities actually have a value on it."""
    leveled = [point for point in comparison_points if point.level in _LEVEL_RADIUS_FRACTION]
    entities = list(dict.fromkeys(point.entity for point in leveled))[:_RADAR_MAX_ENTITIES]
    if not entities:
        return []
    criteria_by_entity = {
        entity: {point.criterion for point in leveled if point.entity == entity}
        for entity in entities
    }
    shared = set.intersection(*criteria_by_entity.values()) if criteria_by_entity else set()
    return [
        criterion
        for criterion in dict.fromkeys(point.criterion for point in leveled)
        if criterion in shared
    ]


def has_radar(comparison_points: list[Any]) -> bool:
    return len(radar_axes(comparison_points)) >= _RADAR_MIN_AXES


def metric_comparison_groups(metric_points: list[Any]) -> list[tuple[str, list[Any]]]:
    """Periods where two or more differently-labelled metrics share a unit -
    a genuine like-for-like item comparison, as opposed to the same metric
    tracked over time (which is `bar_metric_groups`/`render_metric_chart`).
    """
    by_period: dict[str, list[Any]] = {}
    for point in metric_points:
        by_period.setdefault(point.period, []).append(point)
    groups: list[tuple[str, list[Any]]] = []
    for period, points in by_period.items():
        by_unit: dict[str, list[Any]] = {}
        for point in points:
            by_unit.setdefault(point.unit or "", []).append(point)
        for unit_points in by_unit.values():
            if len({point.label for point in unit_points}) >= 2:
                groups.append((period, unit_points))
    return groups


def has_metric_comparison(metric_points: list[Any]) -> bool:
    return bool(metric_comparison_groups(metric_points))


def _timeline_period(sentence: str, reference_year: int | None = None) -> str | None:
    """The period label for a timeline row, or None if the year is unknown.

    A quarter with no year ("2분기 매출액을 1조1522억원으로 예상") is only
    usable when the sentence names a year somewhere else, in which case the
    two are combined. Otherwise there is nothing to sort it by and it is left
    out - an undated row silently placed among dated ones is worse than a
    missing row.
    """
    full = _FULL_PERIOD_RE.search(sentence or "")
    # Whichever dating expression comes first is the one dating this
    # sentence's figure. "지난해 하반기 … 2024년 상반기를 시작으로" is dated by
    # the relative one; "2026년 2분기 … 전년 동기 대비" by the explicit one, and
    # treating its trailing "전년" as the subject's date lost the row entirely.
    if has_relative_period(sentence):
        relative_at = min(
            (sentence.find(marker) for marker, _ in _RELATIVE_YEAR_OFFSETS if marker in sentence),
            default=len(sentence),
        )
        if full is None or relative_at < full.start():
            # Resolve it when the document's year is known; refuse to label at
            # all when it isn't - a wrong date on a timeline is worse than a
            # missing row.
            return resolve_relative_period(sentence, reference_year)
    if full:
        label = re.sub(r"\s+", " ", full.group(0)).strip()
        if label.startswith("'"):
            label = "20" + label[1:]
        if _BARE_QUARTER_RE.search(label):
            return label
        quarter = _BARE_QUARTER_RE.search(sentence)
        if quarter and "월" not in label:
            return f"{label} {re.sub(r'\\s+', '', quarter.group(0))}"
        return label
    return None


def timeline_entries(
    evidence: list[str],
    metric_points: list[Any],
    reference_year: int | None = None,
) -> list[tuple[str, str]]:
    """(period, text) pairs in chronological order, from evidence sentences
    that actually carry a date and from metric points that state a period.
    Undated prose is left out - a numbered list of undated statements is not
    a timeline, which is all the old registry block produced."""
    entries: list[tuple[str, str]] = []
    for point in metric_points:
        # `period` is free text and is not always a time. An app-churn
        # analysis used it for the compared subject ("B tv+ 앱"), which put
        # "B tv+ 앱 — 30일 이탈률 42%" on a timeline as though it were a date.
        if is_time_period(point.period):
            entries.append((point.period, f"{point.label} {_format_number(point.value)}{point.unit or ''}"))
    for sentence in dated_items(evidence):
        period = _timeline_period(sentence, reference_year)
        # A bare "2분기" with no year anywhere in the sentence can't be placed
        # on an axis, and guessing the year would be fabrication - so the
        # entry is skipped rather than shown out of order. This is why the
        # observed timeline had "3분기 '24년 …" sitting after 2026 entries.
        if period:
            entries.append((period, clean_citation(sentence)))
    deduped = list(dict.fromkeys(entries))
    # Two sentences can state the same fact in different words ("2026년 1분기
    # 영업이익 5,376억원" and "1분기 영업이익이 5376억원을 기록"). Keyed on the
    # figures they cite, so the restatement drops out.
    unique: list[tuple[str, str]] = []
    for period, text in deduped:
        if any(
            existing_period == period and is_duplicate_statement(existing_text, text)
            for existing_period, existing_text in unique
        ):
            continue
        unique.append((period, text))
    return sorted(unique, key=lambda entry: period_sort_key(entry[0]))


def has_timeline(
    evidence: list[str], metric_points: list[Any], reference_year: int | None = None
) -> bool:
    return bool(timeline_entries(evidence, metric_points, reference_year))


def has_cause_map(risks: list[str], impacts: list[str], actions: list[str]) -> bool:
    return sum(1 for column in (risks, impacts, actions) if column) >= 2
