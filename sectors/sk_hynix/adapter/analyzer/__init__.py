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

from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError

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
            "description": "1-3 sentence factual summary of the document, sourced only from its content",
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
    },
    "required": ["summary", "key_points", "sentiment"],
    "additionalProperties": False,
}


def _load_system_prompt() -> str:
    return "\n\n".join(
        [
            _GLOBAL_PROMPT_PATH.read_text(encoding="utf-8"),
            _SECTOR_PROMPT_PATH.read_text(encoding="utf-8"),
        ]
    )


def _analyze_document(client: OpenAI, system_prompt: str, document: SourceDocument) -> DocumentAnalysis:
    user_content = (
        f"Title: {document.title}\nURL: {document.url}\n\n{document.content}\n\n"
        "---\n"
        "위 문서가 영어 등 외국어라도, summary/key_points는 반드시 한국어로만 작성하세요."
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
    )


def analyze(source_documents: list[SourceDocument]) -> list[DocumentAnalysis]:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"template_only: {_API_KEY_ENV_VAR} is not configured",
        )

    client = OpenAI(api_key=api_key)
    system_prompt = _load_system_prompt()

    return [_analyze_document(client, system_prompt, document) for document in source_documents]
