"""2nd-pass, AI-based entity/keyword/intent refinement — sector-agnostic.

The 1st-pass rule-based extractor (see core/entity/extractor.py) just
splits the question on whitespace, so its `keywords` rarely appear verbatim
in a real headline (e.g. "전망은?" with the question mark still attached),
and its intent classification is simple keyword matching. This step asks an
LLM to turn the raw question into clean, natural search terms AND a more
reliable intent classification in the same call — the kind of words that
would actually show up in a news article title, and the category of
question this actually is.

No sector name is ever referenced here: the prompt is written to work for
any sector's questions (semiconductors, broadband, or anything else), and
this module has no knowledge of which sector a request will end up routed
to. Sector adapters (e.g. sectors/sk_hynix/adapter/collector) combine these
question-specific keywords with their own curated profile.json keywords —
this step only has to get the question-specific part right.

Falls back to the rule-based result whenever no API key is configured, or
if the API call itself fails for any reason — this is a quality
enhancement, not a required stage, and must never be a new way for the
pipeline to break.
"""

from __future__ import annotations

import json
import os
import sys

from openai import OpenAI

from common.contracts import EntityExtractionResult, UserRequest

_API_KEY_ENV_VAR = "TRENDSPARC_ENTITY_AI_API_KEY"
_MODEL = "gpt-4o-mini"
_STAGE = "entity"

_INTENT_CATEGORIES = (
    "current_status",  # 현황파악
    "issue_response",  # 이슈대응
    "future_business",  # 미래사업
    "root_cause",  # 원인분석
)

_PERSPECTIVE_CATEGORIES = (
    "market_landscape",  # 시장 전체의 현황/동향/경쟁구도/점유율을 묻는 질문
    "company_update",  # 특정 회사의 서비스/실적/마일스톤을 묻는 질문
    "competitor_comparison",  # 둘 이상의 대상을 비교하는 질문
    "regulatory_policy",  # 법/규제/정책 관련 질문
)

_SYSTEM_PROMPT = """You are a search-keyword extraction and intent-classification \
assistant for TrendSparC, an internal AI trend-intelligence tool used across multiple, \
unrelated business sectors (e.g. semiconductors, broadband/telecom, or others not yet \
known to you). You will be given one user question. Your job is to turn it into clean \
search terms a collector can match against real news article titles, AND classify what \
kind of question it is — never assume a specific industry, and never hardcode behavior \
for one topic over another.

Return five fields:
- primary_intent: exactly one of {intent_categories} — pick whichever best describes \
what the question is actually asking (current_status = 현황파악, issue_response = \
이슈대응, future_business = 미래사업, root_cause = 원인분석). Use "current_status" as \
the default when none of the others clearly apply.
- perspective: exactly one of {perspective_categories} — this is a DIFFERENT axis from \
primary_intent: it's about what the question is examining, not why it's being asked. \
market_landscape = the question is about the market/industry as a whole (size, growth, \
competitive landscape, market share) rather than any one company. company_update = the \
question is about one specific company's own service, product, results, or milestones. \
competitor_comparison = the question explicitly compares two or more named entities \
against each other. regulatory_policy = the question is about a law, regulation, or \
government policy. This distinction matters a lot: if a question names a specific brand \
but is really asking about the market that brand competes in (e.g. "OK캐쉬백 포인트 \
마케팅 시장 현황은?" — the brand is just an example of the market being asked about), \
classify it as market_landscape, not company_update, even though a brand name appears. \
Use "company_update" as the default when none of the others clearly apply.
- organizations: companies, agencies, or institutions actually named or clearly \
implied by the question. Empty list if none.
- technologies: products, technologies, brands, or standards actually named or \
clearly implied by the question — this includes named consumer/business products \
and services (e.g. a loyalty program, an app, a platform name), not just technical \
standards. If the question names a specific product, service, or brand, it belongs \
here (or in organizations, if it's the name of a company/institution itself), never \
in the generic keywords list below. Empty list if none.
- keywords: short, canonical topic/domain terms in the style of a professionally \
curated industry keyword glossary — the kind of terse entries a domain analyst would \
maintain for filtering news (e.g. topic areas, business concepts, generic technical \
terms), not descriptive phrases or sentence fragments, and never a named entity that \
already belongs in organizations/technologies. Each entry should be plausible as a \
standalone glossary entry and likely to appear verbatim in a real news headline about \
this exact question. Do not just copy tokens from the question's raw text with \
grammatical particles or punctuation still attached. Keep the list short (typically \
3-6 core concepts rather than padding it).

Language: these terms feed a search engine as one combined query, which \
generally requires every term to appear together on a matching page — so never \
list both a Korean and an English form of the *same* concept (e.g. do not return \
both "반도체" and "Semiconductors", or both "경쟁력" and "Competitiveness"); \
picking both makes the combined query match almost nothing. For each \
organization/technology/keyword, output exactly ONE form: whichever language the \
question itself is written in, unless that concept is overwhelmingly more common \
in the other language in real headlines (e.g. a widely-used English acronym for a \
technical standard). Do not translate a term into a language it would not \
realistically appear in.

Never invent facts, entities, or context that the question does not support. If the \
question is vague or short, keep your output correspondingly short rather than \
guessing broadly.""".format(
    intent_categories=", ".join(_INTENT_CATEGORIES),
    perspective_categories=", ".join(_PERSPECTIVE_CATEGORIES),
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_intent": {"type": "string", "enum": list(_INTENT_CATEGORIES)},
        "perspective": {"type": "string", "enum": list(_PERSPECTIVE_CATEGORIES)},
        "organizations": {"type": "array", "items": {"type": "string"}},
        "technologies": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["primary_intent", "perspective", "organizations", "technologies", "keywords"],
    "additionalProperties": False,
}


def extract_entities_ai(
    request: UserRequest, rule_based_result: EntityExtractionResult
) -> EntityExtractionResult:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        return rule_based_result

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=_MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": request.question},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "entity_extraction",
                    "schema": _SCHEMA,
                    "strict": True,
                },
            },
        )
        message = response.choices[0].message
        if message.refusal:
            raise RuntimeError(message.refusal)
        data = json.loads(message.content)
        return EntityExtractionResult(
            request_id=request.request_id,
            primary_intent=data["primary_intent"],
            perspective=data["perspective"],
            organizations=data["organizations"],
            technologies=data["technologies"],
            keywords=data["keywords"],
        )
    except Exception as exc:  # noqa: BLE001 - AI refinement is best-effort, never fatal
        print(f"[{_STAGE}] AI-based keyword refinement failed, using rule-based result: {exc}", file=sys.stderr)
        return rule_based_result
