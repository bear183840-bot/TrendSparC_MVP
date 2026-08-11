"""Solar Pro 3 — Coverage/Gap Check (prompt B) and Evidence Verification
(prompt E), doc1 §6/§10/§12 plus doc2 §7/§8's additive extensions.

Both prompts now return richer, sometimes loosely-typed JSON than a strict
schema would (they run through _solar.call_json's `{"type": "json_object"}`
mode, not OpenAI Structured Outputs, so nothing guarantees an enum field
actually matches one of its allowed values). Every parser below defensively
clamps enum-like fields to a known value (never lets an unrecognized string
reach a Pydantic Literal field, which would raise and crash the router) and
never invents a URL/id that wasn't in the input it was given.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any

from sources.collectors.source_router import _prompts, _solar
from sources.collectors.source_router.contracts import (
    ConfirmedFact,
    Contradiction,
    CoverageAspect,
    CoverageDecision,
    CoveredItem,
    EvidenceVerification,
    KeyFact,
    NextQuery,
    SearchPlan,
    SourceAssessment,
    SourceToInspect,
    SummaryVerification,
    WebSearchResult,
)

_COVERAGE_STATUSES: set[str] = {"covered", "partially_covered", "missing", "uncertain"}
_RELEVANCE_LEVELS: set[str] = {"high", "medium", "low"}
_EVIDENCE_QUALITY_LEVELS: set[str] = {"high", "medium", "low", "unclear"}
_SUMMARY_VERIFICATION_STATUSES: set[str] = {
    "accurate",
    "partially_accurate",
    "misleading",
    "unsupported",
    "unavailable",
}
_EVIDENCE_STRENGTHS: set[str] = {"direct", "indirect", "contextual", "insufficient"}


def _clamp(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else default


def _clamp_optional(value: Any, allowed: set[str]) -> str | None:
    text = str(value or "").strip()
    return text if text in allowed else None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_list(raw: Any) -> list[str]:
    """A bare string is one item, not a list of its characters.

    The schema asks for an array, but a model that answers with a single
    sentence instead used to be iterated character by character - a live
    run recorded limitations as ["I", "P", "T", "V", "가", ...] and the
    whole explanation was destroyed. Non-iterables are wrapped for the
    same reason.
    """
    if raw is None:
        return []
    if isinstance(raw, str) or not isinstance(raw, Iterable):
        raw = [raw]
    return [str(value).strip() for value in raw if str(value).strip()]


def _parse_next_queries(raw: Any) -> list[NextQuery]:
    """Accepts either prompt B/E's object shape
    ({"query","purpose","priority"}) or a bare string, so a hand-built
    fallback/test fixture and either prompt's real output both work."""
    parsed: list[NextQuery] = []
    for item in raw or []:
        if isinstance(item, dict):
            query = str(item.get("query", "")).strip()
            if not query:
                continue
            parsed.append(
                NextQuery(
                    query=query,
                    purpose=str(item.get("purpose", "")).strip(),
                    priority=_safe_int(item.get("priority"), 1),
                )
            )
        else:
            query = str(item).strip()
            if query:
                parsed.append(NextQuery(query=query))
    return parsed


def _grounded_urls(cited: list[str], known_urls: set[str]) -> list[str]:
    return [url for url in cited if url in known_urls]


