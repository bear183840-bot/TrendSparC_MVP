"""Generate a complete, evidence-bound report from a structured synthesis."""

from __future__ import annotations

import json
import os
import re
import sys
from copy import deepcopy

from audience.contracts import load_audience_profile
from common.ai_client import openai_client_kwargs
from common.content_quality_validator import (
    dated_items,
    dedupe_across_blocks,
    dedupe_structured_across_sections,
    metric_value_type,
    relative_metric_context,
)
from common.contracts import (
    ActionImpact,
    ComparisonPoint,
    GeneratedReport,
    GeneratedReportSection,
    MetricPoint,
    QuestionBrief,
    ReportPlan,
    TrendSynthesis,
)
from core.report_planner.planner import COMPARISON_SECTIONS
from common.section_titles import section_title
from core.sector_router.affiliates import foreign_entity_names_for

_DOC_ID_RE = re.compile(r"\[doc_id=([^\]]+)\]")
# Optional - points this stage at an OpenAI-API-compatible alternative
# provider (e.g. Upstage Solar) instead of stock OpenAI. Unset by default;
# see common/ai_client.py.
_BASE_URL_ENV_VAR = "TRENDSPARC_REPORT_GENERATOR_BASE_URL"


# Sections whose job is to summarise the whole report. They yield a shared
# item to any more specific section that also holds it.
_SUMMARY_SECTIONS = {"overview", "executive_summary", "key_points"}

_ACTION_SECTIONS = {
    "response_actions", "improvement_plan", "strategic_recommendation",
    "recommended_action", "decision_required",
}
_TRACEABLE_FIELDS = (
    "key_points", "evidence", "risks", "opportunities", "actions", "monitoring_indicators",
)
# Structured fields (metric_points/comparison_points) are excluded here — they're
# lists of Pydantic objects, not "[doc_id=...]"-tagged strings, so they can't be
# joined into summary text the way the fields below can.
_TEXT_SUMMARY_FIELDS = (
    "key_points", "evidence", "risks", "opportunities", "strengths",
    "weaknesses", "actions", "monitoring_indicators",
)

_REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "executive_summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "section_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "opportunities": {"type": "array", "items": {"type": "string"}},
                    "actions": {"type": "array", "items": {"type": "string"}},
                    "monitoring_indicators": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": ["string", "null"]},
                },
                "required": [
                    "section_id", "title", "summary", "key_points", "evidence", "risks",
                    "opportunities", "actions", "monitoring_indicators", "confidence",
                ],
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
        # Structured extraction of the figures already sitting in evidence
        # prose. The regex extractor kept missing real numbers because Korean
        # financial sentences carry an unbounded variety of qualifiers
        # ("누적", "잠정", "연결", "전년 동기 대비 …"), and adding one pattern
        # at a time never converged. Asking the model that is already reading
        # this evidence costs no extra call. Every returned figure is still
        # checked against the evidence text before it is accepted
        # (_verified_ai_metric_points) - the model widens recall, it is never
        # trusted for the number itself.
        "metric_series": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "subject": {"type": ["string", "null"]},
                    "period": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "is_forecast": {"type": "boolean"},
                    "value_type": {
                        "type": "string",
                        "enum": ["actual", "estimate", "forecast", "target", "guidance"],
                    },
                    "is_relative": {"type": "boolean"},
                    "comparison_period": {"type": ["string", "null"]},
                    "value_origin": {"type": "string", "enum": ["source"]},
                    "share_of": {"type": ["string", "null"]},
                    "source_sentence": {"type": "string"},
                },
                "required": [
                    "label", "subject", "period", "value", "unit", "is_forecast", "value_type",
                    "is_relative", "comparison_period", "value_origin", "share_of", "source_sentence",
                ],
            },
        },
        # Comparisons stated in prose ("TV(84.9%)가 유튜브를 앞섰다") were never
        # extracted at all: only the sector analyzer produced comparison_points,
        # and only from documents it happened to read that way. Asking here
        # costs nothing extra and covers every question, not the financial ones.
        "comparison_points": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entity": {"type": "string"},
                    "criterion": {"type": "string"},
                    "value": {"type": "string"},
                    "level": {"type": ["string", "null"]},
                    "source_sentence": {"type": "string"},
                },
                "required": ["entity", "criterion", "value", "level", "source_sentence"],
            },
        },
        # An action's expected impact, only where a source states one. The
        # column was blank because nothing linked the two; the previous filler
        # paired the Nth action with the Nth business_impact, which read as a
        # finding while carrying none.
        "action_impacts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string"},
                    "expected_impact": {"type": "string"},
                    "impact_value": {"type": ["number", "null"]},
                    "impact_unit": {"type": ["string", "null"]},
                    "source_sentence": {"type": "string"},
                },
                "required": [
                    "action", "expected_impact", "impact_value", "impact_unit",
                    "source_sentence",
                ],
            },
        },
    },
    "required": [
        "title", "executive_summary", "sections", "limitations",
        "metric_series", "comparison_points", "action_impacts",
    ],
}

# Digits, with separators stripped, must reappear in the sentence the model
# says it read the figure from. "4조 5,406억원" -> "45406" is not literally in
# the text, so the check is on the *significant digit runs* instead.
_DIGIT_RUN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# A metric/comparison/action_impact whose only problem is a mismatched
# source_sentence (not a missing/invented fact) gets one repair attempt,
# mirroring sectors/sk_broadband/adapter/analyzer's _repair_failed_claim_quotes.
# Capped the same way that repair caps its candidate passages per claim - the
# corpus here is small (a handful of synthesis sentences), but the failure
# count and prompt size are still bounded defensively.
_MAX_REPAIR_ITEMS_TOTAL = 15
_MAX_REPAIR_CANDIDATES_PER_ITEM = 5

_QUOTE_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "sentence_id": {"type": ["string", "null"]},
                },
                "required": ["item_id", "sentence_id"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["repairs"],
    "additionalProperties": False,
}


def _take(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:limit]


def _take_raw(values: list, limit: int) -> list:
    """Slice without dedup — for structured (non-hashable-friendly) items like
    MetricPoint/ComparisonPoint, not plain strings."""
    return list(values)[:limit]


def _doc_id(value: str) -> str | None:
    match = _DOC_ID_RE.search(value)
    return match.group(1) if match else None


def _timeline_key_points(synthesis: TrendSynthesis, limit: int) -> list[str]:
    """Real dated evidence sentences + metric_series period labels only — never
    copies overview's key_points (that just duplicated Overview verbatim). If
    neither source yields a real point in time, returns [] so the timeline
    block's own empty-state ("근거에서 확인된 일정이 없습니다") shows honestly."""
    dated_evidence = dated_items(synthesis.evidence)
    metric_labels = [
        f"{point.period} — {point.label}: {point.value}{point.unit}"
        for point in synthesis.metric_series
        if point.period
    ]
    return _take([*dated_evidence, *metric_labels], limit)


def _ensure_all_actions_reachable(
    sections: list[GeneratedReportSection], synthesis: TrendSynthesis
) -> list[GeneratedReportSection]:
    """Guarantee every synthesis.recommended_actions item is reachable somewhere in
    the assembled report. OpenAI may only surface a subset of the analyzer-extracted
    actions per section; anything it dropped gets appended (with its original
    [doc_id=...] marker intact) to the first action-role section instead of silently
    disappearing. Matched by doc_id, not exact text, since the OpenAI writer may
    paraphrase the action while keeping the marker attached."""
    covered_doc_ids = {
        doc_id
        for section in sections
        for action in section.actions
        for doc_id in [_doc_id(action)]
        if doc_id is not None
    }
    missing = [action for action in synthesis.recommended_actions if _doc_id(action) not in covered_doc_ids]
    if not missing:
        return sections
    target_id = next(
        (section.section_id for section in sections if section.section_id in _ACTION_SECTIONS),
        None,
    )
    if target_id is None:
        return sections
    return [
        section.model_copy(update={"actions": [*section.actions, *missing]})
        if section.section_id == target_id
        else section
        for section in sections
    ]


