"""Which visual shape a piece of evidence honestly supports.

Pure predicates over the synthesis contracts - no Streamlit, no HTML. They
answer "is this drawable as X", never "should we draw X here", which is the
slot templates' job (common/purpose_slots.py).

These used to live in components.py, next to the renderers that call them.
That made every consumer of a data question import the whole rendering layer
(and Streamlit with it) - purpose_slots.py needed seven predicates and pulled
in the entire dashboard to get them. Keeping the judgement here and the
drawing there means a decision about data never depends on a UI module.
"""

from __future__ import annotations

import re
from typing import Any

from common.number_format import format_number
from common.content_quality_validator import (
    _RELATIVE_YEAR_OFFSETS,
    classify_metric_shape,
    rank_by_relevance,
    has_relative_period,
    resolve_relative_period,
    dated_items,
    filter_shared_comparison_axis,
    group_metric_points_by_label,
    entity_kind,
    is_demographic,
    is_duplicate_statement,
    is_time_period,
    order_comparison_entities,
    normalize_comparison_axes,
    semantic_entity_key,
    semantic_metric_key,
    select_chartable_series,
    strip_particle,
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


# Digit grouping now lives in `common/number_format.py` alongside the scaling
# rule, so the two cannot drift; re-exported here because every existing
# caller imports it from this module.
_format_number = format_number


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


def time_bar_groups(metric_points: list[Any]) -> list[list[Any]]:
    """Only the before/after-over-time labels - movement, not ranking."""
    by_label = group_metric_points_by_label(metric_points)
    return [points for points in by_label.values() if classify_metric_shape(points) == "bar"]


def split_aggregate(points_for_one_label: list[Any]) -> tuple[list[Any], Any | None]:
    """(items, total) for one label, where a total is present.

    Evidence routinely states a whole and its parts in one breath -
    "숏폼 이용률 93.2%, 그중 유튜브 쇼츠 78.8%, 릴스 46.2%, 틱톡 22.9%".
    The whole arrives as a point with no `subject`, and drawn beside the
    parts it becomes a fourth bar taller than all of them, labelled by its
    period because it has no subject to be labelled by - which is how a bar
    reading "2024" ended up leading a platform ranking. The total is real and
    worth showing; it is just not one of the items.
    """
    items = [point for point in points_for_one_label if getattr(point, "subject", None)]
    if not items or len(items) == len(points_for_one_label):
        return points_for_one_label, None
    totals = [point for point in points_for_one_label if not getattr(point, "subject", None)]
    return items, totals[0]


def item_bar_groups(metric_points: list[Any]) -> list[list[Any]]:
    """Only the across-items labels - ranking, not movement.

    Split out from `bar_metric_groups` because the two answer different
    questions and were competing for the same slot: 시장 상황 asks which way
    things are moving, and a three-way comparison between companies has no
    direction in it at all. Whichever slot ran first used to claim both.
    """
    by_label = group_metric_points_by_label(metric_points)
    groups: list[list[Any]] = []
    for points in by_label.values():
        if classify_metric_shape(points) != "comparison":
            continue
        subjects = [
            getattr(point, "subject", None)
            or (point.period if not is_time_period(point.period) else None)
            for point in points
        ]
        valid = [
            subject for subject in subjects
            if subject
            and len(subject) <= 40
            and subject.casefold().strip() != points[0].label.casefold().strip()
            and not re.search(r"\d[\d,.]*\s*(?:%|원|명|개|건|배|시간|분)", subject)
        ]
        # One explicit aggregate may sit beside the items. More malformed or
        # missing names mean several different subquestions were collapsed
        # under one broad heading; drawing that as one ranking is false.
        if len(valid) < 2 or len(valid) / len(points) < 0.75:
            continue
        groups.append(points)
    return groups


def ranking_list_groups(metric_points: list[Any], minimum_items: int = 4) -> list[list[Any]]:
    """Long categorical comparisons that read better as a ranked list.

    This is purely shape-based: no platform, company, country, or question
    vocabulary is inspected. Two or three items remain an ordinary bar;
    four or more earn the denser rank/value treatment.
    """
    return [
        points for points in item_bar_groups(metric_points)
        if len(split_aggregate(points)[0]) >= minimum_items
    ]


def ranking_comparison_groups(
    comparison_points: list[Any], minimum_items: int = 3
) -> list[list[Any]]:
    """Explicit rank criteria encoded as ComparisonPoint rows."""
    grouped: dict[str, list[Any]] = {}
    for point in comparison_points or []:
        criterion = (getattr(point, "criterion", "") or "").strip()
        normalized = criterion.casefold()
        if "순위" not in normalized and "rank" not in normalized and "ranking" not in normalized:
            continue
        grouped.setdefault(criterion, []).append(point)
    return [
        points for points in grouped.values()
        if len({point.entity for point in points}) >= minimum_items
    ]


def comparison_points_without_rank_dimensions(comparison_points: list[Any]) -> list[Any]:
    """Qualitative comparisons left after explicit rankings take ownership."""
    return [
        point for point in comparison_points
        if "순위" not in (point.criterion or "").casefold()
        and "rank" not in (point.criterion or "").casefold()
        and "ranking" not in (point.criterion or "").casefold()
    ]


def has_ranking_list(
    metric_points: list[Any], comparison_points: list[Any] | None = None
) -> bool:
    return bool(
        ranking_list_groups(metric_points)
        or ranking_comparison_groups(comparison_points or [])
    )


def grouped_bar_series(metric_points: list[Any]) -> list[tuple[str, list[str], dict[str, list[Any]]]]:
    """(label, categories, {subject: points}) for the artwork's grouped bars.

    A metric measured for two or more subjects across two or more shared
    categories - 연령대별 롱폼/숏폼 이용률, 요일별 IPTV/OTT. Three axes at
    once, which is exactly what `subject` was added for and what neither the
    single-series bar nor the trend line can draw: one draws the wrong
    comparison, the other implies a path between categories.

    Both floors matter. Fewer than two subjects is an ordinary bar chart; a
    category only one subject was measured on is dropped rather than drawn as
    a lone bar in a group, which would read as "the others are zero".
    """
    by_label = {
        label: [point for point in points if getattr(point, "subject", None) and point.period]
        for label, points in group_metric_points_by_label(metric_points).items()
    }
    groups = []
    for label, points in by_label.items():
        by_subject: dict[str, dict[str, Any]] = {}
        for point in points:
            by_subject.setdefault(point.subject, {})[point.period] = point
        if len(by_subject) < 2:
            continue
        shared = [
            period for period in dict.fromkeys(point.period for point in points)
            if all(period in periods for periods in by_subject.values())
        ]
        if len(shared) < 2:
            continue
        groups.append((
            label,
            shared,
            {subject: [periods[period] for period in shared] for subject, periods in by_subject.items()},
        ))
    return groups


def has_grouped_bars(metric_points: list[Any]) -> bool:
    return bool(grouped_bar_series(metric_points))


def _strip_leading_subject(label: str, subject: str) -> str:
    """`label` with a leading exact copy of `subject` removed, if present.

    Case/whitespace-insensitive so "KT 점유율" strips to "점유율" regardless
    of how the subject itself was cased. Only a *leading* match is removed -
    "IPTV 대비 SO 점유율" keeps "IPTV" since it names something else first.
    """
    subject_clean = subject.strip().casefold()
    if not subject_clean:
        return label
    lowered = label.casefold()
    if lowered.startswith(subject_clean):
        return label[len(subject_clean):].strip()
    return label


def _has_unbalanced_bracket(text: str) -> bool:
    """A dangling `(`/`)` (or full-width `（`/`）`) means the text is a cut
    fragment of a parenthetical, not a complete label - live-verified
    2026-08-11: "KT 점유율 (B" (an unclosed paren from a source table's own
    "(A안)"/"(B안)" column sub-headers) read as a complete, distinct
    attribute next to the genuinely complete "KT 시장점유율", multiplying
    one real figure into several fake ones.
    """
    return (
        text.count("(") != text.count(")")
        or text.count("（") != text.count("）")
    )


def entity_attribute_groups(metric_points: list[Any]) -> list[tuple[str, list[Any]]]:
    """(subject, points) for two or more subjects each measured on several of
    their OWN distinct percentage attributes, with no shared category between
    subjects at all - "롱폼 콘텐츠: 깊이감 71.1%, 전문지식 습득 68.4%" and
    "숏폼 콘텐츠: 가성비 구독 64.7%, 광고 요금제 34.8%" name two subjects
    whose attributes don't overlap, so `grouped_bar_series` (which requires
    the *same* categories measured for every subject) can never group them -
    each subject would need a value for the other's attributes that no
    source stated.

    General condition, not this question's vocabulary: any 2+ subjects with
    2+ distinct attribute labels each. A subject whose points already carry
    a stated `share_of` is excluded - that is a real composition, drawn by
    `share_groups` instead, and showing it here too would be the same data
    twice. Without `share_of` nothing else ever draws it as a composition,
    so a coincidental sum near 100% is not reason enough to hide it -
    live-verified 2026-08-11: the real "숏폼 콘텐츠" case (가성비 구독
    64.7% + 광고 요금제 34.8%) sums to 99.5% by coincidence despite being
    two unrelated survey answers, not a stated whole split in two.
    """
    by_subject: dict[str, dict[str, Any]] = {}
    for point in metric_points:
        subject = (getattr(point, "subject", None) or "").strip()
        label = (point.label or "").strip()
        if not subject or (point.unit or "").strip() not in {"%", "％"}:
            continue
        if not label or _has_unbalanced_bracket(label):
            continue
        # A label that just restates the subject ("subject: IPTV, label:
        # IPTV") names no attribute at all - live-verified 2026-08-11, a
        # table-cell recovery path falls back to the bare entity name as the
        # label when its own column header didn't survive cleanly, and that
        # fallback must not be read as a real attribute here.
        if semantic_metric_key(label) == semantic_metric_key(subject):
            continue
        # One point per semantic label per subject, not per exact string -
        # "KT 점유율"/"KT 시장점유율" from two different source passages are
        # the same attribute stated twice, not two attributes, even though
        # their raw label text differs. The subject name is stripped from
        # the front first: `semantic_metric_key` keeps topic-bearing words
        # on purpose (so "HBM market size" and "DRAM market size" stay
        # separate), which is right for a *label* but means a subject's own
        # name baked into its own label ("KT 점유율" vs "KT 시장점유율")
        # would never collapse without this - the alias entries this relies
        # on ("시장점유율"/"점유율" -> "market share") are entity-neutral by
        # design, see common/content_quality_validator.py.
        attribute_key = semantic_metric_key(_strip_leading_subject(label, subject))
        by_subject.setdefault(subject, {}).setdefault(attribute_key, point)
    groups: list[tuple[str, list[Any]]] = []
    for subject, by_label in by_subject.items():
        points = list(by_label.values())
        if len(points) < 2:
            continue
        if all(getattr(point, "share_of", None) for point in points):
            continue
        groups.append((subject, points))
    return groups if len(groups) >= 2 else []


def has_entity_attribute_bars(metric_points: list[Any]) -> bool:
    return bool(entity_attribute_groups(metric_points))


def status_levels(comparison_points: list[Any], limit: int = 4) -> list[tuple[str, str, str]]:
    """(criterion, entity + value, level) for the artwork's KPI status bar.

    A qualitative counterpart to the KPI row: where a figure isn't available
    but the source graded something, the grade is still worth the top of the
    page. Only points the document actually graded are eligible - a value with
    no stated `level` has no standing to be shown as a status.
    """
    graded = [point for point in normalize_comparison_axes(comparison_points) if point.level]
    seen: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for point in graded:
        if point.criterion in seen:
            continue
        seen.add(point.criterion)
        rows.append((point.criterion, f"{point.entity} · {point.value}", point.level))
    return rows[:limit]


def level_matrix(
    comparison_points: list[Any], entity_limit: int = 5, criterion_limit: int = 6
) -> tuple[list[str], list[str], dict[tuple[str, str], tuple[str, str]]]:
    """(entities, criteria, {(criterion, entity): (level, value)}) for a grid.

    `status_levels` keeps one row per criterion and throws the rest away - it
    was built for a single band across the top of the page. When several
    entities were graded on the same criteria, that discards most of what the
    documents said: five criteria x four competitors is twenty gradings shown
    as four. This returns the whole grid so the artwork's Competitor Analysis
    card can be drawn, and the band renderer keeps its own narrower view.

    Order is the evidence's own, not alphabetical: the first entity discussed
    is usually the subject of the question.
    """
    graded = [point for point in normalize_comparison_axes(comparison_points or []) if point.level]
    entities: list[str] = []
    criteria: list[str] = []
    cells: dict[tuple[str, str], tuple[str, str]] = {}
    for point in graded:
        if point.entity not in entities:
            entities.append(point.entity)
        if point.criterion not in criteria:
            criteria.append(point.criterion)
        cells.setdefault((point.criterion, point.entity), (point.level, point.value))
    entities = entities[:entity_limit]
    criteria = criteria[:criterion_limit]
    cells = {key: value for key, value in cells.items()
             if key[0] in criteria and key[1] in entities}
    return entities, criteria, cells


def has_level_matrix(comparison_points: list[Any]) -> bool:
    """A grid needs two of each axis - otherwise it is a list or a band."""
    entities, criteria, cells = level_matrix(comparison_points)
    return len(entities) >= 2 and len(criteria) >= 2 and len(cells) >= 4


def benchmark_grid(
    comparison_points: list[Any], metric_points: list[Any],
    entity_limit: int = 6, dimension_limit: int = 7,
) -> tuple[list[str], list[str], dict[tuple[str, str], str]]:
    """Comparable entities x shared qualitative/numeric dimensions.

    It covers companies, countries, brands and technologies without knowing
    any of those vocabularies. Demographic subjects are excluded because
    they have their own segment block. A missing cell stays blank rather
    than becoming zero.
    """
    comparison_points = normalize_comparison_axes(comparison_points or [])
    metric_points = [
        point for points in group_metric_points_by_label(metric_points or []).values()
        for point in points
    ]
    cells: dict[tuple[str, str], str] = {}
    entities: list[str] = []
    dimensions: list[str] = []

    def add(entity: str | None, dimension: str | None, value: str) -> None:
        if not entity or not dimension or is_demographic(entity):
            return
        if entity not in entities:
            entities.append(entity)
        if dimension not in dimensions:
            dimensions.append(dimension)
        cells.setdefault((dimension, entity), value)

    def is_rank_dimension(dimension: str | None) -> bool:
        normalized = (dimension or "").strip().casefold()
        return "순위" in normalized or "rank" in normalized or "ranking" in normalized

    for point in comparison_points or []:
        # Rank facts belong to the ranking block. Treating the same fact as a
        # benchmark dimension duplicates it under the competitor section and
        # produces a sparse, misleading grid.
        if not is_rank_dimension(point.criterion):
            add(point.entity, point.criterion, point.value)
    for point in metric_points or []:
        add(
            getattr(point, "subject", None), point.label,
            f"{_format_number(point.value)}{point.unit or ''}",
        )

    shared_dimensions = [
        dimension for dimension in dimensions
        if sum((dimension, entity) in cells for entity in entities) >= 2
    ][:dimension_limit]
    shared_entities = [
        entity for entity in entities
        if sum((dimension, entity) in cells for dimension in shared_dimensions) >= 2
    ][:entity_limit]
    filtered = {
        key: value for key, value in cells.items()
        if key[0] in shared_dimensions and key[1] in shared_entities
    }
    return shared_entities, shared_dimensions, filtered


def has_benchmark_grid(comparison_points: list[Any], metric_points: list[Any]) -> bool:
    entities, dimensions, cells = benchmark_grid(comparison_points, metric_points)
    return len(entities) >= 2 and len(dimensions) >= 2 and bool(cells)


def has_status_levels(comparison_points: list[Any], minimum: int = 2) -> bool:
    return len(status_levels(comparison_points)) >= minimum


def varies_by_subject(points_for_one_label: list[Any]) -> bool:
    """True when one metric was measured for two or more different subjects -
    the axis the figures vary along is *who*, not *when*."""
    return len({point.subject for point in points_for_one_label if getattr(point, "subject", None)}) >= 2


def metric_axis_labels(points_for_one_label: list[Any]) -> list[str]:
    """The row label for each point, on whichever axis actually varies.

    A subject-varying group carries the same period on every row, so labelling
    those rows by period would print the same string three times; a
    time-varying group has no subject to show. Where both vary (one metric,
    several companies, several quarters) the label has to name both or two
    rows collide.
    """
    if not varies_by_subject(points_for_one_label):
        return [point.period for point in points_for_one_label]
    periods = {point.period for point in points_for_one_label}
    return [
        f"{point.subject or point.period} ({point.period})"
        if len(periods) >= 2 and point.subject and point.period
        else (point.subject or point.period)
        for point in points_for_one_label
    ]


def metric_insight(points: list[Any], grounded_claims: list[Any]) -> tuple[str, str | None] | None:
    """The one claim that explains a plotted series, as (text, source_url).

    The reference design puts a sentence of interpretation under every chart.
    The link needed for it already exists — `MetricPoint.evidence_synthesis_claim_id`
    points at the `SynthesisClaim` the figure was read out of — it had simply
    never been followed. Reading it is the whole implementation: nothing here
    writes an interpretation, so a series whose points carry no claim link
    gets no caption rather than a generated one.

    Where several plotted points link to different claims, the most-referenced
    one wins; it is the claim the series as a whole is about.
    """
    by_id = {claim.synthesis_claim_id: claim for claim in grounded_claims}
    referenced = [
        point.evidence_synthesis_claim_id for point in points
        if getattr(point, "evidence_synthesis_claim_id", None) in by_id
    ]
    if not referenced:
        return None
    best = max(set(referenced), key=referenced.count)
    claim = by_id[best]
    return claim.claim, claim.source_url


# A donut asserts that its slices are the whole. Percentages that add past
# 100 are being measured over different bases (multi-select survey answers
# usually are), and drawing those as one circle states something false.
SHARE_SUM_TOLERANCE = 2.0
SHARE_MIN_SLICES = 2
# Below this the remainder is rounding, not a real unnamed rest, and naming
# it "기타" would put a made-up slice on the chart for nothing.
SHARE_REMAINDER_MIN = 1.0
_EXISTING_OTHER_NAMES = {"기타", "그 외", "그외", "나머지", "other", "others", "etc"}


def derived_share_remainder(whole: str, slices: list[Any]) -> Any | None:
    """The unnamed rest of a partial composition, or None.

    A source that lists the top few slices of a whole it has named leaves a
    remainder that is arithmetic, not a reading - so it is returned as a
    point marked `derived`, carrying the claim ids of the slices it was
    subtracted from and no `evidence_claim_id` of its own. Anything that
    would make the subtraction a guess returns None instead: no named
    whole, a sum already at 100, a sum over 100, a remainder small enough
    to be rounding, or a rest the source already named itself.
    """
    from common.contracts import MetricPoint

    if not whole or len(slices) < SHARE_MIN_SLICES:
        return None
    if any((getattr(point, "unit", None) or "").strip() not in {"%", "％"} for point in slices):
        return None
    periods = {getattr(point, "period", None) for point in slices}
    if len(periods) != 1:
        return None
    subjects = [str(getattr(point, "subject", "") or "").strip() for point in slices]
    if not all(subjects) or len(set(subjects)) != len(subjects):
        return None
    if any(subject.casefold() in _EXISTING_OTHER_NAMES for subject in subjects):
        return None
    if any(getattr(point, "derived", False) for point in slices):
        return None
    known_sum = sum(float(point.value) for point in slices)
    if known_sum < 0 or known_sum > 100 - SHARE_REMAINDER_MIN:
        return None
    remainder = round(100.0 - known_sum, 2)
    claim_ids = [
        claim_id for claim_id in (
            getattr(point, "evidence_synthesis_claim_id", None)
            or getattr(point, "evidence_claim_id", None)
            for point in slices
        ) if claim_id
    ]
    doc_ids: list[str] = []
    urls: list[str] = []
    for point in slices:
        for doc_id in (getattr(point, "supporting_doc_ids", None) or [getattr(point, "doc_id", None)]):
            if doc_id and doc_id not in doc_ids:
                doc_ids.append(doc_id)
        for url in (getattr(point, "supporting_source_urls", None) or [getattr(point, "source_url", None)]):
            if url and url not in urls:
                urls.append(url)
    return MetricPoint(
        label="기타",
        subject="기타",
        period=next(iter(periods)) or "시점 미상",
        value=remainder,
        unit="%",
        share_of=whole,
        derived=True,
        derivation="100 - sum(known shares)",
        source_claim_ids=claim_ids,
        supporting_doc_ids=doc_ids,
        supporting_source_urls=urls,
    )


def latest_share_group(groups: list[tuple[str, list[Any]]]) -> tuple[str, list[Any]] | None:
    """The most recent composition among groups that share one whole.

    A "현황" question wants this half-year's split, not last year's; the
    caller decides whether recency is what matters, this only orders.
    """
    dated = [
        (whole, slices) for whole, slices in groups
        if slices and is_time_period(getattr(slices[0], "period", None))
    ]
    if not dated:
        return groups[0] if groups else None
    return max(dated, key=lambda item: str(getattr(item[1][0], "period", "")))


def share_groups(metric_points: list[Any]) -> list[tuple[str, list[Any]]]:
    """(whole, slices) for every set of figures that really partitions one whole.

    Three conditions, all necessary: the source named the same whole for each
    slice (`share_of`), the figures are percentages, and they do not add up to
    more than 100. The last one is the arithmetic check that catches a model
    labelling multi-select answers as shares - "이용자의 62%가 유튜브, 55%가
    넷플릭스" is two overlapping groups, not two slices, and it fails the sum.

    Slices that fall short of 100 are kept and the renderer shows the
    remainder as unaccounted-for, since a source often names only the top
    few. Inventing a "기타" slice to close the circle would be the fabrication
    this whole check exists to prevent.
    """
    normalized_points = [
        point for points in group_metric_points_by_label(metric_points).values()
        for point in points
    ]
    by_whole: dict[tuple[str, str], list[Any]] = {}
    whole_labels: dict[tuple[str, str], str] = {}
    for point in normalized_points:
        whole = (getattr(point, "share_of", None) or "").strip()
        if whole and (point.unit or "").strip() in {"%", "％"}:
            period_key = point.period if is_time_period(point.period) else (point.period or "")
            key = (semantic_metric_key(whole), period_key)
            whole_labels.setdefault(key, whole)
            by_whole.setdefault(key, []).append(point)
    groups = []
    for key, points in by_whole.items():
        if len(points) < SHARE_MIN_SLICES:
            continue
        subjects = [semantic_entity_key(getattr(point, "subject", None)) for point in points]
        if not all(subjects) or len(set(subjects)) != len(subjects):
            continue
        if any(point.value < 0 for point in points):
            continue
        if sum(point.value for point in points) > 100 + SHARE_SUM_TOLERANCE:
            continue
        groups.append((whole_labels[key], sorted(points, key=lambda point: point.value, reverse=True)))
    return groups


def has_share_split(metric_points: list[Any]) -> bool:
    return bool(share_groups(metric_points))


def competitor_panels(
    comparison_points: list[Any], metric_points: list[Any], limit: int = 3
) -> list[tuple[str, list[tuple[str, str, str | None]], list[Any], Any]]:
    """Per-competitor panels: (entity, graded rows, figures, share slice).

    The artwork stacks a process rail, an importance bar and a donut inside
    each competitor's panel. Our evidence supports only what is genuinely
    attributable to one named entity, so a panel is assembled from exactly
    three things and no more: the criteria a document graded for that entity,
    the figures whose `subject` is that entity, and that entity's slice of a
    stated whole where one exists.

    The process rail is deliberately absent. Nothing in the data dates a
    claim *to a competitor*, and a per-company timeline built from the
    report's own chronology would attribute this company's milestones to a
    rival - which is the one thing a competitor panel must never do.

    An entity with a single fact isn't a panel; it is a row in the comparison
    table, and it stays there.
    """
    comparison_points = normalize_comparison_axes(comparison_points or [])
    normalized_metric_points = [
        point for points in group_metric_points_by_label(metric_points or []).values()
        for point in points
    ]
    entities = list(dict.fromkeys(point.entity for point in comparison_points))
    shares = {
        point.subject: point
        for _, slices in share_groups(normalized_metric_points)
        for point in slices
        if getattr(point, "subject", None)
    }
    panels = []
    for entity in entities:
        graded = [
            (point.criterion, point.value, point.level)
            for point in comparison_points if point.entity == entity
        ]
        figures = [
            point for point in normalized_metric_points
            if semantic_entity_key(getattr(point, "subject", None)) == semantic_entity_key(entity)
        ]
        share = shares.get(entity)
        if len(graded) + len(figures) + (1 if share else 0) < 2:
            continue
        panels.append((entity, graded[:4], figures[:2], share))
    return panels if len(panels) >= 2 else []


def has_competitor_panels(comparison_points: list[Any], metric_points: list[Any]) -> bool:
    return bool(competitor_panels(
        comparison_points_of_kind(comparison_points, demographic=False), metric_points
    ))


def competitor_panels_not_covered_by_ranking(
    comparison_points: list[Any], metric_points: list[Any]
) -> list[tuple[str, list[tuple[str, str, str | None]], list[Any], Any | None]]:
    """Panels whose entity has not already been claimed by a rank block."""
    rank_entities = {
        point.entity
        for group in ranking_comparison_groups(comparison_points)
        for point in group
    }
    if has_ranking_list(metric_points, comparison_points):
        rank_entities |= {
            point.subject
            for group in item_bar_groups(metric_points)
            if len(split_aggregate(group)[0]) >= 3
            for point in split_aggregate(group)[0]
            if getattr(point, "subject", None)
        }
    return [
        panel for panel in competitor_panels(
            comparison_points_of_kind(comparison_points, demographic=False), metric_points
        )
        if panel[0] not in rank_entities
    ]


def has_landscape(metric_points: list[Any]) -> bool:
    """Whether the evidence supports a market overview with two real parts.

    A landscape is broader than a line chart: it needs one core trend or
    snapshot structure and one complementary structure.  The complement may
    be an explicit part-to-whole split, a current player comparison, or a
    separate headline KPI.  A lone time series remains a chart.
    """
    return landscape_parts(metric_points) is not None


_LANDSCAPE_GENERIC_TOKENS = frozenset({
    "metric_market_size", "market", "시장", "size", "revenue", "매출", "규모", "가치",
    "share", "점유율", "비중", "구성비", "growth", "rate", "성장률", "증가율", "감소율",
    "증감률", "cagr", "current", "현재", "전체", "total", "지표", "수치",
})
_LANDSCAPE_SCOPE_ALIASES = {
    "global": frozenset({"global", "worldwide", "글로벌", "세계"}),
    "korea": frozenset({"korea", "korean", "국내", "한국"}),
}


def _landscape_context(points: list[Any]) -> tuple[set[str], set[str], set[str], set[str]]:
    """Topic, geography, measurement family and explicit time context."""
    raw = " ".join(
        str(value)
        for point in points
        for value in (getattr(point, "label", ""), getattr(point, "share_of", ""))
        if value
    ).casefold()
    normalized = re.sub(r"[^0-9a-z가-힣_]+", " ", raw)
    tokens = set(normalized.split())
    scopes = {
        scope for scope, aliases in _LANDSCAPE_SCOPE_ALIASES.items()
        if tokens & aliases
    }
    topics = tokens - _LANDSCAPE_GENERIC_TOKENS
    for aliases in _LANDSCAPE_SCOPE_ALIASES.values():
        topics -= aliases
    families: set[str] = set()
    semantic = " ".join(semantic_metric_key(getattr(point, "label", "")) for point in points)
    if "metric_market_size" in semantic or re.search(r"(?:market|시장).*(?:size|규모|가치)", raw):
        families.add("market_size")
    if re.search(r"\b(?:share|cagr|growth|rate)\b|점유율|비중|구성비|성장률|증가율|감소율|증감률", raw):
        families.add("market_structure")
    # Year-only, not the full (flag, year, quarter) sort key: this is an
    # "are these two blocks describing the same time context" overlap test,
    # not a chronological ordering, and a trend point stated as a bare
    # "2025년" legitimately shares its year with a share point stated as
    # "2025년 상반기" - narrowing this to full sort-key equality would make
    # a landscape's donut incompatible with its own trend chart the moment
    # either side states a quarter/half the other doesn't, for no reason
    # this check actually cares about.
    periods = {
        period_sort_key(getattr(point, "period", ""))[:2]
        for point in points if is_time_period(getattr(point, "period", ""))
    }
    return topics, scopes, families, periods


def _landscape_compatible(core: list[Any], complement: list[Any]) -> bool:
    """Whether two independently valid blocks describe one environment.

    Missing context is not filled by similarity. Generic market-size + market
    share/growth is the only topic-free pairing allowed because both labels
    explicitly state the same market structure.
    """
    core_topics, core_scopes, core_families, core_periods = _landscape_context(core)
    other_topics, other_scopes, other_families, other_periods = _landscape_context(complement)
    if core_scopes or other_scopes:
        if core_scopes != other_scopes:
            return False
    if core_topics or other_topics:
        if not core_topics or not other_topics or not (core_topics & other_topics):
            return False
    elif not ({"market_size"} <= core_families and "market_structure" in other_families):
        return False
    if core_periods and other_periods and not (core_periods & other_periods):
        return False
    return True


def landscape_parts(metric_points: list[Any]) -> tuple[str, list[Any], str, list[Any]] | None:
    """``(core_kind, core_points, complement_kind, complement_points)``.

    Every returned point is evidence-stated. This function groups and selects
    only; it never fills a missing period, share, or headline value.
    """
    grouped = group_metric_points_by_label(metric_points)
    trend = select_chartable_series(metric_points)
    shares = share_groups(metric_points)
    item_groups = item_bar_groups(metric_points)
    kpi_groups = [
        points for points in grouped.values()
        if classify_metric_shape(points) == "kpi"
    ]

    if trend:
        for _, share_points in shares:
            if _landscape_compatible(trend, share_points):
                return "trend", trend, "share", share_points
        for item_points in item_groups:
            if _landscape_compatible(trend, item_points):
                return "trend", trend, "comparison", item_points
        compatible_kpis = [
            points[0] for points in kpi_groups
            if _landscape_compatible(trend, [points[0]])
        ][:3]
        if compatible_kpis:
            return "trend", trend, "kpi", compatible_kpis
        return None

    # Snapshot landscape: at least two distinct headline measures plus a
    # genuine structure. A collection of unrelated one-off figures alone is
    # a KPI grid, not an overview.
    headline = [points[0] for points in kpi_groups[:4]]
    if len(headline) >= 2:
        for _, share_points in shares:
            if _landscape_compatible(headline, share_points):
                return "kpi", headline, "share", share_points
    return None


def comparison_points_of_kind(comparison_points: list[Any], demographic: bool) -> list[Any]:
    """Comparisons whose entities are (or are not) slices of people.

    The split every section-aware caller needs: 경쟁사 wants organisations,
    a demographic breakdown wants age or gender, and neither should be shown
    under the other's heading. Ordered by whatever the category implies -
    age brackets youngest first.
    """
    selected = [
        point for point in comparison_points
        if is_demographic(point.entity) == demographic
    ]
    return order_comparison_entities(normalize_comparison_axes(selected))


def comparison_points_not_covered_by_ranking(
    comparison_points: list[Any], metric_points: list[Any]
) -> list[Any]:
    """Drop rank-only facts already represented by a categorical metric block.

    Analyzer and report generation can legitimately encode the same sourced
    ranking once as ComparisonPoint and once as MetricPoint. Keeping both is
    useful for validation, but rendering both creates a duplicate table.
    Non-rank criteria and rankings without a corresponding metric series stay.
    """
    ranked_points = [
        point
        for group in item_bar_groups(metric_points)
        if len(split_aggregate(group)[0]) >= 3
        for point in split_aggregate(group)[0]
        if getattr(point, "subject", None)
    ]
    ranked_subjects = {point.subject for point in ranked_points}
    explicitly_ranked_entities = {
        point.entity
        for group in ranking_comparison_groups(comparison_points)
        for point in group
    }
    ranked_values: dict[str, set[float]] = {}
    for point in ranked_points:
        ranked_values.setdefault(point.subject, set()).add(float(point.value))

    def is_covered(point: Any) -> bool:
        criterion = (getattr(point, "criterion", "") or "").strip().casefold()
        is_rank = "순위" in criterion or "rank" in criterion or "ranking" in criterion
        entity = getattr(point, "entity", None)
        if is_rank and entity in ranked_subjects | explicitly_ranked_entities:
            return True
        numeric = re.search(r"-?\d+(?:\.\d+)?", getattr(point, "value", "") or "")
        return bool(
            numeric and entity in ranked_values
            and any(abs(float(numeric.group()) - value) < 1e-9 for value in ranked_values[entity])
        )

    return [point for point in comparison_points if not is_covered(point)]


def metric_points_not_covered_by_ranking(metric_points: list[Any]) -> list[Any]:
    """Metrics left after the ranking card claims its categorical series."""
    if not has_ranking_list(metric_points):
        return metric_points
    covered_labels = {
        group[0].label
        for group in item_bar_groups(metric_points)
        if group and len(split_aggregate(group)[0]) >= 3
    }
    return [point for point in metric_points if point.label not in covered_labels]


def has_comparison(comparison_points: list[Any], demographic: bool | None = None) -> bool:
    """True only when 2+ entities share a real common criterion - two
    entities that each only state a *different* metric (no overlap) don't
    make a comparable table, just two unrelated facts side by side.

    `demographic` narrows it to one kind of entity: False for the competitor
    table (organisations), True for an age or gender breakdown. Left None it
    asks the old question, which is still the right one wherever the section
    is about comparison in general.
    """
    points = (
        comparison_points if demographic is None
        else comparison_points_of_kind(comparison_points, demographic)
    )
    shared = filter_shared_comparison_axis(points)
    return len({point.entity for point in shared}) >= 2


def radar_axes(comparison_points: list[Any]) -> list[str]:
    """Criteria every compared entity has a stated `level` for. A radar with
    a missing vertex misreads as a zero, so an axis only counts when all
    plotted entities actually have a value on it."""
    leveled = [
        point for point in normalize_comparison_axes(comparison_points)
        if point.level in _LEVEL_RADIUS_FRACTION
    ]
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
    """Explicit periods with two to five top-level KPIs sharing a unit.

    Merely sharing ``%`` and ``시점 미상`` does not make dozens of unrelated
    figures comparable. Subject-bearing points belong to an item/ranking
    series; this block is for top-level measures pinned to the same period.
    """
    normalized_points = [
        point for points in group_metric_points_by_label(metric_points).values()
        for point in points
    ]
    by_period: dict[str, list[Any]] = {}
    for point in normalized_points:
        if not is_time_period(point.period) or getattr(point, "subject", None):
            continue
        by_period.setdefault(point.period, []).append(point)
    groups: list[tuple[str, list[Any]]] = []
    for period, points in by_period.items():
        by_unit: dict[str, list[Any]] = {}
        for point in points:
            by_unit.setdefault(point.unit or "", []).append(point)
        for unit_points in by_unit.values():
            distinct: dict[str, Any] = {}
            for point in unit_points:
                distinct.setdefault(point.label.casefold().strip(), point)
            if len(distinct) >= 2:
                groups.append((period, list(distinct.values())[:5]))
    return groups


def metric_snapshot_groups(metric_points: list[Any]) -> list[tuple[str, list[Any]]]:
    """Same-context headline metrics whose own units stay visible.

    Unlike ``metric_comparison_groups`` these values are not put on one
    numeric axis. They may mix market size, growth and share, provided they
    are top-level figures from the same explicit period.
    """
    by_period: dict[str, list[Any]] = {}
    for points in group_metric_points_by_label(metric_points).values():
        for point in points:
            if is_time_period(point.period) and not getattr(point, "subject", None):
                by_period.setdefault(point.period, []).append(point)
    groups: list[tuple[str, list[Any]]] = []
    for period, points in by_period.items():
        distinct: dict[str, Any] = {}
        for point in points:
            distinct.setdefault(point.label.casefold().strip(), point)
        units = {(point.unit or "").strip() for point in distinct.values()}
        if len(distinct) >= 2 and len(units) >= 2:
            groups.append((period, list(distinct.values())[:5]))
    return groups


def has_metric_comparison(metric_points: list[Any]) -> bool:
    return bool(metric_comparison_groups(metric_points))


def decision_matrix(
    comparison_points: list[Any], entity_limit: int = 6,
) -> tuple[list[str], str, str, dict[str, tuple[float, float, str, str]]] | None:
    """Two evidence-backed axes for a set of decision candidates.

    Numeric values use their stated number; qualitative values require an
    explicit ``level`` already verified by the analyzer. Coordinates are
    normalized only for drawing relative positions—no High/Medium/Low label
    or threshold is invented.
    """
    comparison_points = normalize_comparison_axes(comparison_points or [])
    by_entity: dict[str, dict[str, Any]] = {}
    criterion_order: list[str] = []
    for point in comparison_points or []:
        by_entity.setdefault(point.entity, {})[point.criterion] = point
        if point.criterion not in criterion_order:
            criterion_order.append(point.criterion)
    shared = [
        criterion for criterion in criterion_order
        if sum(criterion in rows for rows in by_entity.values()) >= 2
    ]
    if len(shared) < 2:
        return None

    def grounded_coordinate(point: Any) -> float | None:
        if getattr(point, "level", None) in LEVEL_RADIUS_FRACTION:
            return LEVEL_RADIUS_FRACTION[point.level]
        match = re.search(r"-?\d+(?:\.\d+)?", getattr(point, "value", "") or "")
        return float(match.group()) if match else None

    for x_axis, y_axis in (
        (shared[left], shared[right])
        for left in range(len(shared)) for right in range(left + 1, len(shared))
    ):
        raw: list[tuple[str, float, float, str, str]] = []
        for entity, rows in by_entity.items():
            if x_axis not in rows or y_axis not in rows:
                continue
            x_value = grounded_coordinate(rows[x_axis])
            y_value = grounded_coordinate(rows[y_axis])
            if x_value is None or y_value is None:
                continue
            raw.append((entity, x_value, y_value, rows[x_axis].value, rows[y_axis].value))
        if len(raw) < 2:
            continue
        x_values = [row[1] for row in raw]
        y_values = [row[2] for row in raw]

        def scale(value: float, values: list[float]) -> float:
            low, high = min(values), max(values)
            return 0.5 if high == low else (value - low) / (high - low)

        cells = {
            entity: (scale(x, x_values), scale(y, y_values), x_text, y_text)
            for entity, x, y, x_text, y_text in raw[:entity_limit]
        }
        return list(cells), x_axis, y_axis, cells
    return None


def has_decision_matrix(comparison_points: list[Any]) -> bool:
    return decision_matrix(comparison_points) is not None


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


def _timeline_metric_series(metric_points: list[Any]) -> list[Any] | None:
    """The single repeated-period metric `timeline_entries` would plot, if any.

    Split out of `timeline_entries` so a caller that only needs to know
    *which* metric a timeline would draw (not render its rows) - the
    dedup-identity path in `purpose_slots._consumption` - can ask without
    duplicating the selection rule.
    """
    points_by_label = {
        label: [point for point in points if is_time_period(point.period)]
        for label, points in group_metric_points_by_label(metric_points).items()
    }
    return max(
        (
            points for points in points_by_label.values()
            if len({point.period for point in points}) >= 2
        ),
        key=lambda points: len({point.period for point in points}),
        default=None,
    )


def timeline_evidence_label(metric_points: list[Any]) -> str | None:
    """The label of the metric a timeline would plot, or None if it would
    fall back to dated prose instead. Used only to key cross-block dedup -
    see `purpose_slots._consumption`'s "timeline" entry."""
    series = _timeline_metric_series(metric_points)
    return series[0].label if series else None


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
    series = _timeline_metric_series(metric_points)
    # One timeline, one measurement definition. If no repeated metric exists,
    # fall back to dated events only; never insert unrelated one-off KPIs
    # between those events merely because they have dates.
    if series:
        for point in series:
            entries.append((point.period, f"{point.label} {_format_number(point.value)}{point.unit or ''}"))
    else:
        method_re = re.compile(
            r"표본|조사\s*대상|응답자|대면\s*면접|실시한.{0,20}조사|"
            r"조사.{0,50}(?:국민|명)|sample|respondents?|surveyed",
            re.IGNORECASE,
        )
        for sentence in dated_items(evidence):
            if method_re.search(sentence):
                continue
            period = _timeline_period(sentence, reference_year)
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


# What a source says about where something stands. These are literal words a
# document either used or didn't, so reading them is not a judgement - but
# they only ever *downgrade* certainty: a sentence with no marker is dated
# but unlabelled, never assumed finished.
_ACTIVE_MARKERS = ("진행 중", "진행중", "추진 중", "추진중", "확대하고 있다", "협의 중",
                   "협의중", "시범", "베타", "준비 중", "준비중", "논의 중", "논의중")
_PLANNED_MARKERS = ("예정", "계획", "전망", "목표", "추진할", "도입할", "검토 중", "검토중",
                    "출시할", "예상")
_DONE_MARKERS = ("완료", "출시했", "도입했", "체결했", "종료", "달성했", "마무리")


def timeline_status(sentence: str, period: str, as_of_date: str | None = None) -> str:
    """`done` / `active` / `todo` for one timeline row.

    Derived, not invented. A marker the document actually wrote wins outright
    ("진행 중" is active however its date reads), and only where the sentence
    says nothing about status does the date decide - a period after the
    report's own as-of date has not happened yet.

    The default is `active`, not `done`. A dated sentence with no completion
    word is a thing that was reported, and marking it finished would be the
    one reading the evidence never supports; every other outcome here is
    either stated or arithmetic.
    """
    text = sentence or ""
    if any(marker in text for marker in _ACTIVE_MARKERS):
        return "active"
    if any(marker in text for marker in _PLANNED_MARKERS):
        return "todo"
    if any(marker in text for marker in _DONE_MARKERS):
        return "done"
    reference = None
    try:
        reference = int(str(as_of_date)[:4]) if as_of_date else None
    except ValueError:
        reference = None
    if reference is not None:
        year_match = re.search(r"20\d{2}", period or "")
        if year_match:
            year = int(year_match.group(0))
            if year > reference:
                return "todo"
            if year < reference:
                return "done"
    return "active"


def timeline_entries_with_status(
    evidence: list[str],
    metric_points: list[Any],
    reference_year: int | None = None,
    as_of_date: str | None = None,
) -> list[tuple[str, str, str]]:
    """`timeline_entries` plus each row's stated progress state."""
    return [
        (period, text, timeline_status(text, period, as_of_date))
        for period, text in timeline_entries(evidence, metric_points, reference_year)
    ]


def has_timeline(
    evidence: list[str], metric_points: list[Any], reference_year: int | None = None
) -> bool:
    """True only when the entries actually span more than one point in time.

    One date repeated down a column is a snapshot wearing a timeline's
    layout. The block exists to show *when things changed*; with a single
    period there is no change to show, and a snapshot has its own blocks
    (kpi_grid, metric_comparison, item_bar).
    """
    entries = timeline_entries(evidence, metric_points, reference_year)
    return len({period for period, _ in entries}) >= 2


def _children_by_parent(grounded_claims: list[Any]) -> dict[str, list[Any]]:
    by_id = {claim.synthesis_claim_id: claim for claim in grounded_claims}
    children: dict[str, list[Any]] = {}
    for claim in grounded_claims:
        parent = getattr(claim, "parent_synthesis_claim_id", None)
        if parent in by_id and parent != claim.synthesis_claim_id:
            children.setdefault(parent, []).append(claim)
    return children


def cause_roots(grounded_claims: list[Any]) -> list[Any]:
    """Claims at least one other claim derives from, that derive from nothing.

    A claim nobody derives from is a finding, not the root of anything, and
    belongs in the ordinary list.
    """
    children = _children_by_parent(grounded_claims)
    return [
        claim for claim in grounded_claims
        if claim.synthesis_claim_id in children
        and not getattr(claim, "parent_synthesis_claim_id", None)
    ]


def cause_forest(grounded_claims: list[Any], max_depth: int = 3) -> list[dict]:
    """The whole stated chain as nested {claim, children} nodes.

    Three levels by default - root cause, what it drove, and what that in turn
    drove - because that is as deep as the delivered artwork goes and as deep
    as a document's own wording usually reaches. Anything below the cut is
    dropped rather than flattened up a level, which would attribute a
    third-order effect directly to the root.

    `cause_tree` remains the two-level view; this is what the renderer walks,
    so a document that stated a longer chain still shows it instead of having
    its middle layer silently become the leaf layer.
    """
    children = _children_by_parent(grounded_claims)

    def build(claim: Any, depth: int, seen: set[str]) -> dict:
        node = {"claim": claim, "children": []}
        if depth >= max_depth:
            return node
        for child in children.get(claim.synthesis_claim_id, []):
            if child.synthesis_claim_id in seen:
                continue
            node["children"].append(build(child, depth + 1, seen | {child.synthesis_claim_id}))
        return node

    return [
        build(root, 1, {root.synthesis_claim_id})
        for root in cause_roots(grounded_claims)
    ]


def cause_tree(grounded_claims: list[Any], max_depth: int = 2) -> list[tuple[Any, list[Any]]]:
    """Root claims with the claims the evidence says follow from them.

    The flat two-level view, kept because `has_cause_tree` and its tests read
    it. `cause_forest` is what the renderer walks.
    """
    if max_depth < 2:
        return []
    children = _children_by_parent(grounded_claims)
    return [
        (root, children[root.synthesis_claim_id]) for root in cause_roots(grounded_claims)
    ]


def has_cause_tree(grounded_claims: list[Any]) -> bool:
    return bool(cause_tree(grounded_claims))


def importance_ranked(grounded_claims: list[Any], limit: int = 5) -> list[Any]:
    """Claims the model scored for importance, strongest first.

    Only claims carrying both a score and its stated basis - the verifier
    drops one without the other, and a renderer must show the basis, so a
    claim that can't explain its own score never reaches a bar.

    Restricted to `claim_type == "factor"` - live-verified 2026-08-11: this
    fed "Key Drivers" (block_title "driver_bars") from every claim type the
    model happened to score, so an `opportunity` claim like "AI 메모리 수요
    증가에 기반한 시장 성장 기회가 있다" or a `risk` claim ended up ranked
    under a heading that promises causes, not general findings. `factor` is
    the one claim_type the schema defines as "무엇이 그것을 좌우하는가" - an
    actual driver/reason, not a fact, impact, or opportunity about the
    subject. A `business_impact`/`risk`/`opportunity` claim can still be
    important; it just isn't a *driver*, and this block's whole promise is
    that ranking.
    """
    scored = [
        claim for claim in grounded_claims
        if getattr(claim, "claim_type", None) == "factor"
        and getattr(claim, "importance", None) is not None
        and (getattr(claim, "importance_basis", None) or "").strip()
    ]
    return sorted(scored, key=lambda claim: claim.importance, reverse=True)[:limit]


def has_importance_ranking(grounded_claims: list[Any]) -> bool:
    """Whether these scores actually rank anything.

    Two conditions. One bar is not a ranking - it's a single claim with a
    number stuck to it. And a set of claims the model scored identically is
    not one either: a live run drew four bars all reading 100/100 under the
    heading 영향도, which is a full-width block whose entire content is "the
    model did not distinguish these". A ranking has to separate at least two
    things or it has nothing to say.
    """
    ranked = importance_ranked(grounded_claims)
    return len(ranked) >= 2 and len({claim.importance for claim in ranked}) >= 2


# Function words and reporting verbs that recur in every Korean article
# regardless of subject. They are not a topic, so counting them would rank
# "따르면" above whatever the documents were actually about.
_TERM_STOPWORDS = frozenset({
    "있다", "없다", "한다", "했다", "된다", "됐다", "이다", "관련", "대한", "대해", "통해",
    "위해", "따르면", "밝혔다", "말했다", "설명", "분석", "전망", "예상", "지난해", "올해",
    "이번", "지난", "가장", "많은", "다양", "경우", "때문", "이후", "이전", "기준", "정도",
    "수준", "부분", "상황", "내용", "결과", "필요", "이용", "제공", "서비스", "그리고",
    "하지만", "또한", "특히", "현재", "최근", "계속", "다시", "모두", "각각", "이러한",
})
_TERM_STOPWORDS = _TERM_STOPWORDS | {
    "것으", "나타났", "나타났다", "기록했", "기록했다", "응답했", "응답했다",
    # URL/domain scaffolding is not a repeated business topic.
    "http", "https", "www", "com", "org", "net",
}
_TERM_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")
def recurring_terms(
    grounded_claims: list[Any], min_documents: int = 2, limit: int = 8
) -> list[tuple[str, int, Any]]:
    """Words that recur across *separate* documents, with one claim each.

    A measurement over the collected evidence, not an interpretation of it:
    the count is how many distinct documents used the word, and every term
    carries a real claim the reader can open. Nothing is inferred about what
    the word means or why it matters.

    Requiring two documents is the whole safeguard against noise. One article
    repeating its own vocabulary says nothing about a market; the same word
    turning up in unrelated sources is the observation worth showing. Terms
    are counted once per document for the same reason - a single long article
    must not out-vote three short ones.
    """
    docs_by_term: dict[str, set[str]] = {}
    claim_by_term: dict[str, Any] = {}
    for claim in grounded_claims:
        doc_id = getattr(claim, "doc_id", None) or getattr(claim, "synthesis_claim_id", "")
        text = f"{getattr(claim, 'claim', '')} {getattr(claim, 'evidence_quote', '')}"
        for term in {
            stem for token in _TERM_RE.findall(text)
            if (stem := strip_particle(token)) not in _TERM_STOPWORDS and len(stem) >= 2
        }:
            docs_by_term.setdefault(term, set()).add(doc_id)
            claim_by_term.setdefault(term, claim)
    ranked = sorted(
        (
            (term, len(doc_ids), claim_by_term[term])
            for term, doc_ids in docs_by_term.items()
            if len(doc_ids) >= min_documents
        ),
        key=lambda row: (-row[1], row[0]),
    )
    return ranked[:limit]


def has_recurring_terms(grounded_claims: list[Any], minimum: int = 3) -> bool:
    # Two words shared between two articles is a coincidence, not a pattern
    # worth a card of its own.
    return len(recurring_terms(grounded_claims or [])) >= minimum


def has_cause_map(risks: list[str], impacts: list[str], actions: list[str]) -> bool:
    return sum(1 for column in (risks, impacts, actions) if column) >= 2


# --- KPI candidate selection ----------------------------------------------
#
# KPI had no selection at all: `kpi_grid` availability was a count
# (`len(metric_series) >= 2`) and the block handed the whole series to the
# renderer in list order, so the first card was whichever metric synthesis
# happened to put first. Live-verified 2026-08-10 that produced
# "609 증감률 1.8%" and later "유료방송시장 전체 가입자 수 3,629만 (2023년)"
# for the question "IPTV 가입자 수 현황은?" - neither the question nor the
# recency of the figure was ever consulted.
#
# `render_kpi_row` already ranks by `question_terms` and already collapses
# one label's several periods into a latest-plus-delta card; the generic
# slot path simply never passed the question through. This adds the two
# things that ranking cannot do on its own: dropping a metric whose value
# two sources disagree about, and keeping one representative per metric so
# a single series cannot fill the grid.
KPI_MAX_CANDIDATES = 6


def rank_kpi_candidates(
    metric_points: list[Any],
    question_terms: list[str] | None = None,
    limit: int = KPI_MAX_CANDIDATES,
) -> list[Any]:
    """Representative, conflict-free metrics for a KPI row, best first.

    Relevance to the question outranks recency, and recency only breaks
    ties inside one metric: a 2025 advertising-market figure must not
    displace a 2024 subscriber count when subscribers are what was asked
    about. A metric whose identity carries two different values is left out
    entirely - picking the first, the latest or the average would each be
    inventing an answer the evidence does not give.
    """
    from common.metric_identity import (
        canonical_period,
        conflicting_metric_groups,
        metric_identity,
    )

    conflicted = {
        metric_identity(point)
        for group in conflicting_metric_groups(metric_points)
        for point in group
    }
    representatives: dict[str, Any] = {}
    for point in metric_points:
        if metric_identity(point) in conflicted:
            continue
        key = semantic_metric_key(getattr(point, "label", None))
        current = representatives.get(key)
        if current is None:
            representatives[key] = point
            continue
        # Same metric, several periods: the KPI card shows one reading and
        # the series belongs to a chart, so keep the most recent stated one.
        incumbent = canonical_period(getattr(current, "period", None)) or ""
        challenger = canonical_period(getattr(point, "period", None)) or ""
        if challenger > incumbent:
            representatives[key] = point

    # `rank_by_relevance` answers "does this match at all", which is the
    # right question where it is used and the wrong one here: for "IPTV
    # 가입자 수 현황은?" both "IPTV 가입자 수" and "유료방송시장 전체 가입자
    # 수" match, so the original list order decided the first card - which is
    # how the whole-market figure kept leading a question about IPTV.
    # Counting the distinct terms a label covers separates them without
    # changing that helper for its other callers.
    terms = [term.casefold() for term in (question_terms or []) if len(term) >= 2]

    def _score(point: Any) -> int:
        label = f"{getattr(point, 'label', '') or ''} {getattr(point, 'subject', '') or ''}".casefold()
        return sum(1 for term in terms if term in label)

    candidates = list(representatives.values())
    if terms:
        candidates.sort(key=_score, reverse=True)
    return candidates[:limit]


def headline_kpi(
    metric_points: list[Any], question: str | None, core_entities: list[str] | None = None,
) -> Any | None:
    """The one figure that answers the question, or None if there isn't one.

    Deliberately not a new notion of importance. It is the top of
    `rank_kpi_candidates` - the same relevance-over-recency ranking the KPI
    grid already uses - narrowed by the conditions that make a figure
    quotable on its own:

    * it is grounded, meaning it carries the claim id of a quote verified
      against the source text (`evidence_claim_id`), and a document to go
      back to;
    * it actually answers *this* question, meaning its label matches at
      least one term of it;
    * when `core_entities` is given (see `executive_summary_supporting_kpis`
      for why - generic sector words like "배터리" match a market-wide
      figure exactly as well as the company being asked about), it also
      names one of them.

    These are what leave the slot empty rather than filling it. A question
    that no single number answers - "왜 가입자가 줄었나" - has no headline
    KPI, and putting the largest figure lying around there would assert a
    relevance nothing established.
    """
    terms = [term.casefold() for term in (question or "").split() if len(term) >= 2]
    if not terms:
        return None
    entities = [entity.casefold() for entity in (core_entities or []) if entity]
    for point in rank_kpi_candidates(metric_points, (question or "").split()):
        if not getattr(point, "evidence_claim_id", None):
            continue
        if not (getattr(point, "doc_id", None) or getattr(point, "source_url", None)):
            continue
        label = f"{getattr(point, 'label', '') or ''} {getattr(point, 'subject', '') or ''}".casefold()
        if not any(term in label for term in terms):
            continue
        if entities and not any(entity in label for entity in entities):
            continue
        return point
    return None


_EXEC_SUMMARY_KPI_LIMIT = 3


def executive_summary_supporting_kpis(
    metric_points: list[Any],
    question: str | None,
    headline_point: Any | None,
    limit: int = _EXEC_SUMMARY_KPI_LIMIT,
    core_entities: list[str] | None = None,
) -> list[Any]:
    """A few more figures worth a small KPI card beside the summary's
    headline number - "[핵심 메시지] [KPI][KPI][KPI]", never a text
    restatement of numbers already drawable as cards.

    Same ranking Key Metrics uses (`rank_kpi_candidates`), minus whichever
    metric the headline already shows - a caller seeds these into
    `resolve_slots`'s dedup state (see `common/purpose_slots.
    kpi_evidence_key`) so Key Metrics does not repeat them either.

    `core_entities` (the entity stage's own extracted organizations/
    technologies for this question, when the caller has them) is an
    optional hard filter on top of the soft ranking. Live-verified
    2026-08-11: "SK온 배터리 사업 수익성 부진의 원인은?" ranked a
    2040-forecast humanoid-robot battery-demand figure into a supporting
    KPI slot, because `rank_kpi_candidates`'s term overlap counts generic
    sector words ("배터리") the same as the actual company name ("SK온") -
    a figure about the whole battery market scored exactly as "relevant" as
    one about the company being asked about. Entities are a much sharper
    signal (they name *who* the question is about, not just its topic
    vocabulary), so when they're available, a candidate whose label+subject
    names none of them is dropped rather than padded in to fill the quota -
    same "don't force-fill" principle as `_driver_bars`.
    """
    candidates = rank_kpi_candidates(metric_points, (question or "").split())
    if core_entities:
        entities = [entity.casefold() for entity in core_entities if entity]
        candidates = [
            point for point in candidates
            if any(
                entity in f"{getattr(point, 'label', '') or ''} {getattr(point, 'subject', '') or ''}".casefold()
                for entity in entities
            )
        ]
    if headline_point is not None:
        headline_key = semantic_metric_key(getattr(headline_point, "label", None))
        candidates = [
            point for point in candidates
            if semantic_metric_key(getattr(point, "label", None)) != headline_key
        ]
    return candidates[:limit]


def executive_summary_comparison(
    metric_points: list[Any],
) -> tuple[str, str, list[Any]] | None:
    """One comparison-shaped group worth a compact visualization in the
    Executive Summary - "[competitor comparison visualization]" in the
    reference layout - or None when nothing here is shaped for one.

    Composition (a stated whole split into named parts, e.g. "KT 25% / SKB
    19% / LGU+ 16%") is preferred over a bare same-period item comparison:
    a share-of-whole reads as one relationship, where an item comparison is
    several independent figures that happen to share a period. Only the
    single most useful group is returned - the Executive Summary gets one
    compact visualization, not a full section's worth; `render_metric_bar`/
    `render_share_split` already own the fuller versions further down the
    page.

    Returns `("share", whole_name, points)` or `("comparison", period, points)`.
    """
    shares = share_groups(metric_points)
    if shares:
        whole, points = shares[0]
        return "share", whole, points
    groups = metric_comparison_groups(metric_points)
    if groups:
        period, points = groups[0]
        return "comparison", period, points
    return None
