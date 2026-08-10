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
import unicodedata
from typing import Any, Literal

from common.contracts import MetricPoint

MetricShape = Literal["kpi", "bar", "line", "comparison"]

_YEAR_RE = re.compile(r"(20\d{2}|\d{2})")
_QUARTER_RE = re.compile(r"([1-4])\s*(?:Q|분기)", re.I)
_TIMELINE_DATE_RE = re.compile(r"(20\d{2}\s*년(?:\s*\d{1,2}\s*월)?|[1-4]\s*분기|\d{1,2}\s*월\s*\d{1,2}\s*일)")


# Korean particles glue onto the noun, so "근거를" and "근거가" are different
# strings for any literal match. Trimming a trailing particle is not
# morphology - it is the one rule that stops the same noun being read as two
# words - so it only applies when a real stem is left behind.
_PARTICLES = ("으로서", "으로써", "에서는", "에게서", "으로", "에서", "에게", "부터",
              "까지", "이라", "라는", "이나", "과의", "와의", "의", "은", "는", "이",
              "가", "을", "를", "과", "와", "에", "도", "로", "만", "보다")


def strip_particle(token: str) -> str:
    """`token` without its trailing Korean particle, where one is attached."""
    if not re.fullmatch(r"[가-힣]+", token):
        return token
    for particle in _PARTICLES:
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[: -len(particle)]
    return token




# What a compared entity *is*, so a section can ask for the kind it means.
# Live-observed: a 경쟁사 table listed 50대 / 60대 / 70대 이상 - the analyzer
# had correctly extracted an age breakdown, and the slot took it because the
# only question asked was "are there two entities sharing a criterion". A
# competitor section that shows age brackets is not a smaller mistake than an
# empty one; it states something false about the market.
#
# Only kinds that can be recognised from the text itself are named here.
# Everything else is `entity`, which is what a company, brand or product looks
# like - so the default keeps working exactly as before for the ordinary case.
# Brackets are written several ways in the same report - "20대", "30~40대",
# "10-20대", "만 15세", "50대 이상". A range missed by the pattern reads as an
# organisation, which is how "30~40대" once sat in a competitor table beside
# two correctly-classified age brackets.
_AGE_BRACKET_RE = re.compile(
    r"(?:^|\s)(?:만\s*)?\d{1,3}\s*(?:[~\-–]\s*\d{1,3}\s*)?(?:대|세)"
    r"(?:\s*(?:이상|이하|미만|초과))?\s*$"
    r"|^전\s*연령"
)
_GENDER_WORDS = ("남성", "여성", "남자", "여자", "male", "female")
_HOUSEHOLD_WORDS = ("1인 가구", "1인가구", "2인 가구", "가구원", "세대주")
_CUSTOMER_SEGMENT_WORDS = (
    "이용자", "사용자", "가입자", "고객", "시청자", "헤비 유저", "라이트 유저",
    "신규 가입", "기존 가입", "학생", "직장인", "소득층", "user segment",
    "subscriber", "customer segment",
)

EntityKind = Literal["age", "gender", "household", "segment", "entity"]


def entity_kind(entity: str) -> EntityKind:
    """Which category a comparison's entity belongs to."""
    text = (entity or "").strip()
    if _AGE_BRACKET_RE.search(text):
        return "age"
    lowered = text.casefold()
    if any(word in lowered for word in _GENDER_WORDS):
        return "gender"
    if any(word in text for word in _HOUSEHOLD_WORDS):
        return "household"
    if any(word in lowered for word in _CUSTOMER_SEGMENT_WORDS):
        return "segment"
    return "entity"


# Korean marks the subject or topic of a sentence with a particle, so the
# phrase before the first one is what the sentence is *about*. That is the
# only part worth classifying: "50대의 숏폼 이용 경험은 64.1%" is a statement
# about an age bracket, while "KT는 50대 이용자 비중이 높다" is a statement
# about a company that happens to mention one. Testing the whole sentence for
# an age term cannot tell those apart, and would drop the second from 경쟁사.
_SUBJECT_PARTICLE_RE = re.compile(r"^(.{1,24}?)(?:은|는|이|가|의|에서|에게|도|만)\s")


def leading_subject_kind(text: str) -> EntityKind:
    """What kind of thing the sentence's opening subject is.

    Falls back to the first few words when no particle is found (headline-style
    fragments, English, a bare noun phrase), which is the same span a reader
    would take as the subject.
    """
    stripped = (text or "").strip().lstrip("0123456789.·-​ ")
    match = _SUBJECT_PARTICLE_RE.match(stripped)
    head = match.group(1) if match else " ".join(stripped.split()[:2])
    return entity_kind(strip_particle(head.strip()))


def is_demographic(entity: str) -> bool:
    """Whether this is a slice of people rather than a named organisation."""
    return entity_kind(entity) != "entity"


def is_market_category_entity(entity: str | None, market_keywords: list[str] | None) -> bool:
    """Whether `entity` names the market/category itself - e.g. "IPTV"
    sitting in a competitor list beside "KT"/"SKB"/"LGU+" - rather than a
    company, product, segment or country actually being compared.

    `entity_kind()` above has no vocabulary for this: a category label and a
    company name are both a bare noun phrase with no age/gender/household/
    segment marker, so both default to `"entity"`. This checks the entity
    against the sector's own registered `SectorProfile.market_keywords`
    instead - the same field `core/entity/search_terms.py` already anchors
    market_landscape searches on (see CLAUDE.md) - rather than a new entity
    classifier or a name-specific denylist. A sector with no registered
    market keywords excludes nothing: silence here means "unknown", not
    "safe to drop", so a missing/incomplete profile never removes a real
    competitor.
    """
    if not entity or not market_keywords:
        return False
    key = semantic_entity_key(entity)
    return any(key == semantic_entity_key(keyword) for keyword in market_keywords if keyword)