def _parse_coverage_aspects(
    raw: Any, known_urls: set[str]
) -> tuple[list[CoverageAspect], list[str]]:
    """Grounds "covered"/"partially_covered" verdicts against known_urls —
    same anti-fabrication pattern as sources_to_inspect's URL filter, added
    2026-08-09 after a live run produced a "covered" aspect whose reason
    cited a claim absent from every result it was given. A status without a
    real citation surviving the filter is downgraded to "uncertain" rather
    than trusted at face value.

    Also returns the rejected aspect texts (2026-08-11) so the caller can
    feed them back to the model on a later round via
    `previously_rejected_claims` — see CoverageDecision.rejected_claims."""
    aspects: list[CoverageAspect] = []
    rejected: list[str] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        aspect = str(item.get("aspect", "")).strip()
        if not aspect:
            continue
        status = _clamp(item.get("status"), _COVERAGE_STATUSES, "uncertain")
        grounded = _grounded_urls(_str_list(item.get("source_urls")), known_urls)
        if status in ("covered", "partially_covered") and not grounded:
            print(
                f"[source_router.coverage] UNGROUNDED CLAIM WARNING: aspect {aspect!r} was reported "
                f"status={status!r} but cited no source_urls actually present in this round's evidence "
                "pool - downgrading to 'uncertain'.",
                file=sys.stderr,
            )
            status = "uncertain"
            rejected.append(aspect)
        aspects.append(
            CoverageAspect(
                aspect=aspect,
                status=status,  # type: ignore[arg-type]
                reason=str(item.get("reason", "")).strip(),
                source_urls=grounded,
            )
        )
    return aspects, rejected


def _parse_covered_items(
    raw: Any, known_urls: set[str]
) -> tuple[list[CoveredItem], list[str]]:
    """Same grounding as _parse_coverage_aspects, for the flat
    covered_information list — a claim with no real source_urls is dropped
    entirely rather than kept as an unverified string (there's no status to
    downgrade to here, unlike CoverageAspect).

    Also returns the rejected claim texts (2026-08-11), same reason as
    _parse_coverage_aspects above."""
    items: list[CoveredItem] = []
    rejected: list[str] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            text = str(entry.get("text", "")).strip()
            cited = _str_list(entry.get("source_urls"))
        else:
            # Bare-string shape (older prompt revision, or the model ignored
            # the source_urls requirement) - no citation at all, so it can't
            # be grounded; dropped rather than trusted silently.
            text = str(entry).strip()
            cited = []
        if not text:
            continue
        grounded = _grounded_urls(cited, known_urls)
        if not grounded:
            print(
                f"[source_router.coverage] UNGROUNDED CLAIM WARNING: dropping covered_information "
                f"claim with no real source_urls in this round's evidence pool: {text[:200]!r}",
                file=sys.stderr,
            )
            rejected.append(text)
            continue
        items.append(CoveredItem(text=text, source_urls=grounded))
    return items, rejected


def _validate_sufficiency(
    sufficient: bool,
    missing: list[str],
    contradictions: list[Contradiction],
    covered: list[CoveredItem],
) -> bool:
    """Cross-checks `sufficient` against the same response's own
    `missing_information`/`contradictions`/`covered_information`, the same
    anti-fabrication pattern `_parse_coverage_aspects`/`_parse_covered_items`
    already apply to `covered`/`covered_information` individually — the
    model's say-so on `sufficient` was previously trusted verbatim
    (`bool(data.get("sufficient", False))`) with no check against fields in
    the very same JSON blob.

    Live-verified 2026-08-11: a real coverage response had
    `missing_information: []` and a `reason` arguing the evidence was
    adequate, yet `sufficient: false` — directly contradicting coverage.md's
    own STEP 7 rule ("sufficient=true only when ... no missing information
    would materially change the answer"). Only corrects False -> True
    (never the reverse - a `sufficient: true` claim isn't second-guessed
    here, since STEP 7 allows immaterial missing items to coexist with
    true).

    `covered` (already grounded-filtered by `_parse_covered_items` before
    it reaches here) must also be non-empty. Live-verified same day, a
    second run (OTT ecosystem question): every proposed covered_information
    claim that round was ungrounded and dropped, so `covered` was empty,
    yet `missing_information` was *also* empty and there was no
    contradiction — the earlier (two-condition) version of this check
    corrected sufficient=false -> true anyway, ending the gap-loop with
    zero original-source documents ever secured. "Nothing missing and
    nothing covered" is not sufficiency, it's an empty round; only correct
    when there is real, grounded, positive evidence to point to.

    Only three of STEP 7's four conditions are mechanically checkable from
    other structured fields in the same response (missing_information being
    empty, no unresolved contradiction, and now covered_information being
    non-empty) - "critical claims have adequate evidence" still has no
    separate structured field to check strength against, so this cannot
    catch every self-contradiction, only these specific, verifiable ones."""
    if sufficient:
        return sufficient
    if missing:
        return sufficient
    if not covered:
        return sufficient
    if any(contradiction.needs_resolution for contradiction in contradictions):
        return sufficient
    print(
        "[source_router.coverage] SUFFICIENCY SELF-CONTRADICTION: model returned "
        "sufficient=false with empty missing_information, non-empty grounded "
        "covered_information, and no unresolved contradiction - correcting to "
        "sufficient=true per coverage.md's own STEP 7 rule.",
        file=sys.stderr,
    )
    return True


