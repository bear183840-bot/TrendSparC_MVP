"""2nd-pass, AI-based synthesis refinement — sector-agnostic.

The 1st-pass rule-based synthesizer (see core/synthesis/synthesizer.py) just
concatenates every document's key_points into one flat list, in whatever
order the source documents happened to be processed — so overlapping points
from multiple documents about the same fact appear multiple times, with no
prioritization. This step asks an LLM to de-duplicate near-identical
points, rank what's left by actual importance, and produce a short
synthesis_text overview — the kind of consolidation a human analyst would
do by hand before writing a report.

It also asks the model to (a) group points that restate the same underlying
claim across different doc_ids, and (b) flag genuinely conflicting claims
about the same topic. The model's own claim groupings are semantic pattern
matching it's good at, but *how many independent sources* back a group is
never trusted from the model — this module verifies that itself using
TrendSynthesis.doc_source_map, since two documents from the same registered
source are not independent corroboration of each other.

No sector name is ever referenced here (sector-agnostic, like
core/entity/ai_based.py).

Falls back to the rule-based result whenever no API key is configured, the
input has no highlights to refine, or the API call itself fails for any
reason — this is a quality enhancement, not a required stage, and must
never be a new way for the pipeline to break.
"""

from __future__ import annotations

import json
import os
import sys

from openai import OpenAI

from common.ai_usage import emit_ai_usage
from common.ai_client import openai_client_kwargs
from common.contracts import (
    Contradiction,
    ContradictingClaim,
    CorroboratedPoint,
    SynthesisClaim,
    SynthesisConclusion,
    TrendSynthesis,
)

_API_KEY_ENV_VAR = "TRENDSPARC_SYNTHESIS_AI_API_KEY"
_MODEL_ENV_VAR = "TRENDSPARC_SYNTHESIS_AI_MODEL"
# Stage-local provider switch: Upstage-compatible URL -> Solar default,
# no URL -> OpenAI default. An explicit model env var always wins, so the
# stage can be switched back independently. See common/ai_client.py.
_BASE_URL_ENV_VAR = "TRENDSPARC_SYNTHESIS_AI_BASE_URL"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_UPSTAGE_MODEL = "solar-pro3"
_STAGE = "synthesis"


def _model() -> str:
    configured = os.environ.get(_MODEL_ENV_VAR)
    if configured:
        return configured
    base_url = os.environ.get(_BASE_URL_ENV_VAR, "").casefold()
    return _DEFAULT_UPSTAGE_MODEL if "upstage.ai" in base_url else _DEFAULT_OPENAI_MODEL
# Below this many distinct source_ids, a claim group is not "corroborated" —
# it's just the same source (or the same lone source) restating itself.
_MIN_INDEPENDENT_SOURCES_FOR_CORROBORATION = 2

_SYSTEM_PROMPT = """You are a synthesis assistant for TrendSparC, an internal AI \
trend-intelligence tool used across multiple, unrelated business sectors. You will be \
given the original question, verified structured claims, and a legacy flat list of \
tagged points for backward compatibility. Each structured claim has a stable \
synthesis_claim_id that already passed Analyzer quote verification.

Your job:
- Remove near-duplicate points (the same fact stated more than once, even if worded \
differently). Keep whichever phrasing is clearest/most complete, and never merge two \
genuinely different facts into a single point.
- Order the remaining points from most to least directly relevant to answering the \
original question (not just "important in general").
- Write a short (2-4 sentence) synthesis_text paragraph in Korean that directly \
answers the original question using the remaining points — a "so what" overview \
grounded in what was actually asked, not a generic bullet-point restatement.
- Some evidence is general industry research that never names the company (media-mix \
figures by age bracket, component price trends, industry cost structures), and some is \
about the company itself. Do not simply list both. State explicitly what the general \
finding IMPLIES FOR THIS COMPANY — which of its own circumstances the industry figure \
bears on, and what follows from that pairing. A point that restates industry research \
without connecting it to the company answers a question nobody asked. Where the two \
genuinely cannot be linked from the evidence, say that rather than inventing the link.
- Return a conclusions array. Each conclusion must be supported only by IDs from the \
supplied verified_claims array. Put every supporting synthesis_claim_id in \
supporting_claim_ids and assign a conservative confidence. Do not return a conclusion \
when no verified claim supports it. The IDs are internal provenance metadata and are \
not presentation copy.
- Separately, group the legacy pre-deduplication tagged points by underlying claim: \
for each group of >= 1 point that states essentially the same fact (even if worded \
differently across documents), list the claim and every doc_id that stated it. \
Include single-doc_id groups too — do not skip claims that only appear once. Do not \
count or judge how many independent sources back each group yourself; just group by \
doc_id, a separate process will verify independence.
- Separately, identify genuine contradictions: cases where two or more documents make \
factually conflicting claims about the same specific topic (not just different \
emphasis or scope — an actual conflict, e.g. two different numbers for the same \
metric, or opposite claims about whether something happened). For each, give a short \
topic label and list each conflicting claim with its doc_id. Leave this empty if you \
find no genuine conflicts — do not manufacture contradictions from minor wording \
differences.

Never invent a fact, number, or claim that isn't already present in the input points. \
Never invent a doc_id that wasn't in the input. If the input is very short (1-2 \
points), it's fine for synthesis_text to be brief and for little or no deduplication \
to occur."""

