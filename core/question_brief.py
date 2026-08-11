"""Question-first contract generation, optional AI refinement, and validation.

This module deliberately has no sector or renderer vocabulary.  It turns a
question into the answers a user requested and the evidence shapes needed to
support those answers; later stages decide collection and presentation.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from common.ai_client import openai_client_kwargs
from common.contracts import (
    AnswerFulfillment,
    EvidenceRequirement,
    QuestionBrief,
    QuestionContext,
    RequestedAnswer,
    TrendSynthesis,
)
from core.question_coverage import derive_question_coverage

_API_KEY_ENV = "TRENDSPARC_QUESTION_BRIEF_AI_API_KEY"
_FALLBACK_API_KEY_ENV = "TRENDSPARC_ENTITY_AI_API_KEY"
_MODEL_ENV = "TRENDSPARC_QUESTION_BRIEF_AI_MODEL"
_BASE_URL_ENV = "TRENDSPARC_QUESTION_BRIEF_AI_BASE_URL"
_FALLBACK_BASE_URL_ENV = "TRENDSPARC_ENTITY_AI_BASE_URL"
_FALLBACK_MODEL_ENV = "TRENDSPARC_ENTITY_AI_MODEL"
_ANSWER_TYPES = (
    "status", "compare", "trend", "cause", "issue_response", "recommend", "strategy",
    "impact", "case_study", "ranking", "driver", "pain_point", "causal_effect",
)
_BANNED_REQUIREMENT_TERMS = (
    "dashboard", "block", "kpi", "bar", "table", "chart", "timeline",
    "audience", "executive", "management", "practitioner", "external",
    "current_status", "future_business", "root_cause", "issue_response",
)
_ISSUE_RESPONSE_SIGNALS = ("이슈", "리스크", "위험", "대응", "조치", "issue", "risk", "response")
_CAUSE_SIGNALS = ("원인", "왜", "이유", "근본", "root cause", "why")
_STRATEGY_SIGNALS = (
    "미래", "향후", "중장기", "성장전략", "신사업", "진출", "투자", "사업기회",
    "사업 포트폴리오", "시장 확대", "신규 사업", "전략 방향", "roadmap", "portfolio",
)
_RECOMMEND_SIGNALS = (
    "추천", "뭐가 좋", "어떤 것을 선택", "어느 것이 적합", "무엇을 써야",
    "우선순위", "최적", "적합한", "선정", "골라",
)
_COMPARE_SIGNALS = ("비교", "대비", " vs ", "차이", "경쟁력")
_TREND_SIGNALS = ("추이", "변화", "지난", "최근", "연도별", "전망", "트렌드", "트랜드", "동향")
_IMPACT_SIGNALS = ("미치는 영향", "영향 분석", "영향")
_CASE_STUDY_SIGNALS = ("케이스", "사례", "레퍼런스", "벤치마크")
_RANKING_SIGNALS = ("인기 순위", "순위", "랭킹")
_DRIVER_SIGNALS = ("고려 요인", "결정 요인", "선택 요인", "가입 요인")
_PAIN_POINT_SIGNALS = ("페인 포인트", "불만", "장벽", "어려움")
_CAUSAL_EFFECT_SIGNALS = ("효과 분석", "유인 효과", "영향 효과", "효과")
_DIMENSION_PATTERNS = (
    ("연령층", ("연령층별", "연령대별", "세대별")),
    ("지역", ("지역별", "국내외", "국가별")),
    ("기간", ("최근", "지난", "연도별", "분기별", "월별")),
)
_ACTION_TERMS = {
    "recommend": ("추천", "선정", "골라", "선택"),
    "compare": ("비교", "대비", "차이"),
    "trend": ("추이", "변화"),
    "cause": ("원인", "이유"),
    "issue_response": ("대응", "조치"),
    "strategy": ("전략", "방향"),
}

_REFINEMENT_PROMPT = """You refine TrendSparC's QuestionBrief before evidence collection.