def exclude_market_category_entities(
    comparison_points: list[Any], market_keywords: list[str] | None,
) -> list[Any]:
    """`comparison_points` with any market/category-labelled entity dropped.

    Applied once, centrally, to the synthesis before it reaches slot
    resolution or any renderer - every Competitive Landscape-shaped block
    (`competitor_panels`, `benchmark_grid`, `level_matrix`, `table`, `radar`)
    reads `comparison_points` independently, so filtering each of them
    separately would be as easy to miss in one as the original bug was.
    """
    if not market_keywords:
        return comparison_points
    return [
        point for point in comparison_points
        if not is_market_category_entity(getattr(point, "entity", None), market_keywords)
    ]


# A closed, deterministic set of Korean rollup words. A table's own
# subtotal/total row ("IPTV 총계", "SO 소계", "전체 합계") is not a peer of
# the rows it sums, in any sector - it is that group's own aggregate,
# mixed in as if it were one more comparable entity. Matched anywhere in the
# entity string (not just a suffix), since the qualifier can lead or follow
# the category name depending on how the source table phrased its row.
_TOTAL_ROW_ENTITY_RE = re.compile(r"(총계|소계|합계|전체\s*합계)")

_COMPARISON_VALUE_RE = re.compile(r"-?\d+(?:\.\d+)?")


def is_total_row_entity(entity: str | None) -> bool:
    """Whether this entity is a table's own subtotal/total row rather than
    one of the things being compared."""
    return bool(entity and _TOTAL_ROW_ENTITY_RE.search(entity))


def _comparison_numeric_value(value: str | None) -> float | None:
    match = _COMPARISON_VALUE_RE.search(value or "")
    return float(match.group()) if match else None


# Mirrors block_shapes.SHARE_MIN_SLICES / SHARE_SUM_TOLERANCE - not imported
# from there because block_shapes imports this module, and importing back
# would be circular. Kept in sync by the shared "a composition sums to ~100%"
# definition both modules document, not by a runtime reference.
_COMPOSITION_MIN_SLICES = 2
_COMPOSITION_SUM_TOLERANCE = 2.0


def is_composition_group(points: list[Any]) -> bool:
    """Whether one criterion's comparison rows are a composition (parts of
    one whole) rather than a set of peers being compared to each other.

    Structural, not vocabulary-based: `IPTV 59.57% / SO 33.01% / 위성 7.41%`
    sums to ~100% under one criterion - that is what a composition *is*,
    the same test `share_groups()` already applies to MetricPoint's
    `share_of` groups, run here on ComparisonPoint (which carries no
    `share_of` field to key off directly). `KT 25.24% / SKB 18.51% / LGU+
    15.82%` also sums under 100 but is genuinely a competitor comparison -
    the distinguishing fact both use is the same: percentages that
    partition a whole vs. percentages that do not, and only the former
    reads as one.
    """
    if len(points) < _COMPOSITION_MIN_SLICES:
        return False
    values = [_comparison_numeric_value(getattr(point, "value", None)) for point in points]
    if any(value is None for value in values):
        return False
    total = sum(values)
    return 100 - 15 <= total <= 100 + _COMPOSITION_SUM_TOLERANCE


def exclude_non_competitor_comparisons(
    comparison_points: list[Any], market_keywords: list[str] | None,
) -> list[Any]:
    """`comparison_points` narrowed to rows that are actually comparable
    peers of the same entity type - the shape a Competitive Landscape
    block needs.

    Three deterministic passes, all reusing data already on the contract,
    no new classifier and no per-company name list:
    1. `exclude_market_category_entities` - the sector's own registered
       market/category vocabulary.
    2. total/subtotal rows (`is_total_row_entity`) - a table's own rollup
       is never a peer of what it rolls up.
    3. whole criterion groups that are compositions (`is_composition_group`)
       - "what this whole is made of" is a different block purpose from
       "how do these peers compare" even when both arrive as percentages.
    """
    filtered = exclude_market_category_entities(comparison_points, market_keywords)
    filtered = [point for point in filtered if not is_total_row_entity(getattr(point, "entity", None))]
    by_criterion: dict[str, list[Any]] = {}
    for point in filtered:
        by_criterion.setdefault(getattr(point, "criterion", None), []).append(point)
    # One table commonly states the same composition twice - a percentage
    # column and its raw-count column - as two different criteria. The
    # percentage version sums to ~100% and is caught directly; the count
    # version (e.g. 21,414,521 / 12,091,056 / 2,720,523) will not sum near
    # 100 by coincidence, so it needs the entity set it shares with an
    # already-identified composition, not its own numbers, to be recognised.
    composition_entity_sets = [
        frozenset(getattr(point, "entity", None) for point in points)
        for points in by_criterion.values()
        if is_composition_group(points)
    ]
    composition_criteria = set()
    for criterion, points in by_criterion.items():
        entities = frozenset(getattr(point, "entity", None) for point in points)
        if is_composition_group(points) or entities in composition_entity_sets:
            composition_criteria.add(criterion)
    return [point for point in filtered if getattr(point, "criterion", None) not in composition_criteria]


