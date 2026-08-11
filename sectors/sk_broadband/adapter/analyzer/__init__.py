"""SK Broadband sector analyzer."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

from common.ai_usage import emit_ai_usage
from common.ai_client import openai_client_kwargs
from common.analyzer_quality import normalize_quote
from common.content_quality_validator import (
    COMPARISON_COMPLETENESS_INSTRUCTION,
    SWOT_COMPLETENESS_INSTRUCTION,
    TABLE_COMPLETENESS_INSTRUCTION,
    metric_value_type,
    relative_metric_context,
    strip_particle,
)
from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from common.metric_identity import normalize_comparison_points
from common.metric_quality import clean_dimension
from sources.openai_retry import call_with_retry, call_with_truncation_retry

_API_KEY_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY"
_FALLBACK_API_KEY_ENV_VAR = "OPENAI_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_MODEL"
# Stage-local provider switch. The current Solar deployment uses an Upstage
# base URL; removing it restores the OpenAI endpoint. Explicit model config
# always wins, so either provider can be selected later. See common/ai_client.py.
_BASE_URL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_BASE_URL"
_DEFAULT_OPENAI_MODEL = "gpt-4o"
_DEFAULT_UPSTAGE_MODEL = "solar-pro3"
_MAX_CONTENT_CHARS = 12000
_PDF_CHUNK_OVERLAP_CHARS = 500
_DEFAULT_MAX_PDF_CHUNKS = 12
_MAX_EVIDENCE_PASSAGE_CHARS = 2_000
_MAX_REPAIR_PASSAGES_PER_CLAIM = 3
_DEFAULT_ANALYSIS_MAX_TOKENS = 4500
_DENSE_ANALYSIS_MAX_TOKENS = 7000
_DENSE_FIGURE_COUNT = 40
_DEFAULT_REPAIR_MAX_TOKENS = 1600
_DENSE_REPAIR_MAX_TOKENS = 2600
_DENSE_REPAIR_CLAIM_COUNT = 8
# Output ceilings, paired with the token ceilings above. Without them the
# three analysis arrays are unbounded while max_tokens is not, so a
# table-dense chunk overflows and the whole document is lost to a
# JSONDecodeError on truncated JSON - live-verified 2026-08-10, twice at
# the 7,000-token ceiling, which _analysis_max_tokens() had already picked
# and so had nowhere left to escalate to.
#
# Measured on the stored runs, analysis output runs ~8x the source chars
# (a 1,725-char SKT IR table produced 13,682 chars of JSON), so a full
# 12,000-char chunk would need ~40,000 output tokens. The fix has to bound
# the output, not raise the ceiling.
#
# Sized against real demand rather than guessed: across all 31 stored runs
# the largest simultaneous demand from every selected block in one
# dashboard was 38 items, and the hungriest single block contract wants 4
# (ranking_list / composition_breakdown). These caps are per analysis call
# and synthesis pools across documents, so the guaranteed floor is
# cap x min_analyzed_documents (3) = 42 claims / 48 metrics / 24
# comparisons - above the worst observed whole-dashboard demand. Replaying
# the caps over every stored run never cut a pool below what that run's
# blocks actually consumed.
_MAX_CLAIMS_PER_CALL = 14
_MAX_METRIC_POINTS_PER_CALL = 16
_MAX_COMPARISON_POINTS_PER_CALL = 8
_MAX_PDF_CHUNKS_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_MAX_PDF_CHUNKS"
_STAGE = "sectors.sk_broadband.adapter.analyzer"

_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent
_GLOBAL_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "analyzer_system_prompt.md"
_SECTOR_PROMPT_PATH = _SECTOR_ROOT / "prompts" / "analyzer_prompt.md"

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 500, "description": "질문 관련 핵심 사실. 한국어 1~3문장."},
        # `sentiment` and `relevance_reason` used to be asked for here. Every
        # consumer of both was this analyzer's own chunk merge - traced across
        # the whole repository, nothing downstream of it ever read either one
        # (see the removal note above `_merge_chunk_analyses`). Asking the
        # model for a field no reader has costs an output field on every call
        # and a schema branch on every validation.
        #
        # `relevance_level` stays: `_merge_chunk_analyses` uses it to drop a
        # chunk the model itself judged irrelevant, and `relevant_to_question`
        # - which decides whether the whole document survives - is derived
        # from it.
        "relevance_level": {
            "type": "string",
            "enum": ["direct", "partial", "background", "irrelevant"],
            "description": "direct=질문에 직접 답함, partial=일부 필요 증거를 제공, background=맥락만 제공, irrelevant=무관.",
        },
        "grounded_claims": {
            "type": "array",
            "maxItems": _MAX_CLAIMS_PER_CALL,
            "description": (
                "질문에 답하는 핵심 주장과 이를 직접 뒷받침하는 원문 인용. 인용은 원문에 그대로 존재해야 함. "
                f"최대 {_MAX_CLAIMS_PER_CALL}개. 상한에 걸리면 다음 순서로 남길 것: "
                "(1) answer_requirements의 요구 축을 직접 확인해 주는 주장, "
                "(2) information_needs를 직접 뒷받침하는 주장, "
                "(3) 그 외 보조 근거. 문서에 근거가 없으면 개수를 채우려 하지 말 것."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string", "maxLength": 80, "description": "문서 안의 짧은 고유 ID."},
                    "claim_type": {
                        "type": "string",
                        "enum": ["key_point", "business_impact", "risk", "opportunity", "strength", "weakness", "comparison", "metric", "factor", "action", "monitoring"],
                    },
                    "claim": {
                        "type": "string", "maxLength": 350,
                        "description": "한국어로 쓸 것. 원문이 영어 등 다른 언어여도 반드시 한국어로 번역·요약. "
                                        "고유명사(회사명·제품명 등)만 원문 표기 유지 가능.",
                    },
                    "evidence_passage_id": {
                        "type": ["string", "null"],
                        "maxLength": 80,
                        "description": "인용문을 복사한 evidence_passages의 passage_id.",
                    },
                    "evidence_quote": {"type": "string", "maxLength": 500, "description": "원문에서 그대로 복사한 최소 충분 구절."},
                    "evidence_location": {"type": ["string", "null"], "maxLength": 180, "description": "확인 가능한 문단·절·표 위치, 아니면 null."},
                    "as_of_date": {"type": ["string", "null"], "maxLength": 80, "description": "명시된 기준 시점 원문, 아니면 null."},
                    # Per-claim `confidence` is no longer asked for. It reached
                    # `SynthesisClaim.confidence` and `SynthesisConclusion.
                    # confidence` (core/synthesis/synthesizer.py:187,362) and
                    # stopped there - no block, eligibility rule or renderer
                    # reads either. `_normalize_analysis_payload` still supplies
                    # the contract's required value, so the field is asked of
                    # the model once per claim less on every call.
                    "parent_claim_id": {
                        "type": ["string", "null"],
                        "description": (
                            "이 주장이 '무엇 때문에 일어났는지'를 설명하는 상위 주장의 claim_id. "
                            "문서가 인과관계를 실제로 서술한 경우에만 지정하고, 추측하지 말 것. "
                            "같은 문서 안의 다른 claim_id여야 하며, 순환 참조 금지. 아니면 null."
                        ),
                    },
                    "importance": {
                        "type": ["integer", "null"],
                        "description": (
                            "질문에 답하는 데 이 주장이 얼마나 중요한지 0~100. 문서에 없는 판단이므로 "
                            "화면에 'AI 판단'으로 표기됨. 이유를 importance_basis에 못 쓰겠으면 null."
                        ),
                    },
                    "importance_basis": {
                        "type": ["string", "null"],
                        "maxLength": 240,
                        "description": "그 중요도로 본 이유. importance를 채웠으면 필수. 반드시 한국어로 작성.",
                    },
                },
                "required": ["claim_id", "claim_type", "claim", "evidence_passage_id", "evidence_quote", "evidence_location", "as_of_date", "parent_claim_id", "importance", "importance_basis"],
                "additionalProperties": False,
            },
        },
        "covered_information_needs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 160},
            "description": "이 문서가 질문에 관해 실제 근거를 제공하는 정보 항목.",
        },
        "metric_points": {
            "type": "array",
            "maxItems": _MAX_METRIC_POINTS_PER_CALL,
            "description": (
                "문서에 명시된 수치+시점 쌍만 추출. 추정하거나 계산하지 말 것. 없으면 빈 배열. "
                f"최대 {_MAX_METRIC_POINTS_PER_CALL}개. 상한에 걸리면 질문의 요구 축(answer_requirements)에 "
                "직접 답하는 수치를 먼저 남기고, 표의 모든 칸을 기계적으로 옮기지 말 것. "
                "라벨이 표의 행 조각(예: '159', 'A | 3.0%')처럼 그 자체로 의미를 갖지 못하는 항목은 제외."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "maxLength": 120, "description": "무엇을 나타내는 수치인지."},
                    "subject": {
                        "type": ["string", "null"],
                        "maxLength": 120,
                        "description": "수치의 주체·항목(기업, 플랫폼, 연령대 등). 원문 표현을 그대로 쓰고 없으면 null.",
                    },
                    "period": {"type": "string", "maxLength": 80, "description": "문서에 명시된 시점 그대로."},
                    "value": {"type": "number"},
                    "unit": {"type": "string", "maxLength": 40, "description": "원문 단위. 없으면 빈 문자열."},
                    "is_forecast": {
                        "type": "boolean",
                        "description": "원문이 전망·예상·목표·추정이라고 명시한 수치만 true.",
                    },
                    "value_type": {
                        "type": "string",
                        "enum": ["actual", "estimate", "forecast", "target", "guidance"],
                        "description": "원문의 상태. 전망/추정/목표/가이던스를 실제값으로 바꾸지 말 것.",
                    },
                    "is_relative": {
                        "type": "boolean",
                        "description": "YoY/CAGR/전년 대비/배수처럼 원문이 상대 변화로 명시한 수치만 true.",
                    },
                    "comparison_period": {
                        "type": ["string", "null"],
                        "maxLength": 80,
                        "description": "원문이 명시한 비교 기준(전년 대비, 2025년 대비 등). 없으면 null.",
                    },
                    "value_origin": {
                        "type": "string",
                        "enum": ["source"],
                        "description": "Analyzer는 원문 수치만 추출하므로 항상 source. 계산값 생성 금지.",
                    },
                    "share_of": {
                        "type": ["string", "null"],
                        "maxLength": 120,
                        "description": "원문이 이 비율들의 공통 전체를 명시한 경우 그 표현. 아니면 null.",
                    },
                    "evidence_claim_id": {
                        "type": "string",
                        "maxLength": 80,
                        "description": "이 수치 전체를 직접 인용한 claim_type=metric grounded_claim의 claim_id.",
                    },
                },
                "required": [
                    "label", "subject", "period", "value", "unit", "is_forecast", "value_type",
                    "is_relative", "comparison_period", "value_origin",
                    "share_of", "evidence_claim_id",
                ],
                "additionalProperties": False,
            },
        },
        "comparison_points": {
            "type": "array",
            "maxItems": _MAX_COMPARISON_POINTS_PER_CALL,
            "description": (
                "문서에 명시된 대상 간 비교만 추출. level은 문서가 명시적으로 우열을 말할 때만 채우고 그 외엔 null. "
                f"없으면 빈 배열. 최대 {_MAX_COMPARISON_POINTS_PER_CALL}개. 상한에 걸리면 질문이 비교를 요구한 "
                "기준(criterion)부터 남길 것."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "maxLength": 100, "description": "비교 대상."},
                    "criterion": {"type": "string", "maxLength": 160, "description": "비교 기준."},
                    "value": {"type": "string", "maxLength": 220, "description": "문서에 명시된 값이나 서술."},
                    "level": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                    "evidence_claim_id": {"type": "string", "maxLength": 80, "description": "comparison grounded_claim의 claim_id."},
                },
                "required": ["entity", "criterion", "value", "level", "evidence_claim_id"],
                "additionalProperties": False,
            },
        },
        # `action_level` removed for the same reason as `sentiment`: its only
        # reader was this analyzer's own merge. It was also inert in practice
        # - all three documents of the archived 유료방송 run came back
        # "insufficient_data", because `:2278` already forced that whenever
        # the document stated no action claim.
        "analysis_confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "문서 근거만 기준으로 한 분석 확신도.",
        },
    },
    "required": ["summary", "relevance_level", "grounded_claims", "covered_information_needs", "metric_points", "comparison_points", "analysis_confidence"],
    "additionalProperties": False,
}

_QUOTE_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string", "maxLength": 80},
                    "evidence_passage_id": {"type": ["string", "null"], "maxLength": 80},
                    "evidence_quote": {"type": ["string", "null"], "maxLength": 500},
                },
                "required": ["claim_id", "evidence_passage_id", "evidence_quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["repairs"],
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
    configured = os.environ.get(_MODEL_ENV_VAR)
    if configured:
        return configured
    base_url = os.environ.get(_BASE_URL_ENV_VAR, "").casefold()
    return _DEFAULT_UPSTAGE_MODEL if "upstage.ai" in base_url else _DEFAULT_OPENAI_MODEL


def _trim_content(content: str | None) -> str:
    if not content:
        return ""
    if len(content) <= _MAX_CONTENT_CHARS:
        return content
    return content[:_MAX_CONTENT_CHARS] + "\n\n[본문이 길어 분석 입력에서 일부가 생략되었습니다.]"


_WEB_FOOTER_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:"
    r"무단\s*전재(?:\s*및\s*재배포)?\s*금지|"
    r"copyright\b.*all rights reserved|"
    r"관련\s*기사|추천\s*기사|많이\s*본\s*뉴스|오늘\s*많이\s*본\s*뉴스|뉴스\s*브리핑"
    r")[ \t]*$"
)
_WEB_NOISE_RE = re.compile(
    r"(?i)(?:ERR_BLOCKED_BY_CLIENT|This page has been blocked by an extension|"
    r"Base64-Image-Removed|^\s*Reload\s*$|^\s*ad[\w.-]*\.(?:com|kr)\s*$)"
)


def _clean_analysis_content(content: str | None) -> str:
    """Remove only unmistakable web chrome; never rank or drop article prose."""
    if not content:
        return ""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    footer = _WEB_FOOTER_RE.search(text)
    if footer:
        text = text[:footer.start()]
    return "\n".join(
        line for line in text.splitlines() if not _WEB_NOISE_RE.search(line)
    ).strip()


def _is_pdf_document(document: SourceDocument) -> bool:
    if (document.media_type or "").split(";", 1)[0].strip().lower() == "application/pdf":
        return True
    title = (document.title or "").lower()
    path = urlparse(document.url or "").path.lower()
    return title.endswith(".pdf") or path.endswith(".pdf")


def _max_pdf_chunks() -> int:
    raw = os.environ.get(_MAX_PDF_CHUNKS_ENV_VAR)
    if raw is None:
        return _DEFAULT_MAX_PDF_CHUNKS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_PDF_CHUNKS


def _split_pdf_content(content: str) -> list[str]:
    """Split without dropping text, preferring paragraph/line boundaries."""
    chunks: list[str] = []
    start = 0
    content_length = len(content)
    while start < content_length:
        hard_end = min(start + _MAX_CONTENT_CHARS, content_length)
        end = hard_end
        if hard_end < content_length:
            minimum_boundary = start + (_MAX_CONTENT_CHARS // 2)
            paragraph_end = content.rfind("\n\n", minimum_boundary, hard_end)
            line_end = content.rfind("\n", minimum_boundary, hard_end)
            boundary = max(paragraph_end, line_end)
            if boundary > start:
                end = boundary
        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= content_length:
            break
        next_start = max(start + 1, end - _PDF_CHUNK_OVERLAP_CHARS)
        start = next_start
    return chunks


def _question_terms(question: str, information_needs: list[str]) -> list[str]:
    """Question and information-need words, as stems.

    Stemmed because these are matched against document text by substring, and
    Korean attaches particles to both sides: a question asking about "근거를"
    would otherwise never match a document saying "근거가". The chunk side
    needs no stemming - "근거" is a substring of "근거가" either way.
    """
    text = " ".join([question, *information_needs]).lower()
    tokens = re.findall(r"[가-힣a-z0-9]{2,}", text)
    return list(dict.fromkeys(
        stem for token in tokens if len(stem := strip_particle(token)) >= 2
    ))


# A statistic is worth reading even in a chunk that names none of the
# question's words - "전체의 62.5%" in a paragraph about the same topic in
# other terms is exactly the figure a block needs. So a chunk is only skipped
# when it has neither.
_FIGURE_RE = re.compile(r"\d[\d,.]*\s*(?:%|퍼센트|명|건|원|억|조|만|시간|분|배|위|점|개)")


def _analysis_max_tokens(content: str) -> int:
    """Give dense tables room to finish without making every call larger.

    Solar twice reached the old 4,500-token ceiling exactly on chunks with
    66 and 106 explicit figures, producing unusable truncated JSON. Ordinary
    prose and moderately numeric articles completed below the old ceiling.
    This changes only the output ceiling; no source passage is removed.
    """
    return (
        _DENSE_ANALYSIS_MAX_TOKENS
        if len(_FIGURE_RE.findall(content)) >= _DENSE_FIGURE_COUNT
        else _DEFAULT_ANALYSIS_MAX_TOKENS
    )


def _repair_max_tokens(failed_claim_count: int) -> int:
    return (
        _DENSE_REPAIR_MAX_TOKENS
        if failed_claim_count >= _DENSE_REPAIR_CLAIM_COUNT
        else _DEFAULT_REPAIR_MAX_TOKENS
    )


# A periodical is many articles bound together, and only some of them are
# about the question. Measured on a live 100-page KOCCA issue: the two chunks
# carrying the actual 숏폼/롱폼 analysis matched question terms 125 and 104
# times, while the PD interviews and drama columns matched 27, 21, 19 and 15.
# *Distinct* terms didn't separate them at all (6-9 everywhere, since the whole
# magazine is about broadcasting) - frequency did.
#
# So the cut is relative to the best chunk in the same document, never an
# absolute count, and it only applies to documents long enough to be a
# collection rather than an article. The top three always survive regardless.
_PERIODICAL_MIN_CHUNKS = 4
_PERIODICAL_KEEP_RATIO = 0.25
_PERIODICAL_ALWAYS_KEEP = 3


def _term_hits(chunk: str, terms: list[str]) -> int:
    lowered = chunk.lower()
    return sum(lowered.count(term) for term in terms)


def _periodical_chunks(
    candidates: list[tuple[int, str]], terms: list[str]
) -> list[tuple[int, str]]:
    """The chunks of a long collection that are plausibly about the question.

    Not a quality judgement on prose - a rule about which *articles* in a
    bound volume are on topic. Applied only to documents of
    `_PERIODICAL_MIN_CHUNKS` or more; an ordinary page or report keeps every
    chunk it has.
    """
    if len(candidates) < _PERIODICAL_MIN_CHUNKS or not terms:
        return candidates
    scored = [(index, chunk, _term_hits(chunk, terms)) for index, chunk in candidates]
    best = max(score for _, _, score in scored)
    if best <= 0:
        return candidates
    cutoff = best * _PERIODICAL_KEEP_RATIO
    ranked = sorted(scored, key=lambda item: -item[2])
    keep = {index for index, _, _ in ranked[:_PERIODICAL_ALWAYS_KEEP]}
    keep.update(index for index, _, score in scored if score >= cutoff)
    return [(index, chunk) for index, chunk, _ in scored if index in keep]


def _chunk_can_answer(chunk: str, terms: list[str]) -> bool:
    """Whether a chunk could contribute anything to this question.

    Deliberately generous, and deliberately not a ranking. Anything holding a
    question term or any figure at all is kept; only a chunk with neither is
    skipped. That is what makes this safe to apply before the model sees it -
    the material being dropped cannot contain an answer or a number, so no
    later stage loses a possibility it would otherwise have had.

    This exists because a single collected document can be a whole magazine
    issue. One live run scraped a 100-page KOCCA periodical: seven chunks
    analysed, seven model calls spent, and the only claim returned was about a
    dancer in a survival show. The relevant pages were two.
    """
    if not terms:
        return True
    lowered = chunk.lower()
    if any(term in lowered for term in terms):
        return True
    return bool(_FIGURE_RE.search(chunk))


def _selected_pdf_chunks(
    chunks: list[str], question: str, information_needs: list[str]
) -> list[tuple[int, str]]:
    """Analyze all normal PDFs; bound exceptionally large ones predictably.

    When the bound is exceeded, always retain the beginning and conclusion,
    then fill the remaining slots with the chunks that contain the most
    question/information-need terms. Returned indexes preserve PDF order.
    """
    limit = _max_pdf_chunks()
    indexed = list(enumerate(chunks, 1))
    if len(indexed) <= limit:
        return indexed
    required_indexes = {1, len(indexed)} if limit >= 2 else {1}
    terms = _question_terms(question, information_needs)
    ranked = sorted(
        indexed,
        key=lambda item: (
            -sum(item[1].lower().count(term) for term in terms),
            item[0],
        ),
    )
    selected_indexes = set(required_indexes)
    for index, _ in ranked:
        if len(selected_indexes) >= limit:
            break
        selected_indexes.add(index)
    return [item for item in indexed if item[0] in selected_indexes]


def _normalized_text(value: str) -> str:
    """Normalize extraction artifacts without weakening factual matching."""
    return normalize_quote(value)


def _split_evidence_passages(content: str) -> list[dict[str, str]]:
    """Expose bounded, verbatim source passages with stable local IDs."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", content) if block.strip()]
    passages: list[str] = []
    for block in blocks or ([content.strip()] if content.strip() else []):
        remaining = block
        while len(remaining) > _MAX_EVIDENCE_PASSAGE_CHARS:
            minimum = _MAX_EVIDENCE_PASSAGE_CHARS // 2
            boundary = max(
                remaining.rfind("\n", minimum, _MAX_EVIDENCE_PASSAGE_CHARS),
                remaining.rfind(". ", minimum, _MAX_EVIDENCE_PASSAGE_CHARS),
                remaining.rfind("다. ", minimum, _MAX_EVIDENCE_PASSAGE_CHARS),
            )
            end = boundary + (2 if boundary >= 0 and remaining[boundary : boundary + 2] == "다." else 1)
            if boundary < minimum:
                end = _MAX_EVIDENCE_PASSAGE_CHARS
            passage = remaining[:end].strip()
            if passage:
                passages.append(passage)
            remaining = remaining[end:].strip()
        if remaining:
            passages.append(remaining)
    return [
        {"passage_id": f"P{index:03d}", "text": text}
        for index, text in enumerate(passages, 1)
    ]