Your job is to improve the interpretation of a user's question while preserving its scope.
You do not answer the question, recommend a business action, invent a fact, create a metric,
cite a source, judge whether evidence exists, or choose a report or UI format.

You receive the original user question and a rule-based QuestionBrief draft. Return one valid
QuestionBrief JSON object only, conforming exactly to the supplied schema.

Rules:
1. Preserve explicit user requests and their separation. Every user-explicit requested answer in the draft must
remain represented as a distinct requested answer. If the draft already separates explicit deliverables, preserve
their answer IDs, answer types, question anchors, and order: do not merge them into a broader answer, duplicate
them, or move evidence from one answer to another. You may split one unsplit compound requested answer only when
every result is linked to a different explicit phrase in the original question; use `origin = ai_refined` and a
concise rationale for every split result. Preserve any user-stated selection criteria as criteria, not as a new
requested answer. Do not remove, replace, weaken, or retype an explicit user request unless correcting an
unambiguous rule-based parsing error while keeping the same original-question anchor. Do not add a requested
answer whose business goal, entity, comparison, time range, decision, or outcome was not explicitly requested or
necessarily implied.
2. Refine the evidence requirements for each preserved answer. Every evidence requirement must contain a valid `for_answer_id`
referencing its one requested answer. Do not copy, pool, or substitute requirements across distinct
answers. Every AI-derived or AI-refined evidence requirement must include a concise, concrete `rationale`. A derived
requirement may use terms absent from the question when they are plausible evidence patterns for that requested
answer. Set `derivation_type` to `semantic_inference` for a newly derived requirement. Treat acceptable evidence
patterns as alternatives, not mandatory metrics.
3. Keep scope intact. Do not add competitors, customer segments, countries, time periods, KPIs,
sources, business strategies, or decision goals unless explicitly required or strictly necessary
to interpret an explicit comparison. Do not use audience labels, report-purpose labels, report
section names, dashboard block names, or search-query wording as requested answers or evidence
requirements.
4. Keep answer shapes honest. A comparison or ranking requirement must name its compared subject, comparison
dimension, and whether a common basis is required; rankings need the same population, period, and measure. A trend
needs the same definition over multiple time points. A case study needs identifiable company, initiative, and timing.
A driver, impact, or causal-effect requirement needs evidence that directly links the stated condition to the stated
decision, impact, or effect; a pain point needs reported friction or a barrier. Do not imply rankings, scores,
numeric values, causal effects, or source material already exist.
5. Do not answer or assess fulfillment. Do not provide an answer, recommendation, action plan,
fact, number, source, citation, document reference, or evidence claim. Do not assign fulfilled,
partial, or unmet, and do not create, edit, or infer fulfillment fields. Fulfillment is determined
only after collection and deterministic evidence validation.
6. Preserve provenance. Preserve `origin = user_explicit` for explicit user requests. Use
`origin = ai_refined` only for a refined interpretation and `origin = derived` only for a new
evidence requirement. Every ai_refined or derived item must include `rationale`. Keep IDs stable
for untouched draft items and create new IDs only for genuinely new items.