# Analyzers label each key point by what kind of signal it is - the sector
# prompts ask for "시장 변화", "전략 영향", "Risk", "Opportunity", "Action"
# prefixes. Sections that would otherwise all receive the same flat list can
# take the slice that matches what they are about.
_KEY_POINT_LABELS: dict[str, tuple[str, ...]] = {
    "trend": ("시장 변화", "Market", "Trend"),
    "market_status": ("시장 변화", "Market"),
    "impact": ("전략 영향", "Impact"),
    # Not "시장 변화": market_status owns that label, and both sections
    # claiming it made the two cards restate each other.
    "current_situation": ("전략 영향", "Opportunity"),
}


def _labelled_key_points(section_id: str, key_points: list[str], limit: int) -> list[str]:
    """Key points whose analyzer label matches this section's subject.

    Falls back to the whole list when the sector's analyzer doesn't use
    labels, or when nothing matches - a section with its own slice is better
    than a section with none, and losing a real point to a labelling
    convention would be worse than repeating one.
    """
    prefixes = _KEY_POINT_LABELS.get(section_id)
    if not prefixes:
        return _take(key_points, limit)
    matched = [
        point for point in key_points
        if any(point.strip().startswith(prefix) for prefix in prefixes)
    ]
    return _take(matched or key_points, limit)


def _digit_runs(text: str) -> set[str]:
    return {run.replace(",", "").rstrip(".0") or "0" for run in _DIGIT_RUN_RE.findall(text or "")}


_LABEL_PERIOD_RE = re.compile(r"(?:20\d{2}|'\d{2})\s*년|\s*[1-4]\s*분기|\s*상반기|\s*하반기")
_LABEL_NOISE_RE = re.compile(r"\b(?:누적|연결|별도|개별|잠정|연간|전사|예상|전망|추정)\b|[()（）]")
_LABEL_ALIASES = {"매출액": "매출", "영업이익률": "영업이익률", "순이익률": "순이익률"}


