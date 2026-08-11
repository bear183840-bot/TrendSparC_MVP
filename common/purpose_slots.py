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

import re
from dataclasses import dataclass
from typing import Any, Callable

# Data-shape predicates only - deliberately NOT the rendering module. Slot
# resolution is a decision about evidence, so it must not depend on Streamlit
# or on anything that imports it.
from common import block_shapes
from common.content_quality_validator import (
    plotted_chart_series,
    select_chartable_series,
)
from common.content_quality_validator import (
    leading_subject_kind,
    semantic_entity_key,
    semantic_metric_key,
)

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
    "Bar": ("bar", "item_bar", "ranking_list", "grouped_bar", "metric_comparison"),
    "KPI Status Bar": ("status_bar",),
    "Share Split": ("share_split", "composition_breakdown"),
    "Matrix": ("matrix",),
    "Timeline": ("timeline",),
    "Table": ("table", "segment_table"),
    "Competitor Panels": ("competitor_panels", "benchmark_table"),
    "Level Matrix": ("level_matrix",),
    "Cause Map": ("cause_map",),
    "Root Cause Tree": ("cause_tree",),
    "Driver Bars": ("driver_bars",),
    "Action List": ("action_list",),
    "Factor List": ("factor_list",),
    "Keyword List": ("recurring_terms", "keyword_tags"),
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
    # Which kind of subject this slot's *prose* is about, when that is part
    # of what the slot means. 경쟁사 asks about organisations; a sentence whose
    # subject is an age bracket answers a different question and belongs to
    # 이용자 구성. Left None for every slot where the distinction is not part
    # of the heading - most of them.
    #
    # This exists because routing the structured comparisons was only half the
    # fix: when 경쟁사 found no organisation data it fell to the same section's
    # prose, and that prose was "50대의 숏폼 콘텐츠 이용 경험 비중은 64.1%".
    # The card was correct about having no competitor table and still wrong.
    subject: str | None = None
    # An optional slot disappears when its data isn't there, instead of
    # resolving to the last-resort placeholder. Use it for a slot that asks a
    # question only some evidence can answer (relative weighting of causes) -
    # its absence says nothing was measured, where an empty card would claim
    # the report tried and failed at something it always shows.
    optional: bool = False
    # Narrative metadata travels into the pre-collection plan and diagnostics.
    # It explains the question this position answers rather than merely naming
    # the picture selected for it.
    role: str = "support"
    question_answered: str = ""
    why_here: str = ""


@dataclass(frozen=True)
class ResolvedSlot:
    """What a slot decided to show: an ordered composition of blocks.

    Usually one block. But a slot is a *question*, not a picture, and the
    evidence for one question sometimes arrives in two shapes at once - a
    platform ranking and a set of one-off figures both answer 시장 상황, and
    showing only the first because a slot may hold exactly one block threw
    the second away. So a slot keeps drawing while there is unshown data its
    own candidate list can honestly draw, and stops as soon as the next
    candidate would only redraw what is already on the page.
    """
    slot: Slot
    block_types: tuple[str, ...]
    section_id: str | None
    items: list[str]
    # Evidence identities already drawn by an earlier slot on this page. A
    # renderer that draws a *set* of things - every composed whole, every
    # ranked group - subtracts these so it adds what is new instead of
    # repeating a card the reader has already scrolled past. Empty for a
    # caller that resolves one slot in isolation.
    drawn_before: frozenset[str] = frozenset()

    @property
    def block_type(self) -> str:
        """The lead block - the one that answers the slot's question most
        directly. Every caller that only wants the headline shape reads this.
        """
        return self.block_types[0] if self.block_types else LAST_RESORT

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
         ("share_split", "grouped_bar", "composition_breakdown", "ranking_list", "item_bar",
          "metric_comparison", "table", "narrative_list"),
         ("key_metrics", "market_status"), (), optional=True),
    # A dated sequence is more coherent than a cross-KPI snapshot. The latter
    # remains a fallback only when no real timeline exists.
    Slot("market", "시장 상황", "시장이 어느 방향으로 움직이는가",
         ("landscape", "chart", "bar", "timeline", "metric_comparison",
          "narrative_list"),
         ("market_status", "current_situation")),
    Slot("metrics", "지표", "확인된 수치를 제시",
         ("kpi_grid", "chart", "kpi_single", "status_bar"), ("key_metrics",)),
    # level_matrix leads: where the documents graded several competitors on
    # several criteria, the grid shows every grading at once. table shows the
    # same entities' free-text values, radar needs a full numeric profile -
    # each is the richest form its own data supports, in that order.
    Slot("competitor", "경쟁사", "다른 주체와 견주면 어디쯤인가",
         ("benchmark_table", "table", "level_matrix", "radar"),
         ("market_status",), subject="organisation"),
    # 요인/페인포인트 questions ("가입 고려 요인", "인기 요인") answer with a
    # list, and a list is what the evidence actually holds - so this slot has
    # its own place rather than being squeezed into 시장 상황's prose
    # fallback. driver_bars first, because a scored factor list beats an
    # unordered one where the analyzer managed to score it.
    # `fields` used to also fall back to risks/weaknesses/opportunities when
    # `factors` was empty - live-verified 2026-08-11: those are SWOT
    # categories, not causes, so "Key Drivers" ended up listing plain
    # opportunity/risk sentences ("AI 메모리 수요 증가에 기반한 시장 성장
    # 기회가 있다") under a heading that promises "왜 그런가". A slot with no
    # real factor content should render nothing (it's optional=True), not
    # borrow content that answers a different question.
    Slot("factors", "요인", "무엇이 그것을 좌우하는가",
         ("driver_bars", "factor_list", "narrative_list"),
         (),
         ("factors",), optional=True),
    # Age and gender breakdowns have their own place. They used to land in
    # 경쟁사 because the only question asked was "do two entities share a
    # criterion" - true of 50대 vs 60대, and wrong for that heading.
    # Reads the same section as 경쟁사 and takes the half that slot rejects, so
    # a demographic finding is moved rather than deleted.
    Slot("segments", "이용자 구성", "어떤 집단에서 어떻게 다른가",
         ("grouped_bar", "segment_table", "narrative_list"),
         ("market_status",), (), subject="demographic", optional=True),
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
         ("chart", "bar", "ranking_list", "item_bar", "metric_comparison", "narrative_list"), ("impact",),
         ("business_impacts",)),
    Slot("options", "선택지", "택할 수 있는 길들의 비교",
         ("matrix", "level_matrix", "benchmark_table", "table", "narrative_list"),
         ("risk_and_opportunity", "impact")),
    Slot("recommendation", "권장 조치", "무엇을 먼저 할 것인가",
         ("action_list", "narrative_list"), ("response_actions", "recommended_action"),
         ("recommended_actions",)),
)

