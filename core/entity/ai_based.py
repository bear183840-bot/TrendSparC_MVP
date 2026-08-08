"""AI-first entity extraction and registry-constrained sector routing.

The 1st-pass rule-based extractor (see core/entity/extractor.py) just
splits the question on whitespace, so its `keywords` rarely appear verbatim
in a real headline (e.g. "전망은?" with the question mark still attached),
and its intent classification is simple keyword matching. This step asks an
LLM to turn the raw question into clean, natural search terms AND a more
reliable intent classification in the same call — the kind of words that
would actually show up in a news article title, and the category of
question this actually is.

The available sector IDs and display names come from the live registry rather
than branches in this module. Internal profile keywords and source settings
remain local. Sector adapters combine the extracted question terms with their
own curated profile data after routing.

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

from common.ai_usage import emit_ai_usage
from common.ai_client import openai_client_kwargs
from common.contracts import EntityExtractionResult, SectorProfile, UserRequest

_API_KEY_ENV_VAR = "TRENDSPARC_ENTITY_AI_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_ENTITY_AI_MODEL"
# Provider and model are intentionally stage-local. The current deployment
# can use Upstage Solar through this OpenAI-compatible base URL, while removing
# the URL (and optionally setting the model env var) switches back to OpenAI.
# See common/ai_client.py.
_BASE_URL_ENV_VAR = "TRENDSPARC_ENTITY_AI_BASE_URL"
_DEFAULT_OPENAI_MODEL = "gpt-4o"
_DEFAULT_UPSTAGE_MODEL = "solar-pro3"
_STAGE = "entity"


def _model() -> str:
    configured = os.environ.get(_MODEL_ENV_VAR)
    if configured:
        return configured
    base_url = os.environ.get(_BASE_URL_ENV_VAR, "").casefold()
    return _DEFAULT_UPSTAGE_MODEL if "upstage.ai" in base_url else _DEFAULT_OPENAI_MODEL


def _normalize_for_matching(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())

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

_INFORMATION_NEED_CATEGORIES = (
    "financial_performance",
    "customer_market",
    "product_technology",
    "operations_supply",
    "strategy_investment",
    "competition",
    "regulation_risk",
    "user_sentiment",
)

_EXPLICIT_MARKET_SCOPE = (
    "시장", "산업", "업계", "섹터", "시장규모", "시장 규모", "점유율",
    "경쟁구도", "경쟁 구도", "market", "industry", "sector", "market share",
)

_SYSTEM_PROMPT = """You are a search-keyword extraction, intent-classification, and \
sector-routing assistant for TrendSparC. First infer what the user is fundamentally \
asking, then classify and extract. The question may contain typos, broken spacing, \
slang, banmal, conversational filler, or several rambling sentences. Never ask a \
follow-up question and never rewrite the user's original text. Silently use the most \
likely interpretation supported by it (for example, "하이닉스 hbm 요즘어떰" means \
a question about SK hynix HBM).

Choose sector_id only from the supplied registered sector choices. Use "general" \
when none clearly applies; never force an unrelated question into the closest \
business. routing_confidence must be low, medium, or high.

Follow this routing and perspective order exactly:
1. Compare the wording against every supplied routing_aliases entry, allowing normal \
Korean particles, spacing, capitalization, and obvious phonetic spelling.
2. If one business alias clearly matches, select that sector and put its canonical \
display company/business name in organizations.
3. An alias-matched question is company_update by default. Change it to \
market_landscape only when the user explicitly asks about a market, industry, sector, \
market size/share, or competitive landscape. Generic status, trend, performance, \
revenue, investment, subscriber, utilization, sales, and development words do not by \
themselves make a question market-level.
4. If no alias matches, infer from the business topic. Use general only when neither \
an alias nor a business topic clearly supports a registered sector.

Examples:
- "오케캐시백 시럽 요새 반응 어떰" -> infer OK캐쉬백/Syrup and select the matching sector.
- "요즘 회사에서 자꾸 AI 데이터센터 얘기 나오는데 SKT가 하는거 잘되고있나요 \
갑자기 궁금해서요" -> ignore filler and select the SKT/telecom sector.
- "오늘 점심 뭐먹지" -> sector_id="general"; invent no business connection.
- When the user says "우리", "우리 회사", or "우리 쪽" without a company name, use \
the business topic plus the registered sector choices to resolve the intended SK \
business when there is one clear match. Examples: memory semiconductor/NVIDIA -> \
SK hynix; internet bundle/IPTV -> SK Broadband; carrier AI data center -> SK Telecom; \
points/rewards -> SK Planet; EV battery/factory -> SK Innovation.

