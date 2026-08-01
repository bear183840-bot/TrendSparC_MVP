"""Build a SourcePlan from the sector's source registry.

Registries live under sources/registry/<sector_id>/*.json. Each registered
source is parsed into a PlannedSource so a sector's adapter/collector can act
on SourcePlan alone, without re-reading and re-parsing the registry itself.
Only fields already present in the registry entry are carried over — nothing
here invents a reliability tier or other field for an unregistered source.

sources/registry/common/*.json is merged into every sector's SourcePlan
regardless of sector_id — it holds sources useful across all sectors (see
sources/registry/common/README.md), not sector-specific business sources.

When a `perspective` is given (see EntityExtractionResult.perspective),
planned_sources is stable-sorted by each source's `content_type` so the
sources most likely to have the right kind of content get searched first
under the collector's shared rate-limit budget: analytical/industry-press
coverage first for market_landscape questions, official/press_release
coverage first for company_update questions. Sources with no content_type
set, or a perspective with no defined priority, keep the registry's
original order.

`select_top_sources()` below is a separate, opt-in narrowing step on top of
an already-built SourcePlan — it does NOT change plan_sources()'s contract
("return every registered source") so existing callers/tests are unaffected.
Call it explicitly wherever a question-aware top-N selection is actually
wanted (see its docstring).
"""

from __future__ import annotations

import json
from pathlib import Path

from common.contracts import PlannedSource, SourcePlan

_COMMON_REGISTRY_DIR_NAME = "common"

_CONTENT_TYPE_PRIORITY_BY_PERSPECTIVE: dict[str, dict[str | None, int]] = {
    "market_landscape": {"analysis": 0, None: 1, "press_release": 2},
    "company_update": {"press_release": 0, None: 1, "analysis": 2},
}

_MAX_SELECTED_SOURCES = 6

# Per-role ceiling applied by select_top_sources() so one role (e.g. four
# different competitor newsrooms) can't fill every slot. Roles with no entry
# here (including unset/None) have no ceiling — they only compete on score.
_ROLE_MAX_QUOTA: dict[str, int] = {
    "official": 2,
    "competitor_official": 1,
    "regulatory_official": 1,
    "market_analysis": 2,
    "search": 2,
    "user_sentiment": 1,
}

_RELIABILITY_SCORE: dict[str, float] = {"official": 1.0, "analyst_media": 0.7, "user_generated": 0.4}
_FREQUENCY_SCORE: dict[str, float] = {"daily": 1.0, "weekly": 0.7, "monthly": 0.4}

_ROLE_SCORE_BY_REPORT_PURPOSE: dict[str, dict[str, float]] = {
    "current_status": {"market_analysis": 1.0, "search": 0.9, "official": 0.8, "competitor_official": 0.8},
    "issue_response": {"regulatory_official": 1.0, "search": 0.9, "official": 0.9, "market_analysis": 0.8},
    "future_business": {"market_analysis": 1.0, "official": 0.9, "competitor_official": 0.8, "search": 0.7},
    "root_cause": {"market_analysis": 1.0, "search": 0.9, "regulatory_official": 0.8, "official": 0.7},
}

# Neutral score used whenever a factor's underlying field isn't set on a
# source (or no question context is available for it) — an unset field must
# not be penalized relative to sources that do have it set.
_NEUTRAL_SCORE = 0.5
_PLANNING_PRIORITY_BONUS = {"core": 0.25, "standard": 0.0, "supporting": -0.05}


def _topic_match_score(source: PlannedSource, question_keywords: list[str]) -> float:
    if not source.topics or not question_keywords:
        return _NEUTRAL_SCORE
    matches = 0
    for keyword in question_keywords:
        keyword_lower = keyword.lower()
        if any(keyword_lower in topic.lower() or topic.lower() in keyword_lower for topic in source.topics):
            matches += 1
    return min(1.0, matches / len(question_keywords))


def _purpose_match_score(source: PlannedSource, perspective: str | None) -> float:
    priority_map = _CONTENT_TYPE_PRIORITY_BY_PERSPECTIVE.get(perspective)
    if not priority_map:
        return _NEUTRAL_SCORE
    max_priority = max(priority_map.values())
    priority = priority_map.get(source.content_type, 1)
    return 1.0 - (priority / max_priority) if max_priority else 1.0