_FUTURE_BUSINESS: tuple[Slot, ...] = (
    Slot("market_shift", "시장 변화", "시장이 어떻게 바뀌고 있는가",
         ("landscape", "chart", "bar", "ranking_list", "item_bar", "timeline", "narrative_list"),
         ("trend", "market_status")),
    Slot("opportunity", "기회", "어디에 기회가 있는가",
         ("matrix", "bar", "item_bar", "narrative_list"), ("opportunity",)),
    # No `sections`: there is no planned section about required capability, and
    # borrowing investment_signal's key_points put "디지털 광고 시장에서의
    # 존재감을 확대하는 기회" on screen under the heading "필요 역량" - a
    # section id and its rendered content saying different things. A slot may
    # only show what is genuinely its own; synthesis.strengths is what this
    # question actually has to say about capability.
    # Same split as 현황파악's: a media-habit breakdown by age is the answer
    # to a brand question, but it is not a statement about required capability,
    # which is where the untyped comparison table used to put it.
    Slot("segments", "대상 고객", "어떤 집단을 겨냥하는가",
         ("grouped_bar", "segment_table", "narrative_list"), (), (), optional=True),
    # Optional now that its table only takes organisations. A question about
    # which audience to target has plenty to say and nothing to say about
    # required capability; before, the audience table filled this heading, so
    # the emptiness was never visible. An empty card is the wrong way to show
    # it - the slot simply does not appear.
    Slot("capability", "필요 역량", "그 기회를 잡으려면 무엇이 있어야 하는가",
         ("radar", "benchmark_table", "table", "narrative_list"), (), ("strengths",), optional=True),
    Slot("roadmap", "실행 단계", "어떤 순서로 움직이는가",
         ("timeline", "action_list", "narrative_list"), ("strategic_recommendation",)),
    Slot("risk", "위험", "무엇이 어긋날 수 있는가",
         ("matrix", "narrative_list"), ("risk", "risk_and_opportunity"), ("risks",)),
)