def _age_sort_key(entity: str) -> tuple:
    """Age brackets in their natural order, not in evidence order.

    Evidence order is whichever sentence the analyzer read first, so a run
    that happened to quote the older brackets first presented 50대/60대/70대
    이상 as though those were the age story - on a question about short-form
    video, where the younger brackets are the point.
    """
    match = re.search(r"\d{1,3}", entity or "")
    return (0, int(match.group(0))) if match else (1, entity or "")


def order_comparison_entities(points: list[Any]) -> list[Any]:
    """Comparisons in an order the category itself implies.

    Age brackets read youngest first because that is how a reader scans a
    demographic split; everything else keeps the order the evidence gave,
    which for companies is already meaningful (it is the order they were
    discussed in).
    """
    if not points or not all(entity_kind(point.entity) == "age" for point in points):
        return points
    return sorted(points, key=lambda point: _age_sort_key(point.entity))


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


# Korean copy usually dates a figure relative to when it was written -
# "지난해 하반기", "올 상반기", "전년 동기". Live-observed on a 2026-05
# article: "지난해 하반기 … 3615만70명 … 2024년 상반기를 시작으로 감소세"
# was labelled 2024년, because the only literal year in the sentence sat in a
# different clause. The figure was 2025 하반기.
_RELATIVE_YEAR_OFFSETS: tuple[tuple[str, int], ...] = (
    ("지지난해", -2), ("재작년", -2),
    ("지난해", -1), ("작년", -1), ("전년", -1),
    ("올해", 0), ("올 ", 0), ("금년", 0),
    ("내년", 1), ("차년", 1),
)
_HALF_RE = re.compile(r"(상반기|하반기)")


def resolve_relative_period(sentence: str, reference_year: int | None) -> str | None:
    """Turn "지난해 하반기" into "2025년 하반기", given the document's year.

    Returns None when the sentence carries no relative expression, or when
    there is no reference year to resolve it against - guessing which year a
    reader meant is exactly the mislabelling this exists to prevent.
    """
    text = sentence or ""
    for marker, offset in _RELATIVE_YEAR_OFFSETS:
        index = text.find(marker)
        if index < 0:
            continue
        if reference_year is None:
            return None
        year = reference_year + offset
        # Only a qualifier that follows the marker belongs to it: in
        # "지난해 하반기 … 상반기보다", the second 상반기 is the comparison.
        tail = text[index : index + len(marker) + 12]
        half = _HALF_RE.search(tail)
        quarter = re.search(r"([1-4])\s*분기", tail)
        if half:
            return f"{year}년 {half.group(1)}"
        if quarter:
            return f"{year}년 {quarter.group(1)}분기"
        return f"{year}년"
    return None


def has_relative_period(sentence: str) -> bool:
    return any(marker in (sentence or "") for marker, _ in _RELATIVE_YEAR_OFFSETS)


def is_time_period(period: str | None) -> bool:
    """Whether a MetricPoint.period names a point in time at all.

    Live-observed: an app-churn analysis stored the compared subject in
    `period`, and both report_planner and the timeline block read those as
    two distinct dates - so a report with no chronology whatsoever was given
    a Timeline section listing "B tv+ 앱" as if it were a moment.
    """
    return bool(_TIME_PERIOD_RE.search(period or ""))


_COMPARABLE_STATE_PATTERNS = (
    re.compile(r"^(?:current|현재|현행)$", re.I),
    re.compile(r"^(?:target|목표)$", re.I),
    re.compile(r"^(?:before|이전|정책\s*전|도입\s*전)$", re.I),
    re.compile(r"^(?:after|이후|정책\s*후|도입\s*후)$", re.I),
    re.compile(r"^(?:previous\s*generation|current\s*generation|이전\s*세대|현\s*세대)$", re.I),
)


def is_comparable_state(period: str | None) -> bool:
    """Whether ``period`` names one side of an explicitly stated state pair.

    These labels are evidence, not dates, but two of them still describe a
    meaningful before/after or current/target delta.  Arbitrary categories
    (companies, age groups, platforms) deliberately do not qualify.
    """
    normalized = re.sub(r"\s+", " ", (period or "").strip())
    return any(pattern.fullmatch(normalized) for pattern in _COMPARABLE_STATE_PATTERNS)


def canonical_time_id(period: str | None) -> str:
    """Canonical display/sort key for an explicitly stated time label."""
    raw = unicodedata.normalize("NFKC", period or "").strip()
    year_match = re.search(r"(?:FY\s*)?(20\d{2})|(?:'|\b)(\d{2})(?:년|\b)", raw, re.I)
    if not year_match:
        return re.sub(r"\s+", " ", raw)
    year = year_match.group(1) or f"20{year_match.group(2)}"
    # `(?<!\d)` on the trailing form: without it "2024 Q3" matched the "4 Q"
    # sitting inside the year and was read as Q4. The leading form (`Q3`) is
    # tried first, so only a genuinely standalone "3분기"/"3Q" reaches it.
    quarter = re.search(r"(?:Q\s*([1-4])|(?<!\d)([1-4])\s*(?:Q|분기))", raw, re.I)
    if quarter:
        return f"{year}년 {quarter.group(1) or quarter.group(2)}분기"
    month = re.search(r"(\d{1,2})\s*월", raw)
    if month:
        return f"{year}년 {int(month.group(1))}월"
    # Half-years, the same way quarters and months are handled above. Without
    # this branch "2024년 하반기" fell through to "2024년", so the two halves
    # of one year became one time id - and `share_groups`, which keys on this,
    # merged two complete compositions into a single group summing to 200%.
    # `metric_identity.canonical_period` normalizes the same notion for metric
    # identity; this is its display/sort counterpart, not a second parser.
    half = re.search(r"(상반기|하반기)|H\s*([12])|([12])\s*H", raw, re.I)
    if half:
        name = half.group(1)
        if not name:
            name = "상반기" if (half.group(2) or half.group(3)) == "1" else "하반기"
        return f"{year}년 {name}"
    return f"{year}년"


