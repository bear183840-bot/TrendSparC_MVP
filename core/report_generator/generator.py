"""Generate a complete, evidence-bound report from a structured synthesis."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy

from audience.contracts import load_audience_profile
from common.content_quality_validator import (
    dated_items,
    dedupe_across_blocks,
    dedupe_structured_across_sections,
)
from common.contracts import (
    GeneratedReport,
    GeneratedReportSection,
    MetricPoint,
    ReportPlan,
    TrendSynthesis,
)
from core.report_planner.planner import COMPARISON_SECTIONS
from common.section_titles import section_title
from core.sector_router.affiliates import foreign_entity_names_for

_DOC_ID_RE = re.compile(r"\[doc_id=([^\]]+)\]")


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
                    "period": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "source_sentence": {"type": "string"},
                },
                "required": ["label", "period", "value", "unit", "source_sentence"],
            },
        },
    },
    "required": ["title", "executive_summary", "sections", "limitations", "metric_series"],
}

# Digits, with separators stripped, must reappear in the sentence the model
# says it read the figure from. "4조 5,406억원" -> "45406" is not literally in
# the text, so the check is on the *significant digit runs* instead.
_DIGIT_RUN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def _verified_ai_metric_points(
    raw_points: list[dict], synthesis: TrendSynthesis, foreign_names: set[str]
) -> list[MetricPoint]:
    """Keep only AI-extracted figures that are actually present in the evidence.

    The model is allowed to *find* numbers the regex missed; it is not allowed
    to state one. A point survives only if the digits of its value appear in
    some evidence/key_point/highlight sentence, mirroring how
    _verified_metric_points works in the sector analyzers. Figures whose label
    names a different SK affiliate are dropped too - metric_series has no
    subject field, so everything in it reads as this company's own number.
    """
    corpus = [*synthesis.evidence, *synthesis.key_points, *synthesis.highlights]
    corpus_digits: set[str] = set()
    for sentence in corpus:
        corpus_digits |= _digit_runs(sentence)

    verified: list[MetricPoint] = []
    for raw in raw_points:
        label = (raw.get("label") or "").strip()
        if not label or not (raw.get("period") or "").strip():
            continue
        if any(name in label for name in foreign_names):
            continue
        stated = _digit_runs(raw.get("source_sentence", "")) | _digit_runs(str(raw.get("value", "")))
        if not stated & corpus_digits:
            continue
        verified.append(
            MetricPoint(
                label=normalize_metric_label(label) or label,
                period=raw["period"].strip(),
                value=float(raw["value"]),
                unit=(raw.get("unit") or "").strip() or None,
            )
        )
    return verified


def _diversity_limitations(synthesis: TrendSynthesis) -> list[str]:
    if synthesis.source_count and synthesis.unique_source_count == 1:
        source_label = synthesis.source_ids[0] if synthesis.source_ids else "단일 출처"
        return [
            f"수집 문서는 {synthesis.source_count}건이지만 고유 출처는 {synthesis.unique_source_count}개({source_label})뿐입니다. "
            "경쟁 현황과 전략 판단은 추가 출처로 교차 검증해야 합니다."
        ]
    return []


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
                confidence=", ".join(_take(synthesis.confidence_labels, 2)) or None,
                **kwargs,
            )
        )
    limitations = _diversity_limitations(synthesis)
    if synthesis.source_count == 0:
        limitations.append("분석에 사용할 수집 문서가 없어 결론을 확정할 수 없습니다.")
    limitations.extend(_missing_needs_limitation(missing_information_needs))
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


def generate_report(
    question: str,
    synthesis: TrendSynthesis,
    report_plan: ReportPlan,
    audience_id: str,
    canonical_entities: list[str] | None = None,
    missing_information_needs: list[str] | None = None,
) -> GeneratedReport:
    """Use structured output when configured; otherwise create an evidence-safe report."""
    api_key = os.getenv("TRENDSPARC_REPORT_GENERATOR_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or synthesis.source_count == 0:
        return _fallback_report(synthesis, report_plan, audience_id, missing_information_needs=missing_information_needs)

    try:
        from openai import OpenAI

        profile = load_audience_profile(audience_id)
        purpose_id = report_plan.report_purpose.purpose_id if report_plan.report_purpose else report_plan.primary_intent
        payload = {
            "question": question,
            "canonical_entities": list(dict.fromkeys(canonical_entities or [])),
            "sector_id": synthesis.sector_id,
            "purpose": {
                "id": purpose_id,
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
        schema = deepcopy(_REPORT_SCHEMA)
        section_schema = schema["properties"]["sections"]
        section_schema["minItems"] = len(report_plan.sections)
        section_schema["maxItems"] = len(report_plan.sections)
        section_schema["items"]["properties"]["section_id"]["enum"] = list(report_plan.sections)
        response = OpenAI(api_key=api_key).responses.create(
            model=os.getenv("TRENDSPARC_REPORT_GENERATOR_MODEL", "gpt-4o-mini"),
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are TrendSparC's final report writer. Write distinct, complete content for every "
                        "requested section, calibrated to the audience and purpose. Use only the supplied synthesis. "
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
                        "The output-language rule is strict: write the title, executive summary, every section, "
                        "and every limitation in the question's language. For a Korean question, all narrative "
                        "text must be Korean; keep only proper names and standard acronyms such as NVIDIA, HBM, "
                        "AI, and ARPU in English. Before returning JSON, verify every narrative field against "
                        "the question's language.\n"
                        "metric_series is a separate, mandatory job: read every sentence in "
                        "synthesis.evidence, synthesis.key_points and synthesis.highlights and structure "
                        "EVERY figure you find there (revenue, operating profit, subscriber counts, growth "
                        "rates, forecasts) as {label, period, value, unit, source_sentence}. Qualifiers such "
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
                        "company's, and those numbers must not appear here. When in doubt, leave it out."
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
        extracted_metrics = _verified_ai_metric_points(
            parsed.get("metric_series") or [], synthesis, foreign_entity_names_for(synthesis.sector_id)
        )
        fallback = _fallback_report(synthesis, report_plan, audience_id)
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
        )