def normalize_metric_label(label: str) -> str:
    """Strip period and qualifier text that belongs in `period`, not the label.

    Live-observed: the model returned the same metric as "누적 연결 매출액",
    "2026년 1분기 매출" and "2026년 2분기 매출 예상". Charts group points by
    label, so three revenue figures that should have formed one 3-period trend
    line stayed three unrelated one-off numbers and no chart was drawn. The
    period is already carried in `period`; folding a copy of it into the label
    only breaks the grouping.
    """
    cleaned = _LABEL_NOISE_RE.sub(" ", _LABEL_PERIOD_RE.sub(" ", label or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·-–")
    return _LABEL_ALIASES.get(cleaned, cleaned) or (label or "").strip()


def _metric_points_with_failures(
    raw_points: list[dict], synthesis: TrendSynthesis, foreign_names: set[str],
    *, value_must_be_in_own_sentence: bool = False,
) -> tuple[list[MetricPoint], list[dict]]:
    """Split candidate figures into verified points and repair-eligible failures.

    The model is allowed to *find* numbers the regex missed; it is not allowed
    to state one. A point survives only if the digits of its value appear in
    some evidence/key_point/highlight sentence, mirroring how
    _verified_metric_points works in the sector analyzers. Figures whose label
    names a different SK affiliate are dropped too: an affiliate name in the
    `label` is a sign the model put the subject in the wrong field, and read
    as-is the figure would pass for this company's own number. A competitor
    named in `subject` is fine - that is what the field is for.

    Missing label/period or a foreign-affiliate label are structural problems
    - no re-quote can fix them, so those are dropped outright, same as
    before. Only "the stated digits don't show up anywhere in the corpus" is
    treated as repair-eligible and returned in the second list, tagged with a
    stable item_id, for _repair_failed_extraction_quotes to attempt.

    `value_must_be_in_own_sentence` tightens the check to "this figure appears
    in the sentence being cited for it", and the repair path must set it.
    The default check compares against the digits of the *whole* corpus, which
    a repaired item passes for free: repair substitutes a sentence taken from
    that same corpus, so any sentence containing a digit satisfies it and the
    test degenerates into "the chosen sentence has a number in it". Live-
    reproduced: a value of 999만명 present nowhere in the evidence was
    rejected, then accepted once its source_sentence was swapped for a real
    one about 682만명.
    """
    corpus = [*synthesis.evidence, *synthesis.key_points, *synthesis.highlights]
    corpus_digits: set[str] = set()
    for sentence in corpus:
        corpus_digits |= _digit_runs(sentence)

    verified: list[MetricPoint] = []
    failures: list[dict] = []
    for index, raw in enumerate(raw_points):
        label = (raw.get("label") or "").strip()
        if not label or not (raw.get("period") or "").strip():
            continue
        if any(name in label for name in foreign_names):
            continue
        sentence = raw.get("source_sentence", "")
        if value_must_be_in_own_sentence:
            supported = bool(_digit_runs(str(raw.get("value", ""))) & _digit_runs(sentence))
        else:
            supported = bool(
                (_digit_runs(sentence) | _digit_runs(str(raw.get("value", "")))) & corpus_digits
            )
        if not supported:
            failures.append({"item_id": f"m{index}", "kind": "metric", "raw": raw})
            continue
        is_relative, comparison_period = relative_metric_context(sentence)
        verified.append(
            MetricPoint(
                label=normalize_metric_label(label) or label,
                subject=(raw.get("subject") or "").strip() or None,
                period=raw["period"].strip(),
                value=float(raw["value"]),
                unit=(raw.get("unit") or "").strip() or None,
                is_forecast=_is_stated_forecast(raw),
                value_type=metric_value_type(raw.get("source_sentence", "")),
                is_relative=is_relative,
                comparison_period=comparison_period,
                value_origin="source",
                share_of=(raw.get("share_of") or "").strip() or None,
            )
        )
    return verified, failures


def _verified_ai_metric_points(
    raw_points: list[dict], synthesis: TrendSynthesis, foreign_names: set[str]
) -> list[MetricPoint]:
    return _metric_points_with_failures(raw_points, synthesis, foreign_names)[0]


def _apply_comparison_multi_entity_filter(points: list[ComparisonPoint]) -> list[ComparisonPoint]:
    """A criterion held by only one entity is dropped - one row is not a
    comparison, and it would render as a table with a single line. Applied
    once, after repair has had a chance to add entities back in, since this
    is a property of the whole list rather than any single point."""
    entities_per_criterion: dict[str, set[str]] = {}
    for point in points:
        entities_per_criterion.setdefault(point.criterion, set()).add(point.entity)
    return [
        point for point in points
        if len(entities_per_criterion[point.criterion]) >= 2
    ]


def _comparison_points_with_failures(
    raw_points: list[dict], synthesis: TrendSynthesis
) -> tuple[list[ComparisonPoint], list[dict]]:
    """AI-extracted comparisons, kept only where the source text supports them.

    Same contract as the metric verifier: the model widens recall over prose
    the sector analyzer never structured, but a claim it cannot point at in
    the evidence is dropped. Missing entity/criterion/value is structural -
    dropped outright. A source_sentence that doesn't literally appear in the
    corpus (and whose entity isn't mentioned anywhere either) is the
    repair-eligible case: the model likely paraphrased a real sentence
    instead of copying it verbatim.

    The single-entity-per-criterion filter is applied by the caller via
    _apply_comparison_multi_entity_filter, after any repaired points are
    merged in.
    """
    corpus = " ".join([*synthesis.evidence, *synthesis.key_points, *synthesis.highlights])
    verified: list[ComparisonPoint] = []
    failures: list[dict] = []
    for index, raw in enumerate(raw_points):
        entity = (raw.get("entity") or "").strip()
        criterion = (raw.get("criterion") or "").strip()
        value = (raw.get("value") or "").strip()
        sentence = (raw.get("source_sentence") or "").strip()
        if not (entity and criterion and value):
            continue
        if sentence and sentence not in corpus and entity not in corpus:
            failures.append({"item_id": f"c{index}", "kind": "comparison", "raw": raw})
            continue
        level = raw.get("level")
        verified.append(
            ComparisonPoint(
                entity=entity,
                criterion=criterion,
                value=value,
                level=level if level in {"low", "medium", "high"} else None,
            )
        )
    return verified, failures


def _verified_ai_comparison_points(
    raw_points: list[dict], synthesis: TrendSynthesis
) -> list[ComparisonPoint]:
    verified, _ = _comparison_points_with_failures(raw_points, synthesis)
    return _apply_comparison_multi_entity_filter(verified)


_CONFIDENCE_ORDER = ("low", "medium", "high")


def section_confidence(confidence_labels: list[str]) -> str | None:
    """The most conservative confidence stated across the evidence.

    `GeneratedReportSection.confidence` was a free `str` and got
    ", ".join(confidence_labels) written into it, so a field whose only valid
    values are low/medium/high ended up holding
    'high [doc_id=…], high [doc_id=…]'. Downstream code comparing it to
    "high" silently never matched. Take the lowest label present - a section
    is only as certain as its weakest evidence - and return None when the
    labels say nothing usable.
    """
    found = {
        level
        for label in confidence_labels or []
        for level in _CONFIDENCE_ORDER
        if (label or "").strip().lower().startswith(level)
    }
    for level in _CONFIDENCE_ORDER:
        if level in found:
            return level
    return None


# A figure is a forecast only if the evidence says so. The words below are
# the ones Korean coverage actually uses to mark one; the model's own
# `is_forecast` flag is confirmed against them rather than taken on trust,
# so a historical figure cannot be relabelled as a projection.
_FORECAST_MARKERS = ("전망", "예상", "목표", "추정", "계획", "가이던스", "예측", "forecast", "estimate")


def _is_stated_forecast(raw: dict) -> bool:
    if not raw.get("is_forecast"):
        return False
    context = f"{raw.get('period') or ''} {raw.get('source_sentence') or ''}"
    return any(marker in context for marker in _FORECAST_MARKERS)


def _stated_impact_size(raw: dict, sentence: str) -> tuple[float | None, str | None]:
    """The magnitude of an impact, only when the quoted sentence contains it.

    Same rule as every other number here: the model may point at a figure, it
    may not supply one. A value whose digits are absent from the sentence it
    claims to come from is dropped, and the prose impact is kept without a bar.
    """
    raw_value = raw.get("impact_value")
    if raw_value is None:
        return None, None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None, None
    if not (_digit_runs(str(raw_value)) & _digit_runs(sentence)):
        return None, None
    return value, (raw.get("impact_unit") or "").strip() or None


def _action_impacts_with_failures(
    raw_impacts: list[dict], synthesis: TrendSynthesis
) -> tuple[list[ActionImpact], list[dict]]:
    """Action->outcome links the evidence genuinely states.

    Three structural ways to be dropped outright, none of them fixable by a
    better quote: the action isn't one we actually recommended, the
    "impact" just restates the action, or a required field is empty. Only
    "the quoted sentence isn't in the evidence" is repair-eligible - the
    outcome may still be genuinely stated somewhere, just not verbatim in
    what the model copied.
    """
    corpus = " ".join([*synthesis.evidence, *synthesis.key_points, *synthesis.highlights])
    known_actions = {
        _DOC_ID_RE.sub("", action).strip(): action
        for action in synthesis.recommended_actions
    }
    verified: list[ActionImpact] = []
    failures: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_impacts):
        action = _DOC_ID_RE.sub("", raw.get("action") or "").strip()
        impact = (raw.get("expected_impact") or "").strip()
        sentence = (raw.get("source_sentence") or "").strip()
        if not (action and impact and sentence) or action in seen:
            continue
        if action not in known_actions:
            continue
        if impact == action or impact in action or action in impact:
            continue
        if sentence not in corpus:
            failures.append({"item_id": f"a{index}", "kind": "action", "raw": raw})
            continue
        seen.add(action)
        value, unit = _stated_impact_size(raw, sentence)
        verified.append(
            ActionImpact(
                action=known_actions[action], expected_impact=impact, evidence_quote=sentence,
                impact_value=value, impact_unit=unit,
            )
        )
    return verified, failures


def _verified_action_impacts(
    raw_impacts: list[dict], synthesis: TrendSynthesis
) -> list[ActionImpact]:
    return _action_impacts_with_failures(raw_impacts, synthesis)[0]


def _dedupe_action_impacts(impacts: list[ActionImpact]) -> list[ActionImpact]:
    """Keep the first ActionImpact per action text.

    _action_impacts_with_failures's own within-call `seen` set only guards a
    single pass; merging its initial-pass output with a second, repaired-pass
    output (see _repair_failed_extraction_quotes's caller) can in theory let
    the same action survive twice. This is the backstop for that merge.
    """
    seen: set[str] = set()
    deduped: list[ActionImpact] = []
    for impact in impacts:
        if impact.action in seen:
            continue
        seen.add(impact.action)
        deduped.append(impact)
    return deduped


def _indexed_corpus_sentences(synthesis: TrendSynthesis) -> list[dict[str, str]]:
    """The same evidence/key_points/highlights corpus the verifiers above
    check source_sentence against, indexed into stable per-sentence IDs so a
    repair call can select one rather than write free text (which would risk
    inventing a sentence that was never actually said)."""
    sentences = list(
        dict.fromkeys(
            text.strip()
            for text in [*synthesis.evidence, *synthesis.key_points, *synthesis.highlights]
            if text and text.strip()
        )
    )
    return [{"sentence_id": f"S{index:03d}", "text": text} for index, text in enumerate(sentences, 1)]


def _repair_query_terms(item: dict) -> list[str]:
    kind = item["kind"]
    raw = item["raw"]
    if kind == "metric":
        text = f"{raw.get('label') or ''} {raw.get('subject') or ''} {raw.get('period') or ''} {raw.get('value') or ''}"
    elif kind == "comparison":
        text = f"{raw.get('entity') or ''} {raw.get('criterion') or ''} {raw.get('value') or ''}"
    else:  # action
        text = f"{raw.get('action') or ''} {raw.get('expected_impact') or ''}"
    return list(dict.fromkeys(re.findall(r"[가-힣a-z0-9]{2,}", text.lower())))


def _repair_candidates_for_item(item: dict, corpus: list[dict[str, str]]) -> list[dict[str, str]]:
    terms = _repair_query_terms(item)
    ranked = sorted(
        enumerate(corpus),
        key=lambda pair: (-sum(pair[1]["text"].lower().count(term) for term in terms), pair[0]),
    )
    return [sentence for _, sentence in ranked[:_MAX_REPAIR_CANDIDATES_PER_ITEM]]


def _repair_failed_extraction_quotes(
    client, model: str, failures: list[dict], synthesis: TrendSynthesis
) -> dict[str, str]:
    """One extra, bounded API call that gives metric/comparison/action_impact
    items a second chance at a matching source_sentence - mirroring
    sectors/sk_broadband/adapter/analyzer's _repair_failed_claim_quotes, but
    over a small pre-extracted sentence corpus instead of raw scraped pages,
    so the model picks a sentence_id rather than writing a quote (nothing it
    returns can be a sentence that wasn't actually in the corpus).

    Only called with items that already passed every structural check in
    their `_with_failures` counterpart - the claim/label/entity/action itself
    is never touched here, only which real sentence backs it.
    """
    if not failures:
        return {}
    bounded_failures = failures[:_MAX_REPAIR_ITEMS_TOTAL]
    corpus = _indexed_corpus_sentences(synthesis)
    if not corpus:
        return {}

    candidates_by_item = {
        item["item_id"]: _repair_candidates_for_item(item, corpus) for item in bounded_failures
    }
    referenced_ids = {
        sentence["sentence_id"]
        for candidates in candidates_by_item.values()
        for sentence in candidates
    }
    repair_input = {
        "candidate_sentences": [sentence for sentence in corpus if sentence["sentence_id"] in referenced_ids],
        "items_to_repair": [
            {
                "item_id": item["item_id"],
                "kind": item["kind"],
                "looking_for": " ".join(_repair_query_terms(item)),
                "candidate_sentence_ids": [
                    sentence["sentence_id"] for sentence in candidates_by_item[item["item_id"]]
                ],
            }
            for item in bounded_failures
        ],
        "instructions": (
            "각 item이 실제로 필요로 하는 사실을 candidate_sentence_ids로 주어진 후보 문장 중에서만 "
            "골라 sentence_id로 반환하라. 후보 중 그 사실을 직접 뒷받침하는 문장이 없으면 반드시 "
            "sentence_id를 null로 반환하라. 문장을 새로 쓰거나 후보 밖의 문장을 고르지 말라."
        ),
    }
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=1600,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You repair source citations only. Never invent a sentence - choose "
                        "sentence_id only from the candidates offered, or null if none of them "
                        "actually state the fact."
                    ),
                },
                {"role": "user", "content": json.dumps(repair_input, ensure_ascii=False)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "report_generator_quote_repair",
                    "schema": _QUOTE_REPAIR_SCHEMA,
                    "strict": True,
                },
            },
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            return {}
        repairs = json.loads(message.content).get("repairs", [])
    except Exception as exc:  # noqa: BLE001
        print(f"[report_generator] quote repair failed: {exc}", file=sys.stderr)
        return {}

    corpus_by_id = {sentence["sentence_id"]: sentence["text"] for sentence in corpus}
    repaired: dict[str, str] = {}
    for repair in repairs:
        item_id = repair.get("item_id")
        sentence_id = repair.get("sentence_id")
        allowed_ids = {
            sentence["sentence_id"] for sentence in candidates_by_item.get(item_id, [])
        }
        if not item_id or sentence_id not in allowed_ids:
            continue
        repaired[item_id] = corpus_by_id[sentence_id]
    return repaired