Return JSON only."""


def _language(question: str) -> str:
    if re.search(r"[가-힣]", question):
        return "ko"
    if re.search(r"[A-Za-z]", question):
        return "en"
    return "other"


def classify_question_shapes(question: str) -> list[str]:
    """Classify only the answer form explicit in the original question.

    This deliberately does not inspect entity extraction, report purpose,
    audience, or sector metadata.  Those contracts have separate downstream
    jobs and must not decide what the user asked for.
    """
    terms = question.casefold()
    signal_groups = {
        "issue_response": _ISSUE_RESPONSE_SIGNALS,
        "cause": _CAUSE_SIGNALS,
        "recommend": _RECOMMEND_SIGNALS,
        "compare": _COMPARE_SIGNALS,
        "trend": _TREND_SIGNALS,
        "impact": _IMPACT_SIGNALS,
        "case_study": _CASE_STUDY_SIGNALS,
        "ranking": _RANKING_SIGNALS,
        "driver": _DRIVER_SIGNALS,
        "pain_point": _PAIN_POINT_SIGNALS,
        "causal_effect": _CAUSAL_EFFECT_SIGNALS,
        "strategy": _STRATEGY_SIGNALS,
    }
    found: list[tuple[int, str]] = []
    for answer_type, signals in signal_groups.items():
        positions = [terms.find(signal.casefold()) for signal in signals if terms.find(signal.casefold()) >= 0]
        if positions:
            found.append((min(positions), answer_type))
    found_types = {answer_type for _, answer_type in found}
    # "신규 사업 케이스" is a benchmark request, not a request for a new
    # strategy. A paired noun phrase plus a trend asks for a comparison even
    # when it omits the literal word "비교".
    if "case_study" in found_types:
        found = [(position, answer_type) for position, answer_type in found if answer_type != "strategy"]
    found_types = {answer_type for _, answer_type in found}
    if {"impact", "strategy"}.issubset(found_types):
        found = [(position, answer_type) for position, answer_type in found if answer_type != "issue_response"]
    if "trend" in found_types and re.search(r"[가-힣A-Za-z0-9]+(?:와|과)\s*[가-힣A-Za-z0-9]+", question):
        found.append((min(position for position, answer_type in found if answer_type == "trend"), "compare"))
    return list(dict.fromkeys(answer_type for _, answer_type in sorted(found))) or ["status"]


def classify_question_shape(question: str) -> str:
    """Compatibility helper returning the primary explicit answer shape."""
    return classify_question_shapes(question)[0]


def _dimensions(question: str) -> list[str]:
    return [
        dimension for dimension, signals in _DIMENSION_PATTERNS
        if any(signal in question for signal in signals)
    ]


def _selection_criteria_and_body(question: str) -> tuple[list[str], str]:
    """Split a direct Korean ``~에 맞는 <answer subject>`` qualifier.

    This is deliberately narrow. If the wording is not this explicit, keep
    the whole question as the subject rather than inventing a criterion.
    """
    match = re.search(r"^(?P<criterion>.+?)(?:에|을|를)\s*맞는\s+(?P<body>.+)$", question.strip())
    if not match:
        return [], question.strip()
    criterion = match.group("criterion").strip()
    body = match.group("body").strip()
    return ([criterion] if criterion and body else []), (body or question.strip())


def _shared_prefix(first: str, second: str) -> str:
    """Carry an explicit modifier from ``광고 매체 및 모델`` to the last item."""
    first_words = first.split()
    if len(first_words) < 2 or " " in second:
        return second
    return " ".join([*first_words[:-1], second])


def _parallel_requested_answers(question: str, answer_type: str) -> list[RequestedAnswer]:
    """Conservatively split an explicit ``A 및 B 추천/비교`` question.

    A split is emitted only when a known answer action follows a two-item
    parallel noun phrase. Everything else remains one answer for AI review.
    """
    action_terms = _ACTION_TERMS.get(answer_type, ())
    action = next((term for term in action_terms if term in question), None)
    if not action:
        return []
    criteria, body = _selection_criteria_and_body(question)
    match = re.search(
        r"(?P<before>.*?)(?P<first>[가-힣A-Za-z0-9][가-힣A-Za-z0-9 .+\-]*?)\s*"
        r"(?:및|와|과|/|,)\s*(?P<second>[가-힣A-Za-z0-9][가-힣A-Za-z0-9 .+\-]*?)\s*"
        + re.escape(action),
        body,
    )
    if not match:
        return []
    first = match.group("first").strip()
    second = match.group("second").strip()
    # A broad leading clause is context, not part of the subject.  The final
    # two words before the connector are the only stable generic noun phrase
    # boundary we can recover without sector vocabulary.
    first_words = first.split()
    if len(first_words) > 2:
        first = " ".join(first_words[-2:])
    second = _shared_prefix(first, second)
    if not first or not second or first == second:
        return []
    dimensions = _dimensions(question)
    first_anchor = " ".join([*( ["연령층별"] if "연령층" in dimensions and "연령층별" in question else []), first])
    if first_anchor not in question:
        first_anchor = first
    second_anchor = f"{match.group('second').strip()} {action}"
    if second_anchor not in question:
        second_anchor = match.group("second").strip()
    return [
        RequestedAnswer(
            answer_id="answer_1", question_anchor=first_anchor, answer_type=answer_type,
            subject=first, dimensions=dimensions, selection_criteria=criteria,
        ),
        RequestedAnswer(
            answer_id="answer_2", question_anchor=second_anchor, answer_type=answer_type,
            subject=second, dimensions=dimensions, selection_criteria=criteria,
        ),
    ]


def _composite_requested_answers(question: str, shapes: list[str]) -> list[RequestedAnswer]:
    """Split only explicit, known multi-deliverable Korean question forms."""
    normalized = question.strip()
    dimensions = _dimensions(normalized)
    patterns = (
        (
            {"impact", "strategy"},
            re.compile(
                r"(?P<impact>.+?(?:미치는\s+)?영향)\s*(?:과|와|및)\s*"
                r"(?P<strategy>.+?(?:대응\s*전략|대응\s*방안|중장기\s*전략|전략))$"
            ),
            (("impact", "impact"), ("strategy", "strategy")),
        ),
        (
            {"ranking", "trend"},
            re.compile(
                r"(?P<ranking>.+?(?:인기\s*순위|순위|랭킹))\s*(?:과|와|및)\s*"
                r"(?P<trend>.+?(?:트렌드|트랜드|추이|변화).*)$"
            ),
            (("ranking", "ranking"), ("trend", "trend")),
        ),
        (
            {"driver", "pain_point"},
            re.compile(
                r"(?P<driver>.+?(?:고려\s*요인|결정\s*요인|선택\s*요인|가입\s*요인))\s*(?:과|와|및)\s*"
                r"(?P<pain>.+?(?:페인\s*포인트|불만|장벽|어려움).*)$"
            ),
            (("driver", "driver"), ("pain", "pain_point")),
        ),
    )
    available = set(shapes)
    for required_shapes, pattern, fields in patterns:
        if not required_shapes.issubset(available):
            continue
        match = pattern.search(normalized)
        if not match:
            continue
        return [
            RequestedAnswer(
                answer_id=f"answer_{index}",
                question_anchor=match.group(group).strip(),
                answer_type=answer_type,
                subject=match.group(group).strip(),
                dimensions=dimensions,
            )
            for index, (group, answer_type) in enumerate(fields, start=1)
        ]
    return []


def _model() -> str:
    configured = os.getenv(_MODEL_ENV) or os.getenv(_FALLBACK_MODEL_ENV)
    if configured:
        return configured
    base_url = os.getenv(_BASE_URL_ENV) or os.getenv(_FALLBACK_BASE_URL_ENV) or ""
    return "solar-pro3" if "upstage.ai" in base_url.casefold() else "gpt-4o"


def _requirements_for(answer_type: str) -> list[tuple[str, str, bool, list[str]]]:
    mapping = {
        "status": [("status", "현재 상태", False, ["현재 상태를 확인할 수 있는 핵심 사실", "직접 확인된 수치"])],
        "compare": [("comparison", "동일 기준 비교", True, ["비교 대상별 동일 기준 값", "출처가 명시한 차이"])],
        "trend": [("trend", "동일 정의 시계열", True, ["동일 정의·단위의 복수 시점 값"])],
        "cause": [
            ("status", "현상 자체", False, ["관찰된 현상 근거"]),
            ("causal_link", "원인과 결과 연결", False, ["출처가 명시한 원인과 결과 연결"]),
        ],
        "issue_response": [
            ("status", "이슈와 현재 영향", False, ["이슈 사실관계", "현재 영향"]),
            ("action", "대응 선택 근거", False, ["선택지별 효과·제약 또는 위험 근거"]),
        ],
        "recommend": [
            ("comparison", "후보별 적합성", True, ["후보별 공통 선택 기준", "대상 또는 조건별 확인된 차이"]),
            ("action", "추천의 근거", False, ["추천 적합성·제약을 뒷받침하는 근거"]),
        ],
        "strategy": [
            ("status", "현재 위치와 변화", False, ["현재 위치", "시장 변화"]),
            ("risk", "기회와 위험", False, ["기회·필요 역량·위험 근거"]),
            ("action", "실행 선택", False, ["실행 선택의 근거", "확인 지표"]),
        ],
        "impact": [
            ("causal_link", "원인과 영향의 연결", False, ["출처가 원인과 영향을 직접 연결한 근거"]),
            ("outcome", "대상에 발생한 영향", False, ["산업·서비스·고객·운영·재무 영향"]),
        ],
        "case_study": [
            ("status", "사례의 추진 사실", False, ["기업·사업·시점이 확인되는 사례 사실"]),
            ("comparison", "사례 간 공통 비교 기준", True, ["동일 기준으로 비교 가능한 추진 방식·결과"]),
        ],
        "ranking": [
            ("comparison", "동일 기준 순위", True, ["동일 모집단·기간·측정 기준의 순위 또는 순서"]),
        ],
        "driver": [
            ("causal_link", "결정·가입 요인", False, ["대상자의 선택 또는 가입 결정에 연결된 요인"]),
        ],
        "pain_point": [
            ("risk", "불편·장벽", False, ["대상자가 직접 경험하거나 보고한 불편·장벽"]),
        ],
        "causal_effect": [
            ("causal_link", "조건과 효과의 연결", False, ["조건 또는 변화와 효과를 직접 연결한 근거"]),
            ("outcome", "효과의 방향 또는 규모", False, ["효과의 방향·크기·지속성에 관한 근거"]),
        ],
    }
    return mapping.get(answer_type, mapping["status"])


def _has_banned_requirement_vocabulary(text: str) -> bool:
    """Match renderer vocabulary as words, not inside legitimate evidence text.

    For example, ``bar`` is forbidden as a chart instruction but must not
    reject the evidence term ``barrier`` in a pain-point requirement.
    """
    normalized = text.casefold()
    return any(
        re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", normalized)
        for term in _BANNED_REQUIREMENT_TERMS
    )


def build_rule_based_question_brief(
    request_id: str,
    question: str,
) -> QuestionBrief:
    """Build the no-key baseline; it is intentionally conservative."""
    required_shapes = classify_question_shapes(question)
    normalized_type = required_shapes[0]
    coverage = derive_question_coverage(question)
    time_scope = (
        f"지난 {coverage.minimum_distinct_periods}년"
        if coverage.minimum_distinct_periods else None
    )
    geography_scope = " vs ".join(coverage.comparison_anchors) if len(coverage.comparison_anchors) >= 2 else None
    context = QuestionContext(
        question=question,
        language=_language(question),
        question_answer_type=normalized_type,
        required_answer_shapes=required_shapes,
        time_scope=time_scope,
        geography_scope=geography_scope,
        explicit_constraints=[
            *[value for value in ("비교", "연령층별", "기간", "지역") if value in question],
            *( ["복수 시점"] if coverage.minimum_distinct_periods else []),
            *( ["명시 비교축"] if len(coverage.comparison_anchors) >= 2 else []),
        ],
    )
    answers = _composite_requested_answers(question, required_shapes)
    if not answers:
        answers = _parallel_requested_answers(question, normalized_type)
    if not answers:
        answers = [RequestedAnswer(
            answer_id="answer_1",
            question_anchor=question.strip(),
            answer_type=normalized_type,
            subject=question.strip(),
            dimensions=_dimensions(question),
        )]
    requirements = [
        EvidenceRequirement(
            requirement_id=f"evidence_{answer_index}_{shape}_{requirement_index}",
            for_answer_id=answer.answer_id,
            kind=kind,
            semantic_target=target,
            comparison_dimension="comparison subject" if common_basis else None,
            common_basis_required=common_basis,
            acceptable_evidence_patterns=patterns,
        )
        for answer_index, answer in enumerate(answers, start=1)
        for shape in (
            [answer.answer_type]
            if len({item.answer_type for item in answers}) > 1
            else required_shapes
        )
        for requirement_index, (kind, target, common_basis, patterns) in enumerate(_requirements_for(shape), start=1)
    ]
    return QuestionBrief(
        request_id=request_id,
        question_context=context,
        requested_answers=answers,
        evidence_requirements=requirements,
    )


def validate_question_brief(candidate: QuestionBrief, draft: QuestionBrief) -> QuestionBrief:
    """Reject scope expansion and malformed AI refinements deterministically."""
    if candidate.request_id != draft.request_id:
        raise ValueError("request_id changed during QuestionBrief refinement")
    if candidate.question_context.question != draft.question_context.question:
        raise ValueError("original question changed during QuestionBrief refinement")
    if candidate.fulfillment:
        raise ValueError("fulfillment is forbidden before evidence collection")
    answer_ids = {answer.answer_id for answer in candidate.requested_answers}
    if not answer_ids:
        raise ValueError("QuestionBrief needs at least one requested answer")
    explicit_answers = [answer for answer in draft.requested_answers if answer.origin == "user_explicit"]
    if len(candidate.requested_answers) < len(explicit_answers):
        raise ValueError("AI merged explicit requested answers")
    preserved_candidate_ids: set[str] = set()
    for explicit in explicit_answers:
        direct_matches = [
            answer for answer in candidate.requested_answers
            if answer.answer_id not in preserved_candidate_ids
            and (answer.question_anchor == explicit.question_anchor
                 or explicit.question_anchor in answer.question_anchor)
        ]
        directly_preserved = bool(direct_matches)
        if directly_preserved:
            preserved_candidate_ids.add(direct_matches[0].answer_id)
        # A legitimate AI refinement may split one compound, explicit ask into
        # two anchored asks.  The rule draft is deliberately conservative and
        # often has the whole question as its sole anchor, so accept only a
        # real split (not a silent replacement) here.
        split_preserved = [
            answer for answer in candidate.requested_answers
            if answer.origin == "ai_refined"
            and answer.question_anchor in explicit.question_anchor
            and (answer.rationale or "").strip()
        ]
        if not directly_preserved and len(split_preserved) < 2:
            raise ValueError("AI removed an explicit requested answer")
        if explicit.selection_criteria and not any(
            set(explicit.selection_criteria).issubset(set(answer.selection_criteria))
            for answer in candidate.requested_answers
        ):
            raise ValueError("AI removed an explicit selection criterion")
    question_normalized = " ".join(candidate.question_context.question.casefold().split())
    for answer in candidate.requested_answers:
        anchor = " ".join(answer.question_anchor.casefold().split())
        if not anchor or anchor not in question_normalized:
            raise ValueError("requested answer is not anchored in the original question")
        if answer.origin == "ai_refined" and not (answer.rationale or "").strip():
            raise ValueError("AI-refined requested answer needs rationale")
        if any(
            " ".join(criterion.casefold().split()) not in question_normalized
            for criterion in answer.selection_criteria
        ):
            raise ValueError("selection criterion is not anchored in the original question")
    for requirement in candidate.evidence_requirements:
        if requirement.for_answer_id not in answer_ids:
            raise ValueError("evidence requirement references an unknown answer")
        if requirement.origin in {"ai_refined", "derived"} and not (requirement.rationale or "").strip():
            raise ValueError("AI-derived evidence requirement needs rationale")
        if requirement.origin == "derived" and requirement.derivation_type != "semantic_inference":
            raise ValueError("derived evidence requirement needs semantic_inference")
        text = " ".join([requirement.semantic_target, *requirement.acceptable_evidence_patterns]).casefold()
        if _has_banned_requirement_vocabulary(text):
            raise ValueError("renderer, audience, purpose, or query vocabulary leaked into evidence requirement")
        if requirement.kind == "comparison" and (
            not requirement.comparison_dimension or not requirement.common_basis_required
        ):
            raise ValueError("comparison requirement needs a common comparison basis")
    return candidate.model_copy(update={"refinement_mode": "ai_refined"})


def _schema() -> dict:
    # Pydantic's JSON schema is the contract, with fulfillment intentionally
    # constrained to an empty list during pre-collection refinement.
    schema = QuestionBrief.model_json_schema()
    schema["properties"]["fulfillment"] = {"type": "array", "maxItems": 0}
    # OpenAI strict JSON schemas require every object to reject undeclared
    # properties and list every property as required (nullable fields use an
    # explicit null union). Pydantic's normal schema is intentionally looser.
    def strictify(node: object) -> None:
        if not isinstance(node, dict):
            return
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
            for child in properties.values():
                strictify(child)
        for key in ("items", "additionalProperties"):
            strictify(node.get(key))
        for key in ("$defs", "anyOf", "allOf", "oneOf"):
            value = node.get(key)
            if isinstance(value, dict):
                for child in value.values():
                    strictify(child)
            elif isinstance(value, list):
                for child in value:
                    strictify(child)
    strictify(schema)
    return schema


def refine_question_brief_ai(draft: QuestionBrief) -> QuestionBrief:
    """Best-effort AI refinement; every failure returns the valid rule draft."""
    api_key = os.getenv(_API_KEY_ENV) or os.getenv(_FALLBACK_API_KEY_ENV)
    if not api_key:
        return draft
    try:
        from openai import OpenAI

        client_kwargs = openai_client_kwargs(_BASE_URL_ENV) or openai_client_kwargs(_FALLBACK_BASE_URL_ENV)
        client = OpenAI(api_key=api_key, **client_kwargs)
        response = client.chat.completions.create(
            model=_model(),
            temperature=0,
            max_tokens=1800,
            messages=[
                {"role": "system", "content": _REFINEMENT_PROMPT},
                {"role": "user", "content": json.dumps({
                    "original_question": draft.question_context.question,
                    "rule_based_draft": draft.model_dump(),
                }, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": {
                "name": "question_brief", "schema": _schema(), "strict": True,
            }},
        )
        message = response.choices[0].message
        if message.refusal:
            raise RuntimeError(message.refusal)
        return validate_question_brief(QuestionBrief.model_validate(json.loads(message.content)), draft)
    except Exception:
        return draft


def legacy_requirement_lists(brief: QuestionBrief) -> tuple[list[str], list[str]]:
    """Temporary adapter for consumers still expecting plain string lists."""
    answers = [answer.subject for answer in brief.requested_answers]
    evidence = [
        "; ".join([requirement.semantic_target, *requirement.acceptable_evidence_patterns])
        for requirement in brief.evidence_requirements
    ]
    return list(dict.fromkeys(answers)), list(dict.fromkeys(evidence))


def build_fulfillment(brief: QuestionBrief, synthesis: TrendSynthesis) -> QuestionBrief:
    """Evaluate each answer's own requirements against traced synthesis evidence.

    This is intentionally after synthesis and intentionally separate from
    renderer eligibility. It evaluates each answer's own requirements, but
    does not invent a semantic one-to-one claim-to-answer match: that would
    require an explicit answer-ID provenance field from earlier stages.
    """
    claims_by_type: dict[str, list] = defaultdict(list)
    for claim in synthesis.grounded_claims:
        claims_by_type[claim.claim_type].append(claim)

    def point_document_ids(point) -> list[str]:
        return list(dict.fromkeys([
            *point.supporting_doc_ids,
            *([point.doc_id] if point.doc_id else []),
        ]))

    def claim_document_ids(claims: list) -> list[str]:
        return list(dict.fromkeys([claim.doc_id for claim in claims if claim.doc_id]))

    def trend_points() -> list:
        grouped: dict[tuple, list] = defaultdict(list)
        for point in synthesis.metric_series:
            grouped[(
                point.label, point.subject, point.unit, point.share_of,
                point.is_relative, point.comparison_period,
            )].append(point)
        return [
            point for points in grouped.values()
            if len({point.period for point in points if point.period}) >= 2
            for point in points
        ]

    def comparable_points() -> list:
        grouped: dict[str, list] = defaultdict(list)
        for point in synthesis.comparison_points:
            if point.criterion:
                grouped[point.criterion.casefold().strip()].append(point)
        return [
            point for points in grouped.values()
            if len({point.entity.casefold().strip() for point in points if point.entity}) >= 2
            for point in points
        ]

    claim_types_by_requirement = {
        "status": {"key_point", "business_impact", "metric", "comparison"},
        "metric": {"metric"},
        "comparison": {"comparison"},
        "trend": {"metric"},
        "causal_link": {"factor"},
        "action": {"action"},
        "outcome": {"business_impact"},
        "risk": {"risk", "opportunity", "strength", "weakness"},
        "definition": {"key_point"},
    }
    fulfillments: list[AnswerFulfillment] = []
    for answer in brief.requested_answers:
        requirements = [item for item in brief.evidence_requirements if item.for_answer_id == answer.answer_id]
        supported: list[str] = []
        scoped_claims: list = []
        scoped_metrics: list = []
        scoped_comparisons: list = []
        for requirement in requirements:
            matched_metrics: list = []
            matched_comparisons: list = []
            matched_claims = [
                claim for claim_type in claim_types_by_requirement[requirement.kind]
                for claim in claims_by_type.get(claim_type, [])
            ]
            if requirement.kind == "metric":
                matched_metrics = list(synthesis.metric_series)
                present = bool(matched_metrics)
            elif requirement.kind == "comparison":
                matched_comparisons = comparable_points()
                present = bool(matched_comparisons)
            elif requirement.kind == "trend":
                matched_metrics = trend_points()
                present = bool(matched_metrics)
            elif requirement.kind == "causal_link":
                matched_claims = [
                    claim for claim in matched_claims if claim.parent_synthesis_claim_id
                ]
                present = bool(matched_claims)
            else:
                present = bool(matched_claims)
            if present:
                supported.append(requirement.requirement_id)
                scoped_claims.extend(matched_claims)
                scoped_metrics.extend(matched_metrics)
                scoped_comparisons.extend(matched_comparisons)
        missing = [item.requirement_id for item in requirements if item.requirement_id not in supported]
        status = "fulfilled" if requirements and not missing else "partial" if supported else "unmet"
        scoped_claims = list({claim.synthesis_claim_id: claim for claim in scoped_claims}.values())
        scoped_metrics = list({point.metric_id or id(point): point for point in scoped_metrics}.values())
        scoped_comparisons = list({point.comparison_id or id(point): point for point in scoped_comparisons}.values())
        document_ids = list(dict.fromkeys([
            *claim_document_ids(scoped_claims),
            *(doc_id for point in scoped_metrics for doc_id in point_document_ids(point)),
            *(doc_id for point in scoped_comparisons for doc_id in point_document_ids(point)),
        ]))
        fulfillments.append(AnswerFulfillment(
            for_answer_id=answer.answer_id,
            status=status,
            supported_requirement_ids=supported,
            missing_requirement_ids=missing,
            claim_ids=[claim.synthesis_claim_id for claim in scoped_claims],
            metric_ids=[point.metric_id for point in scoped_metrics if point.metric_id],
            comparison_ids=[point.comparison_id for point in scoped_comparisons if point.comparison_id],
            document_ids=document_ids,
            explanation=("검증된 synthesis 근거가 연결되었습니다." if status == "fulfilled" else
                         "일부 근거만 확인되었습니다." if status == "partial" else
                         "검증된 synthesis 근거를 확인하지 못했습니다."),
        ))
    return brief.model_copy(update={"fulfillment": fulfillments})
