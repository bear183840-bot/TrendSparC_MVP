"""analyzer for the sk_hynix sector adapter.

Runs each validated SourceDocument through sectors/sk_hynix/prompts/system_prompt.md
(layered on prompts/global_system_prompt.md) via the Claude API, using structured
outputs so every response is a schema-valid DocumentAnalysis payload. No document
is analyzed without a real API response — a missing key, refusal, or API failure
surfaces as a PipelineStageError, never fabricated analysis.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError

_API_KEY_ENV_VAR = "TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY"
_MODEL = "claude-opus-5"
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


def _analyze_document(
    client: anthropic.Anthropic, system_prompt: str, document: SourceDocument
) -> DocumentAnalysis:
    user_content = f"Title: {document.title}\nURL: {document.url}\n\n{document.content}"

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=system_prompt,
            output_config={"format": {"type": "json_schema", "schema": _ANALYSIS_SCHEMA}},
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:  # Claude API/network failure, not a template_only case
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis API call failed for doc '{document.doc_id}'",
            detail=str(exc),
        ) from exc

    if response.stop_reason == "refusal":
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis refused for doc '{document.doc_id}'",
            detail=str(response.stop_details),
        )

    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return DocumentAnalysis(
        doc_id=document.doc_id,
        summary=data["summary"],
        key_points=data["key_points"],
        sentiment=data["sentiment"],
    )


def analyze(source_documents: list[SourceDocument]) -> list[DocumentAnalysis]:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"template_only: {_API_KEY_ENV_VAR} is not configured",
        )

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = _load_system_prompt()

    return [_analyze_document(client, system_prompt, document) for document in source_documents]
