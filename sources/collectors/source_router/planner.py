"""Solar Pro 3 — Search Planner. doc1 §4.

Plans WHAT to search before any web_search call happens, tagging each query
with an angle/purpose/priority. Priority-1 queries run first; priority-2/3
are only spent when Coverage/Gap Check says priority-1 wasn't enough (see
router.py). Falls back to a single direct-question query when no planner key
is configured or the call fails — the router must always have something to
search with.
"""

from __future__ import annotations

from typing import Literal

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import SearchPlan, SearchPlanQuery
from sources.collectors.source_router.question_type_ai_based import refine_question_type_ai
from sources.collectors.source_router.question_type_classifier import classify_question_type

_PURPOSE_IDS = {"current_status", "issue_response", "future_business", "root_cause"}
_AUDIENCE_IDS = {"practitioner", "executive", "management", "external"}
# Ordered (not just set) versions of the above, used only for assembling the
# system prompt from prompts/planner_purposes/*.md and prompts/planner_
# audiences/*.md — order doesn't affect model behavior, just keeps the
# all-branches fallback text deterministic across calls.
_PURPOSE_FILE_ORDER = ("current_status", "issue_response", "future_business", "root_cause")
_AUDIENCE_FILE_ORDER = ("practitioner", "executive", "management", "external")
# question_type (Troubleshooting/Navigating/Investigating/Sensing, see
# question_type_classifier.py's module docstring for why this is a distinct
# third axis) is classified entirely inside this package from `question`
# alone, unlike purpose_id/audience which arrive from upstream callers - so
# plan_searches() computes it itself rather than accepting it as a
# parameter. Order is arbitrary, kept deterministic for the same reason as
# the two tuples above.
_QUESTION_TYPE_FILE_ORDER = ("troubleshooting", "navigating", "investigating", "sensing")
# Web search treats multiple quoted exact-phrase terms in one query as
# roughly an AND (same mechanism CLAUDE.md documents for Firecrawl, live-
# verified here for the GPT-5-mini-based web_search this router uses too) -
# quoting more than a couple of them in one query makes a document matching
# all of them at once vanishingly unlikely. Live-verified 2026-08-10: a
# query with 5 quoted key_terms ("20대" "30대" "40대" "TV광고" "IPTV 광고
# 효과") returned almost nothing across 8 search calls. 2 preserves the one
# pattern that genuinely needs two quoted terms together (a regulator name +
# a precise legal term, see prompts/planner.md's "Regulatory / institutional
# terminology queries" section).
_MAX_KEY_TERMS_PER_QUERY = 2


def _clamp_purpose_id(value: object) -> Literal[
    "current_status", "issue_response", "future_business", "root_cause"
] | None:
    """Same defensive-clamp spirit as coverage.py's module-private _clamp*
    helpers (not imported directly - that module's helpers are private to
    it, and this clamp is small enough not to be worth sharing)."""
    text = str(value or "").strip()
    return text if text in _PURPOSE_IDS else None  # type: ignore[return-value]


def _clamp_audience(value: object) -> Literal[
    "practitioner", "executive", "management", "external"
] | None:
    """Only the 4 selectable personas reach SearchPlan.audience.

    The pipeline's own fallback is `_default` (DEFAULT_AUDIENCE_ID) - the
    underscore-prefixed profile it uses when the caller named no audience,
    deliberately kept out of the selectable set. It is a real runtime value,
    not a bad input, so it has to become None here rather than blow up:
    "no persona was chosen" is exactly what this Optional field means, and
    STEP 2.6's audience adjustment has nothing to adjust toward. Without
    this clamp every run that did not pass --audience died with a
    ValidationError before the first search call.
    """
    text = str(value or "").strip()
    return text if text in _AUDIENCE_IDS else None  # type: ignore[return-value]