def _diversity_limitations(synthesis: TrendSynthesis) -> list[str]:
    if synthesis.source_count and synthesis.unique_source_count == 1:
        source_label = synthesis.source_ids[0] if synthesis.source_ids else "단일 출처"
        return [
            f"수집 문서는 {synthesis.source_count}건이지만 고유 출처는 {synthesis.unique_source_count}개({source_label})뿐입니다. "
            "경쟁 현황과 전략 판단은 추가 출처로 교차 검증해야 합니다."
        ]
    return []


def _fulfillment_disclosures(question_brief: QuestionBrief | None) -> list[str]:
    """Turn post-synthesis gaps into short, factual report disclosures.

    These statements describe only the evidence contract, never an answer or
    a suggested remedy.  They make the rule-based fallback as honest as the
    AI writer, whose prompt receives the same fulfillment payload.
    """
    if not question_brief:
        return []
    answers = {item.answer_id: item for item in question_brief.requested_answers}
    requirements = {item.requirement_id: item for item in question_brief.evidence_requirements}
    disclosures: list[str] = []
    for fulfillment in question_brief.fulfillment:
        if fulfillment.status == "fulfilled":
            continue
        answer = answers.get(fulfillment.for_answer_id)
        if not answer:
            continue
        supported = [
            requirements[item_id].semantic_target
            for item_id in fulfillment.supported_requirement_ids
            if item_id in requirements
        ]
        missing = [
            requirements[item_id].semantic_target
            for item_id in fulfillment.missing_requirement_ids
            if item_id in requirements
        ]
        confirmed_text = ", ".join(dict.fromkeys(supported)) if supported else "확인된 근거 없음"
        missing_text = ", ".join(dict.fromkeys(missing)) if missing else "추가 확인 필요"
        disclosures.append(
            f"‘{answer.subject}’ 요청은 확인된 범위: {confirmed_text}. "
            f"확인하지 못한 근거 형태: {missing_text}."
        )
    return disclosures


def _repair_section(
    section: GeneratedReportSection,
    fallback: GeneratedReportSection,
) -> GeneratedReportSection:
    """Normalize semantic placement and reject untraceable generated bullets."""
    data = section.model_dump()
    if section.section_id in _ACTION_SECTIONS and not data["actions"] and data["key_points"]:
        data["actions"] = data["key_points"]
        data["key_points"] = []
    fallback_data = fallback.model_dump()
    for field in _TRACEABLE_FIELDS:
        traced = [item for item in data[field] if "[doc_id=" in item]
        data[field] = traced or fallback_data[field]
    # Structured facts (metric_points/comparison_points/strengths/weaknesses) are never
    # requested from the OpenAI report writer (see _REPORT_SCHEMA) — always take them
    # from the rule-based fallback, which copies them unmodified from synthesis. This
    # keeps numbers/comparisons exactly as the analyzer extracted them, never rewritten.
    for field in (
        "strengths",
        "weaknesses",
        "metric_points",
        "comparison_points",
        "grounded_claims",
        "conclusions",
    ):
        data[field] = fallback_data[field]
    if not data.get("confidence"):
        data["confidence"] = fallback.confidence
    return GeneratedReportSection.model_validate(data)


def _missing_needs_limitation(missing_information_needs: list[str] | None) -> list[str]:
    """Honest '확인 안 됨' disclosure for information needs the collector
    genuinely couldn't find grounded evidence for, after its full search
    budget - never fabricated, never silently dropped, never allowed to
    block the rest of the report (see sk_broadband's collector, which now
    accepts a partial result instead of all-or-nothing)."""
    if not missing_information_needs:
        return []
    return [
        "다음 정보는 근거를 확인하지 못해 반영하지 못했습니다 (확인 안 됨): "
        + ", ".join(missing_information_needs)
    ]