_SEMANTIC_NOISE_RE = re.compile(
    r"\b(?:expected|estimated|forecast|forecasted|projected|"
    r"actual|estimate|guidance|target|current)\b|"
    r"(?:전망치?|예상치?|추정치?|실적|가이던스|목표치?|현재)",
    re.I,
)
_MARKET_SIZE_PATTERNS = (
    re.compile(r"market\s+(?:expected\s+|forecast\s+)?size", re.I),
    re.compile(r"market\s+revenue", re.I),
    re.compile(r"시장\s*(?:매출\s*)?(?:규모|가치)", re.I),
)


def _lexical_metric_key(label: str | None) -> str:
    """Meaning-preserving lexical normalization before explicit aliases."""
    text = unicodedata.normalize("NFKC", label or "").casefold()
    for pattern in _MARKET_SIZE_PATTERNS:
        text = pattern.sub(" metric_market_size ", text)
    text = _SEMANTIC_NOISE_RE.sub(" ", text)
    # A year belongs on MetricPoint.period. Some extractors repeat it in the
    # label; removing an explicit 20xx token reconnects the same measurement
    # without inventing a missing time point.
    text = re.sub(r"\b20\d{2}\b", " ", text)
    text = re.sub(r"[^0-9a-z가-힣_]+", " ", text)
    return " ".join(text.split())


# Small, explicit and auditable semantic contracts. Add an entry only when
# domain owners are willing to assert identity; unresolved wording stays a
# separate metric. Scope-bearing words (global/Korea, revenue/shipments,
# product names) are deliberately not generic noise.
_EXPLICIT_METRIC_ALIAS_CONTRACTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "hbm metric_market_size",
        ("HBM market size", "HBM market revenue", "HBM 시장 규모", "HBM 시장 가치"),
    ),
    (
        "global hbm metric_market_size",
        (
            "global HBM market size", "global HBM market revenue",
            "worldwide HBM market size", "글로벌 HBM 시장 규모", "세계 HBM 시장 규모",
        ),
    ),
    (
        "iptv subscribers",
        ("IPTV subscribers", "IPTV subscriber count", "IPTV 가입자", "IPTV 가입자 수"),
    ),
    (
        "broadband subscribers",
        (
            "broadband subscribers", "fixed broadband subscribers",
            "초고속인터넷 가입자", "초고속 인터넷 가입자 수",
        ),
    ),
    (
        "ott subscribers",
        ("OTT subscribers", "OTT subscriber count", "OTT 가입자", "OTT 가입자 수"),
    ),
    (
        "paid ott usage rate",
        (
            "paid OTT usage rate", "paid OTT platform usage rate",
            "유료 OTT 이용률", "유료 OTT 플랫폼 이용률",
        ),
    ),
    (
        "ott market share",
        ("OTT market share", "OTT 시장 점유율", "OTT 점유율"),
    ),
    (
        "iptv market share",
        ("IPTV market share", "IPTV 시장 점유율", "IPTV 점유율"),
    ),
    (
        "ott viewing time",
        ("OTT viewing time", "OTT 시청 시간", "OTT 이용 시간"),
    ),
    (
        "media reach",
        ("media reach", "advertising reach", "광고 도달률", "매체 도달률"),
    ),
    (
        "platform usage rate",
        ("platform usage rate", "플랫폼 이용률", "동영상 플랫폼 이용률"),
    ),
    (
        "arpu",
        ("ARPU", "average revenue per user", "가입자당 평균 매출", "가입자당평균매출"),
    ),
    (
        "churn rate",
        ("churn rate", "subscriber churn rate", "해지율", "가입자 이탈률"),
    ),
    (
        "sports subscription intent",
        (
            "sports subscription intent", "스포츠 중계 가입 의향",
            "스포츠 포함 상품 가입 의향",
        ),
    ),
    (
        "brand awareness",
        ("brand awareness", "브랜드 인지도"),
    ),
    (
        "brand preference",
        ("brand preference", "브랜드 선호도"),
    ),
    (
        "model preference",
        ("advertising model preference", "광고 모델 선호도", "모델 선호도"),
    ),
    (
        "brand fit",
        ("brand fit", "brand-model fit", "브랜드 적합도", "브랜드-모델 적합도"),
    ),
    (
        "long form usage rate",
        ("long-form usage rate", "longform usage rate", "롱폼 이용률"),
    ),
    (
        "short form usage rate",
        ("short-form usage rate", "shortform usage rate", "숏폼 이용률"),
    ),
    (
        "set top box unit cost",
        ("set-top box unit cost", "STB unit cost", "셋톱박스 원가", "셋톱박스 단위원가"),
    ),
)
_EXPLICIT_METRIC_ALIAS_INDEX = {
    _lexical_metric_key(alias): canonical
    for canonical, aliases in _EXPLICIT_METRIC_ALIAS_CONTRACTS
    for alias in aliases
}


def semantic_metric_key(label: str | None) -> str:
    """Conservative, deterministic identity for a metric label.

    It only removes presentation/status words and normalizes a small set of
    bilingual *measurement phrases*.  Topic-bearing tokens remain, so
    ``HBM market size`` and ``DRAM market size`` cannot collapse together.
    This is intentionally not fuzzy string matching: similarity alone is not
    evidence that two measurements share a definition.
    """
    key = _lexical_metric_key(label)
    return _EXPLICIT_METRIC_ALIAS_INDEX.get(key, key)


