"""Classifies a question into one of 4 "question types" for query-generation
purposes - Troubleshooting / Navigating / Investigating / Sensing.

This is a THIRD axis, distinct from the two the rest of the pipeline already
has:

- `core/report_purpose/classifier.py`'s `purpose_id` (4 values) answers "what
  kind of REPORT should be built?" and is computed upstream, before
  source_planner ever runs.
- That same module's `question_answer_type` (7 values) answers "what SHAPE
  does the final written answer take?" and only feeds
  `common/purpose_slots.py`'s post-synthesis report layout - zero connection
  to search.
- This module's `question_type` (Troubleshooting/Navigating/Investigating/
  Sensing) answers "what kind of SEARCH ANGLES does this question need?" and
  is used only by sources/collectors/source_router's own query-generation
  prompt assembly (see planner.py's `_assemble_system_prompt`). Nothing else
  in the pipeline consumes it, so it is classified locally here rather than
  threaded through common/contracts.py like the other two.

Rule-based only (1st pass), matching this codebase's established "1st-pass
rule-based -> 2nd-pass AI-based, silent fallback" convention (see
core/entity/{extractor.py,ai_based.py}, core/synthesis/{synthesizer.py,
ai_based.py}, and CLAUDE.md). An AI-based 2nd pass
(question_type_ai_based.py) is deliberately deferred until live testing on
real questions shows this rule-based pass genuinely can't resolve some of
them - see the design plan. The confidence this function returns is exactly
what would gate that future AI pass, and today gates
planner.py's `_pick_branch_ids()` fallback (send every question-type branch
instead of just one) the same way `purpose_confidence` already does for
`purpose_id`.

The keyword lists, weighting scheme (strong_phrase=4 / pattern=3 / word=1),
and the confidence-gap thresholds below were supplied by the user (not
authored by this module) — see 질문유형_1차_Python_분류_대표단어_표현.md.
"""

from __future__ import annotations

import re

QUESTION_TYPE_IDS: tuple[str, ...] = ("troubleshooting", "navigating", "investigating", "sensing")

# 이미 발생했거나 예상되는 문제·위기·리스크를 해결하거나 방어하기 위한
# 대응책을 찾는 질문 (예: "중앙그룹 회생 사태에 따른 IPTV사의 대응 방안").
_STRONG_PHRASES: dict[str, tuple[str, ...]] = {
    "troubleshooting": (
        "대응 방안", "대응방안", "대응 전략", "대응전략", "해결 방안", "해결방안",
        "해결책", "대처 방안", "대처방안", "리스크 대응", "위기 대응", "위기관리",
        "리스크 관리", "리스크 완화", "피해 최소화", "영향 최소화", "방어 전략",
        "회복 전략", "극복 방안", "개선 방안", "문제 해결",
    ),
    # 미래에 어떤 방향으로 움직이거나 무엇을 선택해야 하는지를 결정하기 위한
    # 질문 - 추천, 벤치마킹, 사례/레퍼런스 탐색, 후보 선택이 강한 신호
    # (예: "SK브로드밴드 브랜드 이미지 개선에 맞는 연령층별 광고 매체 및
    # 모델 추천").
    "navigating": (
        "추천해줘", "추천", "적합한", "가장 적합", "우선순위", "선정", "선택",
        "어떤 것이 좋은", "어떤 게 좋은", "방향 설정", "추진 방향", "전략 방향",
        "향후 방향", "성장 방향", "사업 방향", "신규 사업", "사업 기회",
        "벤치마킹", "레퍼런스", "성공 사례", "해외 사례", "사례 조사",
        "추진 사례", "적용 사례",
    ),
    # 특정 현상·행동·결과가 왜 발생했는지, 어떤 요인이 영향을 미치는지,
    # 어떤 효과를 가지는지를 파악하려는 질문 (예: "2030 1인 가구의 유선
    # 인터넷 가입 고려 요인 및 페인 포인트").
    "investigating": (
        "원인 분석", "원인 규명", "영향 분석", "효과 분석", "요인 분석",
        "영향 요인", "결정 요인", "고려 요인", "선택 요인", "가입 요인",
        "구매 요인", "페인 포인트", "페인포인트", "상관관계", "인과관계",
        "가입 유인", "구매 유인", "이탈 요인", "영향을 미치는 요인",
    ),
    # 시장·산업·소비자·기술 등이 현재 어떤 상태인지, 과거부터 어떻게
    # 변해 왔는지, 어떤 트렌드가 나타나는지를 파악하려는 질문 (예: "지난
    # 5년간 OTT 생태계의 변화 추이").
    "sensing": (
        "시장 현황", "산업 현황", "이용 현황", "가입자 현황", "변화 추이",
        "시장 변화", "트렌드 분석", "시장 트렌드", "소비 트렌드", "이용 트렌드",
        "시청 트렌드", "최근 동향", "시장 동향", "산업 동향", "변화 양상",
        "이용률", "보급률", "점유율 추이", "인기 순위", "시장 규모",
    ),
}

