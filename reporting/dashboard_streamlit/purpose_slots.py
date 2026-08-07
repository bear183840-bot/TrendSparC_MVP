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
    "Line / Area": ("chart",),
    "Bar": ("bar", "metric_comparison"),
    "Matrix": ("matrix",),
    "Timeline": ("timeline",),
    "Table": ("table",),
    "Cause Map": ("cause_map",),
    "Action List": ("action_list",),
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
    Slot("market", "시장 상황", "시장이 어느 방향으로 움직이는가",
         ("chart", "bar", "timeline", "narrative_list"), ("market_status", "current_situation")),
    Slot("metrics", "지표", "확인된 수치를 제시",
         ("kpi_grid", "chart", "kpi_single"), ("key_metrics",)),
    Slot("competitor", "경쟁사", "다른 주체와 견주면 어디쯤인가",
         ("table", "radar", "narrative_list"), ("market_status",)),
    Slot("response", "대응 방향", "그래서 무엇을 해야 하는가",
         ("action_list", "narrative_list"), ("recommended_action", "near_term_outlook"),
         ("recommended_actions",)),
)

_ISSUE_RESPONSE: tuple[Slot, ...] = (
    # narrative_list has to stay last everywhere: it matches whenever the slot
    # has any prose at all, so anything listed after it is unreachable.
    Slot("problem", "문제", "무엇이 문제인가",
         ("matrix", "narrative_list"), ("issue", "problem")),
    Slot("cause", "원인", "왜 그렇게 되었는가",
         ("cause_map", "bar", "narrative_list"), ("root_cause", "issue"), ("risks",)),
    Slot("impact", "영향", "그 결과 무엇이 달라지는가",
         ("chart", "bar", "metric_comparison", "narrative_list"), ("impact",),
         ("business_impacts",)),
    Slot("options", "선택지", "택할 수 있는 길들의 비교",
         ("matrix", "table", "narrative_list"), ("risk_and_opportunity", "impact")),
    Slot("recommendation", "권장 조치", "무엇을 먼저 할 것인가",
         ("action_list", "narrative_list"), ("response_actions", "recommended_action"),
         ("recommended_actions",)),
)

_FUTURE_BUSINESS: tuple[Slot, ...] = (
    Slot("market_shift", "시장 변화", "시장이 어떻게 바뀌고 있는가",
         ("chart", "bar", "timeline", "narrative_list"), ("trend", "market_status")),
    Slot("opportunity", "기회", "어디에 기회가 있는가",
         ("matrix", "bar", "narrative_list"), ("opportunity",)),
    Slot("capability", "필요 역량", "그 기회를 잡으려면 무엇이 있어야 하는가",
         ("radar", "table", "narrative_list"), ("investment_signal", "opportunity"), ("strengths",)),
    Slot("roadmap", "실행 단계", "어떤 순서로 움직이는가",
         ("timeline", "action_list", "narrative_list"), ("strategic_recommendation",)),
    Slot("risk", "위험", "무엇이 어긋날 수 있는가",
         ("matrix", "narrative_list"), ("risk", "risk_and_opportunity"), ("risks",)),
)

_ROOT_CAUSE: tuple[Slot, ...] = (
    Slot("problem", "Problem", "어떤 현상이 관찰되는가",
         ("chart", "bar", "narrative_list"), ("problem", "issue")),
    Slot("cause", "Cause", "그 현상의 원인 구조",
         ("cause_map", "bar", "table", "narrative_list"), ("root_cause",)),
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


def _availability() -> dict[str, Callable[[Any, list[str]], bool]]:
    """block_type -> does the data support drawing it.

    Each predicate answers only "is this block honestly drawable", never "is
    it a good idea here" - that judgement is the slot's candidate order.
    """
    return {
        "chart": lambda synthesis, items: block_shapes.has_timeseries(synthesis.metric_series),
        "bar": lambda synthesis, items: bool(block_shapes.bar_metric_groups(synthesis.metric_series)),
        "metric_comparison": lambda synthesis, items: bool(
            block_shapes.metric_comparison_groups(synthesis.metric_series)
        ),
        "kpi_grid": lambda synthesis, items: len(synthesis.metric_series) >= _MIN_KPI_GRID_POINTS,
        "kpi_single": lambda synthesis, items: len(synthesis.metric_series) >= 1,
        "timeline": lambda synthesis, items: block_shapes.has_timeline(
            synthesis.evidence, synthesis.metric_series
        ),
        "table": lambda synthesis, items: block_shapes.has_comparison(synthesis.comparison_points),
        "radar": lambda synthesis, items: block_shapes.has_radar(synthesis.comparison_points),
        "matrix": lambda synthesis, items: sum(
            1 for field in (
                synthesis.strengths, synthesis.weaknesses,
                synthesis.opportunities, synthesis.risks,
            ) if field
        ) >= 2,
        "cause_map": lambda synthesis, items: block_shapes.has_cause_map(
            synthesis.risks, synthesis.business_impacts, synthesis.recommended_actions
        ),
        "action_list": lambda synthesis, items: bool(synthesis.recommended_actions),
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
