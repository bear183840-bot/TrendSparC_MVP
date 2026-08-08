"""Fixed section skeleton per purpose, flexible block per slot.

Two separate ideas, deliberately kept apart:

* The **skeleton** - which slots a purpose has and in what order - is fixed.
  A 현황파악 report always reads 핵심요약 -> 시장상황 -> 지표 -> 경쟁사 ->
  대응방향, so two reports of the same purpose are comparable.
* The **block filling a slot** is not fixed. Each slot declares what it is
  *for* and an ordered list of block types that can serve that intent. The
  first candidate the data actually supports wins.

"정보 없음" is the last resort, reached only when every candidate for a slot
has been tried. Before this existed, a slot whose first-choice block had no
data rendered an empty card with an apology in it, which is how three
identical "검증된 신호가 없습니다" boxes ended up side by side in a report
that had plenty of other evidence to show.

Candidate lists are not "any block that exists" - a candidate has to serve
the same *intent* as the slot. A cause slot may fall back from a cause map to
a contribution bar chart to narrative bullets, because all three explain
causation at decreasing precision. It may not fall back to a KPI card, which
would answer a question nobody asked.

This module lives in common/, not reporting/, on purpose: it has zero
Streamlit dependency (see the predicates it imports from block_shapes, which
are UI-free for the same reason), and core/block_priority_planner needs to
read PURPOSE_SLOTS before collection ever runs - core/ must never import
from reporting/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Data-shape predicates only - deliberately NOT the rendering module. Slot
# resolution is a decision about evidence, so it must not depend on Streamlit
# or on anything that imports it.
from common import block_shapes

# Share of a purpose's slots that may reach the last resort before the report
# as a whole is called under-evidenced. Config, not a magic number - raise it
# to be more forgiving, lower it to warn sooner.
UNDER_EVIDENCED_SLOT_RATIO = 0.5

LAST_RESORT = "no_data"

# The block library arriving from design, and the candidate id each of its
# blocks corresponds to here. Kept explicit so swapping in the real component
# is a rename in one table rather than a hunt through the slot definitions.
#
#   KPI Card (숫자·상태)      -> kpi_grid / kpi_single
#   Line / Area (시간 변화)    -> chart
#   Bar (항목 비교)            -> bar / metric_comparison
#   Matrix (리스크·기회)       -> matrix
#   Timeline (단계·로드맵)     -> timeline
#   Table (정성 비교)          -> table
#   Cause Map (원인→영향)      -> cause_map
#   Action List (권고안)       -> action_list
#   Evidence (작은 링크)       -> evidence
#
# `radar` and `narrative_list` have no counterpart in that set: radar already
# exists here and stays as a capability-comparison option, and narrative_list
# is the plain bullet card every slot falls back to before "정보 없음".
DESIGN_LIBRARY_BLOCKS: dict[str, tuple[str, ...]] = {
    "KPI Card": ("kpi_grid", "kpi_single"),
    "Line / Area": ("chart", "landscape"),
    "Bar": ("bar", "item_bar", "grouped_bar", "metric_comparison"),
    "KPI Status Bar": ("status_bar",),
    "Share Split": ("share_split",),
    "Matrix": ("matrix",),
    "Timeline": ("timeline",),
    "Table": ("table",),
    "Competitor Panels": ("competitor_panels",),
    "Cause Map": ("cause_map",),
    "Root Cause Tree": ("cause_tree",),
    "Driver Bars": ("driver_bars",),
    "Action List": ("action_list",),
    "Factor List": ("factor_list",),
    "Keyword List": ("recurring_terms",),
    "Evidence": ("evidence",),
}


@dataclass(frozen=True)
class Slot:
    slot_id: str
    title: str
    intent: str
    candidates: tuple[str, ...]
    # Which planned section ids can supply this slot's narrative items. The
    # first one present in the report wins.
    sections: tuple[str, ...] = ()
    # Synthesis fields to fall back on when no planned section matched. Without
    # this a slot could report "정보 없음" while the evidence for it sat in
    # synthesis - observed with future_business's 위험 slot, whose sections are
    # not in that purpose's plan even though synthesis.risks was populated.
    fields: tuple[str, ...] = ()
    # An optional slot disappears when its data isn't there, instead of
    # resolving to the last-resort placeholder. Use it for a slot that asks a
    # question only some evidence can answer (relative weighting of causes) -
    # its absence says nothing was measured, where an empty card would claim
    # the report tried and failed at something it always shows.
    optional: bool = False


@dataclass(frozen=True)
class ResolvedSlot:
    slot: Slot
    block_type: str
    section_id: str | None
    items: list[str]

    @property
    def is_last_resort(self) -> bool:
        return self.block_type == LAST_RESORT


# --- the four skeletons -------------------------------------------------

_CURRENT_STATUS: tuple[Slot, ...] = (
    Slot("summary", "핵심 요약", "질문에 대한 직접적인 답",
         ("narrative_list",), ("overview", "key_implication")),
    # `bar` sits between chart and timeline throughout: a metric measured at
    # exactly two points is still a movement, just not a trend line, and
    # dropping straight to prose threw that away.
    # Ranking sits ahead of 시장 상황 so a "무엇이 가장 많이/높게" question
    # claims the comparison bars for the card that is actually about ranking;
    # 시장 상황 then falls to its own chart/timeline. Both slots reading the
    # same metric_series is why order decides which one gets `bar`.
    Slot("ranking", "순위·비교", "항목들 사이에서 무엇이 앞서는가",
         ("share_split", "grouped_bar", "item_bar", "metric_comparison", "table", "narrative_list"),
         ("key_metrics", "market_status"), (), optional=True),
    Slot("market", "시장 상황", "시장이 어느 방향으로 움직이는가",
         ("landscape", "chart", "bar", "item_bar", "timeline", "narrative_list"),
         ("market_status", "current_situation")),
    Slot("metrics", "지표", "확인된 수치를 제시",
         ("kpi_grid", "chart", "kpi_single", "status_bar"), ("key_metrics",)),
    Slot("competitor", "경쟁사", "다른 주체와 견주면 어디쯤인가",
         ("competitor_panels", "table", "radar", "share_split", "narrative_list"),
         ("market_status",)),
    # 요인/페인포인트 questions ("가입 고려 요인", "인기 요인") answer with a
    # list, and a list is what the evidence actually holds - so this slot has
    # its own place rather than being squeezed into 시장 상황's prose
    # fallback. driver_bars first, because a scored factor list beats an
    # unordered one where the analyzer managed to score it.
    Slot("factors", "요인", "무엇이 그것을 좌우하는가",
         ("driver_bars", "factor_list", "narrative_list"),
         ("current_situation", "market_status"),
         ("risks", "weaknesses", "opportunities"), optional=True),
    Slot("keywords", "반복 언급", "여러 출처가 공통으로 짚은 표현",
         ("recurring_terms",), (), (), optional=True),
    # Optional because 현황파악 is a "what is happening" question. Four of the
    # five 현황 questions we tested want no recommendation at all, and a
    # 권고 조치 card appearing under an external-audience market report was
    # answering something nobody asked.
    Slot("response", "대응 방향", "그래서 무엇을 해야 하는가",
         ("action_list", "narrative_list"), ("recommended_action", "near_term_outlook"),
         ("recommended_actions",), optional=True),
)

_ISSUE_RESPONSE: tuple[Slot, ...] = (
    # narrative_list has to stay last everywhere: it matches whenever the slot
    # has any prose at all, so anything listed after it is unreachable.
    Slot("problem", "문제", "무엇이 문제인가",
         ("matrix", "narrative_list"), ("issue", "problem")),
    Slot("cause", "원인", "왜 그렇게 되었는가",
         ("cause_tree", "cause_map", "bar", "item_bar", "narrative_list"),
         ("root_cause", "issue"), ("risks",)),
    Slot("impact", "영향", "그 결과 무엇이 달라지는가",
         ("chart", "bar", "item_bar", "metric_comparison", "narrative_list"), ("impact",),
         ("business_impacts",)),
    Slot("options", "선택지", "택할 수 있는 길들의 비교",
         ("matrix", "table", "narrative_list"), ("risk_and_opportunity", "impact")),
    Slot("recommendation", "권장 조치", "무엇을 먼저 할 것인가",
         ("action_list", "narrative_list"), ("response_actions", "recommended_action"),
         ("recommended_actions",)),
)

_FUTURE_BUSINESS: tuple[Slot, ...] = (
    Slot("market_shift", "시장 변화", "시장이 어떻게 바뀌고 있는가",
         ("landscape", "chart", "bar", "item_bar", "timeline", "narrative_list"),
         ("trend", "market_status")),
    Slot("opportunity", "기회", "어디에 기회가 있는가",
         ("matrix", "bar", "item_bar", "narrative_list"), ("opportunity",)),
    # No `sections`: there is no planned section about required capability, and
    # borrowing investment_signal's key_points put "디지털 광고 시장에서의
    # 존재감을 확대하는 기회" on screen under the heading "필요 역량" - a
    # section id and its rendered content saying different things. A slot may
    # only show what is genuinely its own; synthesis.strengths is what this
    # question actually has to say about capability.
    Slot("capability", "필요 역량", "그 기회를 잡으려면 무엇이 있어야 하는가",
         ("radar", "table", "narrative_list"), (), ("strengths",)),
    Slot("roadmap", "실행 단계", "어떤 순서로 움직이는가",
         ("timeline", "action_list", "narrative_list"), ("strategic_recommendation",)),
    Slot("risk", "위험", "무엇이 어긋날 수 있는가",
         ("matrix", "narrative_list"), ("risk", "risk_and_opportunity"), ("risks",)),
)

_ROOT_CAUSE: tuple[Slot, ...] = (
    Slot("problem", "Problem", "어떤 현상이 관찰되는가",
         ("chart", "bar", "item_bar", "narrative_list"), ("problem", "issue")),
    Slot("cause", "Cause", "그 현상의 원인 구조",
         ("cause_tree", "cause_map", "bar", "item_bar", "table", "narrative_list"),
         ("root_cause",)),
    # Only drawable when the model scored the claims and said why; otherwise
    # the slot resolves to nothing and the skeleton is three slots as before.
    Slot("drivers", "Drivers", "어느 원인이 더 크게 작용하는가",
         ("driver_bars",), ("root_cause",), (), optional=True),
    Slot("improvement", "Improvement", "원인 사슬의 어디를 끊을 것인가",
         ("action_list", "table", "narrative_list"), ("improvement_plan",)),
)

PURPOSE_SLOTS: dict[str, tuple[Slot, ...]] = {
    "current_status": _CURRENT_STATUS,
    "issue_response": _ISSUE_RESPONSE,
    "future_business": _FUTURE_BUSINESS,
    "root_cause": _ROOT_CAUSE,
}

DEFAULT_PURPOSE_SLOTS = _CURRENT_STATUS

# Which summary treatment sits at the top right. Purpose-level presentation
# choice, declared here rather than branched on at render time.
PURPOSE_HEADLINE_STYLE: dict[str, str] = {
    "current_status": "kpi_grid",
    "root_cause": "kpi_grid",
    "issue_response": "risk_opportunity_badges",
    "future_business": "opportunity_readiness_badges",
}


# --- can this data support this block? ----------------------------------

_MIN_KPI_GRID_POINTS = 2
_MIN_FACTOR_ITEMS = 3


def _reference_year(synthesis: Any) -> int | None:
    """Year that "지난해"/"올 상반기" in this run's evidence resolve against."""
    as_of = getattr(synthesis, "as_of_date", None)
    try:
        return int(str(as_of)[:4]) if as_of else None
    except ValueError:
        return None