def _quote_is_in_text(quote: str, text: str) -> bool:
    return bool(quote) and _normalized_text(quote) in _normalized_text(text)


def _verified_claims(
    data: dict,
    document: SourceDocument,
    passages: list[dict[str, str]],
) -> list[dict]:
    passage_by_id = {passage["passage_id"]: passage["text"] for passage in passages}
    verified: list[dict] = []
    seen_claim_ids: set[str] = set()
    for claim in data.get("grounded_claims", []):
        claim_id = claim.get("claim_id", "")
        quote = claim.get("evidence_quote", "")
        if not claim_id or claim_id in seen_claim_ids:
            continue
        passage_id = claim.get("evidence_passage_id")
        if passage_id:
            passage_text = passage_by_id.get(passage_id)
            if passage_text is None or not _quote_is_in_text(quote, passage_text):
                continue
        else:
            passage_id = next(
                (
                    candidate_id
                    for candidate_id, text in passage_by_id.items()
                    if _quote_is_in_text(quote, text)
                ),
                None,
            )
        if not passage_id:
            continue
        seen_claim_ids.add(claim_id)
        location = claim.get("evidence_location")
        verified.append(
            {
                **claim,
                "evidence_passage_id": passage_id,
                "evidence_location": f"{passage_id} / {location}" if location else passage_id,
                "source_url": document.url,
            }
        )
    return verified


def _claim_terms(claim: dict) -> list[str]:
    text = " ".join(
        str(claim.get(field) or "")
        for field in ("claim", "evidence_quote", "as_of_date")
    ).lower()
    return list(dict.fromkeys(re.findall(r"[가-힣a-z0-9]{2,}", text)))


def _repair_passages_for_claim(
    claim: dict, passages: list[dict[str, str]]
) -> list[dict[str, str]]:
    terms = _claim_terms(claim)
    ranked = sorted(
        enumerate(passages),
        key=lambda item: (
            -sum(item[1]["text"].lower().count(term) for term in terms),
            item[0],
        ),
    )
    return [
        passage
        for _, passage in ranked[:_MAX_REPAIR_PASSAGES_PER_CLAIM]
    ]


