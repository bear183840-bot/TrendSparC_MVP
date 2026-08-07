"""analyzer for the sk_hynix sector adapter.

Runs each validated SourceDocument through sectors/sk_hynix/prompts/system_prompt.md
(layered on prompts/global_system_prompt.md) via the OpenAI API, using structured
outputs (Structured Outputs / strict JSON schema) so every response is a
schema-valid DocumentAnalysis payload. No document is analyzed without a real
API response — a missing key, refusal, or API failure surfaces as a
PipelineStageError, never fabricated analysis.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from common.content_quality_validator import (
    COMPARISON_COMPLETENESS_INSTRUCTION,
    SWOT_COMPLETENESS_INSTRUCTION,
)
from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from sources.openai_retry import call_with_retry

_API_KEY_ENV_VAR = "TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY"
_MODEL = "gpt-4o"  # adjust to whichever OpenAI model the paid key should use
_STAGE = "sectors.sk_hynix.adapter.analyzer"

_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent
_GLOBAL_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "global_system_prompt.md"
_SECTOR_PROMPT_PATH = _SECTOR_ROOT / "prompts" / "system_prompt.md"

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1-3 sentence factual summary of the document, written in relation to the original question, sourced only from its content",
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only points tied to an angle explicitly mentioned in the document — never inferred",
        },
        "sentiment": {
            "type": "string",
            "enum": ["positive", "neutral", "negative", "mixed"],
        },
        "relevant_to_question": {
            "type": "boolean",
            "description": "true if this document contains ANY fact that meaningfully informs the answer, even partial evidence — it does not need to fully answer the question by itself, since multiple documents combine into one report. false only if it's genuinely off-topic (its actual subject differs from the question, not just sharing a keyword)",
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
    return "\n\n".join(
        [
            _GLOBAL_PROMPT_PATH.read_text(encoding="utf-8"),
            _SECTOR_PROMPT_PATH.read_text(encoding="utf-8"),
        ]
    )


def _analyze_document(client: OpenAI, system_prompt: str, document: SourceDocument, question: str) -> DocumentAnalysis:
    user_content = (
        f"조사 중인 질문: {question}\n\n"
        f"Title: {document.title}\nURL: {document.url}\n\n{document.content}\n\n"
        "---\n"
        "위 문서가 영어 등 외국어라도, summary/key_points는 반드시 한국어로만 작성하세요. "
        "summary/key_points는 위 질문과 어떻게 관련되는지를 기준으로 작성하고, "
        "이 문서 하나가 질문 전체에 답할 필요는 없습니다 — 여러 문서가 합쳐져 최종 리포트가 되므로, "
        "질문과 관련된 사실을 조금이라도 포함하면(부분적 근거라도) relevant_to_question을 true로 판단하고, "
        "실제 주제가 질문과 무관한 경우(키워드만 겹치고 본문 내용은 다른 경우)에만 false로 판단하세요. "
        f"{SWOT_COMPLETENESS_INSTRUCTION} "
        f"{COMPARISON_COMPLETENESS_INSTRUCTION} "
        "문서에 수치와 시점이 함께 명시되어 있으면(예: '2023년 매출 500억원') "
        "metric_points에 그대로 추출하고, 두 대상을 비교하는 서술이 있으면(예: 'A사가 B사보다 저렴하다') "
        "comparison_points에 추출하세요. 단, 문서에 명시되지 않은 값은 추정하거나 계산하지 마세요. "
        "특히 재무제표나 실적 표에는 같은 항목이 3Q25/3Q24/2Q25처럼 여러 시점 컬럼으로 나란히 나오는 경우가 많습니다 — "
        "이런 표를 보면 절대 한 시점만 뽑지 말고, 같은 label로 시점(period)마다 별도의 metric_point를 하나씩 만들어 "
        "표에 있는 시점 수만큼 전부 추출하세요(예: 매출 3Q25/3Q24/2Q25 세 값이 있으면 metric_point 3개)."
    )

    try:
        response = call_with_retry(lambda: client.chat.completions.create(
            model=_MODEL,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "document_analysis",
                    "schema": _ANALYSIS_SCHEMA,
                    "strict": True,
                },
            },
        ))
    except Exception as exc:  # OpenAI API/network failure, not a template_only case
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis API call failed for doc '{document.doc_id}'",
            detail=str(exc),
        ) from exc

    message = response.choices[0].message
    if message.refusal:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis refused for doc '{document.doc_id}'",
            detail=message.refusal,
        )

    try:
        data = json.loads(message.content)
        summary = data["summary"]
        key_points = data["key_points"]
        sentiment = data["sentiment"]
        relevant_to_question = data["relevant_to_question"]
        business_impact = data["business_impact"]
        risk = data["risk"]
        opportunity = data["opportunity"]
        strength = data["strength"]
        weakness = data["weakness"]
        metric_points = data["metric_points"]
        comparison_points = data["comparison_points"]
        recommended_actions = data["recommended_actions"]
        monitoring_indicators = data["monitoring_indicators"]
        evidence = data["evidence"]
        action_level = data["action_level"]
        analysis_confidence = data["analysis_confidence"]
    except (TypeError, json.JSONDecodeError, KeyError) as exc:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis response for doc '{document.doc_id}' did not match the expected schema",
            detail=str(exc),
        ) from exc

    return DocumentAnalysis(
        doc_id=document.doc_id,
        summary=summary,
        key_points=key_points,
        sentiment=sentiment,
        relevant_to_question=relevant_to_question,
        business_impact=business_impact,
        risk=risk,
        opportunity=opportunity,
        strength=strength,
        weakness=weakness,
        metric_points=metric_points,
        comparison_points=comparison_points,
        recommended_actions=recommended_actions,
        monitoring_indicators=monitoring_indicators,
        evidence=evidence,
        action_level=action_level,
        analysis_confidence=analysis_confidence,
    )


def analyze(
    source_documents: list[SourceDocument],
    question: str,
    information_needs: list[str] | None = None,
) -> list[DocumentAnalysis]:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"template_only: {_API_KEY_ENV_VAR} is not configured",
        )

    client = OpenAI(api_key=api_key)
    system_prompt = _load_system_prompt()

    return [_analyze_document(client, system_prompt, document, question) for document in source_documents]