You are a search-keyword extraction and intent-classification \
assistant for TrendSparC, an internal AI trend-intelligence tool used across multiple, \
unrelated business sectors (e.g. semiconductors, broadband/telecom, or others not yet \
known to you). You will be given one user question. Your job is to turn it into clean \
search terms a collector can match against real news article titles, AND classify what \
kind of question it is — never assume a specific industry, and never hardcode behavior \
for one topic over another.

Return ten fields:
- response_mode: "report" when the user is asking for research, analysis, trends, \
status, comparison, causes, risks, strategy, or decision support. Use "direct_answer" \
for greetings, thanks, casual chat, personal advice, or a simple fact that does not \
benefit from a sourced report.
- direct_answer: a short answer in the user's language only when response_mode is \
"direct_answer"; otherwise null.
- sector_id: one id from the supplied registered sector choices, including "general".
- routing_confidence: low, medium, or high.
- primary_intent: exactly one of {intent_categories} — pick whichever best describes \
what the question is actually asking (current_status = 현황파악, issue_response = \
이슈대응, future_business = 미래사업, root_cause = 원인분석). Use "current_status" as \
the default when none of the others clearly apply.
- perspective: exactly one of {perspective_categories} — this is a DIFFERENT axis from \
primary_intent: it's about what the question is examining, not why it's being asked. \
market_landscape = the question is about the market/industry as a whole (size, growth, \
competitive landscape, market share) rather than any one company. company_update = the \
question is about one specific company's own service, product, results, or milestones. \
competitor_comparison = the question compares multiple entities, including when the \
user names only a technology/product and refers to the comparison group colloquially \
as "other companies", "competitors", "peers", "타사", "경쟁사", or "다른 기업들". \
Named competitors are not required. regulatory_policy = the question is about a law, regulation, or \
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
- information_needs: choose 1-4 values from {information_need_categories}. Select \
the kinds of evidence needed to answer, not sector names or query words. For example, \
a revenue question needs financial_performance; subscriber/MAU/demand questions need \
customer_market; yield/utilization/factory questions need operations_supply; product \
roadmaps need product_technology; CAPEX/partnership questions need strategy_investment. \
Use multiple needs when the question genuinely spans them.

Search readiness: remove greetings, laughter, filler, hearsay framing, and casual \
endings from the extracted fields. Convert the underlying ask into terms that can \
retrieve evidence, such as product/technology plus current status, demand, subscriber \
churn, investment, utilization, customer response, competitive landscape, or risk—as \
supported by the question. Do not put raw phrases such as "요즘 어떰", "진짜임", \
"우리 괜찮아", or "갑자기 궁금해서요" in keywords. Do not invent a named competitor; \
registered source profiles will supply competitor identities where appropriate.

When a colloquial alias or an implied "our business" clearly resolves to one \
registered sector, include that sector's canonical company/business name in \
organizations. Do not return generic conversational placeholders such as "company", \
"situation", "these days", or their Korean equivalents as search keywords. For a \
vague request asking how a company/business is doing, translate the information need \
into 2-4 searchable evidence dimensions supported by the sector, such as business \
performance, the primary customer/product KPI, recent investment or strategy, and \
competitive position. These are search dimensions, not facts: never manufacture a \
number, event, competitor, or conclusion.

Output-language rule is strict: when the question is Korean, organizations and generic \
search concepts must also use the Korean forms normally found in Korean news. Keep only \
proper names and acronyms genuinely searched in English, such as NVIDIA, HBM, AI, and \
ARPU. Never translate ordinary Korean topic phrases into English. A sector choice's \
English display name is only a classification hint and must not determine the output \
language. Before returning, verify that every search term is natural in headlines \
written in the same language as the question.

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
    information_need_categories=", ".join(_INFORMATION_NEED_CATEGORIES),
)