def _parse_contradictions(raw: Any) -> list[Contradiction]:
    parsed: list[Contradiction] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issue", "")).strip()
        if not issue:
            continue
        parsed.append(
            Contradiction(
                issue=issue,
                sources=_str_list(item.get("sources")),
                conflicts_with=str(item.get("conflicts_with", "")).strip() or None,
                possible_explanation=str(item.get("possible_explanation", "")).strip() or None,
                needs_resolution=bool(item.get("needs_resolution", True)),
            )
        )
    return parsed


# ---------------------------------------------------------------------------
# Coverage / Gap Check (prompt B)
# ---------------------------------------------------------------------------

_COVERAGE_SYSTEM_PROMPT_NAME = "coverage"


def _fallback_decision(results: list[WebSearchResult], min_results: int) -> CoverageDecision:
    """Conservative, budget-safe fallback used when no planner key is
    configured or the call failed: sufficient once we have at least
    `min_results` non-empty results, never asks for full-text (there is no
    judgment behind that extra cost without a real assessment) — this keeps
    the router's loop able to terminate even with zero AI keys set."""
    sufficient = len([result for result in results if result.summary or result.key_facts]) >= min_results
    return CoverageDecision(
        sufficient=sufficient,
        needs_full_text=False,
        reason="fallback: no planner API key configured or call failed",
    )


