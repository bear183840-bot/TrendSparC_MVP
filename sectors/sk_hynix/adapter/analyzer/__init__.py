"""Evidence-grounded analyzer for the SK hynix sector."""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from common.ai_client import openai_client_kwargs
from common.analyzer_quality import (
    filter_points_by_verified_claim,
    split_content,
    split_evidence_passages,
    verify_claim_quotes,
)
from common.content_quality_validator import (
    COMPARISON_COMPLETENESS_INSTRUCTION,
    RELATIVE_METRIC_EXTRACTION_INSTRUCTION,
    SWOT_COMPLETENESS_INSTRUCTION,
    TABLE_COMPLETENESS_INSTRUCTION,
)
from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from sources.openai_retry import call_with_truncation_retry

_API_KEY_ENV_VAR = "TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY"
_BASE_URL_ENV_VAR = "TRENDSPARC_SK_HYNIX_ANALYZER_BASE_URL"
_MODEL = "gpt-4o"
_STAGE = "sectors.sk_hynix.adapter.analyzer"
_ANALYSIS_MAX_TOKENS = 4_500
_ANALYSIS_MAX_TOKENS_ESCALATED = 7_000
_MAX_CLAIMS_PER_CALL = 20
_MAX_METRIC_POINTS_PER_CALL = 16
_MAX_COMPARISON_POINTS_PER_CALL = 8

_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent
_ANALYZER_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "analyzer_system_prompt.md"
_SECTOR_PROMPT_PATH = _SECTOR_ROOT / "prompts" / "analyzer_prompt.md"

_CLAIM_TYPES = [
    "key_point", "business_impact", "risk", "opportunity", "strength", "weakness",
    "comparison", "metric", "factor", "action", "monitoring",
]
_CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "claim_type": {"type": "string", "enum": _CLAIM_TYPES},
        "claim": {"type": "string"},
        "evidence_passage_id": {"type": ["string", "null"]},
        "evidence_quote": {"type": "string"},
        "evidence_location": {"type": ["string", "null"]},
        "as_of_date": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["claim_id", "claim_type", "claim", "evidence_passage_id", "evidence_quote", "evidence_location", "as_of_date", "confidence"],
    "additionalProperties": False,
}
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "relevance_level": {"type": "string", "enum": ["direct", "partial", "background", "irrelevant"]},
        "grounded_claims": {"type": "array", "maxItems": _MAX_CLAIMS_PER_CALL, "items": _CLAIM_SCHEMA},
        "metric_points": {"type": "array", "maxItems": _MAX_METRIC_POINTS_PER_CALL, "items": {"type": "object", "properties": {"label": {"type": "string"}, "period": {"type": "string"}, "value": {"type": "number"}, "unit": {"type": ["string", "null"]}, "subject": {"type": ["string", "null"]}, "is_relative": {"type": "boolean"}, "comparison_period": {"type": ["string", "null"]}, "value_origin": {"type": "string", "enum": ["source"]}, "evidence_claim_id": {"type": "string"}}, "required": ["label", "period", "value", "unit", "subject", "is_relative", "comparison_period", "value_origin", "evidence_claim_id"], "additionalProperties": False}},
        "comparison_points": {"type": "array", "maxItems": _MAX_COMPARISON_POINTS_PER_CALL, "items": {"type": "object", "properties": {"entity": {"type": "string"}, "criterion": {"type": "string"}, "value": {"type": "string"}, "level": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]}, "evidence_claim_id": {"type": "string"}}, "required": ["entity", "criterion", "value", "level", "evidence_claim_id"], "additionalProperties": False}},
        "analysis_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["summary", "relevance_level", "grounded_claims", "metric_points", "comparison_points", "analysis_confidence"],
    "additionalProperties": False,
}
_REPAIR_SCHEMA = {"type": "object", "properties": {"repairs": {"type": "array", "items": {"type": "object", "properties": {"claim_id": {"type": "string"}, "evidence_passage_id": {"type": ["string", "null"]}, "evidence_quote": {"type": ["string", "null"]}}, "required": ["claim_id", "evidence_passage_id", "evidence_quote"], "additionalProperties": False}}}, "required": ["repairs"], "additionalProperties": False}


def _load_system_prompt() -> str:
    return "\n\n".join(
        [
            *(path.read_text(encoding="utf-8") for path in (_ANALYZER_PROMPT_PATH, _SECTOR_PROMPT_PATH)),
            SWOT_COMPLETENESS_INSTRUCTION,
            COMPARISON_COMPLETENESS_INSTRUCTION,
            TABLE_COMPLETENESS_INSTRUCTION,
            RELATIVE_METRIC_EXTRACTION_INSTRUCTION,
        ]
    )


