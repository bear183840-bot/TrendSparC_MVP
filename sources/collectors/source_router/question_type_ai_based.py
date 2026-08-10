"""AI-based 2nd-pass refinement for question_type classification.

question_type_classifier.py's rule-based `classify_question_type()` is the
1st pass. This module is the optional 2nd pass, following this codebase's
established "1st-pass rule-based -> 2nd-pass AI-based, silent fallback"
convention (core/entity/{extractor.py,ai_based.py}, core/synthesis/
{synthesizer.py,ai_based.py}, and CLAUDE.md) - missing API key, a failed
call, or an unparsable/refused response must never break anything; the
caller silently keeps the rule-based result instead. This module never
raises and never falls back internally - `classify_question_type_ai`
returns `None` on any failure and leaves the fallback decision to its
caller, matching `_solar.call_json`'s own contract.

Uses this package's own shared "Solar Pro 3" role (`_solar.call_json`)
rather than a new dedicated API key - this is a small, self-contained
classification task that fits the same shared-credential role planner.py/
coverage.py/pdf_parser.py's selection functions already use, not a
sector-scale AI pass that needs its own budget/key.

The classification prompt (prompts/question_type_classifier_ai.md) is
intentionally separate from, and much smaller than, the query-generation
branch content this axis will eventually add to planner.py's
`_assemble_system_prompt` (see prompts/planner_purposes/*.md for the
pattern that content will follow once supplied) - it only sees the 4 type
definitions and their boundary-disambiguation rules, never any query-
generation instructions. Classification and generation never share a
prompt - see the design plan for why.
"""

from __future__ import annotations

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.question_type_classifier import QUESTION_TYPE_IDS

_TYPE_LABEL_TO_ID = {
    "Troubleshooting": "troubleshooting",
    "Navigating": "navigating",
    "Investigating": "investigating",
    "Sensing": "sensing",
}


def _clamp_confidence(value: object) -> str:
    """Maps the model's 0.00-1.00 confidence float onto this codebase's
    Literal["low","medium","high"] convention (see `purpose_confidence` /
    `ReportPurposeClassification.confidence`) so callers gate on it the
    same way regardless of which axis it came from. Never trusts the raw
    number as-is - a model in plain JSON mode can return any value, or
    none at all."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "low"
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def classify_question_type_ai(
    question: str,
    *,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> tuple[str, str] | None:
    """Returns `(question_type, confidence)`, or `None` on missing API key,
    call failure, or an unrecognized/unparsable response. `None` means
    "this pass produced nothing usable" - the caller must keep whatever the
    rule-based `classify_question_type()` already returned, exactly like
    `core/entity/ai_based.py`'s refinement contract."""
    data = _solar.call_json(
        _prompts.load("question_type_classifier_ai"),
        {"question": question},
        caller="question_type_ai",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if not data:
        return None
    question_type = _TYPE_LABEL_TO_ID.get(str(data.get("type", "")).strip())
    if question_type not in QUESTION_TYPE_IDS:
        return None
    return question_type, _clamp_confidence(data.get("confidence"))


def refine_question_type_ai(
    rule_based_result: tuple[str | None, str],
    question: str,
    *,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> tuple[str | None, str]:
    """Orchestrates the full "1st-pass rule-based -> 2nd-pass AI-based,
    silent fallback" contract for question_type end-to-end, mirroring
    `core/synthesis/ai_based.py`'s `refine_synthesis_ai(rule_based_result,
    question)` - callers use this one function instead of open-coding the
    confidence check themselves:

        rule_based_result = classify_question_type(question)
        question_type, confidence = refine_question_type_ai(rule_based_result, question)

    Only spends an AI call when `rule_based_result`'s confidence is not
    already "high" - i.e. "low" or "medium" on this codebase's existing
    Literal["low","medium","high"] scale (see `purpose_confidence` /
    `ReportPurposeClassification.confidence`), even though
    `classify_question_type()` today only ever emits "low"/"high" and never
    "medium" itself. A "high" rule-based result is trusted as-is and never
    pays for a confirming API call.

    Falls back to `rule_based_result` unchanged whenever the AI pass
    produces nothing usable (`classify_question_type_ai` returning `None`)
    - missing key, call failure, or an unrecognized response all look
    identical to the caller here, exactly like every other AI refinement
    pass in this codebase."""
    _, rule_based_confidence = rule_based_result
    if rule_based_confidence == "high":
        return rule_based_result
    ai_result = classify_question_type_ai(
        question, model_override=model_override, timeout_seconds=timeout_seconds
    )
    return ai_result if ai_result is not None else rule_based_result