# The original prompt above is retained temporarily as an audit reference for
# prompt-regression review. Runtime calls use this equivalent, de-duplicated
# version. Once the Solar before/after evaluation is accepted, the legacy text
# can be removed without changing behaviour.
_COMPACT_SYSTEM_PROMPT = """You route and normalize one TrendSparC question for evidence search.
The input may contain typos, broken spacing, slang, banmal, filler, or several rambling
sentences. Infer the most likely meaning supported by the text. Never ask a follow-up question,
never rewrite the original question. Do not invent a named competitor, fact, entity, or context.

Return exactly the schema fields. response_mode is report for research, analysis,
trends, status, comparisons, causes, risks, strategy, or decision support; otherwise
direct_answer for greetings, thanks, casual chat, personal advice, or a simple fact
that needs no sourced report. direct_answer is short and in the user's language only
for direct_answer, otherwise null.

Routing:
1. Choose sector_id only from REGISTERED SECTOR CHOICES. Match routing_aliases despite
normal Korean particles, spacing, capitalization, and obvious phonetic spelling.
2. A clear alias wins; add its canonical company/business name to organizations.
3. Without an alias, use business_topics. Use sector_id="general" when neither clearly
matches; never force an unrelated question into a business.
4. "우리", "우리 회사", "우리 쪽", or "저희" may resolve through a clearly matching
business topic or an explicitly selected UI sector, but never by guessing.
routing_confidence is low, medium, or high.

Classification:
- primary_intent is one of {intent_categories}: current_status is the default;
issue_response is response to an issue; future_business is future opportunity/strategy;
root_cause asks why something happened.
- perspective is independent: market_landscape for an explicitly requested market,
industry, size/share, or competitive landscape; competitor_comparison for multiple
entities or colloquial peers such as 타사/경쟁사/other companies; regulatory_policy for
law, regulation, or policy; otherwise company_update. Naming a brand as an example does
not make a market question company_update.
- information_needs selects 1-4 from {information_need_categories}, describing needed
evidence: financial results; customers/demand; product/technology; operations/supply;
strategy/investment; competition; regulation/risk; or user sentiment.
- answer_requirements: split only the deliverables explicitly requested by the user
into 1-5 short, independently verifiable evidence requirements. Preserve every stated
axis and relationship (time range, compared groups, target segment, cause, effect,
recommendation, or forecast). Do not add a desirable output the user did not ask for,
and do not replace concrete requirements with broad labels such as market analysis.

Search fields:
- organizations: named or clearly implied companies, agencies, institutions.
- technologies: named products, services, platforms, brands, technologies, standards.
- keywords: 3-6 short canonical topic terms likely to appear in real headlines. Named
entities belong above, not here. Remove greetings, laughter, hearsay, punctuation,
particles, filler such as "요즘 어떰" and generic placeholders.
- For a vague business-status question, useful search dimensions include business performance,
its main customer/product KPI, recent investment or strategy, and
competitive position. These are search dimensions, never fabricated facts.

Use the question's language. For Korean questions use normal Korean-news forms, keeping
only genuine proper names/acronyms such as NVIDIA, HBM, AI, ARPU in English. Never emit
both Korean and English forms of the same concept because the collector combines terms
and overly restrictive duplicate forms can return no results. Before returning, verify
that every term is natural in a headline and supported by the question.

Examples: "오케캐시백 시럽 요새 반응 어떰" resolves the registered OK캐쉬백/Syrup
business; "하이닉스 hbm 요즘어떰" resolves SK hynix and HBM; "오늘 점심 뭐먹지"
uses sector_id="general". Do not invent a business connection.""".format(
    intent_categories=", ".join(_INTENT_CATEGORIES),
    information_need_categories=", ".join(_INFORMATION_NEED_CATEGORIES),
)

def _sector_choices(profiles: dict[str, SectorProfile] | None) -> tuple[str, list[str]]:
    choices = [
        {
            "sector_id": profile.sector_id,
            "canonical_name": profile.canonical_name or profile.display_name,
            "routing_aliases": profile.aliases,
            "business_topics": profile.keywords,
        }
        for profile in (profiles or {}).values()
    ]
    sector_ids = [choice["sector_id"] for choice in choices]
    if "general" not in sector_ids:
        sector_ids.append("general")
        choices.append({"sector_id": "general", "canonical_name": "General"})
    return json.dumps(choices, ensure_ascii=False), sector_ids