def _repair_failed_claim_quotes(
    client: OpenAI,
    document: SourceDocument,
    raw_claims: list[dict],
    verified_claims: list[dict],
    passages: list[dict[str, str]],
) -> list[dict]:
    verified_ids = {claim["claim_id"] for claim in verified_claims}
    failed_claims = [
        claim
        for claim in raw_claims
        if claim.get("claim_id") and claim.get("claim_id") not in verified_ids
    ]
    if not failed_claims:
        return verified_claims
    repair_max_tokens = _repair_max_tokens(len(failed_claims))

    candidates_by_claim = {
        claim["claim_id"]: _repair_passages_for_claim(claim, passages)
        for claim in failed_claims
    }
    selected_passage_ids = {
        passage["passage_id"]
        for candidates in candidates_by_claim.values()
        for passage in candidates
    }
    repair_input = {
        "document": {
            "doc_id": document.doc_id,
            "title": document.title,
            "url": document.url,
        },
        "claims_to_repair": [
            {
                "claim_id": claim["claim_id"],
                "claim": claim.get("claim"),
                "failed_evidence_quote": claim.get("evidence_quote"),
                "candidate_passage_ids": [
                    passage["passage_id"]
                    for passage in candidates_by_claim[claim["claim_id"]]
                ],
            }
            for claim in failed_claims
        ],
        "candidate_passages": [
            passage
            for passage in passages
            if passage["passage_id"] in selected_passage_ids
        ],
        "instructions": (
            "주장 문구는 절대 수정하지 말고, 해당 주장을 직접 뒷받침하는 짧은 인용문을 "
            "candidate_passages에서 글자 그대로 복사하라. 직접 근거가 없으면 passage_id와 "
            "quote를 모두 null로 반환하라. 추론·의역·새 주장을 만들지 말라."
        ),
    }
    try:
        repair_system_content = (
            "You repair source citations only. Never change a claim and never "
            "invent or paraphrase a quote."
        )
        repair_user_content = json.dumps(repair_input, ensure_ascii=False)
        response = call_with_retry(
            lambda: client.chat.completions.create(
                model=_model(),
                max_tokens=repair_max_tokens,
                temperature=0,
                messages=[
                    {"role": "system", "content": repair_system_content},
                    {"role": "user", "content": repair_user_content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "sk_broadband_quote_repair",
                        "schema": _QUOTE_REPAIR_SCHEMA,
                        "strict": True,
                    },
                },
            )
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            return verified_claims
        repairs = json.loads(message.content).get("repairs", [])
        emit_ai_usage(
            stage=f"{_STAGE}.quote_repair",
            model=_model(),
            system_content=repair_system_content,
            user_content=repair_user_content,
            schema=_QUOTE_REPAIR_SCHEMA,
            requested_max_tokens=repair_max_tokens,
            response=response,
            counts={"failed_claims": len(failed_claims), "repairs": len(repairs)},
        )
    except Exception as exc:  # noqa: BLE001
        emit_ai_usage(
            stage=f"{_STAGE}.quote_repair",
            model=_model(),
            system_content=locals().get("repair_system_content", ""),
            user_content=locals().get("repair_user_content", ""),
            schema=_QUOTE_REPAIR_SCHEMA,
            requested_max_tokens=repair_max_tokens,
            response=locals().get("response"),
            outcome="failed",
            error_type=type(exc).__name__,
        )
        print(
            f"[{_STAGE}] quote repair failed for doc '{document.doc_id}': {exc}",
            file=sys.stderr,
        )
        return verified_claims

    failed_by_id = {claim["claim_id"]: claim for claim in failed_claims}
    passage_by_id = {passage["passage_id"]: passage["text"] for passage in passages}
    repaired_by_id: dict[str, dict] = {}
    for repair in repairs:
        claim_id = repair.get("claim_id")
        passage_id = repair.get("evidence_passage_id")
        quote = repair.get("evidence_quote")
        original_claim = failed_by_id.get(claim_id)
        allowed_ids = {
            passage["passage_id"] for passage in candidates_by_claim.get(claim_id, [])
        }
        if (
            original_claim is None
            or passage_id not in allowed_ids
            or passage_id not in passage_by_id
            or not quote
            or not _quote_is_in_text(quote, passage_by_id[passage_id])
        ):
            continue
        location = original_claim.get("evidence_location")
        repaired_by_id[claim_id] = {
            **original_claim,
            "evidence_passage_id": passage_id,
            "evidence_quote": quote,
            "evidence_location": f"{passage_id} / {location}" if location else passage_id,
            "source_url": document.url,
        }

    verified_by_id = {claim["claim_id"]: claim for claim in verified_claims}
    return [
        verified_by_id.get(claim.get("claim_id"))
        or repaired_by_id.get(claim.get("claim_id"))
        for claim in raw_claims
        if verified_by_id.get(claim.get("claim_id"))
        or repaired_by_id.get(claim.get("claim_id"))
    ]


def _verified_relations(claims: list[dict]) -> list[dict]:
    """Strip causal links and importance scores the evidence can't carry.

    Both fields are the model's judgement rather than something a document
    states outright, so each is checked the way every other model output here
    is - kept only where it is resolvable, dropped where it is not, and never
    repaired into something plausible:

    - a `parent_claim_id` that doesn't name another claim that survived
      verification becomes None (the claim itself stays; only the link goes),
    - a link that closes a cycle (A->B->A, or a claim parenting itself) is
      dropped, since a cause tree with a loop has no root to draw from,
    - an `importance` outside 0-100, or with no `importance_basis` saying why,
      is discarded whole. A number with no stated reason renders as a
      measurement while carrying an opinion, and the user's requirement was
      the opposite: the judgement must arrive with its context attached.
    """
    known = {claim.get("claim_id") for claim in claims}
    resolved: list[dict] = []
    parents: dict[str, str] = {}
    for claim in claims:
        claim_id = claim.get("claim_id")
        parent = claim.get("parent_claim_id")
        if parent not in known or parent == claim_id:
            parent = None
        importance = claim.get("importance")
        basis = (claim.get("importance_basis") or "").strip()
        if not isinstance(importance, int) or isinstance(importance, bool) or not basis:
            importance, basis = None, None
        elif not 0 <= importance <= 100:
            importance, basis = None, None
        if parent:
            parents[claim_id] = parent
        resolved.append({**claim, "parent_claim_id": parent, "importance": importance,
                         "importance_basis": basis})

    def closes_a_cycle(claim_id: str) -> bool:
        seen = {claim_id}
        current = parents.get(claim_id)
        while current:
            if current in seen:
                return True
            seen.add(current)
            current = parents.get(current)
        return False

    for claim in resolved:
        if claim["parent_claim_id"] and closes_a_cycle(claim["claim_id"]):
            claim["parent_claim_id"] = None
    return resolved


_METHODOLOGY_ONLY_MARKERS = (
    "표본 크기", "표본수", "조사 대상", "조사기간", "조사 기간",
    "sample size", "survey period", "methodology",
)


def _recover_missing_metric_claims(
    claims: list[dict],
    evidence_passages: list[dict],
    question: str,
    information_needs: list[str],
) -> list[dict]:
    """Recover exact numeric sentences the model omitted from claims.

    A passage must share a question/information-need term and the retained
    sentence or table row must carry a literal figure with a unit. Claim and
    quote are identical source text, so this restores structure without
    adding an interpretation or an unsupported fact.
    """
    terms = _question_terms(question, information_needs)
    if not terms:
        return claims
    existing_quotes = {
        _normalized_text(claim.get("evidence_quote") or "") for claim in claims
    }
    recovered = list(claims)
    recovered_index = 0
    for passage in evidence_passages:
        passage_text = passage.get("text") or ""
        lowered_passage = passage_text.casefold()
        if not any(term in lowered_passage for term in terms):
            continue
        rows = re.split(r"(?<=[.!?。])\s+|\n+", passage_text)
        for row in rows:
            quote = row.strip()
            normalized_quote = _normalized_text(quote)
            if not normalized_quote or any(
                existing and (existing in normalized_quote or normalized_quote in existing)
                for existing in existing_quotes
            ):
                continue
            if not _FIGURE_RE.search(quote):
                continue
            lowered = quote.casefold()
            if (
                any(marker in lowered for marker in _METHODOLOGY_ONLY_MARKERS)
                and not re.search(r"%|퍼센트|억원|조원|시간|분|배", quote)
            ):
                continue
            recovered_index += 1
            recovered.append({
                "claim_id": f"det-metric-{recovered_index}",
                "claim_type": "metric",
                "claim": quote,
                "evidence_passage_id": passage.get("passage_id"),
                "evidence_quote": quote,
                "evidence_location": passage.get("passage_id"),
                "as_of_date": None,
                # TODO(confidence-inversion): "high" here means only "this
                # quote was copied verbatim from the source", not that the
                # claim matters more than a model-written one - yet every
                # model claim now normalises to "low" (see the matching note
                # in `_normalize_analysis_payload`), so the two read as an
                # ordering that says the opposite of what is true. Harmless
                # while nothing reads `GroundedClaim.confidence`; fix both
                # sides before anything does.
                "confidence": "high",
                "parent_claim_id": None,
                "importance": None,
                "importance_basis": None,
            })
            existing_quotes.add(normalized_quote)
    return recovered


def _number_is_in_content(value: float, content: str) -> bool:
    """Whether this exact figure appears in the text.

    The candidate set used to be {str(value), f"{value:g}"}. `%g` switches to
    scientific notation at 7 significant digits, so 36,226,100 was looked for
    as "3.62261e+07" and `str()` gave "36226100.0" - neither is in any
    document. Every figure of a million or more was therefore silently
    discarded, which is why subscriber counts never became metric_points while
    smaller revenue figures did.
    """
    compact = content.replace(",", "")
    candidates = {str(value), f"{value:g}"}
    if value == int(value):
        candidates.add(str(int(value)))
    else:
        candidates.add(f"{value:f}".rstrip("0").rstrip("."))
    return any(
        re.search(rf"(?<![\d.]){re.escape(candidate)}(?![\d.])", compact)
        for candidate in candidates
    )


def _period_is_grounded(period: str, text: str) -> bool:
    """Accept harmless notation differences, never an unsupported year."""
    normalized_period = _normalized_text(period)
    normalized_text = _normalized_text(text)
    if normalized_period and normalized_period in normalized_text:
        return True
    period_years = set(re.findall(r"20\d{2}", normalized_period))
    text_years = set(re.findall(r"20\d{2}", normalized_text))
    if period_years:
        return period_years <= text_years
    return False


def _grounded_unit(unit: str, text: str) -> str | None:
    """Return the model unit only when the quote states an equivalent unit."""
    if not unit:
        return ""
    normalized_unit = _normalized_text(unit).casefold()
    normalized_text = _normalized_text(text).casefold()
    if normalized_unit and normalized_unit in normalized_text:
        return unit
    aliases = {
        "%": ("%", "percent", "퍼센트"),
        "p.p.": ("%p", "%pt", "pp", "percentage point", "percent point", "퍼센트포인트"),
        "%p": ("%p", "%pt", "pp", "percentage point", "percent point", "퍼센트포인트"),
        "시간": ("hour", "hours", "시간"),
        "분": ("minute", "minutes", "분"),
        "개": ("service", "services", "item", "items", "개"),
        "명": ("people", "persons", "respondents", "users", "명"),
    }
    candidates = aliases.get(normalized_unit, ())
    return unit if any(candidate in normalized_text for candidate in candidates) else None


def _verified_metric_points(
    data: dict,
    analyzed_content: str,
    grounded_claims: list[dict],
    evidence_passages: list[dict] | None = None,
) -> list[dict]:
    verified: list[dict] = []
    metric_claims = {
        claim["claim_id"]: claim
        for claim in grounded_claims
        if claim["claim_type"] == "metric"
    }
    passage_by_id = {
        passage["passage_id"]: passage["text"]
        for passage in (evidence_passages or [])
    }
    for point in data.get("metric_points", []):
        value = point.get("value")
        if not isinstance(value, (int, float)) or not _number_is_in_content(float(value), analyzed_content):
            continue
        evidence_claim = metric_claims.get(point.get("evidence_claim_id"))
        if evidence_claim is None:
            continue
        quote = evidence_claim["evidence_quote"]
        normalized_quote = _normalized_text(quote)
        if not _number_is_in_content(float(value), quote):
            continue
        passage_id = (evidence_claim.get("evidence_passage_id") or "").rsplit(":", 1)[-1]
        local_context = " ".join(
            value for value in (quote, passage_by_id.get(passage_id, "")) if value
        )
        grounded_unit = _grounded_unit(str(point.get("unit", "")), quote)
        if grounded_unit is None:
            continue
        grounded_period = (
            str(point.get("period", ""))
            if _period_is_grounded(str(point.get("period", "")), local_context)
            else "시점 미상"
        )
        normalized_local = _normalized_text(local_context)
        grounded_subject = point.get("subject") or None
        if grounded_subject and _normalized_text(str(grounded_subject)) not in normalized_local:
            grounded_subject = None
        grounded_share_of = point.get("share_of") or None
        if grounded_share_of and _normalized_text(str(grounded_share_of)) not in normalized_local:
            grounded_share_of = None
        grounded_value_type = metric_value_type(quote)
        grounded_relative, grounded_comparison_period = relative_metric_context(local_context)
        verified.append({
            **point,
            "period": grounded_period,
            "unit": grounded_unit,
            "subject": grounded_subject,
            "share_of": grounded_share_of,
            "is_forecast": grounded_value_type != "actual",
            "value_type": grounded_value_type,
            "is_relative": grounded_relative,
            "comparison_period": grounded_comparison_period,
            "value_origin": "source",
            "evidence_quote": quote,
        })
    return verified


_GROUNDED_METRIC_RE = re.compile(
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    # `개(?!월)`: "6개월 평균값" is a duration, not "6개" of anything - a live
    # run turned that footnote into a metric labelled "※".
    r"(?P<unit>%p|%|퍼센트포인트|퍼센트|조\s*원|억\s*원|만\s*명|명|건|개(?!월)|분|시간|배|점|"
    r"hours?|minutes?|people|persons?|respondents?|users?|services?|items?)",
    re.IGNORECASE,
)
_YEAR_TOKEN_RE = re.compile(r"20\d{2}\s*년?")
_METRIC_LABEL_BOUNDARY_RE = re.compile(r"[\n\r;。!?)]|(?<!\d)\.(?!\d)|→|(?:,\s*)")
_WEAK_METRIC_LABELS = {"약", "보다", "대비", "증가", "감소", "marking a", "at"}


def _nearest_period(text: str, start: int, end: int) -> str:
    after = text[end:end + 28]
    after_match = re.match(
        r"\s*(?:\(\s*|in\s+)(?P<year>20\d{2})\s*년?\)?",
        after,
        flags=re.IGNORECASE,
    )
    if after_match:
        return after_match.group("year")
    years = [match for match in _YEAR_TOKEN_RE.finditer(text[:start])]
    if not years:
        return "시점 미상"
    nearest = years[-1]
    between = text[nearest.end():start]
    if len(between) > 90 or re.search(r"[\n\r;。!?]|(?<!\d)\.(?!\d)", between):
        return "시점 미상"
    return re.sub(r"\s+", "", nearest.group()).strip()


# A number's own thousands separators are not clause boundaries. Masking
# them before the boundary split is what stops `9,008억 원` from being cut
# into `008억 원`; blacklisting the resulting fragments afterwards only ever
# catches the shapes someone happened to see.
_GROUPED_NUMBER_RE = re.compile(r"\d[\d,]*\d")
_COMMA_SENTINEL = "\x00"

# A label that opens with a particle or a comparison connective is the tail
# of the previous clause, not this figure's name - "…로 늘어난 것으로 전년
# 대비" leaves `으로 전년 대비`. Korean attaches these to the end of the
# preceding phrase, so their presence at the *start* of a fragment is the
# signal that the clause boundary was missed.
_DANGLING_LABEL_PREFIX_RE = re.compile(
    r"^(?:으로|로서|로써|로|에서|에게|에|와|과|보다|대비|및|또는|등|그리고|이며|이고)\b\s*"
)
_CLAUSE_TAIL_ONLY_RE = re.compile(r"^(?:전년\s*)?대비$|^증감(?:률|폭)?$|^대비\s*증감(?:률|폭)?$")


# Words that are only a clause tail inside a sentence but are a row's or
# column's actual name inside a table. "증감폭" alone tells a reader nothing
# in prose - in `| 증감폭 (증감률) | 242,585 (0.67%) | …` it is exactly what
# the row measures, and rejecting it would delete a real reading.
_TABLE_STRUCTURAL_LABELS = {"증감", "증감폭", "증감률", "점유율", "가입자 수", "가입자수", "합계", "계"}


def _semantically_complete_label(text: str, *, context: str = "sentence") -> bool:
    """Whether this stands on its own as the name of a measurement.

    A metric whose label or subject is a sentence fragment is not evidence
    anyone can read - live-verified 2026-08-10 the sentence path emitted
    `subject="008억 원) 대비"` and `label="으로 전년 대비 증감률"`, both of
    which reached the dashboard.

    `context` exists because the same string can be a fragment or a name
    depending on where it was read from: the structural checks below hold
    everywhere, but a bare "증감폭" is a dangling tail in prose and a row
    name in a table. Only the table path may pass `context="table"`, and
    only after the row's own structure has already been established.
    """
    candidate = (text or "").strip()
    if not candidate or not re.search(r"[가-힣A-Za-z]", candidate):
        return False
    if _DANGLING_LABEL_PREFIX_RE.match(candidate):
        return False
    if _CLAUSE_TAIL_ONLY_RE.match(candidate) and not (
        context == "table" and candidate in _TABLE_STRUCTURAL_LABELS
    ):
        return False
    # An unmatched bracket in either direction means the split landed inside
    # a parenthetical: "008억 원) 대비" kept the tail of "(9,008억 원)", and
    # "IPTV 점유율(B" (an unmatched *open* paren - live-verified 2026-08-11,
    # a table column header like "점유율(B수치)" split mid-parenthetical the
    # other way) kept the head. Both read as a real, complete-looking label
    # on their own, so only the bracket count reveals either is a fragment.
    if candidate.count(")") > candidate.count("(") or candidate.count("）") > candidate.count("（"):
        return False
    if candidate.count("(") > candidate.count(")") or candidate.count("（") > candidate.count("）"):
        return False
    # A fragment that starts mid-number ("006가구 내") is the far end of a
    # figure the boundary split cut through.
    if re.match(r"^\d", candidate) and not re.match(r"^\d{4}\s*년", candidate):
        return False
    return True


def _clean_label_fragment(fragment: str) -> str:
    """Shared cleanup for a raw clause-boundary split, either direction."""
    fragment = re.sub(
        r"^[\s*#|:'\"“”‘’([{]+|[\s*#|:'\"“”‘’([{]+$", "", fragment
    ).strip()
    fragment = re.sub(r"\b20\d{2}\s*년?\b", "", fragment).strip(" :-()[]")
    fragment = re.sub(r"^\d+(?:\.\d+)?\s*%p?\s*(?:로|보다|에서)?\s*", "", fragment)
    if fragment.endswith("전년"):
        fragment = "전년"
    # Drop a leading connective the boundary split left attached before
    # judging completeness, so "으로 전년 대비 증감" can still recover as
    # "전년 대비 증감" rather than being thrown away wholesale.
    fragment = _DANGLING_LABEL_PREFIX_RE.sub("", fragment).strip()
    return fragment


def _metric_label_before(text: str, position: int, fallback: str) -> str:
    prefix = text[:position]
    # Protect the numeric spans, split on real clause boundaries, restore.
    masked = _GROUPED_NUMBER_RE.sub(
        lambda m: m.group().replace(",", _COMMA_SENTINEL), prefix
    )
    fragment = _clean_label_fragment(
        _METRIC_LABEL_BOUNDARY_RE.split(masked)[-1].replace(_COMMA_SENTINEL, ",")
    )
    if not _semantically_complete_label(fragment):
        fragment = fallback
    return fragment[-70:].strip()


def _metric_label_after(text: str, position: int) -> str:
    """A subject named right after the number, not before it.

    `_metric_label_before` has nothing to work with when the number leads the
    quote entirely - live-verified 2026-08-11: bullet-point survey findings
    are commonly written "<percent>, <description>" (`**\\- 71.1%, "'롱폼
    콘텐츠', 숏폼과 달리 깊이감 있어"**`), so `text[:position]` is empty or
    just markdown/punctuation. Korean headline phrasing like this often
    juxtaposes the subject before a comma with no topic particle attached at
    all ("'롱폼 콘텐츠', 숏폼과 달리..." - not "롱폼 콘텐츠는"), so this reads
    up to the same clause boundary `_metric_label_before` reads backward from
    (comma, sentence end, etc.) rather than requiring a particle - the first
    clause after the number is the subject a reader would take it to be.
    """
    # The number sits right at the start of `suffix` (that's the whole reason
    # this function is being tried), almost always followed immediately by
    # its own delimiter - "71.1%," - so splitting without stripping that
    # leading delimiter first returns an empty leading segment, not the
    # clause after it.
    suffix = text[position:].lstrip("*\\").lstrip(",.;: \t")
    masked = _GROUPED_NUMBER_RE.sub(
        lambda m: m.group().replace(",", _COMMA_SENTINEL), suffix
    )
    segments = [
        segment for segment in _METRIC_LABEL_BOUNDARY_RE.split(masked) if segment.strip()
    ]
    if not segments:
        return ""
    fragment = _clean_label_fragment(segments[0].replace(_COMMA_SENTINEL, ","))
    return fragment[:70].strip() if _semantically_complete_label(fragment) else ""


def _metric_label_near(text: str, start: int, end: int, fallback: str) -> str:
    """Prefer the text before the number; only read after it if that failed.

    Both directions read the same clause a reader would - the label is
    whichever side of the number actually names what was measured. Falling
    all the way to `fallback` (usually the whole claim sentence) only
    happens when neither side offers a real label.
    """
    return _metric_label_before(text, start, "") or _metric_label_after(text, end) or fallback


def _canonical_recovered_unit(unit: str) -> str:
    compact = re.sub(r"\s+", "", unit)
    lowered = compact.casefold()
    if lowered in {"percent", "퍼센트"}:
        return "%"
    if lowered == "퍼센트포인트":
        return "%p"
    if lowered == "만명":
        return "만 명"
    if lowered.startswith("hour"):
        return "시간"
    if lowered.startswith("minute"):
        return "분"
    if lowered in {"people", "person", "persons", "respondent", "respondents", "user", "users"}:
        return "명"
    if lowered in {"service", "services", "item", "items"}:
        return "개"
    return compact.replace("만원", "만 원") if compact == "만원" else compact


_LIST_HEADING_RE = re.compile(
    r"(?P<label>[^,.;\n]{2,60})(?:은|는|:)[ \t]*",
    re.IGNORECASE,
)


def _list_metric_contexts(quote: str, matches: list[re.Match]) -> dict[int, tuple[str, str]]:
    """Find common-series labels and item names in a numeric list.

    This is deliberately vocabulary-free.  It works for platforms, age
    bands, companies, countries, content genres, cost components, and any
    other source sentence shaped like ``heading: item(value), item(value)``.
    A heading is used only when at least two figures belong to it, so an
    ordinary prose sentence with one number keeps the conservative fallback.
    """
    headings = list(_LIST_HEADING_RE.finditer(quote))
    assigned: dict[int, re.Match] = {}
    counts: dict[int, int] = {}
    for index, metric_match in enumerate(matches):
        candidates = [heading for heading in headings if heading.end() <= metric_match.start()]
        if not candidates:
            continue
        heading = candidates[-1]
        # A distant heading from an earlier sentence is not a series label.
        between = quote[heading.end():metric_match.start()]
        if len(between) > 300 or re.search(r"[\n\r;]|(?<!\d)[.!?](?!\d)", between):
            continue
        heading_index = headings.index(heading)
        assigned[index] = heading
        counts[heading_index] = counts.get(heading_index, 0) + 1

    contexts: dict[int, tuple[str, str]] = {}
    for index, metric_match in enumerate(matches):
        # Korean adnominal endings can look like a topic marker (for example
        # ``먹는 방송``).  A one-value pseudo-heading must not split a real
        # multi-item series, so choose the nearest heading that owns at least
        # two figures rather than blindly choosing the nearest ``는`` token.
        candidates = [
            heading for heading in headings
            if heading.end() <= metric_match.start()
            and counts.get(headings.index(heading), 0) >= 2
        ]
        if not candidates:
            continue
        heading = candidates[-1]
        between = quote[heading.end():metric_match.start()]
        if len(between) > 300 or re.search(r"[\n\r;]|(?<!\d)[.!?](?!\d)", between):
            continue
        prefix = quote[heading.end():metric_match.start()]

        # Values are commonly inside parentheses.  If that parenthesis also
        # contains a clarification (e.g. ``먹방(먹는 방송, 40.6%)``), walk
        # back to the unmatched opening parenthesis to keep ``먹방`` as the
        # item rather than treating the clarification as another category.
        stack: list[int] = []
        for position, char in enumerate(prefix):
            if char == "(":
                stack.append(position)
            elif char == ")" and stack:
                stack.pop()
        item_end = stack[-1] if stack else len(prefix)
        item_prefix = prefix[:item_end]
        item = re.split(r"[,;\n]", item_prefix)[-1]
        item = re.sub(r"^(?:등(?:이고|이며|으로)?\s*)", "", item).strip(" \t:'\"()[]")
        label = heading.group("label").strip(" \t:'\"()[]")
        if label and item:
            contexts[index] = (label[-70:], item[-70:])
    return contexts


# --- table-shaped evidence -------------------------------------------------
#
# A markdown table row is not a sentence, and reading it as one is what
# produced the worst dashboard defect this pipeline has had. Live-verified
# 2026-08-10 on 방송미디어통신위원회's 유료방송 가입자 보도자료:
#
#   |  | IPTV (증감률) | 20,565,609 (1.79%) | ... | 21,414,521 (0.49%) |
#
# The sentence path only matches a figure that carries its own unit, so the
# six subscriber counts - the actual answer to "IPTV 가입자 수 현황은?" -
# matched nothing (their unit lives in the table's `(단위: …)` caption), while
# each `(1.79%)` did. `_metric_label_before` then read backwards to the
# nearest comma boundary and produced `609` as the label, because
# _METRIC_LABEL_BOUNDARY_RE splits on commas and `20,565,609` is comma
# grouped. Every such row yielded `609 증감률`, `402 증감률`, … and no period
# at all, which in turn starved `chart`/`bar`/`timeline` of their "3개 이상
# 시점" contract and left the dashboard on a narrative fallback.
#
# These helpers give that path the structure it was missing - column index,
# header rows and caption - rather than growing a regex blacklist. They are
# deliberately narrow: only rows that really are pipe-delimited, only
# headers that sit above the row in the same passage, and never a unit or a
# period that the source did not state.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TIME_TOKEN_RE = re.compile(
    r"(?:20\d{2}\s*년|['’]\d{2}\s*년|상반기|하반기|분기|[1-4]\s*Q|Q\s*[1-4]|\d{1,2}\s*월)"
)
_CAPTION_UNIT_RE = re.compile(r"[(（]\s*단위\s*[:：]\s*([^)）]+)[)）]")
_TABLE_FILLER_CELLS = {"", "-", "—", "구 분", "구분", "비고", "증감"}
_TABLE_CELL_NUMBER_RE = re.compile(
    r"(?P<value>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%p|%|퍼센트포인트|퍼센트|억\s*원|조\s*원|만\s*명|원|명|건|개|배|점)?"
)


