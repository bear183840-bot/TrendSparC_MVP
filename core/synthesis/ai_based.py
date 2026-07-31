"""2nd-pass, AI-based synthesis refinement — sector-agnostic.

The 1st-pass rule-based synthesizer (see core/synthesis/synthesizer.py) just
concatenates every document's key_points into one flat list, in whatever
order the source documents happened to be processed — so overlapping points
from multiple documents about the same fact appear multiple times, with no
prioritization. This step asks an LLM to de-duplicate near-identical
points, rank what's left by actual importance, and produce a short
synthesis_text overview — the kind of consolidation a human analyst would
do by hand before writing a report.

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

from common.contracts import TrendSynthesis

_API_KEY_ENV_VAR = "TRENDSPARC_SYNTHESIS_AI_API_KEY"
_MODEL = "gpt-4o-mini"
_STAGE = "synthesis"

_SYSTEM_PROMPT = """You are a synthesis assistant for TrendSparC, an internal AI \
trend-intelligence tool used across multiple, unrelated business sectors. You will be \
given the original question the user asked, plus a flat JSON array of key_points \
already extracted from several source documents about that question — some may \
restate the same fact in different words, and they carry no particular order.

Your job:
- Remove near-duplicate points (the same fact stated more than once, even if worded \
differently). Keep whichever phrasing is clearest/most complete, and never merge two \
genuinely different facts into a single point.
- Order the remaining points from most to least directly relevant to answering the \
original question (not just "important in general").
- Write a short (2-4 sentence) synthesis_text paragraph in Korean that directly \
answers the original question using the remaining points — a "so what" overview \
grounded in what was actually asked, not a generic bullet-point restatement.

Never invent a fact, number, or claim that isn't already present in the input points. \
If the input is very short (1-2 points), it's fine for synthesis_text to be brief and \
for little or no deduplication to occur."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": {"type": "array", "items": {"type": "string"}},
        "synthesis_text": {"type": "string"},
    },
    "required": ["highlights", "synthesis_text"],
    "additionalProperties": False,
}


def refine_synthesis_ai(rule_based_result: TrendSynthesis, question: str) -> TrendSynthesis:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key or not rule_based_result.highlights:
        return rule_based_result

    try:
        client = OpenAI(api_key=api_key)
        user_content = json.dumps(
            {"question": question, "key_points": rule_based_result.highlights},
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
        return rule_based_result.model_copy(
            update={
                "highlights": data["highlights"],
                "synthesis_text": data["synthesis_text"],
            }
        )
    except Exception as exc:  # noqa: BLE001 - AI refinement is best-effort, never fatal
        print(f"[{_STAGE}] AI-based synthesis refinement failed, using rule-based result: {exc}", file=sys.stderr)
        return rule_based_result
