"""Sector/purpose/question-agnostic content-quality rules.

These are pure functions with no side effects and no dependency on any one
sector, audience, or purpose - every caller (rendering code in
reporting/dashboard_streamlit/, report assembly in
core/report_generator/generator.py, purpose classification in
core/report_purpose/classifier.py) imports from here rather than each
re-implementing its own version of the same rule. Nothing here fabricates
data: every function either reorders/filters/groups items that already
exist, or detects a signal already present in already-computed data (e.g.
`classify_report_purpose`'s own per-purpose scores) - never invents a new
fact.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Literal

from common.contracts import MetricPoint

MetricShape = Literal["kpi", "bar", "line", "comparison"]

_YEAR_RE = re.compile(r"(20\d{2}|\d{2})")
_QUARTER_RE = re.compile(r"([1-4])\s*(?:Q|분기)", re.I)
_TIMELINE_DATE_RE = re.compile(r"(20\d{2}\s*년(?:\s*\d{1,2}\s*월)?|[1-4]\s*분기|\d{1,2}\s*월\s*\d{1,2}\s*일)")


def dated_items(items: list[str]) -> list[str]:
    """Items that contain a concrete date/period marker (year, quarter, or
    month-day) - the shared way to tell genuinely time-anchored content
    apart from prose that merely sits in a "timeline"-named section. Used
    both to build an honest timeline section (report_generator.py) and to
    decide whether a section actually earns the "timeline" block_type
    (layout_generator.py) instead of getting it just because of its name.
    """
    return [item for item in items if item and _TIMELINE_DATE_RE.search(item)]


# MetricPoint.period is free text and is not always a point in time. Analyzers
# legitimately use it to name the subject a figure belongs to ("B tv+ 앱" vs
# "경쟁 OTT 앱 평균", "이용자 설문"), which is a comparison, not a chronology.
# Anything chronological has to check for a real time marker first.
# A trailing 전/후 ("도입 전", "개편 이후") is a real temporal order even with
# no date attached, and the before/after bar depends on it. It has to be
# anchored at the end so it can't match a subject name that merely contains
# those syllables.
_TIME_PERIOD_RE = re.compile(
    r"(?:20\d{2}|'\d{2})\s*년|[1-4]\s*분기|[1-4]\s*Q|\d{1,2}\s*월|상반기|하반기"
    # A bare four-digit year ("2019", "2023") is a period too. Bounded so it
    # can't match inside a longer number or an age bracket like "20대".
    r"|(?<!\d)(?:19|20)\d{2}(?!\d)"
    r"|(?:^|\s)(?:이전|이후|전|후)\s*$",
    re.I,
)


def is_time_period(period: str | None) -> bool:
    """Whether a MetricPoint.period names a point in time at all.

    Live-observed: an app-churn analysis stored the compared subject in
    `period`, and both report_planner and the timeline block read those as
    two distinct dates - so a report with no chronology whatsoever was given
    a Timeline section listing "B tv+ 앱" as if it were a moment.
    """
    return bool(_TIME_PERIOD_RE.search(period or ""))


def has_renderable_content(*value_groups: Any) -> bool:
    """Whether a panel has anything real to show.

    A section with nothing in it used to be rendered anyway, as a card whose
    only content was "검증된 신호가 없습니다." - three of those side by side
    told the reader nothing while taking the space that the sections which did
    have evidence could have used. A section that fails this check is dropped
    entirely rather than filled with an apology.
    """
    for group in value_groups:
        if group is None:
            continue
        if isinstance(group, str):
            if group.strip():
                return True
            continue
        for value in group:
            if value is None:
                continue
            if isinstance(value, str):
                if value.strip():
                    return True
            else:
                return True
    return False


def period_sort_key(period: str) -> tuple:
    """Best-effort chronological key for a (year, quarter) style period
    string, regardless of whether the evidence wrote it "2025년 1분기",
    "1Q25", or similar - never rewrites the displayed text, only used to
    order/compare periods. Falls back to sorting an unparseable period
    alphabetically after every parseable one rather than crashing.

    A period with a year but no quarter ("2025년") sorts by its year, at
    quarter 0. Real evidence mixes annual and quarterly figures freely, and
    treating the annual one as unparseable pushed it behind every quarterly
    period regardless of year - so "2026년 1분기" landed before "2025년"."""
    year_m = _YEAR_RE.search(period or "")
    quarter_m = _QUARTER_RE.search(period or "")
    if not year_m:
        return (1, period or "")
    year = int(year_m.group(1))
    if year < 100:
        year += 2000
    return (0, year, int(quarter_m.group(1)) if quarter_m else 0)

# Words that signal a *prescriptive* ask ("how do I improve/increase this")
# layered on top of what might otherwise read as a pure status question -
# e.g. "가입자 수 변화 알려주고 앞으로 어떻게 늘릴 수 있을지 알려줘" scores
# current_status from primary_intent but never touches future_business at
# all without these, because none of the existing future_business signals
# ("미래","전망","신사업","투자","기회","성장","로드맵",...) are about *how*
# to move a metric - they're about topic area, not framing.
PRESCRIPTIVE_INTENT_SIGNALS: tuple[str, ...] = (
    "어떻게", "방안", "늘리려면", "늘릴", "개선하려면", "개선 방안", "전략", "높이려면",
)

# Single source of truth for the "actively look for all four SWOT fields"
# instruction - previously each of the 6 sector analyzers phrased this
# slightly differently (see sectors/*/adapter/analyzer/__init__.py).
SWOT_COMPLETENESS_INSTRUCTION = (
    "risk/opportunity와 마찬가지로 strength(강점)와 weakness(약점)도 문서에 근거가 있으면 "
    "반드시 채우세요 — 누락하지 말고 적극적으로 찾으세요. 특히 한쪽만(예: strength만) 계속"
    "채워지고 반대쪽(weakness)이 매번 비는 경우가 없도록, 문서에 나온 한계·리스크·경쟁열위도 "
    "weakness 후보로 적극적으로 검토하세요."
)


def rank_by_relevance(items: list[str], question_terms: list[str]) -> list[str]:
    """Reorder `items` so the ones sharing a term with `question_terms` come
    first (stable sort - ties keep original order). Never drops an item:
    something with real evidence behind it just sinks to the back instead of
    vanishing, since low relevance to the question isn't the same as being
    wrong.
    """
    if not question_terms:
        return list(items)
    terms = [term.lower() for term in question_terms if term]

    def _matches(item: str) -> bool:
        lowered = item.lower()
        return any(term in lowered for term in terms)

    relevant = [item for item in items if _matches(item)]
    rest = [item for item in items if not _matches(item)]
    return relevant + rest


def classify_metric_shape(points_for_one_label: list[Any]) -> MetricShape:
    """How one label's points should be visualized.

    Distinct period count decides the shape, but only once the periods are
    known to be points in *time*: a single point is a plain KPI figure, two
    are a before/after bar (two dots don't make a trend), three or more are a
    genuine time series worth a line.

    When the periods are not times - an analyzer legitimately uses `period`
    for the subject a figure belongs to ("SK브로드밴드" / "KT" / "LG유플러스",
    "20대" / "50대 이상") - the label is a `comparison` instead. Live-observed:
    one metric measured across the three IPTV carriers was classified "line"
    and drawn as a chart running SK브로드밴드 → KT → LG유플러스, which asserts
    a progression between companies that means nothing.
    """
    periods = {point.period for point in points_for_one_label}
    if len(periods) <= 1:
        return "kpi"
    if not all(is_time_period(period) for period in periods):
        return "comparison"
    if len(periods) == 2:
        return "bar"
    return "line"


def group_metric_points_by_label(metric_points: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for point in metric_points:
        grouped.setdefault(point.label, []).append(point)
    return grouped


def select_chartable_series(metric_points: list[Any]) -> list[Any]:
    """Of the labels shaped like a real time series (`classify_metric_shape`
    == "line"), pick the one with the most distinct periods as the anchor,
    then keep only the other line-shaped labels that share BOTH overlapping
    periods AND the same unit with it. A label with a different unit (e.g.
    매출 in 억원 next to 가입자 수 in 명) or a disjoint timeline gets
    dropped from the shared chart - not lost, still available via the KPI
    row/bar comparison, just not squeezed onto an axis it doesn't belong on.
    Returns [] when there's no line-shaped data at all (call has_timeseries-
    style logic on the result, don't assume it's non-empty).
    """
    grouped = group_metric_points_by_label(metric_points)
    line_labels = {
        label: points for label, points in grouped.items() if classify_metric_shape(points) == "line"
    }
    if not line_labels:
        return []
    anchor_label = max(line_labels, key=lambda label: len({p.period for p in line_labels[label]}))
    anchor_points = line_labels[anchor_label]
    anchor_period_keys = {period_sort_key(p.period) for p in anchor_points}
    anchor_unit = anchor_points[0].unit
    chartable: list[Any] = []
    for label, points in line_labels.items():
        unit = points[0].unit
        period_keys = {period_sort_key(p.period) for p in points}
        if unit == anchor_unit and period_keys & anchor_period_keys:
            chartable.extend(points)
    return chartable


def filter_shared_comparison_axis(comparison_points: list[Any]) -> list[Any]:
    """Keep only the criteria that at least 2 distinct entities actually
    have a value for (a real shared axis), dropping criteria only one
    entity happens to mention. Prevents building a comparison table that's
    mostly blank cells because two genuinely different metrics (e.g. "IPTV
    가입자 수" vs "국내 월간 이용자 수") got grouped as if comparable.
    """
    if not comparison_points:
        return []
    entities_per_criterion: dict[str, set[str]] = {}
    for point in comparison_points:
        entities_per_criterion.setdefault(point.criterion, set()).add(point.entity)
    shared_criteria = {criterion for criterion, entities in entities_per_criterion.items() if len(entities) >= 2}
    return [point for point in comparison_points if point.criterion in shared_criteria]


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a, b=b).ratio()


# A figure with a unit ("4조 5,406억원", "650만 명", "6.2%"). Deliberately
# excludes a bare year, which carries no fact by itself.
_FIGURE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:조|억|천만|만)?\s*(?:원|명|%|건|위|시간|배)")
_CONTENT_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
# Words that carry sentence structure rather than subject matter - two
# unrelated findings both end in "했다"/"있다" and both say "대비".
_STRUCTURAL_TOKENS = frozenset({
    "있다", "했다", "이다", "된다", "됐다", "한다", "이며", "으로", "에서",
    "대비", "통해", "따라", "위해", "기록", "전망", "밝혔다", "예상",
})
_MIN_CONTENT_OVERLAP = 0.5


def cited_figures(text: str) -> set[str]:
    """Unit-bearing numbers quoted in a sentence, normalized for comparison.

    Thousands separators are stripped along with whitespace: two sources
    reporting the same profit as "5,376억원" and "5376억원" are stating one
    fact, and keeping the comma made them look like two, which is how the
    same figure ended up on the timeline twice in different words.
    """
    return {
        re.sub(r"[\s,]+", "", match.group()) for match in _FIGURE_RE.finditer(text or "")
    }


def _content_tokens(text: str) -> set[str]:
    return {
        token for token in _CONTENT_TOKEN_RE.findall(text or "")
        if token not in _STRUCTURAL_TOKENS
    }


def _content_overlap(a: str, b: str) -> float:
    tokens_a, tokens_b = _content_tokens(a), _content_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def is_duplicate_statement(a: str, b: str, threshold: float = 0.6) -> bool:
    """Whether two sentences state the same fact.

    When both sentences quote figures, the figures decide: sharing one means
    they're restating the same finding, and quoting *different* ones means
    they're different findings no matter how alike the sentences read. That
    second half matters - Korean report prose is highly templated, so
    "2025년 매출은 4조 5,406억원이다" and "2025년 영업이익은 3,741억원이다"
    score 0.62 on plain character similarity and a threshold alone would
    silently delete one of two genuinely distinct metrics.

    With no figures to compare, the sentences must be alike in *wording* AND
    overlap in subject matter, because character similarity alone has the
    same templated-prose problem: "2025년에 신규 요금제를 출시했다" and
    "2025년에 조직 개편을 단행했다" score 0.62 while sharing nothing but the
    year and the sentence skeleton.
    """
    figures_a, figures_b = cited_figures(a), cited_figures(b)
    if figures_a and figures_b:
        return bool(figures_a & figures_b)
    return _similarity(a, b) >= threshold and _content_overlap(a, b) >= _MIN_CONTENT_OVERLAP


def dedupe_across_blocks(blocks: list[list[str]], threshold: float = 0.6) -> list[list[str]]:
    """Given several blocks' candidate text lists (in display order), drop
    an item from a later block if it's a near-duplicate (lexical similarity
    >= threshold) of something already kept in an earlier block. Uses
    stdlib difflib (no new dependency) - catches restated-but-reworded
    facts, not deep semantic paraphrase; that's a deliberate, disclosed
    limitation, not a claim of full semantic dedup.
    """
    seen: list[str] = []
    result: list[list[str]] = []
    for block in blocks:
        kept: list[str] = []
        for item in block:
            if any(is_duplicate_statement(item, prior, threshold) for prior in seen):
                continue
            kept.append(item)
            seen.append(item)
        result.append(kept)
    return result


def dedupe_structured_across_sections(section_items: list[list[Any]]) -> list[list[Any]]:
    """Structured-field counterpart of `dedupe_across_blocks`: given several
    sections' candidate MetricPoint/ComparisonPoint lists (in section
    order), keep an item only in the first section it appears in - single
    ownership per fact, instead of the same evidence-stated number getting
    mechanically copied into every section that happens to ask for
    "metric_points"/"comparison_points". Equality is exact (same field
    values), not fuzzy - these are structured Pydantic objects, not prose,
    so there's no paraphrase to catch, only literal duplication.
    """
    seen: set[tuple] = set()
    result: list[list[Any]] = []
    for items in section_items:
        kept: list[Any] = []
        for item in items:
            data = item.model_dump()
            # Identity/provenance fields describe how a fact is routed, not
            # the fact itself. Ignore them for semantic duplicate detection
            # while retaining doc/source fields so independent documents are
            # not accidentally collapsed into one.
            for field in (
                "metric_id",
                "comparison_id",
                "evidence_claim_id",
                "evidence_synthesis_claim_id",
                "evidence_quote",
            ):
                data.pop(field, None)
            key = tuple(sorted(data.items()))
            if key in seen:
                continue
            seen.add(key)
            kept.append(item)
        result.append(kept)
    return result


def detect_secondary_purpose(scores: dict[str, int], winner: str, threshold: int = 4) -> str | None:
    """`scores` is the per-purpose score dict `classify_report_purpose()`
    already computes internally - this just asks whether any purpose OTHER
    than the winner independently cleared the same bar the winner needed to
    reach "high confidence" on its own (see classifier.py's `top_score >= 4`
    check). Returns the strongest such runner-up, or None when nothing else
    was a real contender. Never invents a signal - only reads scores that
    were already derived from real keyword/intent matches.
    """
    candidates = {purpose_id: score for purpose_id, score in scores.items() if purpose_id != winner and score >= threshold}
    if not candidates:
        return None
    return max(candidates, key=lambda purpose_id: candidates[purpose_id])


# --- Text-to-structured extraction (evidence sentences -> MetricPoint) ---
#
# Analyzers already extract metric_points via their own OpenAI structured-
# output pass, but they don't catch every number - a revenue/profit figure
# stated inline as prose within an `evidence` sentence (e.g. "2025년 매출:
# 4조 5,406억원 (전년 대비 3% 증가)") stays untouched free text otherwise,
# invisible to KPI ranking, chart shape classification, etc. This is a
# second, narrow, regex-based pass over already-collected evidence text -
# never an estimate: a sentence that doesn't cleanly match is left as prose,
# not guessed at, and a YoY percentage is never used to back-calculate a
# prior-year value that isn't itself stated somewhere.

_KOREAN_AMOUNT_RE = re.compile(
    r"(?:(?P<jo>\d[\d,]*(?:\.\d+)?)\s*조)?\s*"
    r"(?:(?P<eok>\d[\d,]*(?:\.\d+)?)\s*억)?\s*"
    r"(?:(?P<cheonman>\d[\d,]*(?:\.\d+)?)\s*천만)?\s*"
    r"(?:(?P<man>\d[\d,]*(?:\.\d+)?)\s*만)?\s*원"
)
# Multipliers expressed in 억 (100,000,000 won) units, not raw won - a raw
# won float for a trillion-won company (e.g. 4540600000000.0) is unreadable
# and doesn't match how these figures are actually reported/read; 억원 is
# the conventional scale for Korean corporate financials, and matches this
# codebase's existing convention of storing MetricPoint.value pre-scaled to
# whatever unit is natural (e.g. "만 명" for subscriber counts).
_KOREAN_AMOUNT_UNIT_MULTIPLIERS = {
    "jo": 1_0000.0,
    "eok": 1.0,
    "cheonman": 0.1,
    "man": 0.0001,
}

# "2025년", "2024년 2분기" style period, then a known financial-statement
# label, then an amount ending in "원", then (optionally) a YoY change
# clause. Intentionally narrow to the pattern actually observed in
# sk_broadband evidence rather than a general-purpose sentence parser -
# widen the label alternation only when a genuinely new recurring pattern
# is confirmed, not speculatively.
#
# `_QUALIFIER` covers the accounting modifiers that routinely sit between the
# period and the label in Korean filings ("2024년 3분기 *누적* 매출액 …",
# "2025년 *연결* 매출"). Live-verified: without it that sentence extracted
# nothing, which left 매출 with a single period, classified it as a one-off
# KPI instead of a series, and suppressed the trend chart entirely for a
# question that was explicitly about the trend.
_QUALIFIER = r"(?:\s*(?:누적|연결|별도|개별|잠정|연간|전사)){0,2}"
_METRIC_SENTENCE_RE = re.compile(
    r"(?P<period>20\d{2}\s*년(?:\s*[1-4]\s*분기)?)"
    + _QUALIFIER
    + r"\s*(?P<label>매출액?|순이익|영업이익률?)\s*[:：]?\s*"
    r"(?P<amount>[^()]+?원)\s*"
    r"(?:\(\s*전년\s*대비\s*(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?P<direction>증가|감소))?"
)
_METRIC_LABEL_NORMALIZATION = {"매출액": "매출", "영업이익률": "영업이익률"}


def parse_korean_amount(text: str) -> float | None:
    """Convert a 조/억/천만/만-unit Korean currency string (e.g. "4조
    5,406억원" -> 45406.0, "1,414억 8천만원" -> 1414.8) into a number of 억원
    (100M won) - the scale these figures are conventionally reported and
    read in, not a raw won integer. Returns None for anything that doesn't
    cleanly match this specific unit grammar - never a best-effort guess,
    since a wrong parsed number is worse than no number (it looks exactly
    as trustworthy as a correct one downstream).
    """
    match = _KOREAN_AMOUNT_RE.fullmatch(text.strip())
    if not match or not any(match.groupdict().values()):
        return None
    total = 0.0
    for group_name, multiplier in _KOREAN_AMOUNT_UNIT_MULTIPLIERS.items():
        value = match.group(group_name)
        if value:
            total += float(value.replace(",", "")) * multiplier
    return total


def extract_metric_points_from_evidence(evidence: list[str]) -> list[MetricPoint]:
    """Pull real, evidence-stated "<year>(<quarter>) <매출/순이익/영업이익>:
    <amount>원" facts out of prose evidence sentences into MetricPoint
    objects, so a stated financial figure becomes chartable/rankable
    structured data instead of only ever appearing as an unstructured
    sentence. A YoY percentage in the same sentence, if present, is not
    turned into a second point - only literal, directly-stated period+value
    pairs are extracted (see module docstring above)."""
    extracted: list[MetricPoint] = []
    for text in evidence:
        if not text:
            continue
        for match in _METRIC_SENTENCE_RE.finditer(text):
            amount = parse_korean_amount(match.group("amount"))
            if amount is None:
                continue
            label = match.group("label")
            label = _METRIC_LABEL_NORMALIZATION.get(label, label)
            period = re.sub(r"\s+", " ", match.group("period")).strip()
            extracted.append(MetricPoint(label=label, period=period, value=amount, unit="억원"))
    return extracted
