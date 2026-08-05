"""SK Broadband sector analyzer."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from openai import OpenAI

from common.content_quality_validator import SWOT_COMPLETENESS_INSTRUCTION
from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from sources.openai_retry import call_with_retry

_API_KEY_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY"
_FALLBACK_API_KEY_ENV_VAR = "OPENAI_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_MODEL"
_DEFAULT_MODEL = "gpt-4o"
_MAX_CONTENT_CHARS = 12000
_STAGE = "sectors.sk_broadband.adapter.analyzer"

_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent
_GLOBAL_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "global_system_prompt.md"
_SECTOR_PROMPT_PATH = _SECTOR_ROOT / "prompts" / "system_prompt.md"

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "질문과 관련된 핵심 사실 요약. 한국어 1~3문장."},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
        "relevance_level": {
            "type": "string",
            "enum": ["direct", "partial", "background", "irrelevant"],
            "description": "direct=질문에 직접 답함, partial=일부 필요 증거를 제공, background=맥락만 제공, irrelevant=무관.",
        },
        "relevance_reason": {
            "type": "string",
            "description": "관련성 등급을 선택한 구체적인 이유. 문서에 없는 내용을 만들지 말 것.",
        },
        "grounded_claims": {
            "type": "array",
            "description": "질문에 답하는 핵심 주장과 이를 직접 뒷받침하는 원문 인용. 인용은 원문에 그대로 존재해야 함.",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string", "description": "문서 안에서 고유한 짧은 ID, 예: c1."},
                    "claim_type": {
                        "type": "string",
                        "enum": ["key_point", "business_impact", "risk", "opportunity", "strength", "weakness", "comparison", "action", "monitoring"],
                    },
                    "claim": {"type": "string"},
                    "evidence_quote": {"type": "string", "description": "원문에서 그대로 복사한 짧은 문장 또는 구절."},
                    "evidence_location": {"type": ["string", "null"], "description": "확인 가능한 경우 문단·절·표 위치, 아니면 null."},
                    "as_of_date": {"type": ["string", "null"], "description": "주장의 기준 시점이 명시된 경우 원문 표현, 아니면 null."},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["claim_id", "claim_type", "claim", "evidence_quote", "evidence_location", "as_of_date", "confidence"],
                "additionalProperties": False,
            },
        },
        "covered_information_needs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "이 문서가 질문에 관해 실제 근거를 제공하는 정보 항목.",
        },
        "metric_points": {
            "type": "array",
            "description": "문서에 명시된 수치+시점 쌍만 추출. 추정하거나 계산하지 말 것. 없으면 빈 배열.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "무엇을 나타내는 수치인지, 예: 'IPTV 가입자 수'"},
                    "period": {"type": "string", "description": "문서에 명시된 시점 그대로, 예: '2023년 2분기'"},
                    "value": {"type": "number"},
                    "unit": {"type": "string", "description": "예: '만 명', '억원'. 없으면 빈 문자열."},
                },
                "required": ["label", "period", "value", "unit"],
                "additionalProperties": False,
            },
        },
        "comparison_points": {
            "type": "array",
            "description": "문서에 명시된 대상 간 비교만 추출. level은 문서가 명시적으로 우열을 말할 때만 채우고 그 외엔 null. 없으면 빈 배열.",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "비교 대상, 예: 'KT'"},
                    "criterion": {"type": "string", "description": "비교 기준, 예: '요금제 가격'"},
                    "value": {"type": "string", "description": "문서에 명시된 값이나 서술, 예: '월 9,900원'"},
                    "level": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                    "evidence_claim_id": {"type": "string", "description": "claim_type=comparison인 grounded_claim의 claim_id."},
                },
                "required": ["entity", "criterion", "value", "level", "evidence_claim_id"],
                "additionalProperties": False,
            },
        },
        "action_level": {
            "type": "string",
            "enum": ["Monitor", "Review", "Prepare", "Act", "insufficient_data"],
            "description": "대응 수준. 근거가 부족하면 insufficient_data.",
        },
        "analysis_confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "문서 근거만 기준으로 한 분석 확신도.",
        },
    },
    "required": ["summary", "sentiment", "relevance_level", "relevance_reason", "grounded_claims", "covered_information_needs", "metric_points", "comparison_points", "action_level", "analysis_confidence"],
    "additionalProperties": False,
}


def _load_system_prompt() -> str:
    return "\n\n".join([
        _GLOBAL_PROMPT_PATH.read_text(encoding="utf-8"),
        _SECTOR_PROMPT_PATH.read_text(encoding="utf-8"),
    ])


def _api_key() -> str | None:
    return os.environ.get(_API_KEY_ENV_VAR) or os.environ.get(_FALLBACK_API_KEY_ENV_VAR)


def _model() -> str:
    return os.environ.get(_MODEL_ENV_VAR, _DEFAULT_MODEL)


def _trim_content(content: str | None) -> str:
    if not content:
        return ""
    if len(content) <= _MAX_CONTENT_CHARS:
        return content
    return content[:_MAX_CONTENT_CHARS] + "\n\n[본문이 길어 분석 입력에서 일부가 생략되었습니다.]"


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _verified_claims(data: dict, document: SourceDocument, analyzed_content: str) -> list[dict]:
    normalized_content = _normalized_text(analyzed_content)
    verified: list[dict] = []
    seen_claim_ids: set[str] = set()
    for claim in data.get("grounded_claims", []):
        claim_id = claim.get("claim_id", "")
        quote = claim.get("evidence_quote", "")
        if not claim_id or claim_id in seen_claim_ids:
            continue
        if not quote or _normalized_text(quote) not in normalized_content:
            continue
        seen_claim_ids.add(claim_id)
        verified.append({**claim, "source_url": document.url})
    return verified


def _number_is_in_content(value: float, content: str) -> bool:
    compact = content.replace(",", "")
    candidates = {str(value), f"{value:g}"}
    return any(re.search(rf"(?<![\d.]){re.escape(candidate)}(?![\d.])", compact) for candidate in candidates)


def _verified_metric_points(data: dict, analyzed_content: str) -> list[dict]:
    verified: list[dict] = []
    normalized_content = _normalized_text(analyzed_content)
    for point in data.get("metric_points", []):
        period = _normalized_text(str(point.get("period", "")))
        unit = _normalized_text(str(point.get("unit", "")))
        value = point.get("value")
        if not period or period not in normalized_content:
            continue
        if unit and unit not in normalized_content:
            continue
        if not isinstance(value, (int, float)) or not _number_is_in_content(float(value), analyzed_content):
            continue
        verified.append(point)
    return verified


def _verified_comparison_points(data: dict, grounded_claims: list[dict]) -> list[dict]:
    comparison_claim_ids = {
        claim["claim_id"] for claim in grounded_claims if claim["claim_type"] == "comparison"
    }
    return [
        point
        for point in data.get("comparison_points", [])
        if point.get("evidence_claim_id") in comparison_claim_ids
    ]


def _claim_texts(grounded_claims: list[dict], claim_type: str) -> list[str]:
    return [claim["claim"] for claim in grounded_claims if claim["claim_type"] == claim_type]


def _joined_claims(grounded_claims: list[dict], claim_type: str) -> str:
    return "; ".join(_claim_texts(grounded_claims, claim_type))


def _analyze_document(
    client: OpenAI,
    system_prompt: str,
    document: SourceDocument,
    question: str,
    information_needs: list[str],
) -> DocumentAnalysis:
    analyzed_content = _trim_content(document.content)
    user_content = json.dumps(
        {
            "question": question,
            "required_information_needs": information_needs,
            "document": {
                "doc_id": document.doc_id,
                "source_id": document.source_id,
                "reliability_tier": document.reliability_tier,
                "title": document.title,
                "url": document.url,
                "published_at": document.published_at.isoformat() if document.published_at else None,
                "content": analyzed_content,
            },
            "analysis_instruction": (
                "질문에 직접 관련된 사실만 사용해 SK Broadband 전략기획 관점의 시장 변화, 영향, "
                "Risk, Opportunity, Strength, Weakness, Action 신호를 추출하라. "
                f"{SWOT_COMPLETENESS_INSTRUCTION} "
                "문서에 수치와 시점이 함께 명시되어 있으면 metric_points로, 대상 간 비교 서술이 있으면 "
                "comparison_points로 추출하되 명시되지 않은 값은 추정하거나 계산하지 말 것. 특히 재무제표나 "
                "실적 표는 같은 항목이 3Q25/3Q24/2Q25처럼 여러 시점 컬럼으로 나란히 나오는 경우가 많으므로, "
                "한 시점만 뽑지 말고 같은 label로 시점마다 별도의 metric_point를 표에 있는 시점 수만큼 전부 추출하라. "
                "관련성은 direct/partial/background/irrelevant 중 하나로 분류하고 이유를 적어라. 질문에 답하는 모든 "
                "핵심 주장은 grounded_claims에 넣고, evidence_quote는 반드시 입력 document.content에서 짧게 그대로 복사하라. "
                "각 claim에는 용도에 맞는 claim_type을 지정하라. 위험·기회·비교·액션 등 전략 판단은 반드시 "
                "별도 grounded_claim으로 만들어라. comparison_points는 "
                "claim_type=comparison인 claim_id를 evidence_claim_id로 참조해야 한다. 문서가 충족한 정보는 반드시 "
                "required_information_needs에 주어진 문자열 중에서만 covered_information_needs로 선택하라. "
                "부족 항목은 코드가 동일한 기준 목록에서 계산한다."
            ),
        },
        ensure_ascii=False,
    )
    try:
        response = call_with_retry(lambda: client.chat.completions.create(
            model=_model(),
            max_tokens=3000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sk_broadband_document_analysis",
                    "schema": _ANALYSIS_SCHEMA,
                    "strict": True,
                },
            },
        ))
    except Exception as exc:  # noqa: BLE001
        raise PipelineStageError(stage=_STAGE, reason=f"analysis API call failed for doc '{document.doc_id}'", detail=str(exc)) from exc

    message = response.choices[0].message
    if getattr(message, "refusal", None):
        raise PipelineStageError(stage=_STAGE, reason=f"analysis refused for doc '{document.doc_id}'", detail=message.refusal)
    try:
        data = json.loads(message.content)
        grounded_claims = _verified_claims(data, document, analyzed_content)
        relevance_level = data["relevance_level"]
        relevant_to_question = relevance_level != "irrelevant"
        relevance_reason = data["relevance_reason"]
        raw_claim_count = len(data.get("grounded_claims", []))
        if not relevant_to_question:
            validation_status = "not_applicable"
            usable_for_synthesis = False
        elif not grounded_claims:
            validation_status = "insufficient_grounding"
            usable_for_synthesis = False
        elif len(grounded_claims) < raw_claim_count:
            validation_status = "partial_grounding"
            usable_for_synthesis = True
        else:
            validation_status = "verified"
            usable_for_synthesis = True
        requested_needs = list(dict.fromkeys(information_needs))
        reported_covered = set(data.get("covered_information_needs", []))
        covered_information_needs = [
            need for need in requested_needs if need in reported_covered
        ] if grounded_claims else []
        missing_information_needs = [
            need for need in requested_needs if need not in covered_information_needs
        ]
        action_claims = _claim_texts(grounded_claims, "action")
        return DocumentAnalysis(
            doc_id=document.doc_id,
            summary=data["summary"],
            sentiment=data["sentiment"],
            relevant_to_question=relevant_to_question,
            relevance_level=relevance_level,
            relevance_reason=relevance_reason,
            grounded_claims=grounded_claims,
            covered_information_needs=covered_information_needs,
            missing_information_needs=missing_information_needs,
            analysis_validation_status=validation_status,
            usable_for_synthesis=usable_for_synthesis,
            key_points=_claim_texts(grounded_claims, "key_point"),
            business_impact=_joined_claims(grounded_claims, "business_impact"),
            risk=_joined_claims(grounded_claims, "risk"),
            opportunity=_joined_claims(grounded_claims, "opportunity"),
            strength=_joined_claims(grounded_claims, "strength"),
            weakness=_joined_claims(grounded_claims, "weakness"),
            metric_points=_verified_metric_points(data, analyzed_content),
            comparison_points=_verified_comparison_points(data, grounded_claims),
            recommended_actions=action_claims,
            monitoring_indicators=_claim_texts(grounded_claims, "monitoring"),
            evidence=[claim["evidence_quote"] for claim in grounded_claims],
            action_level=data.get("action_level", "insufficient_data") if action_claims else "insufficient_data",
            analysis_confidence=data.get("analysis_confidence", "low"),
        )
    except (TypeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise PipelineStageError(stage=_STAGE, reason=f"analysis response for doc '{document.doc_id}' did not match the expected schema", detail=str(exc)) from exc


def analyze(
    source_documents: list[SourceDocument],
    question: str,
    information_needs: list[str] | None = None,
) -> list[DocumentAnalysis]:
    api_key = _api_key()
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"{_API_KEY_ENV_VAR} or {_FALLBACK_API_KEY_ENV_VAR} is not configured")
    client = OpenAI(api_key=api_key)
    system_prompt = _load_system_prompt()
    needs = list(information_needs or [])
    return [
        _analyze_document(client, system_prompt, document, question, needs)
        for document in source_documents
    ]
