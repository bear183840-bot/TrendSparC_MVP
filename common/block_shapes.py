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


def time_bar_groups(metric_points: list[Any]) -> list[list[Any]]:
    """Only the before/after-over-time labels - movement, not ranking."""
    by_label = group_metric_points_by_label(metric_points)
    return [points for points in by_label.values() if classify_metric_shape(points) == "bar"]


def item_bar_groups(metric_points: list[Any]) -> list[list[Any]]:
    """Only the across-items labels - ranking, not movement.

    Split out from `bar_metric_groups` because the two answer different
    questions and were competing for the same slot: 시장 상황 asks which way
    things are moving, and a three-way comparison between companies has no
    direction in it at all. Whichever slot ran first used to claim both.
    """
    by_label = group_metric_points_by_label(metric_points)
    return [points for points in by_label.values() if classify_metric_shape(points) == "comparison"]


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
    by_label: dict[str, list[Any]] = {}
    for point in metric_points:
        if getattr(point, "subject", None) and point.period:
            by_label.setdefault(point.label, []).append(point)
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


def status_levels(comparison_points: list[Any], limit: int = 4) -> list[tuple[str, str, str]]:
    """(criterion, entity + value, level) for the artwork's KPI status bar.

    A qualitative counterpart to the KPI row: where a figure isn't available
    but the source graded something, the grade is still worth the top of the
    page. Only points the document actually graded are eligible - a value with
    no stated `level` has no standing to be shown as a status.
    """
    graded = [point for point in comparison_points if point.level]
    seen: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for point in graded:
        if point.criterion in seen:
            continue
        seen.add(point.criterion)
        rows.append((point.criterion, f"{point.entity} · {point.value}", point.level))
    return rows[:limit]


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
    by_whole: dict[str, list[Any]] = {}
    for point in metric_points:
        whole = (getattr(point, "share_of", None) or "").strip()
        if whole and (point.unit or "").strip() in {"%", "％"}:
            by_whole.setdefault(whole, []).append(point)
    groups = []
    for whole, points in by_whole.items():
        if len(points) < SHARE_MIN_SLICES:
            continue
        if sum(point.value for point in points) > 100 + SHARE_SUM_TOLERANCE:
            continue
        groups.append((whole, sorted(points, key=lambda point: point.value, reverse=True)))
    return groups


def has_share_split(metric_points: list[Any]) -> bool:
    return bool(share_groups(metric_points))


def has_landscape(metric_points: list[Any]) -> bool:
    """Whether one card can carry both halves of the artwork's Landscape:
    how the market moved, and what it is made of.

    Both halves have to stand on their own first - a trend that earns a line
    and a split that earns a donut - because this block only places them side
    by side. It never derives one from the other.
    """
    return has_timeseries(metric_points) and has_share_split(metric_points)


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
    return bool(timeline_entries(evidence, metric_points, reference_year))


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


def importance_ranked(grounded_claims: list[Any], limit: int = 6) -> list[Any]:
    """Claims the model scored for importance, strongest first.

    Only claims carrying both a score and its stated basis - the verifier
    drops one without the other, and a renderer must show the basis, so a
    claim that can't explain its own score never reaches a bar.
    """
    scored = [
        claim for claim in grounded_claims
        if getattr(claim, "importance", None) is not None
        and (getattr(claim, "importance_basis", None) or "").strip()
    ]
    return sorted(scored, key=lambda claim: claim.importance, reverse=True)[:limit]


def has_importance_ranking(grounded_claims: list[Any]) -> bool:
    # One bar is not a ranking; it's a single claim with a number stuck to it.
    return len(importance_ranked(grounded_claims)) >= 2


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
_TERM_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")
# Korean particles glue onto the noun, so a plain word split reads "요금" and
# "요금과" as two different terms and neither reaches the two-document
# threshold. Trimming a trailing particle is not morphology - it is the one
# rule that stops the same noun being counted twice - so it only applies when
# a real stem is left behind.
_PARTICLES = ("으로서", "으로써", "에서는", "에게서", "으로", "에서", "에게", "부터",
              "까지", "이라", "라는", "이나", "과의", "와의", "의", "은", "는", "이",
              "가", "을", "를", "과", "와", "에", "도", "로", "만", "보다")


def _strip_particle(token: str) -> str:
    if not re.fullmatch(r"[가-힣]+", token):
        return token
    for particle in _PARTICLES:
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[: -len(particle)]
    return token


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
            if (stem := _strip_particle(token)) not in _TERM_STOPWORDS and len(stem) >= 2
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