def _lexical_entity_key(entity: str | None) -> str:
    text = unicodedata.normalize("NFKC", entity or "").casefold()
    text = re.sub(r"\b(?:incorporated|inc|corporation|corp|company|co|ltd|limited)\b\.?", " ", text)
    text = re.sub(r"(?:주식회사|㈜)", " ", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


# Cross-script names are never fuzzy-matched. Each group is an explicit
# contract with audit metadata. Ambiguous abbreviations such as "Samsung" or
# "SK" are intentionally absent.
_EXPLICIT_ENTITY_ALIAS_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "canonical": "Samsung Electronics",
        "aliases": ("Samsung Electronics", "Samsung Electronics, Inc.", "삼성전자"),
        "entity_type": "company",
        "sectors": ("sk_hynix",),
    },
    {
        "canonical": "SK hynix",
        "aliases": ("SK hynix", "SK하이닉스", "에스케이하이닉스"),
        "entity_type": "company",
        "sectors": ("sk_hynix",),
    },
    {
        "canonical": "Micron Technology",
        "aliases": ("Micron Technology", "Micron", "마이크론"),
        "entity_type": "company",
        "sectors": ("sk_hynix",),
    },
    {
        "canonical": "SK Broadband",
        "aliases": (
            "SK Broadband", "SK브로드밴드", "SK 브로드밴드",
            "에스케이브로드밴드", "SKB",
        ),
        "entity_type": "company",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "KT",
        "aliases": ("KT", "KT Corporation", "케이티"),
        "entity_type": "company",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "LG Uplus",
        "aliases": ("LG Uplus", "LG U+", "LG유플러스", "LG 유플러스"),
        "entity_type": "company",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "Netflix",
        "aliases": ("Netflix", "넷플릭스"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "YouTube",
        "aliases": ("YouTube", "유튜브"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "TVING",
        "aliases": ("TVING", "Tving", "티빙"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "Wavve",
        "aliases": ("Wavve", "웨이브"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "Coupang Play",
        "aliases": ("Coupang Play", "쿠팡플레이", "쿠팡 플레이"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "Disney+",
        "aliases": ("Disney+", "Disney Plus", "디즈니플러스", "디즈니 플러스"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "Instagram Reels",
        "aliases": ("Instagram Reels", "인스타그램 릴스", "릴스"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "YouTube Shorts",
        "aliases": ("YouTube Shorts", "유튜브 쇼츠"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "TikTok",
        "aliases": ("TikTok", "틱톡"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
    {
        "canonical": "Naver Clip",
        "aliases": ("Naver Clip", "네이버 클립"),
        "entity_type": "platform",
        "sectors": ("sk_broadband",),
    },
)
_EXPLICIT_ENTITY_ALIAS_INDEX = {
    _lexical_entity_key(alias): _lexical_entity_key(contract["canonical"])
    for contract in _EXPLICIT_ENTITY_ALIAS_CONTRACTS
    for alias in contract["aliases"]
}


def semantic_entity_key(entity: str | None) -> str:
    """Deterministic identity across legal suffixes and explicit aliases."""
    key = _lexical_entity_key(entity)
    return _EXPLICIT_ENTITY_ALIAS_INDEX.get(key, key)


_RELATIVE_METRIC_RE = re.compile(
    r"(?:\b(?:yoy|year[- ]on[- ]year|cagr)\b|전년(?:\s*동기)?\s*대비|"
    r"증가율|감소율|성장률|증감률|\d+(?:\.\d+)?\s*배(?:\s*(?:증가|성장|확대))?|"
    r"두\s*배(?:\s*(?:증가|성장|확대)))",
    re.I,
)
_COMPARISON_PERIOD_RE = re.compile(
    r"((?:20\d{2}\s*년?|전년(?:\s*동기)?|직전(?:\s*분기|\s*연도)?|전월)\s*대비)",
    re.I,
)


def relative_metric_context(text: str | None) -> tuple[bool, str | None]:
    """Return an explicit relative-metric signal and stated baseline.

    No absolute value is calculated. This lexical gate validates analyzer
    output from the evidence text; magnitude alone can never make a point
    relative.
    """
    source = unicodedata.normalize("NFKC", text or "")
    if not _RELATIVE_METRIC_RE.search(source):
        return False, None
    comparison = _COMPARISON_PERIOD_RE.search(source)
    return True, comparison.group(1).strip() if comparison else None


def _period_basis(period: str | None) -> str:
    text = canonical_time_id(period) if is_time_period(period) else (period or "")
    if re.search(r"\d{1,2}\s*월", text):
        return "month"
    if re.search(r"[1-4]\s*분기", text):
        return "quarter"
    if re.search(r"(?:상반기|하반기)", text):
        return "half"
    if re.search(r"20\d{2}", text):
        return "year"
    return "category"


_UNIT_SCALES: dict[str, tuple[str, float]] = {
    "usd billion": ("USD million", 1000.0),
    "billion usd": ("USD million", 1000.0),
    "usd bn": ("USD million", 1000.0),
    "$b": ("USD million", 1000.0),
    "usd million": ("USD million", 1.0),
    "million usd": ("USD million", 1.0),
    "usd mn": ("USD million", 1.0),
    "$m": ("USD million", 1.0),
    "조원": ("억원", 10000.0),
    "조 원": ("억원", 10000.0),
    "억원": ("억원", 1.0),
    "억 원": ("억원", 1.0),
    "%": ("%", 1.0),
    "％": ("%", 1.0),
    "%p": ("%p", 1.0),
}


def comparable_unit(unit: str | None) -> tuple[str, float]:
    """Canonical unit and deterministic multiplier, never an exchange rate."""
    normalized = unicodedata.normalize("NFKC", unit or "").casefold().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return _UNIT_SCALES.get(normalized, ((unit or "").strip(), 1.0))


def metric_value_type(text: str | None) -> str:
    """Evidence-stated status of a number, with the most specific marker first."""
    normalized = (text or "").casefold()
    if any(marker in normalized for marker in ("목표", "target")):
        return "target"
    if any(marker in normalized for marker in ("가이던스", "guidance")):
        return "guidance"
    if any(marker in normalized for marker in ("추정", "estimate", "estimated")):
        return "estimate"
    if any(marker in normalized for marker in ("전망", "예상", "예측", "forecast", "projected")):
        return "forecast"
    return "actual"


def _normalized_metric_copy(
    point: Any, *, label: str, unit: str, scale: float, subject: str | None = None,
) -> Any:
    period = canonical_time_id(point.period) if is_time_period(point.period) else point.period
    updates = {
        "label": label, "unit": unit, "value": float(point.value) * scale,
        "period": period,
        "subject": subject if subject is not None else getattr(point, "subject", None),
    }
    copier = getattr(point, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    return point


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

# Questions that need general, non-company knowledge before the company can be
# reasoned about at all: "연령층별 광고 매체 추천" needs industry media-mix
# research, "칩플레이션이 셋톱박스에 미치는 영향" needs semiconductor price
# trends. Searching those with the company name bolted on returns the
# company's own press coverage and none of the research.
#
# Kept lexical and sector-agnostic on purpose - these are properties of how a
# question is phrased, not of any one sector's vocabulary.
_APPLIED_KNOWLEDGE_SIGNALS: tuple[str, ...] = (
    "추천", "방안", "전략", "일반적", "업계", "산업", "트렌드", "동향", "사례",
    "베스트", "표준", "평균", "벤치마크", "비교", "효과", "패턴", "영향",
)
# Perspectives that already say the question is about the wider market rather
# than this company's own reporting (EntityExtractionResult.perspective).
_MARKET_PERSPECTIVES = {"market_landscape", "regulatory_policy"}


def needs_generic_topic_search(question: str, perspective: str | None = None) -> bool:
    """Whether at least one search round should drop the company name.

    Live-observed on "브랜드 이미지 개선에 맞는 연령층별 광고 매체 및 모델
    추천": all three rounds searched "SK브로드밴드 …", so every result was
    SK브로드밴드's own coverage and none of the age-bracket media research a
    person would have found first by searching the topic alone.
    """
    if perspective in _MARKET_PERSPECTIVES:
        return True
    text = question or ""
    return any(signal in text for signal in _APPLIED_KNOWLEDGE_SIGNALS)


def strip_company_from_query(query: str, company_name: str | None) -> str:
    """The same query with the company's name removed, for a generic round."""
    if not company_name:
        return (query or "").strip()
    cleaned = re.sub(re.escape(company_name), " ", query or "", flags=re.I)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


# Single source of truth for the SWOT instruction - previously each of the 6
# sector analyzers phrased this slightly differently (see
# sectors/*/adapter/analyzer/__init__.py).
#
# The earlier wording ("반드시 채우세요", "매번 비는 경우가 없도록") read as a
# quota and contradicted global_system_prompt.md principle 1, which forbids
# filling a gap with a plausible guess. A question about which ad channels
# suit which age bracket has no weaknesses to state, and the model was being
# told both to leave it empty and not to. Search hard, then report what is
# actually there - an empty quadrant is a finding, not a failure.
SWOT_COMPLETENESS_INSTRUCTION = (
    "strength(강점)·weakness(약점)·risk·opportunity는 문서를 끝까지 훑어 근거가 있는 것을 "
    "빠짐없이 찾으세요. 특히 한쪽 방향(예: 강점)만 눈에 띄고 반대 방향을 놓치는 일이 없도록, "
    "문서에 나온 한계·경쟁열위·제약도 같은 비중으로 검토하세요. "
    "다만 이는 네 칸을 모두 채우라는 뜻이 아닙니다. 질문의 성격상 해당 항목이 존재하지 않거나"
    "(예: 매체 추천처럼 위험을 논하는 질문이 아닌 경우) 문서에 근거가 없으면 그 항목은 비워 두세요. "
    "빈 칸은 정직한 결과이며, 근거 없이 지어낸 항목은 전역 원칙 1(추측 금지) 위반입니다."
)

# The comparison instruction was much weaker than the metric one: metric_points
# said "표에 있는 시점 수만큼 전부 추출하라" while comparison_points said only
# "비교 서술이 있으면 추출하라". Live-observed on "TV는 31.7%를 기록해
# 유튜브(25.6%)를 앞서며 1위" - only 25.6% was captured and the 1st-place
# figure the sentence was actually about was dropped.
# A table is not a fact; it is many facts printed together. Live-observed
# twice: a results table laid out as 3Q25/3Q24/2Q25 columns came back as one
# representative figure, so the three-period trend it described could never be
# charted, and a per-age list arrived as a single summary sentence. The loss
# happens at extraction, where no later stage can recover it - synthesis and
# the report writer can only pass along what the analyzer structured.
TABLE_COMPLETENESS_INSTRUCTION = (
    "실적표·통계표처럼 같은 항목이 여러 시점 컬럼으로 나란히 나오면 한 시점만 뽑지 말고, "
    "같은 label로 표에 있는 시점 수만큼 별도의 metric_point를 전부 만들어라. "
    "연령대별·연도별·기업별·플랫폼별로 나열된 수치나 순위도 대표값 하나로 요약하지 말고 "
    "각 행·항목을 개별 metric_point 또는 comparison_point로 전부 분해하라."
)

COMPARISON_COMPLETENESS_INSTRUCTION = (
    "비교 문장에 여러 대상이 등장하면 언급된 대상을 하나도 빠뜨리지 말고 전부 "
    "comparison_points로 만드세요. 한 문장이 A와 B를 비교하면 A와 B 둘 다 별도 항목입니다. "
    "특히 '1위', '가장 높은', '앞선다', '최대' 같은 표현이 붙은 대상은 그 문장의 핵심이므로 "
    "절대 누락하지 마세요 — 뒤에 괄호로 딸려 나온 비교 대상만 뽑고 1위를 빠뜨리는 실수가 "
    "가장 흔합니다. 표가 아니라 산문 속 비교(\"A는 31.7%로 B(25.6%)를 앞섰다\")도 동일하게 "
    "적용됩니다."
)

RELATIVE_METRIC_EXTRACTION_INSTRUCTION = (
    "YoY·CAGR·전년 대비 증감률·배수처럼 원문이 상대 변화를 직접 수치로 말하면 그 상대값도 "
    "metric_point로 보존하고 is_relative=true로 표시하세요. comparison_period에는 원문이 "
    "명시한 비교 기준만 쓰고 value_origin은 source로 두세요. 여러 연도의 성장률이 각각 "
    "명시되면 성장률 자체를 같은 label의 시계열로 추출할 수 있습니다. 단일 '두 배 전망'을 "
    "100→200으로 바꾸거나 기준값과 증감률로 절대값을 계산하면 안 됩니다."
)

QUALITATIVE_LEVEL_EXTRACTION_INSTRUCTION = (
    "문서가 후보의 특정 기준을 매우 높음·높음·중간 수준·낮음·매우 낮음 또는 "
    "high/medium/low로 직접 평가한 경우에만 comparison_point.level을 high/medium/low로 "
    "정규화하세요. 일반 수치가 크거나 표현이 긍정적이라는 이유로 level을 만들지 마세요."
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
    # An explicit `subject` axis usually settles it: the same metric measured
    # for several subjects is a comparison however its periods read.
    #
    # Unless each of those subjects was also tracked over time. "국내 vs 글로벌
    # OTT 가입자, 5년치" is two trends, not a ranking, and calling it a
    # comparison drew five years of movement as a row of bars - the shape the
    # question was actually about disappeared. So a subject split only wins
    # when the time axis isn't there to win instead.
    subjects = {point.subject for point in points_for_one_label if getattr(point, "subject", None)}
    if len(subjects) >= 2:
        periods_per_subject = [
            {
                canonical_time_id(point.period) if is_time_period(point.period) else point.period
                for point in points_for_one_label if point.subject == subject
            }
            for subject in subjects
        ]
        if all(
            len(periods) >= 3 and all(is_time_period(period) for period in periods)
            for periods in periods_per_subject
        ):
            return "line"
        return "comparison"
    periods = {
        canonical_time_id(point.period) if is_time_period(point.period) else point.period
        for point in points_for_one_label
    }
    if len(periods) <= 1:
        return "kpi"
    if not all(is_time_period(period) for period in periods):
        if len(periods) == 2 and all(is_comparable_state(period) for period in periods):
            return "bar"
        return "comparison"
    if len(periods) == 2:
        return "bar"
    return "line"


def group_metric_points_by_label(metric_points: list[Any]) -> dict[str, list[Any]]:
    semantic_groups: dict[tuple[Any, ...], list[tuple[Any, str, float]]] = {}
    for point in metric_points:
        canonical_unit, scale = comparable_unit(getattr(point, "unit", None))
        # Metric identity and series compatibility are separate checks. Even
        # an explicit alias must not merge a different denominator or time
        # basis onto one series.
        denominator = semantic_metric_key(getattr(point, "share_of", None))
        key = (
            semantic_metric_key(point.label), canonical_unit, denominator,
            _period_basis(getattr(point, "period", None)),
            getattr(point, "is_relative", False),
            getattr(point, "comparison_period", None),
            getattr(point, "value_origin", "source"),
        )
        semantic_groups.setdefault(key, []).append((point, canonical_unit, scale))

    grouped: dict[str, list[Any]] = {}
    for rows in semantic_groups.values():
        display_label = rows[0][0].label
        subject_labels: dict[str, str] = {}
        for point, _, _ in rows:
            subject = getattr(point, "subject", None)
            if subject:
                subject_labels.setdefault(semantic_entity_key(subject), subject)
        normalized = [
            _normalized_metric_copy(
                point, label=display_label, unit=unit, scale=scale,
                subject=(subject_labels.get(semantic_entity_key(point.subject)) if point.subject else None),
            )
            for point, unit, scale in rows
        ]
        # Preserve the historic public key wherever possible. If the same
        # display label genuinely occurs with incompatible units, denominator
        # or time basis, keep every group distinct rather than overwriting or
        # merging it onto one false axis.
        key = display_label
        if key in grouped:
            suffix = rows[0][1] or "별도 기준"
            candidate = f"{display_label} [{suffix}]"
            serial = 2
            while candidate in grouped:
                candidate = f"{display_label} [{suffix} {serial}]"
                serial += 1
            key = candidate
            normalized = [
                _normalized_metric_copy(
                    point, label=key, unit=unit, scale=scale,
                    subject=(subject_labels.get(semantic_entity_key(point.subject)) if point.subject else None),
                )
                for point, unit, scale in rows
            ]
        deduped: list[Any] = []
        seen: set[tuple[Any, ...]] = set()
        for point in normalized:
            identity = (
                getattr(point, "subject", None), point.period, float(point.value), point.unit,
                getattr(point, "value_type", "actual"),
                getattr(point, "share_of", None),
            )
            if identity in seen:
                continue
            seen.add(identity)
            deduped.append(point)
        grouped[key] = deduped
    return grouped


def group_metric_points_by_series(metric_points: list[Any]) -> dict[str, list[Any]]:
    """One entry per drawn line: `label` alone, or "label · subject" where a
    subject splits it.

    Charting groups by label, which is right until two subjects share one -
    then both sets of points land on a single polyline and it zigzags between
    국내 and 글로벌 at every year instead of drawing two trends. The display
    name doubles as the legend entry, which is why the subject is folded into
    the key rather than tracked beside it.
    """
    grouped: dict[str, list[Any]] = {}
    for semantic_label, points in group_metric_points_by_label(metric_points).items():
        for point in points:
            subject = getattr(point, "subject", None)
            key = f"{semantic_label} · {subject}" if subject else semantic_label
            grouped.setdefault(key, []).append(point)
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


# Four lines across two axes is not a trend anyone reads; it is a legend with
# a picture attached. The live 유료방송 card plotted IPTV / SO / 위성방송 /
# 증감폭 - three levels and a change between them - and the change, two orders
# of magnitude smaller, dragged a second axis onto the card that the reader
# had to match line-by-line before the chart said anything.
CHART_MAX_SERIES = 3


def plotted_chart_series(chartable_points: list[Any]) -> list[Any]:
    """The series one chart actually draws, out of those it *could*.

    Magnitude decides which survive, because nothing in the evidence says
    which series is "the main one" and the biggest is what sets the axis the
    others are read against. Dropped labels are not lost - as
    `select_chartable_series` already documents, they still reach the reader
    as KPI cards or bars.

    Separate from the renderer so slot resolution can ask what the chart will
    put on screen without importing Streamlit. That question is not
    cosmetic: a block that reports data it will not draw makes every later
    block look redundant.
    """
    by_label = group_metric_points_by_series(chartable_points)
    if len(by_label) <= CHART_MAX_SERIES:
        return chartable_points
    kept = set(sorted(
        by_label,
        key=lambda label: max(abs(point.value) for point in by_label[label]),
        reverse=True,
    )[:CHART_MAX_SERIES])
    return [point for label in kept for point in by_label[label]]


def filter_shared_comparison_axis(comparison_points: list[Any]) -> list[Any]:
    """Keep only the criteria that at least 2 distinct entities actually
    have a value for (a real shared axis), dropping criteria only one
    entity happens to mention. Prevents building a comparison table that's
    mostly blank cells because two genuinely different metrics (e.g. "IPTV
    가입자 수" vs "국내 월간 이용자 수") got grouped as if comparable.
    """
    if not comparison_points:
        return []
    comparison_points = normalize_comparison_axes(comparison_points)
    entities_per_criterion: dict[str, set[str]] = {}
    for point in comparison_points:
        entities_per_criterion.setdefault(point.criterion, set()).add(point.entity)
    shared_criteria = {criterion for criterion, entities in entities_per_criterion.items() if len(entities) >= 2}
    return [point for point in comparison_points if point.criterion in shared_criteria]


def normalize_comparison_axes(comparison_points: list[Any]) -> list[Any]:
    """Canonicalize safe label/entity variants while preserving stated values."""
    criterion_labels: dict[str, str] = {}
    entity_labels: dict[str, str] = {}
    for point in comparison_points or []:
        criterion_labels.setdefault(semantic_metric_key(point.criterion), point.criterion)
        entity_labels.setdefault(semantic_entity_key(point.entity), point.entity)
    normalized = []
    for point in comparison_points or []:
        updates = {
            "criterion": criterion_labels[semantic_metric_key(point.criterion)],
            "entity": entity_labels[semantic_entity_key(point.entity)],
        }
        copier = getattr(point, "model_copy", None)
        normalized.append(copier(update=updates) if callable(copier) else point)
    return normalized


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
                # Merged provenance, filled in later by metric normalization.
                # It lists which documents stated a fact, which is routing
                # again, not the fact - and being a list it is unhashable, so
                # leaving it in the key raised TypeError.
                "supporting_doc_ids",
                "supporting_source_urls",
            ):
                data.pop(field, None)
            key = tuple(
                (name, tuple(value) if isinstance(value, list) else value)
                for name, value in sorted(data.items())
            )
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
    sentence. An explicit YoY percentage in the same sentence is preserved as
    a separate relative metric; it is never used to reconstruct an unstated
    prior-year or endpoint value."""
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
            if match.group("pct"):
                direction = -1.0 if match.group("direction") == "감소" else 1.0
                extracted.append(MetricPoint(
                    label=f"{label} 전년 대비 증감률",
                    period=period,
                    value=float(match.group("pct")) * direction,
                    unit="%",
                    is_relative=True,
                    comparison_period="전년 대비",
                    value_origin="source",
                ))
    return extracted