# A table row does not always survive as pipe-delimited text. The PDF
# pipeline also serialises one as `표 원문 행: 구 분=IPTV (증감률); 2022년=
# 20,565,609 (1.79%); …` - each cell paired with the column header it sat
# under. Live-verified 2026-08-10: because it has no leading `|` it fell to
# the sentence parser, which read the whole run of data cells as one label
# (`1,149,096 (0.69%); 2024년=21,310,251 …`). It is the same table row and
# carries its headers inline, so it belongs on the table path.
_SERIALIZED_ROW_PREFIX_RE = re.compile(r"^\s*표\s*원문\s*행\s*[:：]\s*")
_SERIALIZED_PAIR_RE = re.compile(r"^\s*(?P<header>[^=;]+?)\s*=\s*(?P<value>.*?)\s*$")


def _parse_serialized_table_row(quote: str) -> tuple[list[str], list[str]] | None:
    """Split `header=value; header=value` into aligned header and cell lists."""
    if not _SERIALIZED_ROW_PREFIX_RE.match(quote):
        return None
    body = _SERIALIZED_ROW_PREFIX_RE.sub("", quote).strip().rstrip(".")
    headers: list[str] = []
    cells: list[str] = []
    for part in body.split(";"):
        match = _SERIALIZED_PAIR_RE.match(part)
        if match is None:
            return None
        headers.append(match.group("header").strip())
        cells.append(match.group("value").strip())
    if len(cells) < 2:
        return None
    return headers, cells