_GENERAL_WORDS: dict[str, tuple[str, ...]] = {
    "troubleshooting": (
        "대응", "대처", "해결", "위기", "리스크", "위험", "문제", "방어",
        "완화", "회복", "극복", "피해", "악화", "차질", "위협",
    ),
    "navigating": (
        "추천", "선택", "선정", "후보", "우선순위", "방향", "기회", "대안",
        "옵션", "사례", "레퍼런스", "벤치마킹", "추진", "진출", "확장", "신사업",
    ),
    "investigating": (
        "원인", "이유", "요인", "영향", "효과", "관계", "상관", "인과", "유인",
        "동기", "페인포인트", "페인 포인트", "고려", "결정", "이탈", "선택 이유",
    ),
    "sensing": (
        "현황", "트렌드", "동향", "추이", "변화", "증가", "감소", "성장",
        "시장규모", "시장 규모", "이용률", "보급률", "점유율", "순위", "인기",
        "소비", "시청",
    ),
}

_RAW_PATTERNS: dict[str, tuple[str, ...]] = {
    "troubleshooting": (
        r".+에\s*어떻게\s*대응", r".+에\s*대한\s*대응", r".+을\s*해결.+방법",
        r".+을\s*극복.+방안", r".+리스크.+대응", r".+위기.+전략",
        r".+문제.+해결", r".+영향.+줄이", r".+피해.+최소화",
    ),
    "navigating": (
        r".+추천", r".+중\s*어떤", r".+중\s*무엇", r".+가장\s*적합",
        r".+우선순위", r".+선정", r".+선택", r".+사례.+레퍼런스",
        r".+벤치마킹", r".+어떤\s*방향", r".+추진.+사례",
    ),
    "investigating": (
        r"왜\s*.+", r".+이유", r".+원인", r".+요인", r".+에\s*미치는\s*영향",
        r".+에\s*따른\s*효과", r".+효과.+분석", r".+영향.+분석",
        r".+고려.+요인", r".+결정.+요인", r".+유인.+효과",
    ),
    "sensing": (
        r"최근.+동향", r"최근.+트렌드", r".+변화\s*추이", r".+이용률",
        r".+보급률", r".+점유율", r".+시장\s*규모", r".+인기\s*순위",
        r".+연도별.+변화", r".+지난\s*\d+년.+변화",
    ),
}
_COMPILED_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    type_id: tuple(re.compile(pattern) for pattern in patterns)
    for type_id, patterns in _RAW_PATTERNS.items()
}

# Weighting scheme: a 2-3 word strong phrase is a far more reliable signal
# than any single word alone (a bare "전략"/"영향" appears across all four
# types) - see the module docstring's source doc for the "대응 전략" vs
# "성장 전략" vs "경쟁사 전략 분석" example this is meant to disambiguate.
_WEIGHT = {"strong_phrase": 4, "pattern": 3, "word": 1}


def _score_question(question: str) -> dict[str, int]:
    scores = {type_id: 0 for type_id in QUESTION_TYPE_IDS}
    for type_id in QUESTION_TYPE_IDS:
        for phrase in _STRONG_PHRASES[type_id]:
            if phrase in question:
                scores[type_id] += _WEIGHT["strong_phrase"]
        for pattern in _COMPILED_PATTERNS[type_id]:
            if pattern.search(question):
                scores[type_id] += _WEIGHT["pattern"]
        for word in _GENERAL_WORDS[type_id]:
            if word in question:
                scores[type_id] += _WEIGHT["word"]
    return scores


def classify_question_type(question: str | None) -> tuple[str | None, str]:
    """Rule-based classification into one of QUESTION_TYPE_IDS.

    Returns `(question_type, confidence)`. `confidence` is "low" whenever
    this result shouldn't be trusted alone - planner.py's `_pick_branch_ids`
    then falls back to sending every question-type branch, exactly like it
    already does for a low-confidence `purpose_id`. Per the source
    material's own worked example: what matters most is not the absolute
    top score but the GAP between the top two candidates (a close race means
    the question genuinely mixes signals, e.g. "칩플레이션이 셋톱박스
    업계에 미치는 영향과 IPTV사의 중장기 대응 전략" scores meaningfully on
    both investigating and troubleshooting).

    `question_type` is None only when literally no signal matched anything
    (all four scores are 0) - there is no forced default the way
    `classify_report_purpose()` has one, because unlike `purpose_id` nothing
    downstream requires this axis to always resolve to a concrete value;
    "no idea, send every branch" is a fully valid, intended outcome here.
    """
    if not question or not question.strip():
        return None, "low"
    scores = _score_question(question)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = ranked[0]
    second_score = ranked[1][1]
    if top_score == 0:
        return None, "low"
    gap = top_score - second_score
    if top_score < 4 or gap <= 2:
        return top_type, "low"
    return top_type, "high"