_COMPACT_SYSTEM_PROMPT = """You synthesize verified evidence for TrendSparC.
Answer the original question in Korean without inventing any fact, number, entity,
relationship, claim ID, or document ID.

Inputs contain verified_claims with stable synthesis_claim_id and doc_id. A legacy
tagged-point list is present only when an older analyzer supplied no structured claims.

Return:
- highlights: at most 8 concise, non-duplicate points, ordered by direct relevance.
- synthesis_text: 2-4 concise sentences that answer the question. Connect general
industry evidence to the named company only when the verified evidence supports that
connection; otherwise state the limitation.
- conclusions: at most 6 useful conclusions. Each must list every supporting ID from
verified_claims and use conservative confidence. Omit unsupported conclusions.
- claim_groups: group claims that state the same underlying fact. Return only their
synthesis_claim_id values; do not repeat claim text or provenance. Return only groups
of 2 or more IDs. Code adds every ungrouped verified claim as a singleton afterward.
- contradictions: only genuine factual conflicts about the same scope/period/metric.
Return a short topic and the conflicting synthesis_claim_id values. Different emphasis
or scope is not a contradiction.

Keep wording compact but do not merge distinct facts or drop a distinct claim from
claim_groups. IDs are provenance, never presentation copy."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array", "maxItems": 8,
            "items": {"type": "string", "maxLength": 220},
        },
        "synthesis_text": {"type": "string", "maxLength": 700},
        "conclusions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "conclusion": {"type": "string", "maxLength": 240},
                    "supporting_claim_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["conclusion", "supporting_claim_ids", "confidence"],
            },
            "maxItems": 6,
        },
        "claim_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_ids": {
                        "type": "array", "minItems": 2,
                        "items": {"type": "string"},
                    },
                },
                "required": ["claim_ids"],
                "additionalProperties": False,
            },
        },
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "maxLength": 120},
                    "claim_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic", "claim_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["highlights", "synthesis_text", "conclusions", "claim_groups", "contradictions"],
    "additionalProperties": False,
}


def _split_by_corroboration(
    claim_groups: list[dict],
    doc_source_map: dict[str, str],
    claims_by_id: dict[str, SynthesisClaim] | None = None,
) -> tuple[list[CorroboratedPoint], list[CorroboratedPoint]]:
    """Verify each model-proposed claim group's independent-source count in
    code rather than trusting the model's own count — a group whose doc_ids
    all map to the same source_id (or map to no known doc_id at all) is not
    corroborated, regardless of how many doc_ids it lists.

    A below-threshold group is not dropped: it keeps the exact same doc/source
    attribution as a corroborated one (see CorroboratedPoint's docstring), so
    a renderer can later match a displayed [doc_id=...]-tagged item back to
    "this claim only had one independent source" rather than just the claim
    text, which the AI may have reworded from what's actually shown.
    """
    corroborated: list[CorroboratedPoint] = []
    uncorroborated: list[CorroboratedPoint] = []
    for group in claim_groups:
        claim_ids = list(dict.fromkeys(group.get("claim_ids") or []))
        known_claims = [
            claims_by_id[claim_id]
            for claim_id in claim_ids
            if claims_by_id and claim_id in claims_by_id
        ]
        if known_claims:
            claim = known_claims[0].claim
            doc_ids = list(dict.fromkeys(item.doc_id for item in known_claims))
        else:
            # Backward-compatible parsing for old saved fixtures/providers.
            claim = group.get("claim")
            doc_ids = group.get("doc_ids") or []
        if not claim or not doc_ids:
            continue
        known_doc_ids = [doc_id for doc_id in doc_ids if doc_id in doc_source_map]
        if not known_doc_ids:
            continue  # every doc_id in this group is unknown -> hallucinated group, drop entirely
        supporting_source_ids = list(dict.fromkeys(doc_source_map[doc_id] for doc_id in known_doc_ids))
        point = CorroboratedPoint(
            claim=claim,
            supporting_doc_ids=known_doc_ids,
            supporting_source_ids=supporting_source_ids,
        )
        if len(supporting_source_ids) >= _MIN_INDEPENDENT_SOURCES_FOR_CORROBORATION:
            corroborated.append(point)
        else:
            uncorroborated.append(point)
    return corroborated, uncorroborated


def _filter_contradictions(
    raw_contradictions: list[dict],
    doc_source_map: dict[str, str],
    claims_by_id: dict[str, SynthesisClaim] | None = None,
) -> list[Contradiction]:
    """Drop any contradiction referencing a doc_id that doesn't actually exist
    in this synthesis — a hallucination guard, mirroring the collector's
    "never trust a URL the model just says" principle applied to doc_ids."""
    contradictions: list[Contradiction] = []
    for item in raw_contradictions:
        topic = item.get("topic")
        claim_ids = list(dict.fromkeys(item.get("claim_ids") or []))
        known_claims = [
            claims_by_id[claim_id]
            for claim_id in claim_ids
            if claims_by_id and claim_id in claims_by_id
        ]
        if known_claims:
            claims = [
                ContradictingClaim(
                    claim=claim.claim,
                    doc_id=claim.doc_id,
                    source_id=doc_source_map.get(claim.doc_id),
                )
                for claim in known_claims
            ]
        else:
            # Backward-compatible parsing for old saved fixtures/providers.
            raw_claims = item.get("conflicting_claims") or []
            claims = [
                ContradictingClaim(
                    claim=claim["claim"],
                    doc_id=claim["doc_id"],
                    source_id=doc_source_map.get(claim["doc_id"]),
                )
                for claim in raw_claims
                if claim.get("doc_id") in doc_source_map and claim.get("claim")
            ]
        if topic and len(claims) >= 2:
            contradictions.append(Contradiction(topic=topic, conflicting_claims=claims))
    return contradictions


def _validated_conclusions(
    raw_conclusions: list[dict], rule_based_result: TrendSynthesis
) -> list[SynthesisConclusion]:
    """Keep only conclusions whose every retained support ID really exists."""
    known_claim_ids = {
        claim.synthesis_claim_id for claim in rule_based_result.grounded_claims
    }
    conclusions: list[SynthesisConclusion] = []
    for index, item in enumerate(raw_conclusions, 1):
        text = item.get("conclusion")
        raw_supporting_ids = list(dict.fromkeys(item.get("supporting_claim_ids") or []))
        if (
            not text
            or not raw_supporting_ids
            or any(claim_id not in known_claim_ids for claim_id in raw_supporting_ids)
        ):
            continue
        conclusions.append(
            SynthesisConclusion(
                conclusion_id=f"ai-conclusion-{index}",
                conclusion=text,
                supporting_claim_ids=raw_supporting_ids,
                confidence=item.get("confidence") or "medium",
            )
        )
    return conclusions


def _complete_claim_groups(
    raw_groups: list[dict], claims_by_id: dict[str, SynthesisClaim]
) -> list[dict]:
    """Keep model-proposed duplicate groups and add all safe singletons.

    Asking the model to echo one JSON object per input claim exhausted Solar's
    completion budget. Singleton membership needs no semantic judgement, so
    code supplies it from verified IDs. Overlapping or unknown model IDs are
    removed rather than allowing one claim to appear in several groups.
    """
    assigned: set[str] = set()
    groups: list[dict] = []
    for group in raw_groups:
        claim_ids = [
            claim_id
            for claim_id in dict.fromkeys(group.get("claim_ids") or [])
            if claim_id in claims_by_id and claim_id not in assigned
        ]
        if len(claim_ids) < 2:
            continue
        groups.append({"claim_ids": claim_ids})
        assigned.update(claim_ids)
    groups.extend(
        {"claim_ids": [claim_id]}
        for claim_id in claims_by_id
        if claim_id not in assigned
    )
    return groups


def _expand_claim_aliases(data: dict, original_id_by_alias: dict[str, str]) -> dict:
    """Translate compact model-facing IDs back to pipeline provenance IDs."""
    def expand(items: list[str]) -> list[str]:
        return [original_id_by_alias.get(item, item) for item in items]

    for conclusion in data.get("conclusions") or []:
        conclusion["supporting_claim_ids"] = expand(
            conclusion.get("supporting_claim_ids") or []
        )
    for group in data.get("claim_groups") or []:
        group["claim_ids"] = expand(group.get("claim_ids") or [])
    for contradiction in data.get("contradictions") or []:
        contradiction["claim_ids"] = expand(contradiction.get("claim_ids") or [])
    return data


def refine_synthesis_ai(rule_based_result: TrendSynthesis, question: str) -> TrendSynthesis:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key or not (rule_based_result.highlights or rule_based_result.grounded_claims):
        return rule_based_result

    try:
        client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))
        original_id_by_alias = {
            f"C{index:03d}": claim.synthesis_claim_id
            for index, claim in enumerate(rule_based_result.grounded_claims, 1)
        }
        alias_by_original_id = {
            original_id: alias for alias, original_id in original_id_by_alias.items()
        }
        doc_alias_by_id = {
            doc_id: f"D{index:02d}"
            for index, doc_id in enumerate(dict.fromkeys(
                claim.doc_id for claim in rule_based_result.grounded_claims
            ), 1)
        }
        user_content = json.dumps(
            {
                "question": question,
                "verified_claims": [
                    {
                        "synthesis_claim_id": alias_by_original_id[claim.synthesis_claim_id],
                        "claim_type": claim.claim_type,
                        "claim": claim.claim,
                        "doc_id": doc_alias_by_id[claim.doc_id],
                    }
                    for claim in rule_based_result.grounded_claims
                ],
                # Older sector adapters may have highlights but no verified
                # structured claims. Never send both representations: they
                # repeat the same facts and previously doubled this payload.
                "legacy_tagged_points": (
                    rule_based_result.highlights
                    if not rule_based_result.grounded_claims
                    else []
                ),
            },
            ensure_ascii=False,
        )
        response = client.chat.completions.create(
            model=_model(),
            max_tokens=2500 if len(rule_based_result.grounded_claims) >= 50 else 1500,
            temperature=0,
            messages=[
                {"role": "system", "content": _COMPACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "synthesis_refinement",
                    "schema": _SCHEMA,
                    "strict": True,
                },
            },
        )
        message = response.choices[0].message
        if message.refusal:
            raise RuntimeError(message.refusal)
        data = _expand_claim_aliases(json.loads(message.content), original_id_by_alias)
        claims_by_id = {
            claim.synthesis_claim_id: claim
            for claim in rule_based_result.grounded_claims
        }
        claim_groups = (
            _complete_claim_groups(data.get("claim_groups") or [], claims_by_id)
            if claims_by_id
            else data.get("claim_groups") or []
        )
        corroborated_points, uncorroborated_points = _split_by_corroboration(
            claim_groups,
            rule_based_result.doc_source_map,
            claims_by_id,
        )
        contradictions = _filter_contradictions(
            data.get("contradictions") or [],
            rule_based_result.doc_source_map,
            claims_by_id,
        )
        conclusions = _validated_conclusions(
            data.get("conclusions") or [], rule_based_result
        )
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=_COMPACT_SYSTEM_PROMPT,
            user_content=user_content,
            schema=_SCHEMA,
            requested_max_tokens=2500 if len(rule_based_result.grounded_claims) >= 50 else 1500,
            response=response,
            counts={
                "input_claims": len(rule_based_result.grounded_claims),
                "input_highlights": len(rule_based_result.highlights),
                "output_highlights": len(data.get("highlights", [])),
                "claim_groups": len(data.get("claim_groups", [])),
            },
        )
        return rule_based_result.model_copy(
            update={
                "highlights": data["highlights"],
                "synthesis_text": data["synthesis_text"],
                "corroborated_points": corroborated_points,
                "uncorroborated_points": uncorroborated_points,
                "contradictions": contradictions,
                "conclusions": conclusions or rule_based_result.conclusions,
            }
        )
    except Exception as exc:  # noqa: BLE001 - AI refinement is best-effort, never fatal
        emit_ai_usage(
            stage=_STAGE,
            model=_model(),
            system_content=_COMPACT_SYSTEM_PROMPT,
            user_content=locals().get("user_content", ""),
            schema=_SCHEMA,
            requested_max_tokens=(
                2500 if len(rule_based_result.grounded_claims) >= 50 else 1500
            ),
            response=locals().get("response"),
            outcome="failed",
            error_type=type(exc).__name__,
        )
        print(f"[{_STAGE}] AI-based synthesis refinement failed, using rule-based result: {exc}", file=sys.stderr)
        return rule_based_result