def check_coverage(
    question: str,
    search_plan: SearchPlan,
    results: list[WebSearchResult],
    *,
    previously_rejected_claims: Iterable[str] = (),
    min_results_for_fallback_sufficiency: int = 2,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> CoverageDecision:
    """`previously_rejected_claims` (2026-08-11): claims dropped by an
    earlier round's own _parse_coverage_aspects/_parse_covered_items for
    citing no real source in that round's evidence pool - fed back in so
    the model has some memory of what it already fabricated once, instead
    of being able to repeat the same ungrounded claim indefinitely (the
    payload otherwise carries no history between check_coverage() calls).
    See coverage.md's Inputs section for how this is presented to the
    model."""
    payload = {
        "question": question,
        "search_plan": search_plan.model_dump(),
        # Exact source text is retained for downstream Analyzer, not resent to
        # the coverage model. Verification already contains the compact source
        # judgment and this avoids duplicating potentially large HTML/PDF text.
        "results": [result.model_dump(exclude={"original_content"}) for result in results],
        "previously_rejected_claims": list(dict.fromkeys(previously_rejected_claims)),
    }
    data = _solar.call_json(
        _prompts.load(_COVERAGE_SYSTEM_PROMPT_NAME),
        payload,
        caller="coverage",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if not data:
        return _fallback_decision(results, min_results_for_fallback_sufficiency)

    known_urls = {result.url for result in results}

    coverage_aspects, rejected_aspects = _parse_coverage_aspects(data.get("coverage"), known_urls)

    # `covered`/`missing` predate this prompt revision; `covered_information`/
    # `missing_information` is what the current prompt actually names them —
    # accept either so an older fixture or a future prompt edit both work.
    covered, rejected_covered = _parse_covered_items(
        data.get("covered_information") or data.get("covered"), known_urls
    )
    missing = _str_list(data.get("missing_information") or data.get("missing"))
    rejected_claims = [*rejected_aspects, *rejected_covered]

    sources_to_inspect = [
        SourceToInspect(
            url=str(item.get("url", "")).strip(),
            reason=str(item.get("reason", "")).strip(),
            target_information=_str_list(item.get("target_information")),
        )
        for item in data.get("sources_to_inspect", []) or []
        if isinstance(item, dict) and str(item.get("url", "")).strip() in known_urls
    ]
    contradictions = _parse_contradictions(data.get("contradictions"))
    sufficient = _validate_sufficiency(
        bool(data.get("sufficient", False)), missing, contradictions, covered
    )

    return CoverageDecision(
        sufficient=sufficient,
        coverage=coverage_aspects,
        covered=covered,
        missing=missing,
        contradictions=contradictions,
        needs_full_text=bool(data.get("needs_full_text", False)) and bool(sources_to_inspect),
        sources_to_inspect=sources_to_inspect,
        next_queries=_parse_next_queries(data.get("next_queries")),
        rejected_claims=rejected_claims,
        reason=str(data.get("reason", "")).strip(),
    )


# ---------------------------------------------------------------------------
# Evidence Verification (prompt E) — runs on one fully-scraped/parsed source
# ---------------------------------------------------------------------------


def verify_evidence(
    question: str,
    text: str,
    *,
    url: str = "",
    max_chars: int = 6_000,
    model_override: str | None = None,
    timeout_seconds: int = 30,
) -> EvidenceVerification:
    """All-empty, sufficient=False EvidenceVerification on missing key or
    call failure — the caller (router.py) keeps whatever summary/key_facts
    it already had either way; this only adds structure when available."""
    data = _solar.call_json(
        _prompts.load("evidence_extraction"),
        {"question": question, "url": url, "text": text[:max_chars]},
        caller="coverage.verify_evidence",
        model_override=model_override,
        timeout_seconds=timeout_seconds,
    )
    if not data:
        return EvidenceVerification()

    source_assessment_raw = data.get("source_assessment")
    source_assessment = (
        SourceAssessment(
            url=str(source_assessment_raw.get("url", "")).strip(),
            relevance=_clamp_optional(source_assessment_raw.get("relevance"), _RELEVANCE_LEVELS),  # type: ignore[arg-type]
            evidence_quality=_clamp_optional(
                source_assessment_raw.get("evidence_quality"), _EVIDENCE_QUALITY_LEVELS
            ),  # type: ignore[arg-type]
        )
        if isinstance(source_assessment_raw, dict)
        else None
    )

    summary_verification_raw = data.get("summary_verification")
    summary_verification = (
        SummaryVerification(
            status=_clamp_optional(
                summary_verification_raw.get("status"), _SUMMARY_VERIFICATION_STATUSES
            ),  # type: ignore[arg-type]
            important_omissions=_str_list(summary_verification_raw.get("important_omissions")),
        )
        if isinstance(summary_verification_raw, dict)
        else None
    )

    confirmed_facts = [
        ConfirmedFact(
            fact=str(item.get("fact", "")).strip(),
            evidence_strength=_clamp(
                item.get("evidence_strength"), _EVIDENCE_STRENGTHS, "insufficient"
            ),  # type: ignore[arg-type]
            context=str(item.get("context", "")).strip(),
        )
        for item in data.get("confirmed_facts", []) or []
        if isinstance(item, dict) and str(item.get("fact", "")).strip()
    ]

    return EvidenceVerification(
        source_assessment=source_assessment,
        summary_verification=summary_verification,
        confirmed_facts=confirmed_facts,
        limitations=_str_list(data.get("limitations")),
        contradictions=_parse_contradictions(data.get("contradictions")),
        remaining_gaps=_str_list(data.get("remaining_gaps")),
        sufficient=bool(data.get("sufficient", False)),
        next_queries=_parse_next_queries(data.get("next_queries")),
    )


def key_facts_from_verification(verification: EvidenceVerification) -> list[KeyFact]:
    """Bridges prompt E's qualitative ConfirmedFact list into the same
    KeyFact shape web_search.py's snippet-level facts use, so
    WebSearchResult.key_facts stays one consistent list regardless of which
    stage populated it. No numeric metric/value/unit/time is invented —
    ConfirmedFact never has one, so KeyFact's numeric fields stay None."""
    return [KeyFact(text=fact.fact) for fact in verification.confirmed_facts if fact.fact]
