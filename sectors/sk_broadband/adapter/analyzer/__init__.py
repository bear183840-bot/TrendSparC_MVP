"""SK Broadband sector analyzer."""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

from common.ai_client import openai_client_kwargs
from common.content_quality_validator import (
    COMPARISON_COMPLETENESS_INSTRUCTION,
    SWOT_COMPLETENESS_INSTRUCTION,
    TABLE_COMPLETENESS_INSTRUCTION,
    strip_particle,
)
from common.contracts import DocumentAnalysis, SourceDocument
from common.errors import PipelineStageError
from sources.openai_retry import call_with_retry

_API_KEY_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_API_KEY"
_FALLBACK_API_KEY_ENV_VAR = "OPENAI_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_MODEL"
# Optional - points this stage at an OpenAI-API-compatible alternative
# provider (e.g. Upstage Solar) instead of stock OpenAI. Unset by default;
# see common/ai_client.py.
_BASE_URL_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_BASE_URL"
_DEFAULT_MODEL = "gpt-4o"
_MAX_CONTENT_CHARS = 12000
_PDF_CHUNK_OVERLAP_CHARS = 500
_DEFAULT_MAX_PDF_CHUNKS = 12
_MAX_EVIDENCE_PASSAGE_CHARS = 2_000
_MAX_REPAIR_PASSAGES_PER_CLAIM = 3
_MAX_PDF_CHUNKS_ENV_VAR = "TRENDSPARC_SK_BROADBAND_ANALYZER_MAX_PDF_CHUNKS"
_STAGE = "sectors.sk_broadband.adapter.analyzer"

_SECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _SECTOR_ROOT.parent.parent
_GLOBAL_PROMPT_PATH = _PROJECT_ROOT / "prompts" / "analyzer_system_prompt.md"
_SECTOR_PROMPT_PATH = _SECTOR_ROOT / "prompts" / "analyzer_prompt.md"

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
                        "enum": ["key_point", "business_impact", "risk", "opportunity", "strength", "weakness", "comparison", "metric", "factor", "action", "monitoring"],
                    },
                    "claim": {"type": "string"},
                    "evidence_passage_id": {
                        "type": ["string", "null"],
                        "description": "인용문을 복사한 evidence_passages의 passage_id.",
                    },
                    "evidence_quote": {"type": "string", "description": "원문에서 그대로 복사한 짧은 문장 또는 구절."},
                    "evidence_location": {"type": ["string", "null"], "description": "확인 가능한 경우 문단·절·표 위치, 아니면 null."},
                    "as_of_date": {"type": ["string", "null"], "description": "주장의 기준 시점이 명시된 경우 원문 표현, 아니면 null."},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
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
                        "description": "그 중요도로 본 이유. importance를 채웠으면 필수.",
                    },
                },
                "required": ["claim_id", "claim_type", "claim", "evidence_passage_id", "evidence_quote", "evidence_location", "as_of_date", "confidence", "parent_claim_id", "importance", "importance_basis"],
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
                    "subject": {
                        "type": ["string", "null"],
                        "description": "수치의 주체·항목(기업, 플랫폼, 연령대 등). 원문 표현을 그대로 쓰고 없으면 null.",
                    },
                    "period": {"type": "string", "description": "문서에 명시된 시점 그대로, 예: '2023년 2분기'"},
                    "value": {"type": "number"},
                    "unit": {"type": "string", "description": "예: '만 명', '억원'. 없으면 빈 문자열."},
                    "is_forecast": {
                        "type": "boolean",
                        "description": "원문이 전망·예상·목표·추정이라고 명시한 수치만 true.",
                    },
                    "share_of": {
                        "type": ["string", "null"],
                        "description": "원문이 이 비율들의 공통 전체를 명시한 경우 그 표현. 아니면 null.",
                    },
                    "evidence_claim_id": {
                        "type": "string",
                        "description": "이 수치 전체를 직접 인용한 claim_type=metric grounded_claim의 claim_id.",
                    },
                },
                "required": [
                    "label", "subject", "period", "value", "unit", "is_forecast",
                    "share_of", "evidence_claim_id",
                ],
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