def _repair_failed_claims(client: OpenAI, failed: list[dict], passages: list[dict[str, str]]) -> list[dict]:
    if not failed:
        return []
    payload = {"claims": [{"claim_id": c["claim_id"], "claim": c["claim"]} for c in failed], "passages": passages}
    try:
        response = client.chat.completions.create(
            model=_MODEL, max_tokens=800, temperature=0,
            messages=[{"role": "system", "content": "Repair citations only. Never alter a claim; return an exact quote from a supplied passage or null."}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            response_format={"type": "json_schema", "json_schema": {"name": "sk_hynix_quote_repair", "schema": _REPAIR_SCHEMA, "strict": True}},
        )
        repairs = json.loads(response.choices[0].message.content).get("repairs", [])
    except Exception:
        return []
    originals = {claim["claim_id"]: claim for claim in failed}
    return [{**originals[repair["claim_id"]], **repair} for repair in repairs if repair.get("claim_id") in originals and repair.get("evidence_quote")]


def _analyze_part(client: OpenAI, system_prompt: str, document: SourceDocument, question: str, content: str) -> DocumentAnalysis:
    passages = split_evidence_passages(content)
    user_content = json.dumps({"question": question, "document": {"title": document.title, "url": document.url, "evidence_passages": passages}}, ensure_ascii=False)
    try:
        response, _ = call_with_truncation_retry(
            lambda max_tokens: client.chat.completions.create(model=_MODEL, max_tokens=max_tokens, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}], response_format={"type": "json_schema", "json_schema": {"name": "sk_hynix_document_analysis", "schema": _ANALYSIS_SCHEMA, "strict": True}}),
            [_ANALYSIS_MAX_TOKENS, _ANALYSIS_MAX_TOKENS_ESCALATED],
        )
        message = response.choices[0].message
        if message.refusal:
            raise PipelineStageError(stage=_STAGE, reason=f"analysis refused for doc '{document.doc_id}'", detail=message.refusal)
        data = json.loads(message.content)
    except PipelineStageError:
        raise
    except Exception as exc:
        raise PipelineStageError(stage=_STAGE, reason=f"analysis API call failed for doc '{document.doc_id}'", detail=str(exc)) from exc
    verified, failed = verify_claim_quotes(data["grounded_claims"], passages, source_url=document.url)
    repaired, _ = verify_claim_quotes(_repair_failed_claims(client, failed, passages), passages, source_url=document.url)
    claims = [*verified, *repaired]
    metrics = filter_points_by_verified_claim(data["metric_points"], claims, claim_type="metric")
    comparisons = filter_points_by_verified_claim(data["comparison_points"], claims, claim_type="comparison")
    relevance = data["relevance_level"]
    raw_count = len(data["grounded_claims"])
    status = "not_applicable" if relevance == "irrelevant" else ("insufficient_grounding" if not claims else ("partial_grounding" if len(claims) < raw_count else "verified"))
    return DocumentAnalysis(doc_id=document.doc_id, source_id=document.source_id, source_title=document.title, source_url=document.url, reliability_tier=document.reliability_tier, summary=data["summary"], relevant_to_question=relevance != "irrelevant", relevance_level=relevance, grounded_claims=claims, key_points=[c["claim"] for c in claims if c["claim_type"] == "key_point"], business_impact="; ".join(c["claim"] for c in claims if c["claim_type"] == "business_impact"), risk="; ".join(c["claim"] for c in claims if c["claim_type"] == "risk"), opportunity="; ".join(c["claim"] for c in claims if c["claim_type"] == "opportunity"), strength="; ".join(c["claim"] for c in claims if c["claim_type"] == "strength"), weakness="; ".join(c["claim"] for c in claims if c["claim_type"] == "weakness"), factors=[c["claim"] for c in claims if c["claim_type"] == "factor"], recommended_actions=[c["claim"] for c in claims if c["claim_type"] == "action"], monitoring_indicators=[c["claim"] for c in claims if c["claim_type"] == "monitoring"], metric_points=metrics, comparison_points=comparisons, evidence=[c["evidence_quote"] for c in claims], analysis_confidence=data["analysis_confidence"], analysis_validation_status=status, usable_for_synthesis=relevance != "irrelevant" and bool(claims))


def _merge_parts(document: SourceDocument, parts: list[DocumentAnalysis]) -> DocumentAnalysis:
    claims = [claim for part in parts for claim in part.grounded_claims]
    claim_ids = {claim.claim_id for claim in claims}
    return DocumentAnalysis(doc_id=document.doc_id, source_id=document.source_id, source_title=document.title, source_url=document.url, reliability_tier=document.reliability_tier, summary=" ".join(part.summary or "" for part in parts).strip(), relevant_to_question=any(part.relevant_to_question for part in parts), relevance_level=next((part.relevance_level for part in parts if part.relevance_level != "irrelevant"), "irrelevant"), grounded_claims=claims, key_points=[claim.claim for claim in claims if claim.claim_type == "key_point"], metric_points=[point for part in parts for point in part.metric_points if point.evidence_claim_id in claim_ids], comparison_points=[point for part in parts for point in part.comparison_points if point.evidence_claim_id in claim_ids], evidence=[claim.evidence_quote for claim in claims], analysis_confidence="low" if any(part.analysis_confidence == "low" for part in parts) else "medium", analysis_validation_status="verified" if claims else "insufficient_grounding", usable_for_synthesis=bool(claims))


def analyze(source_documents: list[SourceDocument], question: str, information_needs: list[str] | None = None, evidence_requirements: list[str] | None = None) -> list[DocumentAnalysis]:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"template_only: {_API_KEY_ENV_VAR} is not configured")
    client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))
    prompt = _load_system_prompt()
    results: list[DocumentAnalysis] = []
    for document in source_documents:
        parts = [_analyze_part(client, prompt, document, question, chunk) for chunk in split_content(document.content or "")]
        results.append(parts[0] if len(parts) == 1 else _merge_parts(document, parts))
    return results