def _fallback_report(
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
    limitation: str | None = None,
    missing_information_needs: list[str] | None = None,
    question_brief: QuestionBrief | None = None,
) -> GeneratedReport:
    profile = load_audience_profile(audience_id)
    limit = {"highlight_only": 2, "condensed": 3, "summary": 4}.get(profile.detail_level, 6)
    section_ids: list[str] = []
    kwargs_list: list[dict[str, list]] = []
    for section_id in report_plan.sections:
        key_points = synthesis.key_points or synthesis.highlights
        kwargs: dict[str, list] = {}
        refs = report_plan.section_evidence_map.get(section_id)
        claim_ids = set(refs.claim_ids) if refs else set()
        metric_ids = set(refs.metric_ids) if refs else set()
        comparison_ids = set(refs.comparison_ids) if refs else set()
        kwargs["grounded_claims"] = [
            claim for claim in synthesis.grounded_claims
            if claim.synthesis_claim_id in claim_ids
        ]
        conclusion_ids = set(refs.conclusion_ids) if refs else set()
        kwargs["conclusions"] = [
            conclusion for conclusion in synthesis.conclusions
            if conclusion.conclusion_id in conclusion_ids
        ]
        if section_id in {"issue", "problem", "root_cause", "risk"}:
            # "문제 정의" states what is wrong (the observed weakness); "근본
            # 원인" states why it happens (the risk driving it). Both used to
            # take the same synthesis.risks list, so the two cards read
            # identically in every root_cause report.
            if section_id == "problem":
                kwargs["key_points"] = _take(synthesis.weaknesses or key_points, limit)
                kwargs["weaknesses"] = _take(synthesis.weaknesses, limit)
            else:
                kwargs["risks"] = _take(synthesis.risks, limit)
                kwargs["weaknesses"] = _take(synthesis.weaknesses, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
            if section_id in COMPARISON_SECTIONS:
                kwargs["comparison_points"] = _take_raw(synthesis.comparison_points, limit)
        elif section_id == "risk_and_opportunity":
            kwargs["risks"] = _take(synthesis.risks, limit)
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["strengths"] = _take(synthesis.strengths, limit)
            kwargs["weaknesses"] = _take(synthesis.weaknesses, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in COMPARISON_SECTIONS:
            # business_impacts belongs to "영향"; market_status and
            # current_situation both taking it made all three cards open with
            # the same sentence. The others use their own labelled slice.
            # A section already carrying a comparison table doesn't need a
            # bullet restating what the table shows - and taking one made
            # market_status echo trend's single "시장 변화" point.
            if section_id == "impact":
                kwargs["key_points"] = _take(synthesis.business_impacts, limit)
            elif not synthesis.comparison_points:
                kwargs["key_points"] = _labelled_key_points(section_id, key_points, limit)
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
            kwargs["comparison_points"] = _take_raw(synthesis.comparison_points, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id in _ACTION_SECTIONS:
            # No monitoring_indicators: an action section states what to do.
            # The watch-list is a different question and belongs to the
            # forward-looking section (investment_signal / near_term_outlook),
            # whichever this purpose has - it was appearing under three
            # headings at once.
            kwargs["actions"] = _take(synthesis.recommended_actions, limit)
        elif section_id == "key_metrics":
            # No monitoring_indicators here: this section lists the figures
            # that were found, and the same watch-list was appearing verbatim
            # under key_metrics, near_term_outlook and recommended_action at
            # once. It belongs with the action it qualifies.
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        elif section_id == "timeline":
            kwargs["key_points"] = _timeline_key_points(synthesis, limit)
            # Dated sentences only. Handing it the whole evidence list made the
            # timeline's evidence identical to market_status's, so the section
            # about *when* things happened cited the same undated prose as the
            # section about what the market looks like now.
            kwargs["evidence"] = _take(dated_items(synthesis.evidence), limit)
        elif section_id == "sources":
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        # These four sections were given one identical opportunities list and
        # one identical monitoring list each, so four differently-titled cards
        # said exactly the same thing. They are different questions and now
        # draw on different fields: what is changing, where the opening is,
        # what to watch, and what happens next.
        elif section_id == "trend":
            kwargs["key_points"] = _labelled_key_points(section_id, key_points, limit)
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
        elif section_id == "opportunity":
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["strengths"] = _take(synthesis.strengths, limit)
        elif section_id == "investment_signal":
            kwargs["metric_points"] = _take_raw(synthesis.metric_series, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
        elif section_id == "near_term_outlook":
            kwargs["opportunities"] = _take(synthesis.opportunities, limit)
            kwargs["monitoring_indicators"] = _take(synthesis.monitoring_indicators, limit)
        else:
            kwargs["key_points"] = _take(key_points, limit)
            kwargs["evidence"] = _take(synthesis.evidence, limit)
        if "metric_points" in kwargs and metric_ids:
            kwargs["metric_points"] = [
                point for point in kwargs["metric_points"]
                if point.metric_id in metric_ids
            ]
        if "comparison_points" in kwargs and comparison_ids:
            kwargs["comparison_points"] = [
                point for point in kwargs["comparison_points"]
                if point.comparison_id in comparison_ids
            ]
        section_ids.append(section_id)
        kwargs_list.append(kwargs)

    # Single ownership: the same evidence-stated metric/comparison shouldn't
    # get mechanically copied into every section whose branch above happens
    # to request "metric_points"/"comparison_points" from the same synthesis
    # list - keep it only in the first (i.e. earliest in report_plan.sections
    # order) section that asked for it.
    deduped_metric_points = dedupe_structured_across_sections(
        [kwargs.get("metric_points", []) for kwargs in kwargs_list]
    )
    # "first in plan order" is the right owner except when a later section is
    # specifically *about* the comparison. In a root-cause report the causes
    # ranked by contribution belong under Root Cause, not under the Problem
    # Definition that merely happens to come first.
    comparison_lists = [kwargs.get("comparison_points", []) for kwargs in kwargs_list]
    if "root_cause" in section_ids:
        owner = section_ids.index("root_cause")
        if comparison_lists[owner] or any(comparison_lists):
            claimed = next((points for points in comparison_lists if points), [])
            comparison_lists = [
                claimed if index == owner else ([] if "comparison_points" in kwargs_list[index] else points)
                for index, points in enumerate(comparison_lists)
            ]
    deduped_comparison_points = dedupe_structured_across_sections(comparison_lists)

    # Same single-ownership rule for the narrative lists. Differentiating the
    # section branches above stops the obvious copies, but neighbouring
    # sections still restate each other, and one sentence repeated verbatim
    # under three headings tells the reader nothing three times.
    #
    # `evidence` is deliberately NOT in this list. It is citation, not
    # narrative: the same source sentence legitimately backs several sections,
    # the timeline's evidence is a dated *subset* of what overview cites, and
    # `sources` exists to list all of it. It also made block choice depend on
    # audience - the per-audience item limit runs first, so which sentence
    # survived deduplication differed between practitioner and executive, and
    # the timeline block appeared for one and not the other.
    for field in ("key_points", "risks", "opportunities", "actions", "monitoring_indicators"):
        owned_indexes = [index for index, kwargs in enumerate(kwargs_list) if field in kwargs]
        if len(owned_indexes) < 2:
            continue
        # Ownership goes to the most specific section, not the earliest one.
        # "overview" summarises everything and sits first, so processing in
        # plan order made it claim the very points that "trend" or "impact"
        # had already narrowed down to their own subject - and those sections
        # then fell back to their originals, restoring the duplicate.
        owned_indexes.sort(key=lambda index: section_ids[index] in _SUMMARY_SECTIONS)
        originals = [kwargs_list[index][field] for index in owned_indexes]
        for index, values, original in zip(owned_indexes, dedupe_across_blocks(originals), originals):
            # Emptying a section outright is worse than repeating a sentence:
            # a section with nothing left is dropped from the report entirely
            # (has_renderable_content), so over-eager deduplication silently
            # deleted whole sections - the timeline lost its dated points to
            # overview, and "trend" lost everything and fell to an
            # unclassified block. Deduplication is a nicety; keep the section.
            kwargs_list[index][field] = values or original
    for kwargs, metric_points, comparison_points in zip(kwargs_list, deduped_metric_points, deduped_comparison_points):
        if "metric_points" in kwargs:
            kwargs["metric_points"] = metric_points
        if "comparison_points" in kwargs:
            kwargs["comparison_points"] = comparison_points

    sections: list[GeneratedReportSection] = []
    for section_id, kwargs in zip(section_ids, kwargs_list):
        summary_values = next(
            (kwargs[field] for field in _TEXT_SUMMARY_FIELDS if kwargs.get(field)), []
        )
        sections.append(
            GeneratedReportSection(
                section_id=section_id,
                title=section_title(section_id),
                summary=" ".join(summary_values[:2]) or synthesis.synthesis_text or "분석 가능한 근거가 부족합니다.",
                confidence=section_confidence(synthesis.confidence_labels),
                **kwargs,
            )
        )
    limitations = _diversity_limitations(synthesis)
    if synthesis.source_count == 0:
        limitations.append("분석에 사용할 수집 문서가 없어 결론을 확정할 수 없습니다.")
    limitations.extend(_missing_needs_limitation(missing_information_needs))
    limitations.extend(_fulfillment_disclosures(question_brief))
    if limitation:
        limitations.append(limitation)
    purpose_id = report_plan.report_purpose.purpose_id if report_plan.report_purpose else report_plan.primary_intent
    return GeneratedReport(
        request_id=synthesis.request_id,
        sector_id=synthesis.sector_id,
        audience_id=profile.audience_id,
        purpose_id=purpose_id,
        title=f"{synthesis.sector_id} {purpose_id} 보고서",
        executive_summary=synthesis.synthesis_text or "분석 가능한 근거가 부족합니다.",
        sections=sections,
        source_count=synthesis.source_count,
        unique_source_count=synthesis.unique_source_count,
        limitations=limitations,
        generation_mode="rule_based",
    )



# A gpt-4o account's tokens-per-minute allowance is the real ceiling here, not
# the model's context window. Live-observed on a 롱폼/숏폼 run: the request
# came to 30,881 tokens against a 30,000 TPM limit, the call raised 429, and
# the whole report silently fell back to the rule-based path - which also
# meant none of the figures sitting in the evidence were ever structured.
#
# Budget in characters, because that is what can be measured without adding a
# tokenizer dependency. Korean runs roughly 1.4 tokens per character on
# o200k, so the default leaves room for the system prompt and the response
# inside a 30k allowance. Override per deployment; a larger allowance is a
# reason to raise it, not to remove the check.
_PAYLOAD_CHAR_BUDGET = int(os.getenv("TRENDSPARC_REPORT_GENERATOR_CHAR_BUDGET", "14000"))

# Trimmed in this order once the two structural savings below aren't enough.
# Highlights go first because they restate key_points; evidence goes last and
# keeps a floor, because it is the text every figure is extracted from - a
# report that loses its evidence sentences loses its charts with them.
_TRIM_ORDER = (
    ("highlights", 0),
    ("key_points", 3),
    ("grounded_claims", 4),
    ("metric_series", 12),
    ("evidence", 8),
)


def _claim_for_writer(claim: dict) -> dict:
    """A claim as the report writer needs it, not as the pipeline stores it.

    `section_evidence_map` refers to claims by id, so ids and text have to
    survive. Everything else - passage ids, locations, urls, reliability
    tiers, and the evidence quote that is already in `evidence` verbatim - is
    provenance the writer never reads. On the run that hit the limit it was
    half the request: 21,758 of 42,770 characters.
    """
    return {
        "synthesis_claim_id": claim.get("synthesis_claim_id"),
        "claim_type": claim.get("claim_type"),
        "claim": claim.get("claim"),
        "source_id": claim.get("source_id"),
    }


def _metric_for_writer(point: dict) -> dict:
    """Keep the chart axes and provenance reference, not repeated evidence.

    One evidence sentence can contain many values.  Serialising that same
    sentence, URL, document metadata and two claim ids into every metric made
    a 62-claim run spend 42,802 characters on `metric_series` alone.  The
    sentence already exists once in `synthesis.evidence`; the report writer
    only needs the structured axes plus a stable reference to it.
    """
    compact = {
        "metric_id": point.get("metric_id"),
        "label": point.get("label"),
        "subject": point.get("subject"),
        "period": point.get("period"),
        "value": point.get("value"),
        "unit": point.get("unit"),
        "is_forecast": bool(point.get("is_forecast")),
        "value_type": point.get("value_type", "actual"),
        "evidence_synthesis_claim_id": point.get("evidence_synthesis_claim_id"),
    }
    if point.get("is_relative"):
        compact.update({
            "is_relative": True,
            "comparison_period": point.get("comparison_period"),
            "value_origin": point.get("value_origin", "source"),
        })
    return compact


def _referenced_claim_ids(report_plan: Any) -> set[str]:
    """Claim ids the section map actually points at - those are the ones the
    writer is told to place, so they are the last claims to drop."""
    referenced: set[str] = set()
    for refs in getattr(report_plan, "section_evidence_map", {}).values():
        for field in ("claim_ids", "metric_ids", "comparison_ids", "conclusion_ids"):
            referenced.update(getattr(refs, field, None) or [])
    return referenced


def _fit_payload(payload: dict, report_plan: Any, budget: int) -> dict:
    """Shrink the request until it fits, cheapest loss first.

    Two structural savings come before any content is dropped, and on the run
    that failed they alone took 42,770 characters to 20,069: claims are
    reduced to the four fields the writer reads, and rule-based conclusions -
    which are 1:1 restatements of the claims above them - are dropped.

    Only then are whole items removed, never parts of them. A truncated
    figure ("78.8" from "78.8%") is worse than an absent one: the verifier
    would reject it as unsupported, and the failure would read as a data
    problem rather than a size one.
    """
    synthesis = payload.get("synthesis") or {}
    refs_by_section = getattr(report_plan, "section_evidence_map", {}) or {}
    referenced_claims = {
        claim_id for refs in refs_by_section.values() for claim_id in (refs.claim_ids or [])
    }
    referenced_metrics = {
        metric_id for refs in refs_by_section.values() for metric_id in (refs.metric_ids or [])
    }
    referenced_comparisons = {
        comparison_id for refs in refs_by_section.values() for comparison_id in (refs.comparison_ids or [])
    }
    # The writer needs the evidence routed to actual report sections, not the
    # complete synthesis archive. Preserve the archive in PipelineResult;
    # this is only a transport projection for the LLM request.
    if referenced_claims:
        synthesis["grounded_claims"] = [
            claim for claim in synthesis.get("grounded_claims", [])
            if claim.get("synthesis_claim_id") in referenced_claims
        ]
    if referenced_metrics:
        synthesis["metric_series"] = [
            point for point in synthesis.get("metric_series", [])
            if point.get("metric_id") in referenced_metrics
        ]
    if referenced_comparisons:
        synthesis["comparison_points"] = [
            point for point in synthesis.get("comparison_points", [])
            if point.get("comparison_id") in referenced_comparisons
        ]
    for archive_only_field in (
        "doc_source_map", "doc_url_map", "sources", "corroborated_points",
        "uncorroborated_points", "contradictions", "analysis_validation_status_by_doc_id",
    ):
        synthesis.pop(archive_only_field, None)
    # These are synthesis-level restatements. The selected grounded claims
    # and structured points above remain the writer's source of truth.
    if referenced_claims:
        synthesis["synthesis_text"] = None
        for repeated_field in ("highlights", "key_points", "business_impacts", "risks", "opportunities"):
            synthesis[repeated_field] = []
    claims = synthesis.get("grounded_claims") or []
    if claims:
        synthesis["grounded_claims"] = [_claim_for_writer(claim) for claim in claims]
    metrics = synthesis.get("metric_series") or []
    if metrics:
        synthesis["metric_series"] = [_metric_for_writer(point) for point in metrics]
    conclusions = synthesis.get("conclusions") or []
    if conclusions and all(
        str(item.get("conclusion_id", "")).startswith("rule:") for item in conclusions
    ):
        synthesis["conclusions"] = []

    def size() -> int:
        return len(json.dumps(payload, ensure_ascii=False))

    # Unreferenced claims before referenced ones: the section map names what
    # the writer has to place, so those are the last to go.
    if size() > budget and synthesis.get("grounded_claims"):
        referenced = _referenced_claim_ids(report_plan)
        if referenced:
            synthesis["grounded_claims"] = sorted(
                synthesis["grounded_claims"],
                key=lambda claim: claim.get("synthesis_claim_id") not in referenced,
            )
    dropped: dict[str, int] = {}
    for field, floor in _TRIM_ORDER:
        while size() > budget and len(synthesis.get(field) or []) > floor:
            synthesis[field] = synthesis[field][:-1]
            dropped[field] = dropped.get(field, 0) + 1
    if dropped:
        print(
            "[report_generator] request trimmed to fit the token budget: "
            + ", ".join(f"{field} -{count}" for field, count in dropped.items()),
            file=sys.stderr,
        )
    if size() > budget:
        print(
            f"[report_generator] request is {size()} chars against a {budget} budget even after "
            "trimming; sending as is",
            file=sys.stderr,
        )
    return payload


def generate_report(
    question: str,
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
    canonical_entities: list[str] | None = None,
    missing_information_needs: list[str] | None = None,
    target_company: str | None = None,
    question_brief: QuestionBrief | None = None,
) -> GeneratedReport:
    """Use structured output when configured; otherwise create an evidence-safe report."""
    api_key = os.getenv("TRENDSPARC_REPORT_GENERATOR_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or synthesis.source_count == 0:
        return _fallback_report(
            synthesis, report_plan, audience_id,
            missing_information_needs=missing_information_needs,
            question_brief=question_brief,
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, **openai_client_kwargs(_BASE_URL_ENV_VAR))
        model = os.getenv("TRENDSPARC_REPORT_GENERATOR_MODEL", "gpt-4o")
        profile = load_audience_profile(audience_id)
        purpose_id = report_plan.report_purpose.purpose_id if report_plan.report_purpose else report_plan.primary_intent
        payload = {
            "question": question,
            "canonical_entities": list(dict.fromkeys(canonical_entities or [])),
            "target_company": target_company,
            "sector_id": synthesis.sector_id,
            # QuestionBrief says what the user asked and which answers are
            # evidence-backed. It is not a replacement for the purpose/audience
            # profiles, which still decide reader flow and expression.
            "question_brief": question_brief.model_dump() if question_brief else None,
            "purpose": {
                "id": purpose_id,
                "question_answer_type": (
                    report_plan.report_purpose.question_answer_type or "status"
                    if report_plan.report_purpose else "status"
                ),
                "secondary_id": (
                    report_plan.report_purpose.secondary_purpose_id if report_plan.report_purpose else None
                ),
                "instructions": report_plan.intent_emphasis,
                "required_sections": report_plan.sections,
                "section_evidence_map": {
                    section_id: refs.model_dump()
                    for section_id, refs in report_plan.section_evidence_map.items()
                },
            },
            "audience": profile.model_dump(),
            "synthesis": synthesis.model_dump(),
        }
        payload = _fit_payload(payload, report_plan, _PAYLOAD_CHAR_BUDGET)
        schema = deepcopy(_REPORT_SCHEMA)
        section_schema = schema["properties"]["sections"]
        section_schema["minItems"] = len(report_plan.sections)
        section_schema["maxItems"] = len(report_plan.sections)
        section_schema["items"]["properties"]["section_id"]["enum"] = list(report_plan.sections)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are TrendSparC's final report writer. Write distinct, complete content for every "
                        "requested section, calibrated to the audience and purpose. Use only the supplied synthesis. "
                        "When payload.question_brief is present, address every requested_answers item directly "
                        "or disclose its fulfillment status. Do not convert an unmet or partial answer into "
                        "generic advice; distinguish confirmed content from what remains unverified. For every "
                        "partial or unmet answer, add one short Korean disclosure where that answer is discussed: "
                        "state the confirmed requirement targets and the missing requirement targets from its "
                        "fulfillment record, without proposing a remedy. Before writing, use the full supplied TrendSynthesis: "
                        "select all relevant verified grounded_claims, metric_series, comparison_points, "
                        "risks, opportunities, and source-stated recommended_actions rather than relying on a single "
                        "headline or synthesis_text. The brief "
                        "sets what must be answered, while purpose and audience set how it is ordered and written. "
                        "payload.audience.description and payload.purpose.instructions are not background color to "
                        "skim - they are the authoritative style/structure rules for this exact report. "
                        "audience.description lays out, in numbered sections, that audience's required information "
                        "density, vocabulary level, section length, and closing call-to-action; follow it precisely "
                        "rather than defaulting to a generic tone. purpose.instructions (when non-empty) specifies "
                        "which of this purpose's angles to emphasize and how to structure each section's content - "
                        "follow it for what to highlight and how to frame it, not just which section_ids to include. "
                        "Two reports for the same synthesis but different audience_id or purpose_id must read "
                        "differently in wording, emphasis, and depth, not just in which sections are present. "
                        "When payload.purpose.secondary_id is set, the question asks for two things at once "
                        "(e.g. current status AND how to respond) - do not let the primary purpose crowd out "
                        "the secondary one. Sections with section_id in response_actions, improvement_plan, "
                        "strategic_recommendation, recommended_action, or decision_required must then contain "
                        "at least 4 distinct items in actions, each ending with its own [doc_id=...] citation "
                        "drawn from synthesis.recommended_actions - do not under-fill them to 1-2 items. "
                        "Keep every [doc_id=...] marker attached to its claim, never invent facts, and state uncertainty. "
                        "Use purpose.section_evidence_map to decide which verified conclusions, claims, metrics, and "
                        "comparisons belong in each section; never move an unsupported fact into another section. "
                        "Copy names in canonical_entities exactly; never abbreviate, translate, or respell them. "
                        "Put recommendations in actions, risks in risks, opportunities in opportunities, and sources in evidence. "
                        "Return every required section_id exactly once and in the supplied order. "
                        "For an executive report, use: so-what summary, key metrics, timeline, decision required, risk, sources. "
                        "Include only evidenced KPI values and timeline events; otherwise label what still needs verification. "
                        "Treat unsupported recommendations as proposals to review, not established decisions. "
                        "payload.target_company is the accountable actor for every recommendation in actions. "
                        "Never turn another company, government body, research institute, association, or source "
                        "publisher's announced plan into payload.target_company's action. Keep such third-party "
                        "plans only as evidence or benchmarks. A subjectless proposal may be framed as an action "
                        "for payload.target_company, but must remain a proposal unless evidence supports adoption. "
                        "The output-language rule is strict: write the title, executive summary, every section, "
                        "and every limitation in the question's language. For a Korean question, all narrative "
                        "text must be Korean; keep only proper names and standard acronyms such as NVIDIA, HBM, "
                        "AI, and ARPU in English. Before returning JSON, verify every narrative field against "
                        "the question's language.\n"
                        "metric_series is a separate, mandatory job: read every sentence in "
                        "synthesis.evidence, synthesis.key_points and synthesis.highlights and structure "
                        "EVERY figure you find there as {label, period, value, unit, source_sentence}. "
                        "A figure is any number carrying a unit - not only 매출/영업이익. Percentages "
                        "(84.9%, 45.1%), counts (669만명, 3건), durations (4.2초), rates and forecasts all "
                        "qualify, and a sentence like \"거실 TV(84.9%)에서 가장 활발하게 시청\" contains one. "
                        "Three axes: `label` is what was measured, `subject` is who or what it was "
                        "measured for, `period` is when. Put an age bracket, a company, a survey group or "
                        "any other entity in `subject` - never in `period`, which is for dates only. Leave "
                        "`subject` null when the figure is simply about the company the question is about. "
                        "\"20대의 TV 도달률 22%\" is label=TV 도달률, subject=20대; "
                        "\"KT 912만명\" is label=IPTV 가입자 수, subject=KT. "
                        "Do not skip a figure because it is inside parentheses or mid-sentence. "
                        "Qualifiers such "
                        "as 누적, 잠정, 연결, 별도, or 전년 동기 대비 must never stop you from extracting the "
                        "value - record the qualifier and the point in time in `period` instead (e.g. "
                        "\"2024년 3분기 누적\", \"2026년 2분기(전망)\"). Always include the year in `period`; if a "
                        "sentence says only \"2분기\", take the year from its surrounding context and write it "
                        "out. Use the same `label` for the same metric across periods so a trend can be "
                        "plotted, and express `value` in the unit you put in `unit` (for Korean currency use "
                        "억원, so \"4조 5,406억원\" is value 45406 unit \"억원\"). Copy the sentence you took "
                        "each figure from into `source_sentence` verbatim. "
                        "Exclude any figure that belongs to a different company than the one the question is "
                        "about - articles frequently report a sibling affiliate's results alongside this "
                        "company's, and those numbers must not appear here. When in doubt, leave it out.\n"
                        "comparison_points is the same job for comparisons stated in prose. Whenever a "
                        "sentence sets two or more subjects against each other on a shared criterion, emit "
                        "one entry per subject as {entity, criterion, value, level, source_sentence} - "
                        "every subject the sentence names, never only the one in parentheses. `criterion` "
                        "must be identical across the entries being compared, or they cannot be tabulated. "
                        "Set `level` to low/medium/high only when the source itself ranks them; use null "
                        "otherwise rather than inventing a rank.\n"
                        "action_impacts links a recommended action to what the evidence says will "
                        "follow from it. Copy the action text verbatim from "
                        "synthesis.recommended_actions, state the outcome in `expected_impact`, and put "
                        "the sentence that says so in `source_sentence`. When that sentence states the "
                        "size of the outcome, also fill `impact_value` and `impact_unit` with it "
                        "(\"가입자 30만명 순증\" is 30 and \"만명\"); leave both null when it only "
                        "describes the outcome in words - do not estimate a size. Only include an action whose "
                        "source actually states a consequence - most recommendations do not, and an "
                        "empty list is the correct answer then. Never infer an impact from the action "
                        "itself, never restate the action as its own impact, and never carry an outcome "
                        "over from a different action.\n"
                        "State what the evidence states, at the certainty the evidence states it. A source "
                        "saying a partnership is being expanded (\"추진 중\", \"확대하고 있다\", \"seizing "
                        "the opportunity to expand\") must not be written as an established fact "
                        "(\"운영 중\", \"도입했다\"). Keep the tense and the hedging of the original."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "trend_report",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        parsed = json.loads(response.output_text)
        foreign_names = foreign_entity_names_for(synthesis.sector_id)
        verified_metrics, metric_failures = _metric_points_with_failures(
            parsed.get("metric_series") or [], synthesis, foreign_names
        )
        comparison_pass, comparison_failures = _comparison_points_with_failures(
            parsed.get("comparison_points") or [], synthesis
        )
        verified_impacts, impact_failures = _action_impacts_with_failures(
            parsed.get("action_impacts") or [], synthesis
        )

        # One bounded extra call gives quote-only failures (structurally valid
        # items whose source_sentence just didn't match the corpus verbatim) a
        # second chance - see _repair_failed_extraction_quotes's docstring.
        # Structural failures (missing fields, foreign affiliate, unknown
        # action, self-restating impact) never reach this list.
        all_failures = [*metric_failures, *comparison_failures, *impact_failures]
        repaired_sentences = _repair_failed_extraction_quotes(client, model, all_failures, synthesis)
        if repaired_sentences:
            def _patched(failures: list[dict], kind: str) -> list[dict]:
                return [
                    {**failure["raw"], "source_sentence": repaired_sentences[failure["item_id"]]}
                    for failure in failures
                    if failure["kind"] == kind and failure["item_id"] in repaired_sentences
                ]

            # Strict here, not corpus-wide: see the flag's docstring - the
            # sentence repair just chose is by construction part of the
            # corpus, so the default check would wave every repaired figure
            # through on the strength of some other sentence's digits.
            extra_metrics, _ = _metric_points_with_failures(
                _patched(metric_failures, "metric"), synthesis, foreign_names,
                value_must_be_in_own_sentence=True,
            )
            extra_comparisons, _ = _comparison_points_with_failures(
                _patched(comparison_failures, "comparison"), synthesis
            )
            extra_impacts, _ = _action_impacts_with_failures(
                _patched(impact_failures, "action"), synthesis
            )
            verified_metrics = [*verified_metrics, *extra_metrics]
            comparison_pass = [*comparison_pass, *extra_comparisons]
            verified_impacts = [*verified_impacts, *extra_impacts]

        extracted_metrics = verified_metrics
        extracted_comparisons = _apply_comparison_multi_entity_filter(comparison_pass)
        action_impacts = _dedupe_action_impacts(verified_impacts)
        fallback = _fallback_report(synthesis, report_plan, audience_id, question_brief=question_brief)
        fallback_by_id = {section.section_id: section for section in fallback.sections}
        returned_by_id = {
            section["section_id"]: GeneratedReportSection.model_validate(section)
            for section in parsed["sections"]
            if section.get("section_id") in fallback_by_id
        }
        missing = [section_id for section_id in report_plan.sections if section_id not in returned_by_id]
        sections = [
            _repair_section(returned_by_id.get(section_id, fallback_by_id[section_id]), fallback_by_id[section_id])
            for section_id in report_plan.sections
        ]
        sections = _ensure_all_actions_reachable(sections, synthesis)
        limitations = list(
            dict.fromkeys(
                [
                    *parsed["limitations"],
                    *_diversity_limitations(synthesis),
                    *_missing_needs_limitation(missing_information_needs),
                    *_fulfillment_disclosures(question_brief),
                ]
            )
        )
        if missing:
            limitations.append(
                "OpenAI가 누락한 섹션을 수집 근거 기반 규칙 결과로 보완했습니다: " + ", ".join(missing)
            )
        return GeneratedReport(
            request_id=synthesis.request_id,
            sector_id=synthesis.sector_id,
            audience_id=profile.audience_id,
            purpose_id=purpose_id,
            source_count=synthesis.source_count,
            unique_source_count=synthesis.unique_source_count,
            generation_mode="openai",
            title=parsed["title"],
            executive_summary=parsed["executive_summary"],
            sections=sections,
            limitations=limitations,
            extracted_metric_series=extracted_metrics,
            extracted_comparison_points=extracted_comparisons,
            action_impacts=action_impacts,
        )
    except Exception as exc:
        return _fallback_report(
            synthesis,
            report_plan,
            audience_id,
            limitation=(
                "OpenAI 보고서 생성에 실패해 규칙 기반 결과를 사용했습니다: "
                f"{type(exc).__name__}: {str(exc)[:240]}"
            ),
            missing_information_needs=missing_information_needs,
            question_brief=question_brief,
        )
