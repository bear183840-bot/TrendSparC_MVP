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


def cause_tree(grounded_claims: list[Any], max_depth: int = 2) -> list[tuple[Any, list[Any]]]:
    """Root claims with the claims the evidence says follow from them.

    Two levels only. A deeper tree doesn't fit the column and, more to the
    point, the third level is where a model's causal guesses start rather
    than a document's stated chain. Roots are claims with no parent that at
    least one other claim points at - a claim nobody derives from is a
    finding, not the root of anything, and it belongs in the ordinary list.
    """
    by_id = {claim.synthesis_claim_id: claim for claim in grounded_claims}
    children: dict[str, list[Any]] = {}
    for claim in grounded_claims:
        parent = getattr(claim, "parent_synthesis_claim_id", None)
        if parent in by_id and parent != claim.synthesis_claim_id:
            children.setdefault(parent, []).append(claim)
    if max_depth < 2:
        return []
    return [
        (claim, children[claim.synthesis_claim_id])
        for claim in grounded_claims
        if claim.synthesis_claim_id in children
        and not getattr(claim, "parent_synthesis_claim_id", None)
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