def _score_source(
    source: PlannedSource,
    question_keywords: list[str],
    perspective: str | None,
    report_purpose_id: str | None = None,
) -> float:
    # Weights follow the agreed source-registry redesign: topic match 35%,
    # question-purpose match 20%, reliability 20%, recency 15%, role-known 10%.
    topic_score = _topic_match_score(source, question_keywords)
    purpose_score = _purpose_match_score(source, perspective)
    reliability_score = _RELIABILITY_SCORE.get(source.reliability_tier, _NEUTRAL_SCORE)
    recency_score = _FREQUENCY_SCORE.get(source.frequency, _NEUTRAL_SCORE)
    role_known_score = 1.0 if source.role else _NEUTRAL_SCORE
    base_score = (
        0.35 * topic_score
        + 0.20 * purpose_score
        + 0.20 * reliability_score
        + 0.15 * recency_score
        + 0.10 * role_known_score
    )
    purpose_roles = _ROLE_SCORE_BY_REPORT_PURPOSE.get(report_purpose_id, {})
    purpose_role_score = purpose_roles.get(source.role, _NEUTRAL_SCORE)
    return (
        base_score
        + 0.12 * purpose_role_score
        + _PLANNING_PRIORITY_BONUS.get(source.planning_priority, 0.0)
    )


def select_top_sources(
    source_plan: SourcePlan,
    perspective: str | None = None,
    report_purpose_id: str | None = None,
) -> SourcePlan:
    """Narrow an already-built SourcePlan to the top-scoring sources.

    Opt-in on purpose: plan_sources() keeps returning every registered
    source so existing callers/tests keep working unchanged; call this
    separately wherever a question-aware top-N selection is actually wanted
    (e.g. the sk_broadband pilot). `source_plan.question_keywords` (set via
    plan_sources()) drives topic matching; `perspective` is passed
    separately since SourcePlan doesn't carry it.

    Sectors with `_MAX_SELECTED_SOURCES` or fewer sources get everything
    back, just reordered by score — the cap only trims once a sector's
    registry actually grows past it.
    """
    ranked = sorted(
        source_plan.planned_sources,
        key=lambda source: _score_source(
            source,
            source_plan.question_keywords,
            perspective,
            report_purpose_id,
        ),
        reverse=True,
    )

    if len(ranked) <= _MAX_SELECTED_SOURCES:
        return source_plan.model_copy(update={"planned_sources": ranked})

    selected: list[PlannedSource] = []
    skipped_by_quota: list[PlannedSource] = []
    role_counts: dict[str | None, int] = {}
    # A registry can explicitly designate cross-sector discovery channels as
    # core. Reserve their place before applying role-diversity quotas.
    for source in ranked:
        if source.planning_priority != "core":
            continue
        selected.append(source)
        role_counts[source.role] = role_counts.get(source.role, 0) + 1
        if len(selected) >= _MAX_SELECTED_SOURCES:
            break
    for source in ranked:
        if source in selected:
            continue
        quota = _ROLE_MAX_QUOTA.get(source.role)
        used = role_counts.get(source.role, 0)
        if quota is not None and used >= quota:
            skipped_by_quota.append(source)
            continue
        selected.append(source)
        role_counts[source.role] = used + 1
        if len(selected) >= _MAX_SELECTED_SOURCES:
            break

    # Quotas encourage diversity, but must not leave a plan unnecessarily
    # sparse. Backfill any open slots with the best sources skipped above.
    if len(selected) < _MAX_SELECTED_SOURCES:
        for source in skipped_by_quota:
            if source not in selected:
                selected.append(source)
            if len(selected) >= _MAX_SELECTED_SOURCES:
                break

    return source_plan.model_copy(update={"planned_sources": selected})


def _load_registry_dir(registry_dir: Path) -> list[PlannedSource]:
    planned_sources: list[PlannedSource] = []
    if not registry_dir.is_dir():
        return planned_sources

    for registry_file in sorted(registry_dir.glob("*.json")):
        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for raw_source in data.get("sources", []):
            planned_sources.append(PlannedSource.model_validate(raw_source))

    return planned_sources


def plan_sources(
    request_id: str,
    sector_id: str,
    registry_root: Path,
    question_keywords: list[str] | None = None,
    perspective: str | None = None,
) -> SourcePlan:
    planned_sources = _load_registry_dir(registry_root / sector_id) + _load_registry_dir(
        registry_root / _COMMON_REGISTRY_DIR_NAME
    )

    priority_map = _CONTENT_TYPE_PRIORITY_BY_PERSPECTIVE.get(perspective)
    if priority_map:
        planned_sources = sorted(planned_sources, key=lambda source: priority_map.get(source.content_type, 1))

    notes = None if planned_sources else "no sources registered for this sector — template_only"
    return SourcePlan(
        request_id=request_id,
        sector_id=sector_id,
        planned_sources=planned_sources,
        question_keywords=question_keywords or [],
        notes=notes,
    )
