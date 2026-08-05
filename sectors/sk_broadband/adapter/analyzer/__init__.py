"""SK Broadband sector analyzer."""

from __future__ import annotations

import json
import os
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
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "최대 5개. 시장 변화, 전략 영향, Risk, Opportunity, Action 중 근거가 있는 항목만 한국어로 작성.",
        },
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
        "relevant_to_question": {
            "type": "boolean",
            "description": (
                "이 문서 하나가 질문 전체에 답할 필요는 없다 — 여러 문서가 합쳐져 최종 리포트가 되므로, "
                "질문과 관련된 사실을 조금이라도 포함하면(부분적 근거라도) true. "
                "실제 주제가 질문과 무관한 경우(키워드만 겹치고 본문 내용은 다른 경우)에만 false."
            ),
        },
        "business_impact": {
            "type": "string",
            "description": "질문 관점에서 매출, 비용, 투자, 고객, 경쟁력, 운영 중 어떤 영향이 있는지. 근거 부족 시 빈 문자열.",
        },
        "risk": {
            "type": "string",
            "description": "문서에서 근거가 확인되는 위험 요인. 근거 부족 시 빈 문자열.",
        },
        "opportunity": {
            "type": "string",
            "description": "문서에서 근거가 확인되는 기회 요인. 근거 부족 시 빈 문자열.",
        },
        "strength": {
            "type": "string",
            "description": "문서에서 근거가 확인되는 강점(자사 역량·경쟁 우위). 근거 부족 시 빈 문자열.",
        },
        "weakness": {
            "type": "string",
            "description": "문서에서 근거가 확인되는 약점(자사 취약점). 근거 부족 시 빈 문자열.",
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
                },
                "required": ["entity", "criterion", "value", "level"],
                "additionalProperties": False,
            },
        },
        "recommended_actions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "전략기획팀이 확인, 검토, 준비 또는 실행해야 할 항목. 근거 부족 시 빈 배열.",
        },
        "monitoring_indicators": {
            "type": "array",
            "items": {"type": "string"},
            "description": "후속 모니터링 지표와 실제 대응 단계로 넘어갈 조건. 근거 부족 시 빈 배열.",
        },
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "각 전략 판단의 근거가 된 문서 내용 요약. 문서 전체 복사 금지.",
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
    "required": ["summary", "key_points", "sentiment", "relevant_to_question", "business_impact", "risk", "opportunity", "strength", "weakness", "metric_points", "comparison_points", "recommended_actions", "monitoring_indicators", "evidence", "action_level", "analysis_confidence"],
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


def _analyze_document(client: OpenAI, system_prompt: str, document: SourceDocument, question: str) -> DocumentAnalysis:
    user_content = json.dumps(
        {
            "question": question,
            "document": {
                "doc_id": document.doc_id,
                "source_id": document.source_id,
                "reliability_tier": document.reliability_tier,
                "title": document.title,
                "url": document.url,
                "published_at": document.published_at.isoformat() if document.published_at else None,
                "content": _trim_content(document.content),
            },
            "analysis_instruction": (
                "질문에 직접 관련된 사실만 사용해 SK Broadband 전략기획 관점의 시장 변화, 영향, "
                "Risk, Opportunity, Strength, Weakness, Action 신호를 추출하라. "
                f"{SWOT_COMPLETENESS_INSTRUCTION} "
                "문서에 수치와 시점이 함께 명시되어 있으면 metric_points로, 대상 간 비교 서술이 있으면 "
                "comparison_points로 추출하되 명시되지 않은 값은 추정하거나 계산하지 말 것. 특히 재무제표나 "
                "실적 표는 같은 항목이 3Q25/3Q24/2Q25처럼 여러 시점 컬럼으로 나란히 나오는 경우가 많으므로, "
                "한 시점만 뽑지 말고 같은 label로 시점마다 별도의 metric_point를 표에 있는 시점 수만큼 전부 추출하라."
            ),
        },
        ensure_ascii=False,
    )
    try:
        response = call_with_retry(lambda: client.chat.completions.create(
            model=_model(),
            max_tokens=1800,
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
        return DocumentAnalysis(
            doc_id=document.doc_id,
            summary=data["summary"],
            key_points=data["key_points"],
            sentiment=data["sentiment"],
            relevant_to_question=data["relevant_to_question"],
            business_impact=data.get("business_impact", ""),
            risk=data.get("risk", ""),
            opportunity=data.get("opportunity", ""),
            strength=data.get("strength", ""),
            weakness=data.get("weakness", ""),
            metric_points=data.get("metric_points", []),
            comparison_points=data.get("comparison_points", []),
            recommended_actions=data.get("recommended_actions", []),
            monitoring_indicators=data.get("monitoring_indicators", []),
            evidence=data.get("evidence", []),
            action_level=data.get("action_level", "insufficient_data"),
            analysis_confidence=data.get("analysis_confidence", "low"),
        )
    except (TypeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise PipelineStageError(stage=_STAGE, reason=f"analysis response for doc '{document.doc_id}' did not match the expected schema", detail=str(exc)) from exc


def analyze(source_documents: list[SourceDocument], question: str) -> list[DocumentAnalysis]:
    api_key = _api_key()
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"{_API_KEY_ENV_VAR} or {_FALLBACK_API_KEY_ENV_VAR} is not configured")
    client = OpenAI(api_key=api_key)
    system_prompt = _load_system_prompt()
    return [_analyze_document(client, system_prompt, document, question) for document in source_documents]