def _availability() -> dict[str, Callable[[Any, list[str]], bool]]:
    """block_type -> does the data support drawing it.

    Each predicate answers only "is this block honestly drawable", never "is
    it a good idea here" - that judgement is the slot's candidate order.
    """
    return {
        # Offered ahead of `chart` wherever both fit: it is the same trend
        # plus the composition, never a substitute for either.
        "landscape": lambda synthesis, items: block_shapes.has_landscape(synthesis.metric_series),
        "chart": lambda synthesis, items: block_shapes.has_timeseries(synthesis.metric_series),
        # Two block ids over one renderer: `bar` is a movement between two
        # points in time, `item_bar` is a ranking across items. They read the
        # same list but answer different questions, so a slot asking about
        # direction can't claim the ranking bars and leave 순위 empty.
        "bar": lambda synthesis, items: bool(block_shapes.time_bar_groups(synthesis.metric_series)),
        "item_bar": lambda synthesis, items: bool(block_shapes.item_bar_groups(synthesis.metric_series)),
        # Three axes at once (metric x subject x category) - strictly more
        # than item_bar shows, so it is offered first wherever both fit.
        "grouped_bar": lambda synthesis, items: block_shapes.has_grouped_bars(synthesis.metric_series),
        "status_bar": lambda synthesis, items: block_shapes.has_status_levels(
            synthesis.comparison_points
        ),
        # Composition, not ranking - and only where the source framed the
        # figures as parts of one named whole.
        "share_split": lambda synthesis, items: block_shapes.has_share_split(synthesis.metric_series),
        "metric_comparison": lambda synthesis, items: bool(
            block_shapes.metric_comparison_groups(synthesis.metric_series)
        ),
        "kpi_grid": lambda synthesis, items: len(synthesis.metric_series) >= _MIN_KPI_GRID_POINTS,
        "kpi_single": lambda synthesis, items: len(synthesis.metric_series) >= 1,
        "timeline": lambda synthesis, items: block_shapes.has_timeline(
            synthesis.evidence,
            synthesis.metric_series,
            _reference_year(synthesis),
        ),
        "table": lambda synthesis, items: block_shapes.has_comparison(synthesis.comparison_points),
        # Richer than the table wherever each competitor has several
        # kinds of fact attached, so it is offered first in 경쟁사.
        "competitor_panels": lambda synthesis, items: block_shapes.has_competitor_panels(
            synthesis.comparison_points, synthesis.metric_series
        ),
        "radar": lambda synthesis, items: block_shapes.has_radar(synthesis.comparison_points),
        "matrix": lambda synthesis, items: sum(
            1 for field in (
                synthesis.strengths, synthesis.weaknesses,
                synthesis.opportunities, synthesis.risks,
            ) if field
        ) >= 2,
        # A real chain the documents stated, ahead of cause_map's column
        # layout, which only groups risks/impacts/actions side by side.
        "cause_tree": lambda synthesis, items: block_shapes.has_cause_tree(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "driver_bars": lambda synthesis, items: block_shapes.has_importance_ranking(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "cause_map": lambda synthesis, items: block_shapes.has_cause_map(
            synthesis.risks, synthesis.business_impacts, synthesis.recommended_actions
        ),
        "action_list": lambda synthesis, items: bool(synthesis.recommended_actions),
        # A list is worth its own card only when it is long enough to be a
        # list; two bullets are a sentence and belong in the prose fallback.
        "factor_list": lambda synthesis, items: len(items) >= _MIN_FACTOR_ITEMS,
        "recurring_terms": lambda synthesis, items: block_shapes.has_recurring_terms(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "narrative_list": lambda synthesis, items: bool(items),
    }


def _section_items(report: Any, section_ids: tuple[str, ...]) -> tuple[str | None, list[str]]:
    """Narrative items from the first of `section_ids` the report actually has."""
    if report is None:
        return None, []
    by_id = {section.section_id: section for section in report.sections}
    for section_id in section_ids:
        section = by_id.get(section_id)
        if section is None:
            continue
        items = [
            value
            for field in ("key_points", "risks", "opportunities", "actions", "evidence")
            for value in (getattr(section, field, None) or [])
            if value
        ]
        if items:
            return section_id, items
    return None, []


# narrative_list draws from each slot's own section, so two slots using it
# show different text. Every other candidate draws from one shared pool on the
# synthesis (metric_series, comparison_points, the SWOT fields), so a second
# slot picking the same one would redraw the identical block - the SWOT
# appearing under both 문제 and 선택지, the same timeline under both 시장변화
# and 실행단계. Claimed once, then the next slot moves down its own list.
_REUSABLE_BLOCKS = {"narrative_list"}


def _synthesis_items(synthesis: Any, fields: tuple[str, ...]) -> list[str]:
    return [
        value
        for field in fields
        for value in (getattr(synthesis, field, None) or [])
        if isinstance(value, str) and value.strip()
    ]


def resolve_slots(purpose_id: str | None, synthesis: Any, report: Any) -> list[ResolvedSlot]:
    """Fill each of the purpose's slots with the best block its data supports."""
    slots = PURPOSE_SLOTS.get(purpose_id or "", DEFAULT_PURPOSE_SLOTS)
    availability = _availability()
    claimed: set[str] = set()
    resolved: list[ResolvedSlot] = []
    for slot in slots:
        section_id, items = _section_items(report, slot.sections)
        if not items:
            items = _synthesis_items(synthesis, slot.fields)
        chosen = LAST_RESORT
        for candidate in slot.candidates:
            if candidate in claimed and candidate not in _REUSABLE_BLOCKS:
                continue
            predicate = availability.get(candidate)
            if predicate is not None and predicate(synthesis, items):
                chosen = candidate
                claimed.add(candidate)
                break
        if chosen is LAST_RESORT and slot.optional:
            continue
        resolved.append(ResolvedSlot(slot=slot, block_type=chosen, section_id=section_id, items=items))
    return resolved


def under_evidenced(resolved: list[ResolvedSlot], ratio: float = UNDER_EVIDENCED_SLOT_RATIO) -> bool:
    """Whether enough slots came up empty that the report should say so.

    A single empty slot is normal - not every question has competitor data.
    Half of them means the collection, not the layout, is what failed, and
    the reader deserves to be told that at the top rather than left to infer
    it from a page of thin cards.
    """
    if not resolved:
        return False
    empty = sum(1 for item in resolved if item.is_last_resort)
    return empty / len(resolved) >= ratio