_QUOTE_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "evidence_passage_id": {"type": ["string", "null"]},
                    "evidence_quote": {"type": ["string", "null"]},
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
    return os.environ.get(_MODEL_ENV_VAR, _DEFAULT_MODEL)


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
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00a0", " ").replace("\u00ad", "")
    value = re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", value)
    # PDF extraction often inserts a line break and hyphen inside one word.
    value = re.sub(r"(?<=\w)-\s*\r?\n\s*(?=\w)", "", value)
    return " ".join(value.split())


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
        response = call_with_retry(
            lambda: client.chat.completions.create(
                model=_model(),
                max_tokens=1600,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You repair source citations only. Never change a claim and never "
                            "invent or paraphrase a quote."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(repair_input, ensure_ascii=False),
                    },
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
    except Exception as exc:  # noqa: BLE001
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


def _verified_metric_points(
    data: dict, analyzed_content: str, grounded_claims: list[dict]
) -> list[dict]:
    verified: list[dict] = []
    normalized_content = _normalized_text(analyzed_content)
    metric_claims = {
        claim["claim_id"]: claim
        for claim in grounded_claims
        if claim["claim_type"] == "metric"
    }
    for point in data.get("metric_points", []):
        period = _normalized_text(str(point.get("period", "")))
        unit = _normalized_text(str(point.get("unit", "")))
        subject = _normalized_text(str(point.get("subject") or ""))
        share_of = _normalized_text(str(point.get("share_of") or ""))
        value = point.get("value")
        if not period or period not in normalized_content:
            continue
        if unit and unit not in normalized_content:
            continue
        if not isinstance(value, (int, float)) or not _number_is_in_content(float(value), analyzed_content):
            continue
        evidence_claim = metric_claims.get(point.get("evidence_claim_id"))
        if evidence_claim is None:
            continue
        quote = evidence_claim["evidence_quote"]
        normalized_quote = _normalized_text(quote)
        if period not in normalized_quote:
            continue
        if unit and unit not in normalized_quote:
            continue
        if subject and subject not in normalized_quote:
            continue
        if share_of and share_of not in normalized_quote:
            continue
        if not _number_is_in_content(float(value), quote):
            continue
        forecast_markers = (
            "전망", "예상", "목표", "추정", "계획", "가이던스", "예측",
            "forecast", "estimate",
        )
        verified.append({
            **point,
            "subject": point.get("subject") or None,
            "share_of": point.get("share_of") or None,
            "is_forecast": bool(point.get("is_forecast"))
            and any(marker in normalized_quote.casefold() for marker in forecast_markers),
            "evidence_quote": quote,
        })
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


def _analyze_document(
    client: OpenAI,
    system_prompt: str,
    document: SourceDocument,
    question: str,
    information_needs: list[str],
    *,
    target_block_shapes: list[str] | None = None,
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
    user_content = json.dumps(
        {
            "question": question,
            "required_information_needs": information_needs,
            "target_block_shapes": target_block_shapes or [],
            "document": {
                "doc_id": document.doc_id,
                "source_id": document.source_id,
                "reliability_tier": document.reliability_tier,
                "title": document.title,
                "url": document.url,
                "published_at": document.published_at.isoformat() if document.published_at else None,
                "evidence_passages": evidence_passages,
            },
            "analysis_instruction": (
                "질문·required_information_needs·target_block_shapes에 직접 필요한 근거를 추출하라. "
                "수치·시점·단위, 비교의 양쪽 대상, 순위·요인·날짜 정보를 우선하고 중복 주장은 만들지 마라. "
                f"{SWOT_COMPLETENESS_INSTRUCTION} "
                f"{COMPARISON_COMPLETENESS_INSTRUCTION} "
                f"{TABLE_COMPLETENESS_INSTRUCTION} "
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
    try:
        response = call_with_retry(lambda: client.chat.completions.create(
            model=_model(),
            max_tokens=4500,
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
        grounded_claims = _verified_claims(data, document, evidence_passages)
        grounded_claims = _repair_failed_claim_quotes(
            client,
            document,
            data.get("grounded_claims", []),
            grounded_claims,
            evidence_passages,
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
            metric_points=_verified_metric_points(data, analyzed_content, grounded_claims),
            comparison_points=_verified_comparison_points(data, grounded_claims),
            factors=_claim_texts(grounded_claims, "factor"),
            recommended_actions=action_claims,
            monitoring_indicators=_claim_texts(grounded_claims, "monitoring"),
            evidence=[claim["evidence_quote"] for claim in grounded_claims],
            action_level=data.get("action_level", "insufficient_data") if action_claims else "insufficient_data",
            analysis_confidence=data.get("analysis_confidence", "low"),
        )
    except (TypeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise PipelineStageError(stage=_STAGE, reason=f"analysis response for doc '{document.doc_id}' did not match the expected schema", detail=str(exc)) from exc


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
                remapped.period,
                remapped.value,
                remapped.unit,
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
    sentiments = _unique_text([analysis.sentiment for analysis in relevant_analyses])
    sentiment = sentiments[0] if len(sentiments) == 1 else ("mixed" if sentiments else "neutral")
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

    action_level_rank = {
        "insufficient_data": 0,
        "Monitor": 1,
        "Review": 2,
        "Prepare": 3,
        "Act": 4,
    }
    action_level = max(
        (analysis.action_level or "insufficient_data" for analysis in analyses),
        key=lambda value: action_level_rank[value],
    )
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
    relevance_reasons = _unique_text(
        [analysis.relevance_reason for analysis in analyses]
    )
    if incomplete:
        relevance_reasons.append(
            "문서가 설정된 최대 청크 수를 초과했거나 일부 청크 분석이 실패해 분석된 청크만 병합했습니다."
        )

    return DocumentAnalysis(
        doc_id=document.doc_id,
        source_id=document.source_id,
        source_title=document.title,
        source_url=document.url,
        reliability_tier=document.reliability_tier,
        summary=" ".join(_unique_text([analysis.summary for analysis in relevant_analyses])),
        sentiment=sentiment,
        relevant_to_question=relevant_to_question,
        relevance_level=relevance_level,
        relevance_reason=" ".join(relevance_reasons),
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
        action_level=action_level if _claim_texts(claim_dicts, "action") else "insufficient_data",
        analysis_confidence=analysis_confidence,
    )


def _analyze_chunked_document(
    client: OpenAI,
    system_prompt: str,
    document: SourceDocument,
    question: str,
    information_needs: list[str],
    target_block_shapes: list[str] | None = None,
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
                    target_block_shapes=target_block_shapes,
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
    target_block_shapes: list[str] | None = None,
) -> list[DocumentAnalysis]:
    api_key = _api_key()
    if not api_key:
        raise PipelineStageError(stage=_STAGE, reason=f"{_API_KEY_ENV_VAR} or {_FALLBACK_API_KEY_ENV_VAR} is not configured")
    client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))
    system_prompt = _load_system_prompt()
    needs = list(information_needs or [])
    shapes = list(target_block_shapes or [])
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
                        target_block_shapes=shapes,
                    )
                )
            else:
                analyses.append(
                    _analyze_document(
                        client, system_prompt, document, question, needs,
                        target_block_shapes=shapes,
                    )
                )
        except PipelineStageError as exc:
            failures.append(f"{document.doc_id}: {exc.reason}")
            print(f"[analyzer] doc '{document.doc_id}' could not be analysed: {exc.reason}",
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
