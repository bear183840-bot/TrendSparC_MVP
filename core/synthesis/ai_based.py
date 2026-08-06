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

from common.contracts import (
    Contradiction,
    ContradictingClaim,
    CorroboratedPoint,
    SynthesisConclusion,
    TrendSynthesis,
)

_API_KEY_ENV_VAR = "TRENDSPARC_SYNTHESIS_AI_API_KEY"
_MODEL = "gpt-4o-mini"
_STAGE = "synthesis"
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

_SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": {"type": "array", "items": {"type": "string"}},
        "synthesis_text": {"type": "string"},
        "conclusions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "conclusion": {"type": "string"},
                    "supporting_claim_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["conclusion", "supporting_claim_ids", "confidence"],
            },
        },
        "claim_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "doc_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim", "doc_ids"],
                "additionalProperties": False,
            },
        },
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "conflicting_claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": {"type": "string"},
                                "doc_id": {"type": "string"},
                            },
                            "required": ["claim", "doc_id"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["topic", "conflicting_claims"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["highlights", "synthesis_text", "conclusions", "claim_groups", "contradictions"],
    "additionalProperties": False,
}


def _split_by_corroboration(
    claim_groups: list[dict], doc_source_map: dict[str, str]
) -> tuple[list[CorroboratedPoint], list[str]]:
    """Verify each model-proposed claim group's independent-source count in
    code rather than trusting the model's own count — a group whose doc_ids
    all map to the same source_id (or map to no known doc_id at all) is not
    corroborated, regardless of how many doc_ids it lists."""
    corroborated: list[CorroboratedPoint] = []
    uncorroborated: list[str] = []
    for group in claim_groups:
        claim = group.get("claim")
        doc_ids = group.get("doc_ids") or []
        if not claim or not doc_ids:
            continue
        known_doc_ids = [doc_id for doc_id in doc_ids if doc_id in doc_source_map]
        if not known_doc_ids:
            continue  # every doc_id in this group is unknown -> hallucinated group, drop entirely
        supporting_source_ids = list(dict.fromkeys(doc_source_map[doc_id] for doc_id in known_doc_ids))
        if len(supporting_source_ids) >= _MIN_INDEPENDENT_SOURCES_FOR_CORROBORATION:
            corroborated.append(
                CorroboratedPoint(
                    claim=claim,
                    supporting_doc_ids=known_doc_ids,
                    supporting_source_ids=supporting_source_ids,
                )
            )
        else:
            uncorroborated.append(claim)
    return corroborated, uncorroborated


def _filter_contradictions(raw_contradictions: list[dict], doc_source_map: dict[str, str]) -> list[Contradiction]:
    """Drop any contradiction referencing a doc_id that doesn't actually exist
    in this synthesis — a hallucination guard, mirroring the collector's
    "never trust a URL the model just says" principle applied to doc_ids."""
    contradictions: list[Contradiction] = []
    for item in raw_contradictions:
        topic = item.get("topic")
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


def refine_synthesis_ai(rule_based_result: TrendSynthesis, question: str) -> TrendSynthesis:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key or not (rule_based_result.highlights or rule_based_result.grounded_claims):
        return rule_based_result

    try:
        client = OpenAI(api_key=api_key)
        user_content = json.dumps(
            {
                "question": question,
                "verified_claims": [
                    {
                        "synthesis_claim_id": claim.synthesis_claim_id,
                        "claim_type": claim.claim_type,
                        "claim": claim.claim,
                        "source_id": claim.source_id,
                        "confidence": claim.confidence,
                    }
                    for claim in rule_based_result.grounded_claims
                ],
                "legacy_tagged_points": rule_based_result.highlights,
            },
            ensure_ascii=False,
        )
        response = client.chat.completions.create(
            model=_MODEL,
            max_tokens=1500,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
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
        data = json.loads(message.content)
        corroborated_points, uncorroborated_points = _split_by_corroboration(
            data.get("claim_groups") or [], rule_based_result.doc_source_map
        )
        contradictions = _filter_contradictions(
            data.get("contradictions") or [], rule_based_result.doc_source_map
        )
        conclusions = _validated_conclusions(
            data.get("conclusions") or [], rule_based_result
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
        print(f"[{_STAGE}] AI-based synthesis refinement failed, using rule-based result: {exc}", file=sys.stderr)
        return rule_based_result