def _pick_branch_ids(
    value: str | None, confidence: str | None, known_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Confidence-gated branch selection, shared by purpose_id and (once
    added) a future question_type axis: a confidently-classified value gets
    only its own branch text; anything else (unclassified, or classified
    with confidence="low") falls back to sending every branch so the model
    can still choose for itself - the same "send everything, let the model
    self-select" safety net this whole cut-and-assemble design replaced for
    the confident case, kept as the fallback for the unconfident one."""
    if value in known_ids and confidence != "low":
        return (value,)
    return known_ids


def _pick_audience_ids(value: str | None, known_ids: tuple[str, ...]) -> tuple[str, ...]:
    """audience has no confidence concept - it's either a concrete human-
    selected value (trust it, send only that one branch) or absent (skip the
    whole audience axis, same as STEP 2.6 already does when unspecified)."""
    return (value,) if value in known_ids else ()


def _assemble_system_prompt(
    purpose_id: str | None,
    purpose_confidence: str | None,
    audience: str | None,
    question_type: str | None = None,
    question_type_confidence: str | None = None,
) -> str:
    """Builds the planner system prompt by cutting in only the branch text
    that matches this call's classified purpose_id/audience/question_type,
    instead of sending the whole (now-split) prompt and trusting the model to
    self-select the relevant branch. Falls back to sending every branch of
    an axis whenever that axis is unclassified or not confidently
    classified - see `_pick_branch_ids`/`_pick_audience_ids` above and the
    design plan this implements for why. Mirrors the existing
    `core/report_planner/planner.py`'s `_load_intent_emphasis()` pattern of
    concatenating a common file with a purpose-specific one.

    Assembly order is `head + question_type + purpose + audience + tail`:
    question_type sits right after head (which carries STEP 2's general
    candidate generation) because it was designed as a co-equal 1st-pass
    generator alongside STEP 2, not a refinement of it - purpose_id/audience
    are the 2nd-pass refinements layered on top, so their text comes after."""
    head = _prompts.load("planner_common_head")
    tail = _prompts.load("planner_common_tail")
    question_type_text = "\n\n".join(
        _prompts.load(f"planner_question_types/{qid}")
        for qid in _pick_branch_ids(question_type, question_type_confidence, _QUESTION_TYPE_FILE_ORDER)
    )
    purpose_text = "\n\n".join(
        _prompts.load(f"planner_purposes/{pid}")
        for pid in _pick_branch_ids(purpose_id, purpose_confidence, _PURPOSE_FILE_ORDER)
    )
    audience_text = "\n\n".join(
        _prompts.load(f"planner_audiences/{aid}")
        for aid in _pick_audience_ids(audience, _AUDIENCE_FILE_ORDER)
    )
    return "\n\n".join(
        part for part in (head, question_type_text, purpose_text, audience_text, tail) if part
    )


def _fallback_plan(
    question: str, *, audience: str | None = None, purpose_id: str | None = None
) -> SearchPlan:
    query = question.strip()
    if not query:
        return SearchPlan(
            intent=question,
            queries=[],
            audience=_clamp_audience(audience),
            purpose_id=_clamp_purpose_id(purpose_id),
        )
    return SearchPlan(
        intent=question,
        queries=[SearchPlanQuery(query=query, angle="direct", purpose="fallback", priority=1)],
        audience=_clamp_audience(audience),
        purpose_id=_clamp_purpose_id(purpose_id),
    )


def _apply_quoting(query: str, key_terms: list[str]) -> str:
    """Mechanically wraps each key_term that literally appears in `query` in
    quotation marks — see SearchPlanQuery.key_terms docstring for why this
    is done in code rather than left to the model's own quoting habits
    inside `query`. A term the model listed but didn't actually use in
    `query` (typo, paraphrase) is silently skipped rather than forced in —
    inserting it out of context could produce a nonsensical query."""
    result = query
    for term in key_terms:
        term = term.strip()
        if not term or term not in result:
            continue
        quoted = f'"{term}"'
        if quoted in result:
            continue  # model already quoted it itself - don't double-quote
        result = result.replace(term, quoted)
    return result


def plan_searches(
    question: str,
    *,
    audience: str | None = None,
    purpose_id: str | None = None,
    purpose_confidence: str | None = None,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> SearchPlan:
    """Plans WHAT to search, now also shaped by who the report is for
    (`audience`) and what kind of report it is (`purpose_id`) -
    STEP 2.5/2.6 (see `_assemble_system_prompt`) use these to expand/adjust
    the candidate angles STEP 2 already generates, not to replace them.

    `audience` is never inferred - only echoed back onto the returned
    SearchPlan, clamped to the 4 selectable personas (the pipeline's own
    `_default` fallback means "nobody picked one", which is None here).
    `purpose_id`, if not given, is classified by the same Solar call via
    `resolved_purpose_id` (defensively clamped to the 4 known values).
    `purpose_confidence` (e.g. `ReportPurposeClassification.confidence`)
    gates whether the assembled prompt sends only that one purpose branch or
    falls back to sending all four - see `_assemble_system_prompt`.

    `question_type` is not a parameter here - unlike purpose_id/audience it
    is classified entirely from `question` inside this package (see
    question_type_classifier.py's module docstring), so it's computed
    locally via the same rule-based-then-AI pattern the rest of the
    codebase uses (`classify_question_type` -> `refine_question_type_ai`)
    rather than threaded in from a caller."""
    audience = _clamp_audience(audience)
    question_type, question_type_confidence = refine_question_type_ai(
        classify_question_type(question),
        question,
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    data = _solar.call_json(
        _assemble_system_prompt(
            purpose_id, purpose_confidence, audience, question_type, question_type_confidence
        ),
        {
            "question": question,
            "audience": audience or "unspecified",
            "purpose_id": purpose_id or "infer",
        },
        caller="planner",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if not data:
        return _fallback_plan(question, audience=audience, purpose_id=purpose_id)
    raw_queries = data.get("queries") or data.get("search_plan") or []
    queries = []
    for item in raw_queries:
        if not isinstance(item, dict):
            continue
        raw_query = str(item.get("query", "")).strip()
        if not raw_query:
            continue
        key_terms = [
            str(term).strip() for term in item.get("key_terms") or [] if str(term).strip()
        ][:_MAX_KEY_TERMS_PER_QUERY]
        queries.append(
            SearchPlanQuery(
                query=_apply_quoting(raw_query, key_terms),
                angle=str(item.get("angle", "")).strip(),
                purpose=str(item.get("purpose", "")).strip(),
                priority=int(item.get("priority") or 1),
                key_terms=key_terms,
            )
        )
    if not queries:
        return _fallback_plan(question, audience=audience, purpose_id=purpose_id)
    resolved_purpose_id = purpose_id or _clamp_purpose_id(data.get("resolved_purpose_id"))
    return SearchPlan(
        intent=str(data.get("intent", question)),
        queries=queries,
        audience=audience,
        purpose_id=resolved_purpose_id,
    )