def _schema(sector_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "response_mode": {"type": "string", "enum": ["report", "direct_answer"]},
            "direct_answer": {"type": ["string", "null"]},
            "sector_id": {"type": "string", "enum": sector_ids},
            "routing_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "primary_intent": {"type": "string", "enum": list(_INTENT_CATEGORIES)},
            "perspective": {"type": "string", "enum": list(_PERSPECTIVE_CATEGORIES)},
            "organizations": {"type": "array", "items": {"type": "string"}},
            "technologies": {"type": "array", "items": {"type": "string"}},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "information_needs": {
                "type": "array",
                "items": {"type": "string", "enum": list(_INFORMATION_NEED_CATEGORIES)},
                "minItems": 0,
                "maxItems": 4,
            },
            "answer_requirements": {
                "type": "array",
                "items": {"type": "string", "minLength": 2, "maxLength": 180},
                "minItems": 0,
                "maxItems": 5,
            },
        },
        "required": [
            "response_mode", "direct_answer", "sector_id", "routing_confidence",
            "primary_intent", "perspective", "organizations", "technologies",
            "keywords", "information_needs", "answer_requirements",
        ],
        "additionalProperties": False,
    }


_SELF_REFERENCE_SIGNALS = ("우리", "저희")


def extract_entities_ai(
    request: UserRequest,
    rule_based_result: EntityExtractionResult | None = None,
    profiles: dict[str, SectorProfile] | None = None,
    requested_sector_id: str | None = None,
) -> EntityExtractionResult:
    def fallback(error: str) -> EntityExtractionResult:
        if rule_based_result is not None:
            result = rule_based_result
        else:
            from core.entity.extractor import extract_entities

            result = extract_entities(request)
        return result.model_copy(
            update={
                "routing_confidence": "low",
                "routing_reason": "entity AI unavailable; emergency rule fallback used",
                "needs_ai_routing": True,
                "extraction_method": "rule_fallback",
                "extraction_error": error,
            }
        )

    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        return fallback(f"{_API_KEY_ENV_VAR} is not configured")

    requested_profile = (profiles or {}).get(requested_sector_id) if requested_sector_id else None

    try:
        sector_choices, sector_ids = _sector_choices(profiles)
        system_content = f"{_COMPACT_SYSTEM_PROMPT}\n\nREGISTERED SECTOR CHOICES:\n{sector_choices}"
        if requested_profile is not None:
            requested_canonical = requested_profile.canonical_name or requested_profile.display_name
            system_content += (
                f"\n\nThe user has already explicitly selected sector_id=\"{requested_profile.sector_id}\" "
                f"(canonical business name: \"{requested_canonical}\", aliases: "
                f"{json.dumps(requested_profile.aliases, ensure_ascii=False)}) via the UI before asking this "
                "question. Keep sector_id equal to this value. Resolve any bare self-reference such as "
                "\"우리\", \"우리 회사\", \"우리 쪽\", or \"저희\" to this business specifically — do not guess "
                "a different company."
            )
        client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))
        response = client.chat.completions.create(
            model=_model(),
            max_tokens=500,
            temperature=0,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": request.question},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "entity_extraction",
                    "schema": _schema(sector_ids),
                    "strict": True,
                },
            },
        )
        message = response.choices[0].message
        if message.refusal:
            raise RuntimeError(message.refusal)
        data = json.loads(message.content)
        ai_perspective = data["perspective"]
        if rule_based_result is not None and rule_based_result.perspective in {"competitor_comparison", "regulatory_policy"}:
            ai_perspective = rule_based_result.perspective
        selected_sector_id = data.get("sector_id")
        organizations = list(data["organizations"])
        normalized_question = _normalize_for_matching(request.question)
        alias_matches: list[tuple[int, SectorProfile, str]] = []
        for profile in (profiles or {}).values():
            if profile.sector_id == "general":
                continue
            for alias in profile.aliases:
                normalized_alias = _normalize_for_matching(alias)
                if normalized_alias and normalized_alias in normalized_question:
                    alias_matches.append((len(normalized_alias), profile, alias))
        if alias_matches:
            _, matched_profile, _ = max(alias_matches, key=lambda item: item[0])
            selected_sector_id = matched_profile.sector_id
            canonical_name = matched_profile.canonical_name or matched_profile.display_name
            if canonical_name and canonical_name not in organizations:
                organizations.insert(0, canonical_name)
            if not any(signal in request.question.casefold() for signal in _EXPLICIT_MARKET_SCOPE):
                ai_perspective = "company_update"

        # A UI-level sector selection is a stronger signal than anything this call
        # can infer from question text alone, so it wins even over the model's own
        # sector_id output and the literal-alias match above — this is a hard
        # override, not just a prompt hint, because the model can still ignore
        # instructions (confirmed live: it once picked a different SK affiliate
        # entirely for a bare "우리회사" question despite the sector already being
        # explicitly selected in the UI).
        if requested_profile is not None:
            selected_sector_id = requested_profile.sector_id
            requested_canonical = requested_profile.canonical_name or requested_profile.display_name
            has_self_reference = any(signal in request.question for signal in _SELF_REFERENCE_SIGNALS)
            if requested_canonical and has_self_reference and requested_canonical not in organizations:
                organizations.insert(0, requested_canonical)

        # The model still occasionally puts a named brand/product into the
        # generic keywords list instead of organizations/technologies (e.g.
        # "OK캐쉬백", "Syrup" for sk_planet) even when asked not to - see
        # CLAUDE.md's "Technical gotchas". Rather than re-litigating this in
        # the prompt again, reclassify deterministically against the routed
        # sector's own registered `aliases` (already used above for literal
        # alias matching against the question text) - if a keyword IS a
        # registered alias for this sector, it is a name, not a topic term.
        # This only catches brands the sector has already registered; an
        # unregistered competitor name still relies on the model alone.
        technologies = list(data["technologies"])
        keywords_to_classify = list(data["keywords"])
        final_profile = (profiles or {}).get(selected_sector_id)
        if final_profile is not None:
            canonical_name = final_profile.canonical_name or final_profile.display_name
            normalized_canonical = _normalize_for_matching(canonical_name) if canonical_name else ""
            normalized_aliases = {
                _normalize_for_matching(alias) for alias in final_profile.aliases if alias
            }
            remaining_keywords: list[str] = []
            for keyword in keywords_to_classify:
                normalized_keyword = _normalize_for_matching(keyword)
                if normalized_keyword and normalized_keyword in normalized_aliases:
                    if normalized_canonical and normalized_keyword == normalized_canonical:
                        if keyword not in organizations:
                            organizations.append(keyword)
                    elif keyword not in technologies:
                        technologies.append(keyword)
                    continue
                remaining_keywords.append(keyword)
            keywords_to_classify = remaining_keywords

        named_entities = [*organizations, *technologies]
        normalized_entities = ["".join(value.casefold().split()) for value in named_entities]
        clean_keywords = [
            keyword
            for keyword in keywords_to_classify
            if not any(
                "".join(keyword.casefold().split()) in entity
                or entity in "".join(keyword.casefold().split())
                for entity in normalized_entities
                if entity
            )
        ]
        answer_requirements = list(dict.fromkeys(data.get("answer_requirements", [])))
        if not answer_requirements and data.get("response_mode", "report") == "report":
            answer_requirements = [request.question.strip()]
        result = EntityExtractionResult(
            request_id=request.request_id,
            primary_intent=data["primary_intent"],
            perspective=ai_perspective,
            organizations=list(dict.fromkeys(organizations)),
            technologies=list(dict.fromkeys(technologies)),
            keywords=list(dict.fromkeys(clean_keywords)),
            information_needs=list(dict.fromkeys(data.get("information_needs", []))),
            answer_requirements=answer_requirements,
            response_mode=data.get("response_mode", "report"),
            direct_answer=data.get("direct_answer"),
            sector_id=selected_sector_id,
            routing_confidence=data.get("routing_confidence", "medium"),
            routing_reason="sector selected from registered choices by AI-first intent analysis",
            needs_ai_routing=False,
            extraction_method="ai",
        )
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=system_content,
            user_content=request.question,
            schema=_schema(sector_ids),
            requested_max_tokens=500,
            response=response,
            counts={
                "organizations": len(result.organizations),
                "technologies": len(result.technologies),
                "keywords": len(result.keywords),
                "information_needs": len(result.information_needs),
                "answer_requirements": len(result.answer_requirements),
            },
        )
        return result
    except Exception as exc:  # noqa: BLE001 - AI refinement is best-effort, never fatal
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=locals().get("system_content", _COMPACT_SYSTEM_PROMPT),
            user_content=request.question,
            schema=_schema(locals().get("sector_ids", ["general"])),
            requested_max_tokens=500,
            response=locals().get("response"),
            outcome="failed",
            error_type=type(exc).__name__,
        )
        print(f"[{_STAGE}] AI-based keyword refinement failed, using rule-based result: {exc}", file=sys.stderr)
        return fallback(f"{type(exc).__name__}: {str(exc)[:240]}")