def _split_table_cells(row: str) -> list[str]:
    inner = row.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(cell and set(cell) <= set("-: ") for cell in cells)


def _looks_like_data_row(cells: list[str]) -> bool:
    """A row carrying a bare figure is data, not another header line."""
    return any(
        re.search(r"\d", cell) and not _TIME_TOKEN_RE.search(cell) for cell in cells
    )


# A percentage is a share only when the source says what it is a share OF.
# These name the column as a composition; a growth/usage/conversion rate is
# a percentage of something else entirely and must never acquire a
# denominator here.
_SHARE_CRITERION_RE = re.compile(r"(?:점유율|비중|구성비|구성비율|share)")
_RATE_CRITERION_RE = re.compile(
    r"(?:증감|성장|변화|증가율|감소율|이용률|가입률|전환율|달성률|CAGR|전년|YoY)"
)
# An explicit total row is the structural proof that the rows partition one
# whole. Without it the table may simply list a few named entities and say
# nothing about what they add up to.
_TOTAL_ROW_RE = re.compile(r"^(?:합\s*계|총\s*계|전\s*체|계)$")
_TABLE_TITLE_RE = re.compile(r"[<〈《]\s*(?P<title>[^>〉》]+?)\s*[>〉》]")


def _table_denominator(lines: list[str], start: int, index: int) -> str | None:
    """The whole this table's percentage columns divide, or None.

    Only two structural facts are accepted as proof, in this order: the
    table carries its own total row (합계/총계/전체/계), and the table has a
    title naming what is being counted. Both must be present - a title alone
    describes a topic, and a total alone has no name a reader could show.
    Everything else, including "these add up to about 100", is left as None:
    a sum is a corroboration, never the evidence that a denominator exists.
    """
    has_total = False
    for line in lines[start:]:
        if not _TABLE_ROW_RE.match(line):
            break
        cells = _split_table_cells(line)
        named = _table_row_label(cells)
        if named and _TOTAL_ROW_RE.match(re.sub(r"\s+", " ", named[0]).strip()):
            has_total = True
            break
    if not has_total:
        return None
    for i in range(start - 1, max(-1, start - 8), -1):
        title = _TABLE_TITLE_RE.search(lines[i])
        if title:
            return title.group("title").strip()
    return None


