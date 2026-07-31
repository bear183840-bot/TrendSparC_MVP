"""analyzer for the sk_telecom sector adapter.

Runs each validated SourceDocument through sectors/sk_telecom/prompts/system_prompt.md
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

from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError

# SK텔레콤 전용 환경변수 및 스테이지 설정
_API_KEY_ENV_VAR = "TRENDSPARC_SK_TELECOM_ANALYZER_API_KEY"
_MODEL = "gpt-4o"  # 필요 시 사용 중인 OpenAI 모델로 변경 가능
_STAGE = "sectors.sk_telecom.adapter.analyzer"

# SK텔레콤 디렉토리 구조 반영
_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent
_GLOBAL_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "global_system_prompt.md"
_SECTOR_PROMPT_PATH = _SECTOR_ROOT / "prompts" / "system_prompt.md"

# SK텔레콤 사업 영역(5G/6G, AI 서비스, AI 데이터센터, 알뜰폰·요금제 등) 분석에 최적화된 스키마
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1-3 sentence factual summary of the document regarding SK Telecom's business, technology, or market context, written in relation to the original question, sourced only from its content",
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key factual points tied to specific business or technological angles explicitly mentioned in the document — never inferred",
        },
        "sentiment": {
            "type": "string",
            "enum": ["positive", "neutral", "negative", "mixed"],
        },
        "relevant_to_question": {
            "type": "boolean",
            "description": "true only if this document's content actually addresses the original question above — false if it's off-topic or only superficially shares a keyword with it",
        },
    },
    "required": ["summary", "key_points", "sentiment", "relevant_to_question"],
    "additionalProperties": False,
}


def _load_system_prompt() -> str:
    """글로벌 프롬프트와 SK텔레콤 섹터 전용 프롬프트를 결합하여 로드합니다."""
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
        "이 문서가 실제로 질문에 답이 되는 내용인지 relevant_to_question에 정직하게 판단하세요."
    )

    try:
        response = client.chat.completions.create(
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
        )
    except Exception as exc:  # API/네트워크 실패 시 예외 처리
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
    )


def analyze(source_documents: list[SourceDocument], question: str) -> list[DocumentAnalysis]:
    """입력된 SK텔레콤 관련 문서 목록을 분석하여 DocumentAnalysis 리스트로 반환합니다."""
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"template_only: {_API_KEY_ENV_VAR} is not configured",
        )

    client = OpenAI(api_key=api_key)
    system_prompt = _load_system_prompt()

    return [_analyze_document(client, system_prompt, document, question) for document in source_documents]