_ROOT_CAUSE: tuple[Slot, ...] = (
    Slot("problem", "Problem", "어떤 현상이 관찰되는가",
         ("chart", "bar", "ranking_list", "item_bar", "narrative_list"), ("problem", "issue")),
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


# --- question-first narrative variants ---------------------------------

def _nslot(
    slot_id: str,
    title: str,
    intent: str,
    candidates: tuple[str, ...],
    sections: tuple[str, ...] = (),
    fields: tuple[str, ...] = (),
    *,
    optional: bool = False,
    subject: str | None = None,
    role: str = "support",
    question_answered: str = "",
    why_here: str = "",
) -> Slot:
    return Slot(
        slot_id, title, intent, candidates, sections, fields, subject, optional,
        role, question_answered, why_here,
    )


_STATUS_SNAPSHOT = _nslot(
    "snapshot", "핵심 지표", "현재 상태를 수치로 확인",
    ("kpi_grid", "kpi_single", "status_bar", "narrative_list"),
    ("key_metrics", "current_situation"), role="answer",
    question_answered="현재 핵심 상태는 어떠한가?",
    why_here="현황 질문은 현재값을 먼저 확인해야 이후 변화와 비교를 해석할 수 있다.",
)
_STATUS_MARKET = _nslot(
    "market", "시장 변화", "시장이 어느 방향으로 움직이는가",
    ("landscape", "chart", "timeline", "bar", "narrative_list"),
    ("market_status", "current_situation", "near_term_outlook"), role="evidence",
    question_answered="시장은 어떻게 변하고 있는가?",
    why_here="현재값 다음에 방향과 시점을 보여준다.",
)
_STATUS_COMPARISON = _nslot(
    "comparison", "주요 비교", "같은 기준에서 무엇이 앞서는가",
    ("share_split", "grouped_bar", "entity_attribute_bars", "composition_breakdown",
     "item_bar", "ranking_list", "metric_comparison", "table", "narrative_list"),
    ("key_metrics", "market_status"), role="analysis",
    question_answered="주요 대상은 같은 기준에서 어떻게 다른가?",
    why_here="현황과 변화 확인 뒤 상대적 위치를 비교한다.",
)
_STATUS_EXPLICIT_COMPARISON = _nslot(
    "comparison", "주요 비교", "질문이 지정한 상태·대상을 같은 기준으로 비교",
    ("bar", "share_split", "grouped_bar", "entity_attribute_bars", "composition_breakdown",
     "item_bar", "ranking_list", "metric_comparison", "benchmark_table", "table", "chart",
     "narrative_list"),
    ("key_metrics", "market_status"), role="answer",
    question_answered="질문이 지정한 두 상태 또는 대상은 어떻게 다른가?",
    why_here="명시적 비교 질문은 비교 가능한 실제 상태·대상 구조를 첫 답으로 제시한다.",
)
_STATUS_COMPETITOR = _nslot(
    "competitor", "경쟁 구도", "경쟁 주체와 견주면 어디쯤인가",
    ("benchmark_table", "table", "level_matrix", "radar", "narrative_list"),
    ("market_status",), optional=True, subject="organisation", role="analysis",
    question_answered="경쟁 주체 대비 위치는 어떠한가?",
    why_here="공통 축의 비교 자료가 있을 때만 경쟁 구도를 보강한다.",
)
_STATUS_FACTORS = _nslot(
    "factors", "주요 요인", "무엇이 현재 상태를 좌우하는가",
    ("driver_bars", "factor_list", "narrative_list"), (),
    ("factors",), optional=True,
    role="analysis", question_answered="현재 상태를 좌우하는 요인은 무엇인가?",
    why_here="관찰된 결과 뒤에 그 배경 요인을 해석한다.",
)
_STATUS_SEGMENTS = _nslot(
    "segments", "이용자 구성", "집단별 차이를 확인",
    ("grouped_bar", "segment_table", "narrative_list"), ("market_status",), (),
    optional=True, subject="demographic", role="support",
    question_answered="어떤 이용자 집단에서 차이가 나는가?",
    why_here="질문과 관련된 세그먼트 근거가 있을 때만 상세로 제시한다.",
)
_STATUS_RESPONSE = _nslot(
    "response", "대응 방향", "근거에서 도출되는 다음 행동",
    ("action_list", "narrative_list"), ("recommended_action", "near_term_outlook"),
    ("recommended_actions",), optional=True, role="action",
    question_answered="확인된 현황에 따라 무엇을 할 수 있는가?",
    why_here="행동을 요구했거나 근거 기반 권고가 있을 때만 결론을 닫는다.",
)
_STATUS_SWOT = _nslot(
    "position", "핵심 진단", "현재의 강점·약점·기회·위험",
    ("matrix", "narrative_list"), ("risk_and_opportunity",),
    ("strengths", "weaknesses", "opportunities", "risks"), optional=True,
    role="analysis", question_answered="현재 확인되는 유리함과 위험은 무엇인가?",
    why_here="근거가 있는 SWOT 분면만 사용해 현황의 의미를 압축한다.",
)

_STATUS_GENERAL = (
    _STATUS_SNAPSHOT, _STATUS_MARKET, _STATUS_COMPARISON, _STATUS_COMPETITOR,
    _STATUS_FACTORS, _STATUS_SEGMENTS, _STATUS_SWOT, _STATUS_RESPONSE,
)
_STATUS_COMPARE = (
    _STATUS_EXPLICIT_COMPARISON, _STATUS_SNAPSHOT, _STATUS_COMPETITOR, _STATUS_MARKET,
    _STATUS_FACTORS, _STATUS_SEGMENTS, _STATUS_SWOT, _STATUS_RESPONSE,
)
_STATUS_TREND = (
    _STATUS_MARKET, _STATUS_SNAPSHOT, _STATUS_FACTORS, _STATUS_COMPARISON,
    _STATUS_COMPETITOR, _STATUS_SEGMENTS, _STATUS_SWOT, _STATUS_RESPONSE,
)

_RECOMMEND = (
    _nslot("target", "타깃", "누구에게 맞춰야 하는가",
           ("kpi_grid", "grouped_bar", "segment_table", "narrative_list"),
           ("market_status", "current_situation"), ("factors", "key_points"),
           role="answer", question_answered="추천 대상의 핵심 특성은 무엇인가?",
           why_here="후보를 고르기 전에 선택 기준이 되는 타깃을 먼저 정의한다."),
    _nslot("candidates", "후보", "선택 가능한 후보는 무엇인가",
           ("item_bar", "ranking_list", "table", "narrative_list"),
           ("market_status", "key_metrics"), role="evidence",
           question_answered="검토할 수 있는 후보는 무엇인가?",
           why_here="타깃 기준에 맞춰 비교할 후보군을 빠짐없이 제시한다."),
    _nslot("comparison", "후보 비교", "후보들을 같은 기준으로 비교",
           ("grouped_bar", "benchmark_table", "table", "metric_comparison", "narrative_list"),
           ("market_status",), role="analysis",
           question_answered="후보들은 공통 기준에서 어떻게 다른가?",
           why_here="선택 전에 동일 축의 차이를 확인한다."),
    _nslot("fit", "적합도", "타깃과 후보의 적합성을 판단",
           ("matrix", "level_matrix", "table", "driver_bars", "narrative_list"),
           ("risk_and_opportunity", "key_implication"),
           ("strengths", "weaknesses", "opportunities", "risks", "factors"),
           role="decision", question_answered="어떤 후보가 질문의 조건에 가장 적합한가?",
           why_here="근거에서 확인된 적합도와 위험을 선택 직전에 종합한다."),
    _nslot("recommendation", "추천", "무엇을 선택해야 하는가",
           ("action_list", "narrative_list"),
           ("recommended_action", "strategic_recommendation"), ("recommended_actions",),
           role="decision", question_answered="최종적으로 무엇을 추천하는가?",
           why_here="타깃·후보·비교·적합도 근거를 확인한 뒤 선택을 제시한다."),
    _nslot("execution", "실행", "추천을 어떻게 실행할 것인가",
           ("timeline", "kpi_grid", "narrative_list"),
           ("strategic_recommendation",), ("monitoring_indicators",), optional=True,
           role="action", question_answered="추천안을 어떻게 실행하고 확인할 것인가?",
           why_here="실행 근거가 있을 때만 추천 이후 단계로 제시한다."),
)

_CAUSE_NARRATIVE = (
    _nslot("problem", "문제 증거", "문제가 실제로 존재하는지 확인",
           ("kpi_grid", "kpi_single", "chart", "bar", "ranking_list", "item_bar", "narrative_list"),
           ("problem", "issue"), role="evidence",
           question_answered="분석할 문제가 실제로 어떻게 나타나는가?",
           why_here="원인을 말하기 전에 현상을 근거로 확인한다."),
    _nslot("cause", "원인 구조", "현상의 원인 관계",
           ("cause_tree", "cause_map", "table", "narrative_list"), ("root_cause",),
           role="answer", question_answered="문제를 만든 원인 구조는 무엇인가?",
           why_here="현상이 확인된 뒤 원인 관계를 직접 답한다."),
    _nslot("drivers", "원인 중요도", "어느 원인이 더 크게 작용하는가",
           ("driver_bars", "bar", "item_bar", "kpi_grid"), ("root_cause",),
           optional=True, role="analysis", question_answered="어느 원인을 우선 봐야 하는가?",
           why_here="AI 중요도와 판단 근거가 있을 때 원인 사이의 우선순위를 보인다."),
    _nslot("evidence", "원인 근거", "원인과 영향의 세부 증거",
           ("table", "narrative_list"), ("root_cause", "impact"),
           role="evidence", question_answered="각 원인을 뒷받침하는 실제 근거는 무엇인가?",
           why_here="원인 구조와 중요도를 원문 근거로 검증한다."),
    _nslot("improvement", "개선", "원인 사슬을 어디서 끊을 것인가",
           ("action_list", "table", "narrative_list"), ("improvement_plan",),
           ("recommended_actions",), optional=True, role="action",
           question_answered="해결까지 요청한 경우 무엇을 개선해야 하는가?",
           why_here="질문이 개선을 요구하거나 근거 기반 조치가 있을 때만 닫는다."),
)

_ISSUE_NARRATIVE = (
    _nslot("problem", "문제", "현재 이슈를 명확히 확인",
           ("kpi_grid", "kpi_single", "chart", "matrix", "narrative_list"),
           ("issue", "problem"), ("risks",), role="answer",
           question_answered="지금 대응해야 할 문제는 무엇인가?",
           why_here="대응 논의 전에 문제와 규모를 먼저 고정한다."),
    _nslot("cause", "원인", "문제가 발생한 이유",
           ("cause_tree", "cause_map", "bar", "table", "narrative_list"),
           ("root_cause", "issue"), ("risks",), role="analysis",
           question_answered="문제는 왜 발생했는가?",
           why_here="영향과 대안을 평가하기 전에 원인을 확인한다."),
    _nslot("impact", "영향", "사업과 고객에 미치는 결과",
           ("kpi_grid", "kpi_single", "chart", "bar", "table", "metric_comparison", "narrative_list"),
           ("impact",), ("business_impacts",), role="evidence",
           question_answered="문제가 사업·시장·고객에 미치는 영향은 무엇인가?",
           why_here="대응 우선순위를 정할 수 있도록 영향의 크기와 범위를 보인다."),
    _nslot("options", "선택지", "가능한 대응 대안 비교",
           ("matrix", "benchmark_table", "level_matrix", "table", "item_bar", "narrative_list"),
           ("risk_and_opportunity", "impact"), role="decision",
           question_answered="선택 가능한 대응안과 장단점은 무엇인가?",
           why_here="문제·원인·영향을 확인한 뒤 대안을 비교한다."),
    _nslot("recommendation", "권장 조치", "무엇을 먼저 실행할 것인가",
           ("action_list", "narrative_list"),
           ("response_actions", "recommended_action"), ("recommended_actions",),
           role="decision", question_answered="가장 우선할 대응은 무엇인가?",
           why_here="대안 비교 뒤 근거 기반 권고로 결론을 낸다."),
    _nslot("execution", "실행", "대응의 순서와 확인 지표",
           ("timeline", "kpi_grid", "narrative_list"),
           ("response_actions",), ("monitoring_indicators",), optional=True,
           role="action", question_answered="권장 조치를 언제 어떻게 실행할 것인가?",
           why_here="실행 시점이나 확인 지표가 있을 때만 후속 계획을 제시한다."),
)

_STRATEGY_NARRATIVE = (
    _nslot("current_position", "현재 위치", "현재 사업과 경쟁 위치",
           ("kpi_grid", "kpi_single", "benchmark_table", "table", "bar", "narrative_list"),
           ("investment_signal", "market_status"), optional=True, role="evidence",
           question_answered="현재 우리 회사는 무엇을 하고 어디에 위치하는가?",
           why_here="당사 근거가 있을 때 시장 전망보다 먼저 출발점을 확인한다."),
    _nslot("future_change", "미래 변화", "시장·기술의 향후 변화",
           ("landscape", "chart", "timeline", "bar", "narrative_list"),
           ("trend", "market_status"), role="evidence",
           question_answered="시장과 기술은 앞으로 어떻게 변하는가?",
           why_here="현재 위치 다음에 외부 변화의 방향을 확인한다."),
    _nslot("opportunity", "기회", "변화가 만드는 사업 기회",
           ("matrix", "bar", "item_bar", "table", "narrative_list"), ("opportunity",),
           ("opportunities",), role="analysis",
           question_answered="변화 속에서 어떤 기회가 생기는가?",
           why_here="외부 변화가 사업 후보로 연결되는 지점을 찾는다."),
    _nslot("competitive_fit", "경쟁 적합성", "당사 역량과 경쟁사 대비 적합성",
           ("benchmark_table", "table", "radar", "level_matrix", "bar", "narrative_list"),
           ("investment_signal",), ("strengths", "weaknesses"), optional=True,
           role="analysis", question_answered="우리 역량은 경쟁사 대비 기회에 얼마나 맞는가?",
           why_here="기회를 선택하기 전에 실행 주체의 적합성을 검증한다."),
    _nslot("strategic_choice", "전략 선택", "가능한 방향 중 우선순위 결정",
           ("matrix", "benchmark_table", "table", "item_bar", "narrative_list"),
           ("risk_and_opportunity", "strategic_recommendation"), role="decision",
           question_answered="어떤 전략 방향을 우선해야 하는가?",
           why_here="시장성과 당사 경쟁력을 함께 본 뒤 선택한다."),
    _nslot("recommendation", "추천 방향", "최종 전략 방향",
           ("action_list", "narrative_list"), ("strategic_recommendation",),
           ("recommended_actions",), role="decision",
           question_answered="최종적으로 어디로 가야 하는가?",
           why_here="분석과 선택의 결론을 명확한 방향으로 제시한다."),
    _nslot("execution", "실행 단계", "전략 실행 순서",
           ("action_list", "timeline", "kpi_grid", "narrative_list"),
           ("strategic_recommendation",), ("recommended_actions", "monitoring_indicators"),
           role="action", question_answered="선택한 전략을 어떻게 실행할 것인가?",
           why_here="전략 방향을 실제 행동과 확인 지표로 닫는다."),
    _nslot("risk", "위험", "전략이 어긋날 조건",
           ("matrix", "table", "narrative_list"), ("risk", "risk_and_opportunity"),
           ("risks",), optional=True, role="support",
           question_answered="전략 실행에서 무엇이 어긋날 수 있는가?",
           why_here="실제 위험 근거가 있을 때만 마지막 검토 항목으로 둔다."),
)

PURPOSE_SLOTS: dict[str, tuple[Slot, ...]] = {
    "current_status": _CURRENT_STATUS,
    "issue_response": _ISSUE_RESPONSE,
    "future_business": _FUTURE_BUSINESS,
    "root_cause": _ROOT_CAUSE,
}

DEFAULT_PURPOSE_SLOTS = _CURRENT_STATUS

_ANSWER_TYPE_SLOTS: dict[tuple[str, str], tuple[Slot, ...]] = {
    ("current_status", "status"): _STATUS_GENERAL,
    ("current_status", "compare"): _STATUS_COMPARE,
    ("current_status", "trend"): _STATUS_TREND,
    ("current_status", "recommend"): _RECOMMEND,
    ("root_cause", "cause"): _CAUSE_NARRATIVE,
    ("issue_response", "issue_response"): _ISSUE_NARRATIVE,
    ("future_business", "strategy"): _STRATEGY_NARRATIVE,
}


def slots_for(purpose_id: str | None, question_answer_type: str | None = None) -> tuple[Slot, ...]:
    """Return the purpose narrative refined by the explicit answer shape.

    Purpose remains the stable four-way taxonomy.  Answer type may change the
    first substantive question and its supporting order, but never invents a
    fifth purpose.  Unknown/legacy callers retain the established skeleton.
    """
    purpose = purpose_id or "current_status"
    if question_answer_type:
        exact = _ANSWER_TYPE_SLOTS.get((purpose, question_answer_type))
        if exact is not None:
            return exact
        # Explicit answer modes override a broad purpose where their reader
        # flow is unambiguous.  A recommendation remains recommendation-shaped
        # even if a secondary strategy signal won the broad classifier.
        if question_answer_type == "recommend":
            return _RECOMMEND
        if question_answer_type == "cause":
            return _CAUSE_NARRATIVE
        if question_answer_type == "issue_response":
            return _ISSUE_NARRATIVE
        if question_answer_type == "strategy":
            return _STRATEGY_NARRATIVE
        if question_answer_type == "compare":
            return _STATUS_COMPARE
        if question_answer_type == "trend":
            return _STATUS_TREND
    return PURPOSE_SLOTS.get(purpose, DEFAULT_PURPOSE_SLOTS)


def narrative_configuration_issues(slots: tuple[Slot, ...]) -> list[str]:
    """Validate the configured story before evidence chooses any pictures."""
    issues: list[str] = []
    seen_questions: dict[str, str] = {}
    for slot in slots:
        if not slot.question_answered.strip():
            issues.append(f"{slot.slot_id}: question_answered is empty")
        if not slot.why_here.strip():
            issues.append(f"{slot.slot_id}: why_here is empty")
        normalized = "".join(slot.question_answered.split()).casefold()
        if normalized and normalized in seen_questions:
            issues.append(
                f"{slot.slot_id}: duplicates question answered by {seen_questions[normalized]}"
            )
        elif normalized:
            seen_questions[normalized] = slot.slot_id
    return issues

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
        "ranking_list": lambda synthesis, items: block_shapes.has_ranking_list(
            synthesis.metric_series, synthesis.comparison_points
        ),
        # Three axes at once (metric x subject x category) - strictly more
        # than item_bar shows, so it is offered first wherever both fit.
        "grouped_bar": lambda synthesis, items: block_shapes.has_grouped_bars(synthesis.metric_series),
        # Two or more subjects with their OWN distinct attributes and no
        # shared category between them at all - "grouped_bar" above requires
        # the opposite (every subject measured on the same categories), so
        # this is not a narrower version of it, it is the complementary shape.
        "entity_attribute_bars": lambda synthesis, items: block_shapes.has_entity_attribute_bars(
            synthesis.metric_series
        ),
        "status_bar": lambda synthesis, items: block_shapes.has_status_levels(
            synthesis.comparison_points
        ),
        # Two axes of graded comparison - strictly more than the status band,
        # which keeps one row per criterion.
        "level_matrix": lambda synthesis, items: block_shapes.has_level_matrix(
            block_shapes.comparison_points_without_rank_dimensions(
                synthesis.comparison_points
            )
        ),
        # Composition, not ranking - and only where the source framed the
        # figures as parts of one named whole.
        "share_split": lambda synthesis, items: any(
            2 <= len(slices) <= 3
            for _, slices in block_shapes.share_groups(synthesis.metric_series)
        ),
        "composition_breakdown": lambda synthesis, items: any(
            len(slices) >= 4 for _, slices in block_shapes.share_groups(synthesis.metric_series)
        ),
        "metric_comparison": lambda synthesis, items: bool(
            block_shapes.metric_comparison_groups(synthesis.metric_series)
            or block_shapes.metric_snapshot_groups(synthesis.metric_series)
        ),
        "kpi_grid": lambda synthesis, items: len(synthesis.metric_series) >= _MIN_KPI_GRID_POINTS,
        "kpi_single": lambda synthesis, items: len(synthesis.metric_series) >= 1,
        "timeline": lambda synthesis, items: block_shapes.has_timeline(
            synthesis.evidence,
            synthesis.metric_series,
            _reference_year(synthesis),
        ),
        # Two tables, one renderer, different questions. 경쟁사 asks about
        # organisations; a demographic split is a different section entirely,
        # and showing 50대/60대/70대 이상 under "경쟁사" states something
        # false about the market rather than merely looking odd.
        "table": lambda synthesis, items: block_shapes.has_comparison(
            block_shapes.comparison_points_not_covered_by_ranking(
                synthesis.comparison_points, synthesis.metric_series
            ),
            demographic=False,
        ),
        "segment_table": lambda synthesis, items: block_shapes.has_comparison(
            synthesis.comparison_points, demographic=True
        ),
        # Richer than the table wherever each competitor has several
        # kinds of fact attached, so it is offered first in 경쟁사.
        "competitor_panels": lambda synthesis, items: bool(
            block_shapes.competitor_panels_not_covered_by_ranking(
                synthesis.comparison_points, synthesis.metric_series
            )
        ),
        "benchmark_table": lambda synthesis, items: block_shapes.has_benchmark_grid(
            synthesis.comparison_points, synthesis.metric_series
        ),
        "radar": lambda synthesis, items: block_shapes.has_radar(synthesis.comparison_points),
        # One quadrant is enough: the block renders it as a single accent
        # panel instead of a 2x2 with three holes. Requiring two meant a
        # question with only opportunities lost the block entirely and fell
        # to prose - "쓴다/안 쓴다"의 이분법 rather than 있는 만큼 쓰기.
        "matrix": lambda synthesis, items: any(
            (synthesis.strengths, synthesis.weaknesses,
             synthesis.opportunities, synthesis.risks)
        ) or block_shapes.has_decision_matrix(synthesis.comparison_points),
        # A real chain the documents stated, ahead of cause_map's column
        # layout, which only groups risks/impacts/actions side by side.
        "cause_tree": lambda synthesis, items: block_shapes.has_cause_tree(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "driver_bars": lambda synthesis, items: block_shapes.has_importance_ranking(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "cause_map": lambda synthesis, items: block_shapes.has_cause_map(
            synthesis.factors or synthesis.risks,
            synthesis.business_impacts,
            synthesis.recommended_actions,
        ),
        "action_list": lambda synthesis, items: bool(
            synthesis.recommended_actions
            or getattr(synthesis, "ai_recommended_actions", None)
        ),
        # A list is worth its own card only when it is long enough to be a
        # list; two bullets are a sentence and belong in the prose fallback.
        "factor_list": lambda synthesis, items: len(items) >= _MIN_FACTOR_ITEMS,
        "recurring_terms": lambda synthesis, items: block_shapes.has_recurring_terms(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "keyword_tags": lambda synthesis, items: block_shapes.has_recurring_terms(
            getattr(synthesis, "grounded_claims", []) or []
        ),
        "narrative_list": lambda synthesis, items: bool(items),
    }


# How many blocks one slot may hold. A slot is still a single question, so
# the composition is a lead block plus at most one companion answering that
# same question from data the lead does not touch - past that it stops being
# a section and becomes a dashboard of its own.
_MAX_BLOCKS_PER_SLOT = 2


def _metric_label_keys(groups: list[list[Any]]) -> set[str]:
    return {
        f"metric:{semantic_metric_key(points[0].label)}" for points in groups if points
    }


def _timeline_keys(synthesis: Any) -> set[str]:
    """A timeline's identity is the metric it plots, not the word "timeline".

    A constant key made a timeline invisible to every other shape's dedup -
    live-verified 2026-08-11: a `bar` and a `timeline` slot each independently
    picked the identical "숏폼 콘텐츠 시청 비중" series (`time_bar_groups` and
    `timeline_entries` both prefer the same repeated-period metric,
    `block_shapes._timeline_metric_series`), so the same two numbers rendered
    twice under different shapes. Keying on `metric:{semantic_metric_key}`
    matches the scheme `bar`/`chart`/`metric_comparison` already use, so the
    two-pass claim in `resolve_slots()` recognizes the overlap regardless of
    which shape drew it first - general to any metric, not "숏폼" specific.
    When the timeline instead falls back to dated prose (no repeated metric
    exists), key on the drawn sentences themselves so two different prose
    timelines don't collide but an identical repeat still does.
    """
    label = block_shapes.timeline_evidence_label(synthesis.metric_series)
    if label:
        return {f"metric:{semantic_metric_key(label)}"}
    entries = block_shapes.timeline_entries(
        synthesis.evidence, synthesis.metric_series, _reference_year(synthesis)
    )
    if not entries:
        return {"timeline"}
    return {f"timeline:{period}:{text}" for period, text in entries}


def _comparison_keys(points: list[Any]) -> set[str]:
    return {
        f"cmp:{semantic_entity_key(point.entity)}:{semantic_metric_key(point.criterion)}"
        for point in points
    }


# What a block *does* with the facts it draws, as opposed to which facts.
#
# Dedup on the facts alone is wrong, and the revenue_trend fixture is the
# proof: a 매출액 trend line, a 매출액 KPI card and a 매출액 bar are the same
# three numbers, and a 현황파악 report has separate 시장상황 / 지표 / 순위
# slots precisely because "how did it move", "what is it now" and "how does
# it rank" are three questions. Keying on the facts alone let whichever slot
# ran first answer all three and leave the other two empty.
#
# Two blocks of the *same* family drawing the same facts genuinely are one
# card shown twice - the composition donut that appeared under both 시장 변화
# and 주요 비교. A block type absent from this table gets its own family, so
# it dedupes only against itself, which is the old claimed-once behaviour.
_SHAPE_FAMILIES: dict[str, str] = {
    "share_split": "composition",
    "composition_breakdown": "composition",
    "chart": "trend",
    "kpi_grid": "kpi",
    "kpi_single": "kpi",
    "bar": "bars",
    "item_bar": "bars",
    "ranking_list": "bars",
    "grouped_bar": "bars",
    "entity_attribute_bars": "bars",
    "metric_comparison": "bars",
    # A timeline built from a repeated metric (see `_timeline_keys`) draws
    # the exact figures a bar/item_bar/metric_comparison would for that same
    # metric, just as dots-on-a-line instead of columns - live-verified
    # 2026-08-11: "숏폼 콘텐츠 시청 비중" rendered once as a horizontal bar and
    # once as a timeline, in two different cards. A timeline built from dated
    # prose instead (no repeated metric) keys on the sentences themselves
    # (`timeline:{period}:{text}`), which never collides with a `bars`-family
    # metric key, so this mapping only ever suppresses the genuine duplicate.
    "timeline": "bars",
    "table": "comparison_grid",
    "segment_table": "comparison_grid",
    "benchmark_table": "comparison_grid",
    "level_matrix": "comparison_grid",
    "competitor_panels": "comparison_grid",
    "radar": "comparison_grid",
}

# Keys minted already carrying their family, because the block that draws
# them draws more than one shape - `landscape` is a trend and a composition
# in one card, so a single family for it would be a lie in one direction or
# the other.
_QUALIFIED = "|"


def qualified_key(family: str, key: str) -> str:
    return key if _QUALIFIED in key else f"{family}{_QUALIFIED}{key}"


def share_evidence_key(whole: object) -> str:
    """The consumption key for one composed whole.

    Public because a renderer that subtracts already-drawn compositions has
    to compute the same key the resolver did; two spellings of this rule
    would silently stop matching the first time either changed.
    """
    return f"composition{_QUALIFIED}share:{semantic_metric_key(str(whole or ''))}"


def _share_keys(groups: list[tuple[str, list[Any]]]) -> set[str]:
    """One key per composed whole, in a namespace only compositions use.

    A donut and a stacked rail of the same `share_of` group are the same
    three numbers drawn twice, so both have to land on the same key. The
    period is already inside the whole's own name wherever a source dated it
    ("'25년 하반기 가입자 수·점유율"), so keying on the whole does not merge
    two half-years into one.
    """
    return {share_evidence_key(whole) for whole, _ in groups}


def _landscape_keys(synthesis: Any) -> set[str]:
    """Exactly what the landscape card draws - not every metric there is.

    This used to return a key for every label in the synthesis, which was
    both too coarse to dedupe against (the donut it draws had no key of its
    own, so a second donut elsewhere looked like new data) and too greedy to
    dedupe with (every KPI in the report looked already-drawn).
    """
    parts = block_shapes.landscape_parts(synthesis.metric_series)
    if parts is None:
        return set()
    core_kind, core_points, complement_kind, complement_points = parts
    core_family = "trend" if core_kind == "trend" else "kpi"
    keys = {
        qualified_key(core_family, f"metric:{semantic_metric_key(point.label)}")
        for point in core_points
    }
    if complement_kind == "share":
        whole = (getattr(complement_points[0], "share_of", "") or "") if complement_points else ""
        keys |= {share_evidence_key(whole)} if whole else set()
    else:
        complement_family = "bars" if complement_kind == "comparison" else "kpi"
        keys |= {
            qualified_key(complement_family, f"metric:{semantic_metric_key(point.label)}")
            for point in complement_points
        }
    return keys


def bars_evidence_key(point: Any) -> str:
    """The consumption key for one bars-family metric point (`bar`/
    `item_bar`/`ranking_list`/`grouped_bar`/`metric_comparison` all share
    this family, see `_SHAPE_FAMILIES`).

    Public for the same reason `kpi_evidence_key`/`share_evidence_key` are:
    the Executive Summary's own comparison visualization
    (`common.block_shapes.executive_summary_comparison`) is chosen outside
    `resolve_slots()`, so its facts must be marked drawn in the exact
    spelling `_consumption()`'s `"metric_comparison"` entry already uses.
    """
    return qualified_key("bars", f"metric:{semantic_metric_key(point.label)}")


# A closed set of Korean rollup/total words a table's own row label may
# carry ("IPTV 총계 가입자수") beside a plain sentence restatement of the
# identical reading ("IPTV 가입자 수"). Dedup-key-only normalization - never
# touches what is displayed, and deliberately narrow (matches the same
# vocabulary the analyzer's own total-row detection uses) rather than a
# general fuzzy rewrite.
_TOTAL_QUALIFIER_RE = re.compile(r"(총계|소계|합계)")


def _canonical_metric_key(point: Any) -> str:
    """The same identity `semantic_metric_key(label)` already gives every
    other consumer of a metric label - kept label-based, and deliberately
    period-agnostic, matching `rank_kpi_candidates`'s own behavior of
    folding every period of one label into a single latest-plus-delta card
    (see test_the_same_label_at_a_different_period_is_still_one_kpi_identity).

    On top of that shared identity, two dedup-key-only fixes for one
    label naming the same reading two ways:
    - a table's own total-row wording ("IPTV 총계 가입자수") vs. a sentence
      restating it ("IPTV 가입자 수") - the qualifier is dropped before
      keying;
    - "가입자 수" vs "가입자수" - Korean noun-noun compounds are written
      with and without a space inconsistently by extraction, and
      `semantic_metric_key` collapses whitespace *runs* but does not merge
      a written-together compound with a written-apart one. Internal
      whitespace is removed here, for this key only - this changes what
      counts as *the same label*, not what any other caller of
      `semantic_metric_key` sees.
    Live-verified 2026-08-11: the Executive Summary headline ("IPTV 가입자
    수", 21,535,256) and the first Key Metrics card ("IPTV 총계 가입자수",
    the identical 21,535,256) survived the label-only dedup as two different
    identities until both of these were applied.
    """
    # Cleaned before semantic_metric_key, not after: its own alias table
    # matches specific substrings ("가입자 수" with the space -> "subscribers"),
    # so a label already carrying the qualifier or the no-space spelling
    # missed that alias and fell through as raw Korean while the plain
    # spelling hit it - two different output strings for what should be one
    # key. Stripping first means both spellings reach semantic_metric_key
    # identically and either both hit the alias or neither does.
    cleaned = _TOTAL_QUALIFIER_RE.sub("", point.label or "")
    cleaned = re.sub(r"\s+", "", cleaned)
    return semantic_metric_key(cleaned)


def kpi_evidence_key(point: Any) -> str:
    """The consumption key for one KPI-shaped metric point.

    Public for the same reason `share_evidence_key` is: a caller outside
    this module needs to mark its own pick as already drawn in the exact
    namespace `_kpi_keys`/`resolve_slots` use, so two spellings of "this is
    the same metric" cannot silently drift apart. The Executive Summary's
    headline figure (`headline_kpi`) is picked by the same ranking the Key
    Metrics `kpi_grid` slot uses (`rank_kpi_candidates`) but is rendered
    outside `resolve_slots()` entirely - without this, the identical
    top-ranked metric shows up twice: once as the summary's headline number,
    once again as the first Key Metrics card.
    """
    return qualified_key("kpi", f"metric:{_canonical_metric_key(point)}")


def _kpi_keys(synthesis: Any, question: str | None) -> set[str]:
    """The metrics a KPI grid puts on cards - not every metric it could.

    This used to report one key per point in `metric_series`: 77 keys for a
    grid that draws six. Under a report-wide dedup rule that is not a
    conservative over-report, it is a claim on the whole page - every other
    metric block looked already-drawn and disappeared behind whichever ran
    first. `rank_kpi_candidates` is the same selection `_kpi` renders, so
    asking it is asking the block itself.
    """
    return {
        f"metric:{_canonical_metric_key(point)}"
        for point in block_shapes.rank_kpi_candidates(
            synthesis.metric_series, (question or "").split(),
        )
    }


def _chart_keys(synthesis: Any) -> set[str]:
    """The series a trend chart draws, after unit/period and series caps."""
    return {
        f"metric:{semantic_metric_key(point.label)}"
        for point in plotted_chart_series(
            select_chartable_series(synthesis.metric_series)
        )
    }


def _consumption(question: str | None = None) -> dict[str, Callable[[Any, list[str]], set[str]]]:
    """block_type -> the identity of the data it would put on screen.

    This is what makes composition safe. Two blocks in one slot are worth
    showing only when they draw *different* facts, and the old rule - a block
    type may be claimed once per report - approximated that badly in both
    directions. It let two slots show the same three numbers under different
    headings whenever they picked different block ids for them, and it
    blocked a second comparison table that would have held entirely
    different entities.

    A block whose data cannot be identified at this granularity returns one
    coarse key, which reproduces the old behaviour: claimed once, report-wide.
    """
    by_label = block_shapes.group_metric_points_by_label
    return {
        "landscape": lambda s, i: _landscape_keys(s),
        "chart": lambda s, i: _chart_keys(s),
        "bar": lambda s, i: _metric_label_keys(block_shapes.time_bar_groups(s.metric_series)),
        "item_bar": lambda s, i: _metric_label_keys(block_shapes.item_bar_groups(s.metric_series)),
        "ranking_list": lambda s, i: _metric_label_keys(
            block_shapes.item_bar_groups(s.metric_series)
        ) | {
            f"cmp:{point.entity}"
            for group in block_shapes.ranking_comparison_groups(s.comparison_points)
            for point in group
        },
        "grouped_bar": lambda s, i: {
            f"metric:{semantic_metric_key(label)}"
            for label, _, _ in block_shapes.grouped_bar_series(s.metric_series)
        },
        "entity_attribute_bars": lambda s, i: {
            f"entity_attr:{semantic_entity_key(subject)}"
            for subject, _ in block_shapes.entity_attribute_groups(s.metric_series)
        },
        "share_split": lambda s, i: _share_keys(block_shapes.share_groups(s.metric_series)),
        "composition_breakdown": lambda s, i: _share_keys(
            block_shapes.share_groups(s.metric_series)
        ),
        "metric_comparison": lambda s, i: {
            f"metric:{semantic_metric_key(point.label)}"
            for _, points in (
                *block_shapes.metric_comparison_groups(s.metric_series),
                *block_shapes.metric_snapshot_groups(s.metric_series),
            )
            for point in points
        },
        "kpi_grid": lambda s, i: _kpi_keys(s, question),
        "kpi_single": lambda s, i: _kpi_keys(s, question),
        "timeline": lambda s, i: _timeline_keys(s),
        "table": lambda s, i: _comparison_keys(
            block_shapes.comparison_points_of_kind(s.comparison_points, False)
        ),
        "segment_table": lambda s, i: _comparison_keys(
            block_shapes.comparison_points_of_kind(s.comparison_points, True)
        ),
        "competitor_panels": lambda s, i: _comparison_keys(
            block_shapes.comparison_points_of_kind(s.comparison_points, False)
        ),
        "benchmark_table": lambda s, i: _comparison_keys(s.comparison_points),
        "radar": lambda s, i: _comparison_keys(s.comparison_points),
        "status_bar": lambda s, i: {
            f"cmp:{entity}" for entity, _, _ in block_shapes.status_levels(s.comparison_points)
        },
        "level_matrix": lambda s, i: {
            f"cmp:{entity}" for entity in block_shapes.level_matrix(s.comparison_points)[0]
        },
        "matrix": lambda s, i: (
            {"swot"} if any((s.strengths, s.weaknesses, s.opportunities, s.risks))
            else _comparison_keys(s.comparison_points)
        ),
        "cause_tree": lambda s, i: {"claim_graph"},
        "cause_map": lambda s, i: {"claim_graph"},
        "driver_bars": lambda s, i: {"importance"},
        "action_list": lambda s, i: {
            "actions" if s.recommended_actions else "ai_actions"
        },
        "factor_list": lambda s, i: {f"item:{value}" for value in i},
        "recurring_terms": lambda s, i: {"recurring_terms"},
        "keyword_tags": lambda s, i: {"recurring_terms"},
        # Every slot draws its own section's prose, so two narrative_lists are
        # two different texts. This was the one reusable block under the old
        # rule and stays unclaimable under this one.
        "narrative_list": lambda s, i: set(),
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
# narrative_list draws from each slot's own section, so two of them show
# different text - the one block that may appear in more than one slot.
_REUSABLE_BLOCKS = {"narrative_list"}


def _coarse_key(candidate: str):
    """Fallback identity: the block id itself, i.e. claimed once report-wide."""
    return lambda synthesis, items: {candidate}


def _items_about(items: list[str], subject: str | None) -> list[str]:
    """Only the sentences whose subject matches what the slot is about."""
    if not subject:
        return items
    if subject == "organisation":
        return [item for item in items if leading_subject_kind(item) == "entity"]
    return [item for item in items if leading_subject_kind(item) != "entity"]


def _synthesis_items(synthesis: Any, fields: tuple[str, ...]) -> list[str]:
    return [
        value
        for field in fields
        for value in (getattr(synthesis, field, None) or [])
        if isinstance(value, str) and value.strip()
    ]


def slot_evidence_items(slot: Slot, synthesis: Any, report: Any) -> tuple[str | None, list[str]]:
    """The exact prose inputs `resolve_slots()` gives one slot.

    Exposed for diagnostics so a trace can observe the same evidence without
    reimplementing subject routing or section fallback rules.
    """
    section_id, items = _section_items(report, slot.sections)
    if not items:
        items = _synthesis_items(synthesis, slot.fields)
    return section_id, _items_about(items, slot.subject)


def block_data_supported(block_type: str, synthesis: Any, items: list[str]) -> bool:
    """Whether the evidence alone supports a block, before report-wide claims.

    This is diagnostic only. Final selection remains the two-pass algorithm
    in `resolve_slots()` and still accounts for prior ownership/duplication.
    """
    predicate = _availability().get(block_type)
    return predicate is not None and predicate(synthesis, items)


def resolve_slots(
    purpose_id: str | None,
    synthesis: Any,
    report: Any,
    question_answer_type: str | None = None,
    question: str | None = None,
    initial_drawn: frozenset[str] = frozenset(),
) -> list[ResolvedSlot]:
    """Fill each of the purpose's slots with the best block its data supports.

    `question` is optional and affects only *which* metrics a KPI grid would
    put on cards, which is what it reports having drawn. Without it the grid
    still reports a bounded set, just ranked by the evidence alone.

    `initial_drawn` seeds the report-wide dedup state with facts something
    *outside* this resolution pass already showed - today, the Executive
    Summary's headline figure, which renders before `resolve_slots()` ever
    runs (see `generic_dashboard.py`). Empty by default, which reproduces the
    old "nothing shown yet" behaviour exactly.
    """
    slots = slots_for(purpose_id, question_answer_type)
    availability = _availability()
    consumption = _consumption(question)
    claimed: set[str] = set()
    resolved: list[ResolvedSlot] = []
    # Every evidence identity anything on the page has drawn so far. Claiming
    # a *block type* once was never the same rule as showing a *fact* once:
    # the composition donut reached the page twice under two different block
    # ids, because `landscape` and `share_split` are different types drawing
    # the identical three percentages.
    #
    # This is carried to each slot rather than used to veto a block here.
    # Several block types honestly key on every metric label they might draw
    # from (a KPI grid ranks the whole series and shows six), so "every fact
    # is already drawn" is not a question this stage can answer without
    # over-rejecting - `kpi_grid` and `chart` would both disappear behind
    # whichever block happened to run first. The block itself subtracts, in
    # the one place that knows what it would actually put on screen.
    drawn: set[str] = set(initial_drawn)

    def keys_for(candidate: str, synthesis: Any, items: list[str]) -> set[str]:
        # Same facts + same shape is a repeat; same facts in another shape is
        # another question answered. A block with no declared family is its
        # own, so it still dedupes against itself and nothing else.
        family = _SHAPE_FAMILIES.get(candidate, candidate)
        raw = consumption.get(candidate, _coarse_key(candidate))(synthesis, items)
        return {qualified_key(family, key) for key in raw}

    def drawable(candidate: str, synthesis: Any, items: list[str]) -> bool:
        if candidate in claimed and candidate not in _REUSABLE_BLOCKS:
            return False
        predicate = availability.get(candidate)
        if predicate is None or not predicate(synthesis, items):
            return False
        # A block with nothing left to add is not a block, wherever the
        # facts were drawn. This is only safe because every entry in
        # `_consumption()` reports what its block *draws*: the first attempt
        # at this rule was reverted because `kpi_grid` claimed all 77 metrics
        # for the six it shows, so it swallowed the trend chart, and `chart`
        # claimed nine series for the three it plots. Blocks whose data
        # cannot be identified keep their coarse key, so for them this stays
        # the old claimed-once rule.
        keys = keys_for(candidate, synthesis, items)
        return not (keys and keys <= drawn)

    # Pass 1: every slot gets its lead block first. Composition must never
    # cost a later slot the block that answers it best - 원인 taking the
    # ranking bars as a companion left 영향, whose own first choice they were,
    # with prose. Leads are decided in skeleton order exactly as before, so
    # this pass reproduces the single-block behaviour verbatim.
    leads: list[tuple[Slot, str | None, str | None, list[str], frozenset[str]]] = []
    for slot in slots:
        section_id, items = slot_evidence_items(slot, synthesis, report)
        before = frozenset(drawn)
        lead = next(
            (c for c in slot.candidates if drawable(c, synthesis, items)), None
        )
        if lead is not None:
            claimed.add(lead)
            drawn |= keys_for(lead, synthesis, items)
        leads.append((slot, lead, section_id, items, before))

    # Pass 2: whatever is still unclaimed may join the slot it also fits, as
    # long as it shows facts nothing on the page has put on screen yet.
    for slot, lead, section_id, items, before in leads:
        chosen = [lead] if lead else []
        if lead:
            drawn_here = keys_for(lead, synthesis, items)
            for candidate in slot.candidates:
                if len(chosen) >= _MAX_BLOCKS_PER_SLOT:
                    break
                # The catch-all prose card is a fallback, not a second view,
                # so it never tags along behind a block that already answered.
                if candidate == "narrative_list" or not drawable(candidate, synthesis, items):
                    continue
                keys = keys_for(candidate, synthesis, items)
                # A companion whose every fact is already in this card is the
                # same data twice under one heading.
                if keys and keys <= drawn_here:
                    continue
                chosen.append(candidate)
                claimed.add(candidate)
                drawn_here |= keys
                drawn |= keys
        if not chosen and slot.optional:
            continue
        resolved.append(ResolvedSlot(
            slot=slot,
            block_types=tuple(chosen) or (LAST_RESORT,),
            section_id=section_id,
            items=items,
            drawn_before=before,
        ))
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