def _table_context(
    passage_text: str, row: str
) -> tuple[list[list[str]], str | None, str | None] | None:
    """Header rows above `row` in its own table, plus the table's unit caption.

    Returns None when the row cannot be located, so a quote that was
    reflowed or came from somewhere else simply falls back to the sentence
    path instead of being parsed against the wrong table.
    """
    # Compared with whitespace collapsed: a stored quote has been through
    # normalisation, so "|  | IPTV" no longer matches the passage's "| |
    # IPTV" character for character, and an exact match silently lost the
    # header rows - which is the whole reason to look the row up.
    def _key(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    target = _key(row)
    lines = passage_text.splitlines()
    index = next((i for i, line in enumerate(lines) if _key(line) == target), None)
    if index is None:
        return None
    start = index
    while start - 1 >= 0 and _TABLE_ROW_RE.match(lines[start - 1]):
        start -= 1
    headers: list[list[str]] = []
    for i in range(start, index):
        cells = _split_table_cells(lines[i])
        if _is_table_separator(cells):
            continue
        if _looks_like_data_row(cells):
            break
        headers.append(cells)
    caption_unit: str | None = None
    for i in range(start - 1, max(-1, start - 8), -1):
        match = _CAPTION_UNIT_RE.search(lines[i])
        if match:
            caption_unit = match.group(1).strip()
            break
    return headers, caption_unit, _table_denominator(lines, start, index)


def _column_headers(headers: list[list[str]], columns: int) -> tuple[list[str], list[str]]:
    """Split each column's stacked header cells into period and criterion.

    A source table states the period on one header line and what is being
    measured on another (`'25년 상반기` above `점유율(B)`), and repeats a
    merged cell across the columns it spans. Splitting by whether a cell
    reads as a time expression keeps both without guessing either.
    """
    periods: list[str] = []
    criteria: list[str] = []
    for column in range(columns):
        parts: list[str] = []
        for header in headers:
            if column >= len(header):
                continue
            cell = header[column].strip()
            if cell in _TABLE_FILLER_CELLS or cell in parts:
                continue
            parts.append(cell)
        periods.append(" ".join(p for p in parts if _TIME_TOKEN_RE.search(p)).strip())
        criteria.append(" ".join(p for p in parts if not _TIME_TOKEN_RE.search(p)).strip())
    return periods, criteria


def _table_row_label(
    cells: list[str], criteria: list[str] | None = None
) -> tuple[str, int, bool] | None:
    """The row's own name, its column, and whether the row states a delta.

    A table may lead with more than one label column, and taking the first
    one names the wrong thing. 유료방송 사업자별 rows read
    `| IPTV (3개) | KT | 9,123,463 | 25.24% |`: the first column groups the
    operators by delivery type and the second is the operator. Reading the
    first made every one of KT, SK브로드밴드 and LG유플러스 come back as
    `subject="IPTV"`, so five distinct operators collapsed into one entity -
    which is why the live 경쟁구도 card had a sentence where a ranking should
    have been, with no comparison points behind it at all.

    Which column is the row's identity is settled by the table's own header,
    not by position: `구 분` is filler that names no column, `유료방송 사업자`
    names one. So among the leading label columns, the last one carrying a
    header of its own wins, and a table that gives none keeps the first
    column exactly as before.
    """
    candidates: list[tuple[str, int, bool]] = []
    for column, cell in enumerate(cells):
        # A merged cell that wrapped in the source carries a line break as
        # markup. Left in, `-0.10%p<br>-` no longer reads as a run of digits
        # and was accepted as an entity name.
        stripped = re.sub(r"<\s*br\s*/?\s*>", " ", cell).strip()
        if stripped in _TABLE_FILLER_CELLS or not stripped:
            continue
        # The leading run of label columns ends at the first cell holding a
        # figure; a later text cell is a value, not the row's name.
        if re.fullmatch(r"[\d,.\s%p()-]+", stripped):
            break
        has_delta = "증감" in stripped
        label = re.sub(r"[(（][^)）]*[)）]", "", stripped).strip()
        if not label or re.fullmatch(r"[\d,.\s]+", label):
            return None if not candidates else candidates[-1]
        candidates.append((label, column, has_delta))
    if not candidates:
        return None
    named = [
        candidate for candidate in candidates
        if criteria and candidate[1] < len(criteria)
        and criteria[candidate[1]].strip() not in _TABLE_FILLER_CELLS
    ]
    return named[-1] if named else candidates[0]


def _promotable_table_metric(label: str, subject: str | None) -> bool:
    """Reject the row/column fragments that are not facts on their own."""
    text = (label or "").strip()
    if not text or text in _TABLE_FILLER_CELLS:
        return False
    if re.fullmatch(r"[\d,.\s%p]+", text):
        return False
    if not re.search(r"[가-힣A-Za-z]", text):
        return False
    if subject is not None and re.fullmatch(r"[\d,.\s]+", subject.strip()):
        return False
    # Same completeness rules as the sentence path, read in table context so
    # a row genuinely named "증감폭" survives while a run of data cells that
    # landed in a header slot does not.
    if not _semantically_complete_label(text, context="table"):
        return False
    if subject and not _semantically_complete_label(subject, context="table"):
        return False
    return True


def _table_row_points(
    claim: dict, passage_text: str, document_text: str = ""
) -> tuple[list[dict], list[dict]] | None:
    """Structure one table row into metric points and comparison candidates."""
    quote = claim.get("evidence_quote") or ""
    serialized = _parse_serialized_table_row(quote)
    if serialized is None and not _TABLE_ROW_RE.match(quote):
        return None
    if serialized is not None:
        # This shape carries its own column headers, so it needs no lookup
        # in the passage; the unit still comes from the caption if there is
        # one, exactly as for a pipe-delimited row.
        serialized_headers, cells = serialized
        headers = [serialized_headers]
        caption_unit = None
        # A serialized row carries no table body, so nothing here can prove
        # what a percentage column would be a share of.
        denominator = None
        if passage_text:
            caption = _CAPTION_UNIT_RE.search(passage_text)
            caption_unit = caption.group(1).strip() if caption else None
    else:
        # Passage first, then the whole document. Evidence passages are cut
        # for retrieval, not along table boundaries: live-verified 2026-08-10
        # the 보도자료's caption (line 37) and its two header rows (39, 41)
        # landed in a different passage from the IPTV row (42), so every
        # figure in that table came back with `period="시점 미상"` and no
        # criterion - which is what starved comparison recovery and left the
        # KPI label as bare "IPTV". Widening the lookup does not widen what
        # counts as the same table: `_table_context` walks up only while the
        # lines above are still table rows, so it stops at the blank line or
        # prose separating one table from the next, and its caption search is
        # bounded to that table's own head.
        context = _table_context(passage_text, quote) if passage_text else None
        # Finding the row is not the same as finding its table. A passage cut
        # to the row itself locates it and returns no headers at all, so the
        # test has to be "did this yield headers", not "did this return".
        if (context is None or not context[0]) and document_text:
            wider = _table_context(document_text, quote)
            if wider is not None and wider[0]:
                context = wider
        headers, caption_unit, denominator = (
            context if context is not None else ([], None, None)
        )
        cells = _split_table_cells(quote)
    # Headers first: which of the leading columns is the row's identity is a
    # question only the header row can answer.
    periods, criteria = _column_headers(headers, len(cells))
    named = _table_row_label(cells, criteria)
    if named is None:
        return None
    entity, label_column, row_states_delta = named
    metrics: list[dict] = []
    comparisons: list[dict] = []
    for column, cell in enumerate(cells):
        if column == label_column or cell.strip() in _TABLE_FILLER_CELLS:
            continue
        matches = [m for m in _TABLE_CELL_NUMBER_RE.finditer(cell) if m.group("value")]
        if not matches:
            continue
        period = periods[column] if column < len(periods) else ""
        criterion = criteria[column] if column < len(criteria) else ""
        for order, match in enumerate(matches):
            raw_unit = match.group("unit")
            # A parenthesised percentage beside a bare count is the row's
            # own stated change, and only when the row says so.
            is_delta = order > 0 and bool(raw_unit) and "%" in raw_unit
            if order > 0 and not (is_delta and row_states_delta):
                continue
            unit = _canonical_recovered_unit(raw_unit) if raw_unit else caption_unit
            label = f"{entity} {criterion}".strip() if criterion else entity
            if is_delta:
                label = f"{label} 증감률"
            if not _promotable_table_metric(label, entity):
                continue
            value = float(match.group("value").replace(",", ""))
            if value.is_integer():
                value = int(value)
            metrics.append({
                "label": label,
                "subject": entity,
                "period": period or "시점 미상",
                "value": value,
                "unit": unit,
                "is_forecast": False,
                "value_type": "actual",
                "is_relative": is_delta,
                "comparison_period": None,
                "value_origin": "source",
                # A share, only when three structural facts agree: the table
                # proved a whole exists (`denominator`), this column names
                # itself a composition, and the reading is not a rate. A
                # growth column sits in the same table as a share column, so
                # the table alone is not enough - and `is_delta` covers the
                # parenthesised change written beside a count.
                "share_of": (
                    denominator
                    if (
                        denominator
                        and unit == "%"
                        and not is_delta
                        and _SHARE_CRITERION_RE.search(criterion)
                        and not _RATE_CRITERION_RE.search(criterion)
                    )
                    else None
                ),
                "evidence_claim_id": claim.get("claim_id"),
            })
            # Same name test the metric path applies. A comparison row is
            # read by a human as "this entity, this figure", so an entity
            # that is really a stray delta cell has to be refused here too.
            if (
                criterion and period and not is_delta
                and _semantically_complete_label(entity, context="table")
            ):
                comparisons.append({
                    "entity": entity,
                    "criterion": f"{criterion} {period}".strip(),
                    "value": f"{match.group('value')}{unit or ''}".strip(),
                    "level": None,
                    "evidence_claim_id": claim.get("claim_id"),
                    "_unit": unit,
                })
    return metrics, comparisons


def _passage_lookup(evidence_passages: list[dict] | None) -> dict[str, str]:
    return {
        str(passage.get("passage_id")): passage.get("text") or ""
        for passage in evidence_passages or []
    }


def _dedupe_metric_points(points: list[dict]) -> list[dict]:
    """Collapse identical readings, keep genuinely different ones.

    Identity is (label, subject, period, unit, value): a table repeated in
    two chunks of the same PDF restates the same reading, but two periods of
    the same series are different facts and both must survive.
    """
    seen: set[tuple] = set()
    unique: list[dict] = []
    for point in points:
        key = (
            point.get("label"), point.get("subject"), point.get("period"),
            point.get("unit"), point.get("value"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(point)
    return unique


def _recovered_table_comparison_points(comparisons: list[dict]) -> list[dict]:
    """Only a criterion two named rows actually share becomes a comparison.

    Requires the same criterion, the same period (both are already baked
    into `criterion` by _table_row_points), a compatible unit and at least
    two distinct entities - so a single-row table never invents a rivalry.
    """
    grouped: dict[tuple[str, str | None], list[dict]] = {}
    for item in comparisons:
        grouped.setdefault((item["criterion"], item.get("_unit")), []).append(item)
    kept: list[dict] = []
    for group in grouped.values():
        if len({item["entity"] for item in group}) < 2:
            continue
        for item in group:
            kept.append({key: value for key, value in item.items() if key != "_unit"})
    return kept


def _recovered_metric_points(
    grounded_claims: list[dict],
    evidence_passages: list[dict] | None = None,
    document_text: str = "",
) -> list[dict]:
    """Deterministically structure figures from already-verified quotes.

    Solar can return sound `claim_type=metric` claims while leaving the
    sibling `metric_points` array empty. The quote has already passed exact
    source verification, so parsing literal value+unit pairs here adds no new
    fact. It only restores the structured handoff needed by dashboard blocks.
    """
    recovered: list[dict] = []
    passages = _passage_lookup(evidence_passages)
    for claim in grounded_claims:
        if claim.get("claim_type") not in {"metric", "comparison"}:
            continue
        quote = claim.get("evidence_quote") or ""
        # A pipe-delimited row is read against its own table's headers; the
        # sentence parser below would read its commas as label boundaries.
        passage_text = passages.get(str(claim.get("evidence_passage_id")), "")
        table = _table_row_points(claim, passage_text, document_text)
        if table is not None:
            recovered.extend(table[0])
            continue
        matches = list(_GROUNDED_METRIC_RE.finditer(quote))
        list_contexts = _list_metric_contexts(quote, matches)
        base_label = (
            _metric_label_near(quote, matches[0].start(), matches[0].end(), claim.get("claim") or "수치")
            if matches else claim.get("claim") or "수치"
        )
        last_label: str | None = None
        for index, match in enumerate(matches):
            unit_text = match.group("unit").casefold()
            next_match = matches[index + 1] if index + 1 < len(matches) else None
            if (
                unit_text.startswith(("hour", "시간"))
                and next_match is not None
                and next_match.group("unit").casefold().startswith(("minute", "분"))
                and re.fullmatch(r"\s*(?:and\s*)?", quote[match.end():next_match.start()], re.IGNORECASE)
            ):
                continue
            value = float(match.group("value").replace(",", ""))
            metric_start = match.start()
            if unit_text.startswith(("minute", "분")) and index > 0:
                previous = matches[index - 1]
                between = quote[previous.end():match.start()]
                if (
                    previous.group("unit").casefold().startswith(("hour", "시간"))
                    and re.fullmatch(r"\s*(?:and\s*)?", between, re.IGNORECASE)
                ):
                    value += float(previous.group("value").replace(",", "")) * 60
                    metric_start = previous.start()
            if value.is_integer():
                value = int(value)
            local_label = _metric_label_near(quote, metric_start, match.end(), "")
            if (
                local_label.casefold() in _WEAK_METRIC_LABELS
                or len(local_label) < 2
                or not _semantically_complete_label(local_label)
            ):
                # Cleared rather than kept: a fragment makes a worse subject
                # than no subject at all, and `subject` is what composition
                # and comparison grouping key on.
                local_label = ""
            canonical_unit = (
                "분"
                if metric_start != match.start()
                else _canonical_recovered_unit(match.group("unit"))
            )
            if index in list_contexts and canonical_unit != "%p":
                label, subject = list_contexts[index]
                # The list-context path builds its own item name, so it needs
                # the same completeness gate as `local_label` above.
                if not _semantically_complete_label(subject or ""):
                    subject = None
                if not _semantically_complete_label(label or ""):
                    label = base_label
                last_label = label
            elif canonical_unit == "%p":
                label = f"{last_label or base_label} 증감폭"
                subject = None
            else:
                label = local_label or last_label or base_label
                subject = local_label or None
                last_label = label
            is_relative, comparison_period = relative_metric_context(quote)
            if (
                is_relative and canonical_unit in {"%", "%p", "배"}
                and not re.search(r"(?:CAGR|YoY|성장률|증가율|감소율|증감률|증감폭)", label, re.I)
            ):
                label = f"{label} 증감률"
            recovered.append({
                "label": label,
                "subject": subject,
                "period": _nearest_period(quote, metric_start, match.end()),
                "value": value,
                "unit": canonical_unit,
                "is_forecast": any(
                    marker in quote.casefold()
                    for marker in ("전망", "예상", "목표", "추정", "forecast", "estimate")
                ),
                "value_type": metric_value_type(quote),
                "is_relative": is_relative,
                "comparison_period": comparison_period,
                "value_origin": "source",
                "share_of": None,
                "evidence_claim_id": claim["claim_id"],
                "evidence_quote": quote,
            })
    return _dedupe_metric_points(recovered)


def _recovered_comparison_points(
    grounded_claims: list[dict],
    evidence_passages: list[dict] | None = None,
    document_text: str = "",
) -> list[dict]:
    """Comparisons a table states outright, for when the model emits none.

    Live-verified 2026-08-10: Solar returned `comparison_points: []` for
    every document of a 보도자료 whose tables compare IPTV/SO/위성 and
    KT/SKB/LGU+ on one shared 점유율 column, so every comparison-shaped
    block fell back to prose. Unlike metric recovery this had no
    deterministic counterpart at all - `_verified_comparison_points` only
    validates what the model already produced.
    """
    passages = _passage_lookup(evidence_passages)
    candidates: list[dict] = []
    for claim in grounded_claims:
        passage_text = passages.get(str(claim.get("evidence_passage_id")), "")
        table = _table_row_points(claim, passage_text, document_text)
        if table is not None:
            candidates.extend(table[1])
    return _recovered_table_comparison_points(candidates)


def _merge_metric_points(verified: list[dict], recovered: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple] = set()
    def unit_family(point: dict) -> str:
        unit = re.sub(r"[\s.]", "", str(point.get("unit") or "")).casefold()
        if unit in {"%p", "pp", "%pt", "퍼센트포인트"}:
            return "%p"
        if unit in {"percent", "퍼센트"}:
            return "%"
        return unit

    verified_value_keys = {
        (
            point.get("value"), unit_family(point), point.get("evidence_claim_id"),
            point.get("is_relative", False), point.get("comparison_period"),
        )
        for point in verified
    }
    supplements = [
        point for point in recovered
        if (
            point.get("value"), unit_family(point), point.get("evidence_claim_id"),
            point.get("is_relative", False), point.get("comparison_period"),
        )
        not in verified_value_keys
    ]
    for point in [*verified, *supplements]:
        key = (
            point.get("period"), point.get("value"),
            unit_family(point),
            point.get("evidence_claim_id"),
            point.get("is_relative", False),
            point.get("comparison_period"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(point)
    return merged


def _clean_metric_dimension(value: object, *, maximum: int) -> str:
    """Keep chart dimensions compact without changing any numeric fact.

    URL/path fragments and whole prose sentences are valid evidence text but
    invalid chart axes.  Rejecting them here removes only the broken
    structured projection; the grounded claim and quote remain available in
    the report/evidence layer.
    """
    return clean_dimension(value, maximum=maximum)


def _displayable_metric_points(points: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for point in points:
        label = _clean_metric_dimension(point.get("label"), maximum=60)
        if not label:
            continue
        subject = _clean_metric_dimension(point.get("subject"), maximum=40)
        cleaned.append({**point, "label": label, "subject": subject or None})
    return cleaned


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


def _namespace_chunk_evidence(
    data: dict,
    grounded_claims: list[dict],
    claim_id_prefix: str,
    evidence_location_prefix: str,
) -> tuple[dict, list[dict]]:
    claim_id_map = {
        claim["claim_id"]: f"{claim_id_prefix}:{claim['claim_id']}"
        for claim in grounded_claims
    }
    namespaced_claims = []
    for claim in grounded_claims:
        location = claim.get("evidence_location")
        passage_id = claim.get("evidence_passage_id")
        namespaced_claims.append(
            {
                **claim,
                "claim_id": claim_id_map[claim["claim_id"]],
                # A chunked PDF renames every claim; a parent link left on the
                # old name would point at nothing and be dropped downstream.
                "parent_claim_id": claim_id_map.get(claim.get("parent_claim_id")),
                "evidence_passage_id": (
                    f"{claim_id_prefix}:{passage_id}" if passage_id else None
                ),
                "evidence_location": (
                    f"{evidence_location_prefix} / {location}"
                    if location
                    else evidence_location_prefix
                ),
            }
        )

    def _remap_points(points: list[dict]) -> list[dict]:
        remapped = []
        for point in points:
            evidence_claim_id = claim_id_map.get(point.get("evidence_claim_id"))
            if evidence_claim_id:
                remapped.append({**point, "evidence_claim_id": evidence_claim_id})
        return remapped

    return (
        {
            **data,
            "metric_points": _remap_points(data.get("metric_points", [])),
            "comparison_points": _remap_points(data.get("comparison_points", [])),
        },
        namespaced_claims,
    )


_CLAIM_TYPES = {
    "key_point", "business_impact", "risk", "opportunity", "strength",
    "weakness", "comparison", "metric", "factor", "action", "monitoring",
}


def _load_analysis_json(content: str | None) -> dict:
    """Accept JSON-schema output plus harmless provider wrappers.

    Solar's OpenAI-compatible endpoint can return fenced JSON or a short prose
    prefix even when response_format was supplied. We unwrap those forms but
    never guess how to complete truncated JSON.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise TypeError("analysis payload must be a JSON object")
    return value


def _normalize_analysis_payload(data: dict) -> dict:
    """Fill provider-omitted metadata without inventing evidence.

    Items missing factual core fields are discarded. Only schema bookkeeping
    (null/default flags, confidence, empty arrays) is supplied.
    """
    claims: list[dict] = []
    for raw in data.get("grounded_claims") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("claim_type") not in _CLAIM_TYPES:
            continue
        if not all(isinstance(raw.get(key), str) and raw.get(key).strip()
                   for key in ("claim_id", "claim", "evidence_quote")):
            continue
        claim = dict(raw)
        claim.setdefault("evidence_passage_id", None)
        claim.setdefault("evidence_location", None)
        claim.setdefault("as_of_date", None)
        # TODO(confidence-inversion): since `confidence` was dropped from the
        # model's claim schema, nothing ever supplies it here, so every
        # model-produced claim lands on "low" - while a claim minted by
        # `_recover_missing_metric_claims` is hard-coded "high" (see the
        # matching note there). That ordering is backwards and means nothing.
        # It is inert today: `GroundedClaim.confidence` reaches
        # `SynthesisClaim`/`SynthesisConclusion` (core/synthesis/
        # synthesizer.py:187,362) and no block, eligibility rule or renderer
        # reads either. Anything that starts reading it has to fix this first
        # - the value is bookkeeping, not a judgement about the claim.
        if claim.get("confidence") not in {"low", "medium", "high"}:
            claim["confidence"] = "low"
        claim.setdefault("parent_claim_id", None)
        claim.setdefault("importance", None)
        claim.setdefault("importance_basis", None)
        claims.append(claim)

    metrics: list[dict] = []
    for raw in data.get("metric_points") or []:
        if not isinstance(raw, dict):
            continue
        if not isinstance(raw.get("label"), str) or not isinstance(raw.get("period"), str):
            continue
        if not isinstance(raw.get("value"), (int, float)) or isinstance(raw.get("value"), bool):
            continue
        if not isinstance(raw.get("evidence_claim_id"), str):
            continue
        point = dict(raw)
        point.setdefault("subject", None)
        point.setdefault("unit", "")
        point.setdefault("is_forecast", False)
        value_type = point.get("value_type")
        if value_type not in {"actual", "estimate", "forecast", "target", "guidance"}:
            value_type = "forecast" if point["is_forecast"] else "actual"
        point["value_type"] = value_type
        point.setdefault("is_relative", False)
        point.setdefault("comparison_period", None)
        point["value_origin"] = "source"
        point.setdefault("share_of", None)
        metrics.append(point)

    comparisons: list[dict] = []
    for raw in data.get("comparison_points") or []:
        if not isinstance(raw, dict):
            continue
        if not all(isinstance(raw.get(key), str) and raw.get(key).strip()
                   for key in ("entity", "criterion", "value", "evidence_claim_id")):
            continue
        point = dict(raw)
        if point.get("level") not in {None, "low", "medium", "high"}:
            point["level"] = None
        comparisons.append(point)

    relevance = data.get("relevance_level")
    if relevance not in {"direct", "partial", "background", "irrelevant"}:
        relevance = "partial" if claims else "background"
    confidence = data.get("analysis_confidence")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "summary": str(data.get("summary") or "")[:500],
        "relevance_level": relevance,
        "grounded_claims": claims,
        "covered_information_needs": [
            value for value in (data.get("covered_information_needs") or [])
            if isinstance(value, str)
        ],
        "metric_points": metrics,
        "comparison_points": comparisons,
        "analysis_confidence": confidence,
    }


def _analyze_document(
    client: OpenAI,
    system_prompt: str,
    document: SourceDocument,
    question: str,
    information_needs: list[str],
    *,
    evidence_requirements: list[str] | None = None,
    content_override: str | None = None,
    claim_id_prefix: str | None = None,
    evidence_location_prefix: str | None = None,
) -> DocumentAnalysis:
    analyzed_content = (
        content_override
        if content_override is not None
        else _trim_content(_clean_analysis_content(document.content))
    )
    evidence_passages = _split_evidence_passages(analyzed_content)
    analysis_max_tokens = _analysis_max_tokens(analyzed_content)
    user_content = json.dumps(
        {
            "question": question,
            "required_information_needs": information_needs,
            "evidence_requirements": evidence_requirements or [],
            "document": {
                "doc_id": document.doc_id,
                "title": document.title,
                "published_at": document.published_at.isoformat() if document.published_at else None,
                "evidence_passages": evidence_passages,
            },
            "analysis_instruction": (
                "질문·required_information_needs·evidence_requirements에 직접 필요한 근거를 추출하라. "
                "수치·시점·단위, 비교의 양쪽 대상, 순위·요인·날짜 정보를 우선하고 중복 주장은 만들지 마라. "
                "항목 수를 줄이지 말고 각 claim·인용·이유의 문장만 최소 충분 길이로 간결하게 써라. "
                "질문이 여러 측면을 요구할 때 문서가 그중 한 측면만 직접 뒷받침해도 partial이며, "
                "그 근거를 추출하라. 문서 하나가 질문 전체를 답하지 못한다는 이유로 비우지 마라. "
                "질문 일부에 직접 관련된 수치가 있으면 metric claim과 metric_points를 비우지 마라. "
                "한 문장·표에서 같은 지표로 여러 항목을 비교하면 공통 지표명은 같은 label, "
                "각 항목명은 subject로 분리해 모든 값을 보존하라. "
                "같은 metric이 문서 안에서 표현만 달라져도 의미와 단위가 실제로 같다면 label을 "
                "하나의 간결한 공통 metric명으로 정규화하되, 서로 다른 정의를 유사한 단어만으로 합치지 마라. "
                "각 metric의 value_type은 actual/estimate/forecast/target/guidance 중 원문 표현에 맞게 "
                "보존하고 미래·목표 수치를 actual로 표시하지 마라. "
                "YoY/CAGR/전년 대비 증감률/배수처럼 원문이 상대 변화를 명시하면 is_relative=true, "
                "comparison_period에는 원문 비교 기준만 기록하고 value_origin은 source로 두어라. "
                "상대값으로 절대 기준값이나 누락 시점을 역산하지 마라. 여러 연도의 성장률이 각각 "
                "명시된 경우에는 성장률 자체를 동일 label의 시계열로 보존하라. "
                "share_of는 원문이 하나의 전체와 그 구성요소를 명시한 경우에만 그 전체 이름으로 채워라. "
                "여러 기업·국가·기술을 공통 기준으로 비교한 자료는 entity와 criterion을 유지해 "
                "항목별 comparison_points로 분리하라. "
                "원문이 후보의 기준을 '매우 높음/높음/중간 수준/낮음/매우 낮음' 또는 "
                "high/medium/low로 직접 평가한 경우에만 해당 comparison point의 level로 정규화하라. "
                "시장 규모나 숫자가 크다는 이유로 level을 만들지 마라. "
                "원문이 '때문에', '로 인해', '영향으로', 'caused', 'due to', 'driven by', "
                "'resulted in', 'led to'처럼 인과를 직접 말하면 원인 claim과 "
                "결과 claim을 분리하고 결과의 parent_claim_id를 원인 claim_id로 연결하라. 두 현상이 "
                "같이 증가하거나 순서대로 언급됐다는 사실만으로 parent_claim_id를 만들지 마라. "
                "'~에 따라'는 문장 전체가 결과를 주장할 때만 인과로 보고, '~에 따르면'은 인과가 아니다. "
                f"{SWOT_COMPLETENESS_INSTRUCTION} "
                f"{COMPARISON_COMPLETENESS_INSTRUCTION} "
                f"{TABLE_COMPLETENESS_INSTRUCTION} "
                "명시되지 않은 값은 추정하거나 계산하지 말 것. "
                "metric_points의 모든 수치는 값·단위·시점을 함께 직접 인용한 claim_type=metric "
                "grounded_claim을 먼저 만들고 그 claim_id를 evidence_claim_id로 연결하라. "
                "comparison_points는 claim_type=comparison인 claim_id를 참조해야 한다. "
                "evidence_quote는 반드시 입력 document.evidence_passages 중 하나에서 짧게 그대로 "
                "복사하고 그 passage_id를 evidence_passage_id에 기록하라. "
                "블록에 필요한 서로 다른 근거는 임의 개수 제한 없이 보존하라. "
                "covered_information_needs는 입력 목록에 있는 문자열만 그대로 선택하라."
            ),
        },
        ensure_ascii=False,
    )
    # Escalates to the dense ceiling only if the first attempt is actually
    # cut off (finish_reason == "length") - see call_with_truncation_retry's
    # docstring. If _analysis_max_tokens() already picked the dense ceiling,
    # there is nowhere higher to escalate to; the ladder stays one rung and
    # behavior is unchanged from before this fix.
    token_ceilings = (
        [analysis_max_tokens]
        if analysis_max_tokens >= _DENSE_ANALYSIS_MAX_TOKENS
        else [analysis_max_tokens, _DENSE_ANALYSIS_MAX_TOKENS]
    )
    try:
        response, analysis_max_tokens = call_with_truncation_retry(
            lambda max_tokens: client.chat.completions.create(
                model=_model(),
                max_tokens=max_tokens,
                temperature=0,
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
            ),
            token_ceilings,
        )
    except Exception as exc:  # noqa: BLE001
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=system_prompt,
            user_content=user_content,
            schema=_ANALYSIS_SCHEMA,
            requested_max_tokens=analysis_max_tokens,
            response=locals().get("response"),
            outcome="failed",
            error_type=type(exc).__name__,
        )
        raise PipelineStageError(stage=_STAGE, reason=f"analysis API call failed for doc '{document.doc_id}'", detail=str(exc)) from exc

    message = response.choices[0].message
    if getattr(message, "refusal", None):
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=system_prompt,
            user_content=user_content,
            schema=_ANALYSIS_SCHEMA,
            requested_max_tokens=analysis_max_tokens,
            response=response,
            outcome="refused",
        )
        raise PipelineStageError(stage=_STAGE, reason=f"analysis refused for doc '{document.doc_id}'", detail=message.refusal)
    try:
        data = _normalize_analysis_payload(_load_analysis_json(message.content))
        grounded_claims = _verified_claims(data, document, evidence_passages)
        grounded_claims = _repair_failed_claim_quotes(
            client,
            document,
            data.get("grounded_claims", []),
            grounded_claims,
            evidence_passages,
        )
        grounded_claims = _recover_missing_metric_claims(
            grounded_claims,
            evidence_passages,
            question,
            information_needs,
        )
        grounded_claims = _verified_relations(grounded_claims)
        if claim_id_prefix and evidence_location_prefix:
            data, grounded_claims = _namespace_chunk_evidence(
                data,
                grounded_claims,
                claim_id_prefix,
                evidence_location_prefix,
            )
        relevance_level = data["relevance_level"]
        relevant_to_question = relevance_level != "irrelevant"
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
        metric_points = _displayable_metric_points(
            _merge_metric_points(
                _verified_metric_points(
                    data, analyzed_content, grounded_claims, evidence_passages
                ),
                _recovered_metric_points(
                    grounded_claims, evidence_passages, analyzed_content
                ),
            )
        )
        comparison_points = _verified_comparison_points(data, grounded_claims)
        # Additive, not either/or. As a fallback this ran only when the
        # model produced nothing, so live-verified 2026-08-10 a single model
        # comparison (ARPU) suppressed the three-operator 점유율 comparison
        # sitting in the same document's table, and every comparison-shaped
        # block fell back to prose. The model's own reading is never
        # overwritten - it is listed first and identical rows merge.
        comparison_points = normalize_comparison_points([
            *comparison_points,
            *_recovered_comparison_points(
                grounded_claims, evidence_passages, analyzed_content
            ),
        ])
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=system_prompt,
            user_content=user_content,
            schema=_ANALYSIS_SCHEMA,
            requested_max_tokens=analysis_max_tokens,
            response=response,
            counts={
                "passages": len(evidence_passages),
                "raw_claims": raw_claim_count,
                "verified_claims": len(grounded_claims),
                "metrics": len(metric_points),
                "comparisons": len(comparison_points),
            },
        )
        return DocumentAnalysis(
            doc_id=document.doc_id,
            summary=data["summary"],
            relevant_to_question=relevant_to_question,
            relevance_level=relevance_level,
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
            metric_points=metric_points,
            comparison_points=comparison_points,
            factors=_claim_texts(grounded_claims, "factor"),
            recommended_actions=action_claims,
            monitoring_indicators=_claim_texts(grounded_claims, "monitoring"),
            evidence=[claim["evidence_quote"] for claim in grounded_claims],
            analysis_confidence=data.get("analysis_confidence", "low"),
        )
    except (TypeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=system_prompt,
            user_content=user_content,
            schema=_ANALYSIS_SCHEMA,
            requested_max_tokens=analysis_max_tokens,
            response=response,
            outcome="invalid_response",
            error_type=type(exc).__name__,
        )
        preview = re.sub(r"\s+", " ", str(message.content or ""))[:600]
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"analysis response for doc '{document.doc_id}' did not match the expected schema",
            detail=f"{type(exc).__name__}: {exc}; response_preview={preview}",
        ) from exc


def _unique_text(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _merge_chunk_analyses(
    document: SourceDocument,
    analyses: list[DocumentAnalysis],
    information_needs: list[str],
    *,
    incomplete: bool,
) -> DocumentAnalysis:
    # A chunk the model itself judged irrelevant contributes nothing but noise.
    # Live-observed: one chunk of a magazine issue produced a claim about a
    # dancer's floor technique, which then travelled through synthesis into the
    # report as an "opportunity". Its own relevance_level said `irrelevant`;
    # nothing was reading it. Claims, metrics and comparisons are now taken
    # only from chunks that cleared their own gate - and if every chunk failed
    # it, the document keeps them all, because then the judgement is about the
    # document as a whole and is made once, downstream.
    contributing = [
        analysis for analysis in analyses if analysis.relevance_level != "irrelevant"
    ] or analyses
    dropped = len(analyses) - len(contributing)
    if dropped:
        print(
            f"[analyzer] '{document.doc_id}': {dropped} chunk(s) judged irrelevant and "
            "excluded from the merged analysis",
            file=sys.stderr,
        )

    claim_by_key: dict[tuple[str, str], object] = {}
    claim_id_remap: dict[str, str] = {}
    merged_claims = []
    for analysis in contributing:
        for claim in analysis.grounded_claims:
            key = (claim.claim_type, _normalized_text(claim.evidence_quote))
            existing = claim_by_key.get(key)
            if existing is not None:
                claim_id_remap[claim.claim_id] = existing.claim_id
                continue
            claim_by_key[key] = claim
            claim_id_remap[claim.claim_id] = claim.claim_id
            merged_claims.append(claim)

    valid_claim_ids = {claim.claim_id for claim in merged_claims}
    merged_metrics = []
    seen_metrics: set[tuple] = set()
    merged_comparisons = []
    seen_comparisons: set[tuple] = set()
    for analysis in contributing:
        for point in analysis.metric_points:
            evidence_claim_id = claim_id_remap.get(
                point.evidence_claim_id or "", point.evidence_claim_id
            )
            if evidence_claim_id not in valid_claim_ids:
                continue
            remapped = point.model_copy(
                update={"evidence_claim_id": evidence_claim_id}
            )
            key = (
                remapped.label,
                remapped.subject,
                remapped.period,
                remapped.value,
                remapped.unit,
                remapped.is_relative,
                remapped.comparison_period,
                remapped.value_origin,
                remapped.evidence_claim_id,
            )
            if key not in seen_metrics:
                seen_metrics.add(key)
                merged_metrics.append(remapped)
        for point in analysis.comparison_points:
            evidence_claim_id = claim_id_remap.get(
                point.evidence_claim_id or "", point.evidence_claim_id
            )
            if evidence_claim_id not in valid_claim_ids:
                continue
            remapped = point.model_copy(
                update={"evidence_claim_id": evidence_claim_id}
            )
            key = (
                remapped.entity,
                remapped.criterion,
                remapped.value,
                remapped.level,
                remapped.evidence_claim_id,
            )
            if key not in seen_comparisons:
                seen_comparisons.add(key)
                merged_comparisons.append(remapped)

    relevance_rank = {"irrelevant": 0, "background": 1, "partial": 2, "direct": 3}
    relevance_level = max(
        (analysis.relevance_level or "irrelevant" for analysis in analyses),
        key=lambda value: relevance_rank[value],
    )
    relevant_to_question = relevance_level != "irrelevant"
    relevant_analyses = [
        analysis for analysis in analyses if analysis.relevance_level != "irrelevant"
    ]
    covered_set = {
        need
        for analysis in analyses
        for need in analysis.covered_information_needs
    }
    requested_needs = list(dict.fromkeys(information_needs))
    covered_information_needs = [
        need for need in requested_needs if need in covered_set
    ]
    missing_information_needs = [
        need for need in requested_needs if need not in covered_set
    ]
    claim_dicts = [claim.model_dump() for claim in merged_claims]
    has_grounding = bool(merged_claims)
    if not relevant_to_question:
        validation_status = "not_applicable"
    elif not has_grounding:
        validation_status = "insufficient_grounding"
    elif incomplete or any(
        analysis.analysis_validation_status == "partial_grounding"
        for analysis in analyses
    ):
        validation_status = "partial_grounding"
    else:
        validation_status = "verified"

    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    grounded_confidences = [
        analysis.analysis_confidence
        for analysis in relevant_analyses
        if analysis.grounded_claims and analysis.analysis_confidence
    ]
    analysis_confidence = (
        min(grounded_confidences, key=lambda value: confidence_rank[value])
        if grounded_confidences
        else "low"
    )
    # `incomplete` used to be reported by appending a sentence to
    # `relevance_reason`, which nothing downstream read. It still reaches
    # every consumer that acts on it: it forces `validation_status` to
    # "partial_grounding" above, which is what the pipeline and the
    # dashboard's diagnostics actually branch on.
    return DocumentAnalysis(
        doc_id=document.doc_id,
        source_id=document.source_id,
        source_title=document.title,
        source_url=document.url,
        reliability_tier=document.reliability_tier,
        summary=" ".join(_unique_text([analysis.summary for analysis in relevant_analyses])),
        relevant_to_question=relevant_to_question,
        relevance_level=relevance_level,
        grounded_claims=merged_claims,
        covered_information_needs=covered_information_needs,
        missing_information_needs=missing_information_needs,
        analysis_validation_status=validation_status,
        usable_for_synthesis=relevant_to_question and has_grounding,
        key_points=_claim_texts(claim_dicts, "key_point"),
        business_impact=_joined_claims(claim_dicts, "business_impact"),
        risk=_joined_claims(claim_dicts, "risk"),
        opportunity=_joined_claims(claim_dicts, "opportunity"),
        strength=_joined_claims(claim_dicts, "strength"),
        weakness=_joined_claims(claim_dicts, "weakness"),
        metric_points=merged_metrics,
        comparison_points=merged_comparisons,
        factors=_claim_texts(claim_dicts, "factor"),
        recommended_actions=_claim_texts(claim_dicts, "action"),
        monitoring_indicators=_claim_texts(claim_dicts, "monitoring"),
        evidence=[claim.evidence_quote for claim in merged_claims],
        analysis_confidence=analysis_confidence,
    )


def _analyze_chunked_document(
    client: OpenAI,
    system_prompt: str,
    document: SourceDocument,
    question: str,
    information_needs: list[str],
    evidence_requirements: list[str] | None = None,
) -> DocumentAnalysis:
    is_pdf = _is_pdf_document(document)
    content = (document.content or "") if is_pdf else _clean_analysis_content(document.content)
    chunks = _split_pdf_content(content)
    # PDFs keep their existing cap for very long files; everything then passes
    # the same can-this-answer gate, so a magazine issue costs calls only for
    # the pages that could contain an answer.
    candidates = (
        _selected_pdf_chunks(chunks, question, information_needs)
        if is_pdf else list(enumerate(chunks, 1))
    )
    terms = _question_terms(question, information_needs)
    candidates = _periodical_chunks(candidates, terms)
    selected_chunks = [item for item in candidates if _chunk_can_answer(item[1], terms)]
    if not selected_chunks:
        # Every chunk failed the gate, which is more likely to mean the terms
        # were unusual than that the document is empty. Fall back to analysing
        # what was selected rather than returning nothing.
        selected_chunks = candidates
    kind = "PDF" if is_pdf else "document"
    skipped = len(candidates) - len(selected_chunks)
    print(
        f"[analyzer] {kind} '{document.doc_id}' split into {len(chunks)} chunk(s); "
        f"analyzing {len(selected_chunks)}"
        + (f" ({skipped} skipped: no question term and no figure)" if skipped else ""),
        file=sys.stderr,
    )
    analyses: list[DocumentAnalysis] = []
    failures: list[PipelineStageError] = []
    for chunk_index, chunk in selected_chunks:
        prefix = f"pdf{chunk_index}" if is_pdf else f"part{chunk_index}"
        location = (
            f"PDF 청크 {chunk_index}/{len(chunks)}"
            if is_pdf else f"문서 청크 {chunk_index}/{len(chunks)}"
        )
        try:
            analyses.append(
                _analyze_document(
                    client,
                    system_prompt,
                    document,
                    question,
                    information_needs,
                    evidence_requirements=evidence_requirements,
                    content_override=chunk,
                    claim_id_prefix=prefix,
                    evidence_location_prefix=location,
                )
            )
        except PipelineStageError as exc:
            failures.append(exc)
            print(
                f"[analyzer] {kind} chunk {chunk_index}/{len(chunks)} failed for "
                f"'{document.doc_id}': {exc.reason}",
                file=sys.stderr,
            )
    if not analyses:
        if failures:
            raise failures[-1]
        raise PipelineStageError(
            stage=_STAGE,
            reason=f"document '{document.doc_id}' contained no analyzable text chunks",
        )
    return _merge_chunk_analyses(
        document,
        analyses,
        information_needs,
        incomplete=bool(failures) or len(selected_chunks) < len(chunks),
    )


def analyze(
    source_documents: list[SourceDocument],
    question: str,
    information_needs: list[str] | None = None,
    evidence_requirements: list[str] | None = None,
) -> list[DocumentAnalysis]:
    api_key = _api_key()
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"{_API_KEY_ENV_VAR} or {_FALLBACK_API_KEY_ENV_VAR} is not configured")
    client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))
    system_prompt = _load_system_prompt()
    needs = list(information_needs or [])
    requirements = list(evidence_requirements or [])
    analyses = []
    failures: list[str] = []
    for document in source_documents:
        # One document failing must not take the other four with it.
        # A mixed-source run can contain reports, rankings, surveys, and one
        # malformed page. The stage's own job is to analyse what it can;
        # whether what's left is enough is already decided downstream,
        # against the sector minimum, by code that can trigger recollection.
        try:
            if len(document.content or "") > _MAX_CONTENT_CHARS:
                analyses.append(
                    _analyze_chunked_document(
                        client, system_prompt, document, question, needs,
                        evidence_requirements=requirements,
                    )
                )
            else:
                analyses.append(
                    _analyze_document(
                        client, system_prompt, document, question, needs,
                        evidence_requirements=requirements,
                    )
                )
        except PipelineStageError as exc:
            detail = f": {exc.detail}" if exc.detail else ""
            failures.append(f"{document.doc_id}: {exc.reason}{detail}")
            print(f"[analyzer] doc '{document.doc_id}' could not be analysed: {exc.reason}{detail}",
                  file=sys.stderr)
    if not analyses:
        # Nothing survived - that genuinely is a stage failure, and the reason
        # carries every document's own error rather than only the first.
        raise PipelineStageError(
            stage=_STAGE,
            reason="no document could be analysed",
            detail="; ".join(failures),
        )
    if failures:
        print(f"[analyzer] {len(analyses)} of {len(source_documents)} documents analysed; "
              f"{len(failures)} skipped", file=sys.stderr)
    return analyses
