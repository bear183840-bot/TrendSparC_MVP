"""Question-aware analyzer for sector-unspecified documents and attachments."""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from sources.openai_retry import call_with_retry

_API_KEY_ENV_VAR = "TRENDSPARC_GENERAL_ANALYZER_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_GENERAL_ANALYZER_MODEL"
_STAGE = "sectors.general.adapter.analyzer"
_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent

_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "description": "Question-relevant factual summary."},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
        "relevant_to_question": {"type": "boolean"},
        "business_impact": {"type": "string", "description": "Supported impact; empty when unsupported."},
        "risk": {"type": "string", "description": "Supported risk; empty when unsupported."},
        "opportunity": {"type": "string", "description": "Supported opportunity; empty when unsupported."},
        "strength": {"type": "string", "description": "Supported strength/competitive edge; empty when unsupported."},
        "weakness": {"type": "string", "description": "Supported weakness; empty when unsupported."},
        "metric_points": {
            "type": "array",
            "description": "Only numeric value+period pairs explicitly stated in the document. Never estimate or calculate. Empty array when none.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "period": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                },
                "required": ["label", "period", "value", "unit"],
                "additionalProperties": False,
            },
        },
        "comparison_points": {
            "type": "array",
            "description": "Only explicit comparisons stated in the document. `level` only when the document itself states a ranking, otherwise null. Empty array when none.",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "criterion": {"type": "string"},
                    "value": {"type": "string"},
                    "level": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                },
                "required": ["entity", "criterion", "value", "level"],
                "additionalProperties": False,
            },
        },
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
        "monitoring_indicators": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "action_level": {
            "type": "string",
            "enum": ["Monitor", "Review", "Prepare", "Act", "insufficient_data"],
        },
        "analysis_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": [
        "summary", "key_points", "sentiment", "relevant_to_question", "business_impact",
        "risk", "opportunity", "strength", "weakness", "metric_points", "comparison_points",
        "recommended_actions", "monitoring_indicators", "evidence",
        "action_level", "analysis_confidence",
    ],
}


def _system_prompt() -> str:
    return "\n\n".join(
        [
            (_PROJECT_ROOT / "prompts" / "global_system_prompt.md").read_text(encoding="utf-8"),
            (_SECTOR_ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8"),
        ]
    )


def _analyze(client: OpenAI, prompt: str, document: SourceDocument, question: str) -> DocumentAnalysis:
    try:
        response = call_with_retry(lambda: client.chat.completions.create(
            model=os.getenv(_MODEL_ENV_VAR, "gpt-4o-mini"),
            max_tokens=4096,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Original question: {question}\n\nTitle: {document.title}\n"
                        f"URL: {document.url or 'local attachment'}\n\n{document.content or ''}\n\n"
                        "Judge relevance to the original question: mark relevant_to_question true if this "
                        "document contains ANY fact that meaningfully informs the answer, even partial "
                        "evidence — it does not need to fully answer the question by itself, since multiple "
                        "documents combine into one report. Mark it false only when the document is "
                        "genuinely off-topic (its actual subject differs from the question, not just "
                        "sharing a keyword). Use only this document, leave unsupported "
                        "strategy fields empty, and write in the question's language. Fill strength/weakness "
                        "whenever the document supports them, same as risk/opportunity — do not skip them, and "
                        "actively look for both sides rather than defaulting to only filling strength while "
                        "weakness stays empty every time (or vice versa). "
                        "Extract metric_points only for numbers explicitly tied to a stated period, and "
                        "comparison_points only for explicit comparisons between named entities — never "
                        "estimate or calculate a value the document doesn't state. Financial tables commonly "
                        "show the same line item across several period columns side by side (e.g. 3Q25/3Q24/"
                        "2Q25) — when you see that pattern, extract every period as its own metric_point with "
                        "the same label, not just one."
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "document_analysis", "schema": _ANALYSIS_SCHEMA, "strict": True},
            },
        ))
        message = response.choices[0].message
        if message.refusal:
            raise ValueError(message.refusal)
        return DocumentAnalysis(doc_id=document.doc_id, **json.loads(message.content))
    except Exception as exc:
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis failed for doc '{document.doc_id}'",
            detail=str(exc),
        ) from exc


def analyze(
    source_documents: list[SourceDocument],
    question: str,
    information_needs: list[str] | None = None,
) -> list[DocumentAnalysis]:
    api_key = os.getenv(_API_KEY_ENV_VAR) or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"template_only: {_API_KEY_ENV_VAR} is not configured")
    client = OpenAI(api_key=api_key)
    prompt = _system_prompt()
    return [_analyze(client, prompt, document, question) for document in source_documents]
