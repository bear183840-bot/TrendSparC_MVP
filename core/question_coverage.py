"""Derive and verify structural evidence requirements from any question.

The rules only understand language shapes (time span, comparison, forecast),
never OTT, IPTV, a company, or one mentor example.  They therefore strengthen
collection for every sector without turning feedback examples into special
cases.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from common.contracts import DocumentAnalysis, QuestionCoverageRequirement


_SPAN_RE = re.compile(
    r"(?:지난|최근|과거|last|past)\s*(\d{1,2})\s*(?:개\s*)?(?:년|years?)",
    re.IGNORECASE,
)
_TREND_RE = re.compile(r"추이|변화|증감|흐름|trend|over\s+time|evolution", re.IGNORECASE)
_FORECAST_RE = re.compile(r"전망|예측|향후|미래|forecast|outlook|projection", re.IGNORECASE)
_VS_RE = re.compile(r"\s+(?:vs\.?|versus|대비)\s+", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_CURRENT_MAX_RE = re.compile(r"현재 최대\s*(\d+)개")


def minimum_drawable_periods(requested_periods: int) -> int:
    """Evidence threshold for a partial trend visual.

    Collection still aims for every requested period.  Rendering is less
    brittle: three real points make a line, and a requested N-period horizon
    is visually representative once strictly more than half is present.
    """
    if requested_periods <= 0:
        return 3
    return max(3, requested_periods // 2 + 1)


def _anchor(fragment: str, *, left: bool) -> str:
    fragment = fragment.strip(" \t\r\n()[]{}:,-")
    pieces = re.split(r"[,;/|()]", fragment)
    fragment = (pieces[-1] if left else pieces[0]).strip()
    if left:
        fragment = re.split(r"(?:지난|최근|과거)\s*\d+\s*년(?:간)?", fragment)[-1]
        fragment = re.split(r"의\s+(?:변화|추이|현황)", fragment)[-1]
    else:
        fragment = re.sub(r"\s*(?:간\s*)?(?:비교|차이|현황|추이|변화).*?$", "", fragment)
    words = fragment.split()
    if len(words) > 4:
        words = words[-4:] if left else words[:4]
    return " ".join(words).strip(" \t'\"")


def derive_question_coverage(question: str) -> QuestionCoverageRequirement:
    span = _SPAN_RE.search(question)
    periods = int(span.group(1)) if span and _TREND_RE.search(question) else 0
    periods = min(max(periods, 0), 20)

    anchors: list[str] = []
    separator = _VS_RE.search(question)
    if separator:
        left = _anchor(question[:separator.start()], left=True)
        right = _anchor(question[separator.end():], left=False)
        if left and right and left.casefold() != right.casefold():
            anchors = [left, right]

    return QuestionCoverageRequirement(
        minimum_distinct_periods=periods,
        comparison_anchors=anchors,
        forecast_required=bool(_FORECAST_RE.search(question)),
    )


def coverage_hints(requirement: QuestionCoverageRequirement) -> list[str]:
    hints: list[str] = []
    if requirement.minimum_distinct_periods:
        hints.append(
            "동일한 지표 정의로 서로 다른 시점 "
            f"{requirement.minimum_distinct_periods}개 이상의 실제 수치"
        )
    if len(requirement.comparison_anchors) >= 2:
        hints.append(
            "동일 기준으로 비교 가능한 " + " / ".join(requirement.comparison_anchors)
            + " 양측의 수치 또는 명시적 비교"
        )
    if requirement.forecast_required:
        hints.append("출처가 전망·예측으로 명시한 향후 수치 또는 방향")
    return hints


def _analysis_text(analysis: DocumentAnalysis) -> str:
    values: list[str] = [analysis.summary or "", *analysis.key_points, *analysis.evidence]
    values.extend(claim.claim for claim in analysis.grounded_claims)
    values.extend(claim.evidence_quote for claim in analysis.grounded_claims)
    return " ".join(values).casefold()


def assess_question_coverage(
    analyses: Iterable[DocumentAnalysis],
    requirement: QuestionCoverageRequirement,
) -> list[str]:
    analyses = list(analyses)
    missing: list[str] = []

    if requirement.minimum_distinct_periods:
        periods_by_series: dict[tuple[str, str], set[str]] = defaultdict(set)
        for analysis in analyses:
            for point in analysis.metric_points:
                year = _YEAR_RE.search(point.period or "")
                if year:
                    key = (re.sub(r"\s+", " ", point.label).strip().casefold(), point.unit.casefold())
                    periods_by_series[key].add(year.group(1))
        best = max((len(periods) for periods in periods_by_series.values()), default=0)
        if best < requirement.minimum_distinct_periods:
            missing.append(
                f"동일 지표 시계열 {requirement.minimum_distinct_periods}개 시점 "
                f"(현재 최대 {best}개)"
            )

    if len(requirement.comparison_anchors) >= 2:
        anchors = [anchor.casefold() for anchor in requirement.comparison_anchors]
        comparable = False
        metric_axes: dict[tuple[str, str], set[str]] = defaultdict(set)
        comparison_axes: dict[str, set[str]] = defaultdict(set)
        for analysis in analyses:
            text = _analysis_text(analysis)
            has_structured_fact = bool(analysis.metric_points or analysis.comparison_points)
            if has_structured_fact and all(anchor in text for anchor in anchors):
                comparable = True
                break
            for point in analysis.metric_points:
                subject = (point.subject or "").casefold()
                probe = subject or text
                key = (
                    re.sub(r"\s+", " ", point.label).strip().casefold(),
                    point.unit.casefold(),
                )
                metric_axes[key].update(anchor for anchor in anchors if anchor in probe)
            for point in analysis.comparison_points:
                probe = (point.entity or "").casefold()
                key = re.sub(r"\s+", " ", point.criterion).strip().casefold()
                comparison_axes[key].update(anchor for anchor in anchors if anchor in probe)
        if not comparable:
            comparable = any(
                all(anchor in found for anchor in anchors)
                for found in metric_axes.values()
            )
        if not comparable:
            comparable = any(
                all(anchor in found for anchor in anchors)
                for found in comparison_axes.values()
            )
        if not comparable:
            missing.append("동일 기준 비교: " + " / ".join(requirement.comparison_anchors))

    if requirement.forecast_required:
        has_forecast = any(
            point.is_forecast for analysis in analyses for point in analysis.metric_points
        )
        if not has_forecast:
            missing.append("출처가 명시한 전망 근거")

    return missing


def coverage_safe_summary(
    summary: str,
    requirement: QuestionCoverageRequirement,
    gaps: list[str],
) -> str:
    """Remove a whole-period conclusion when its required series is absent.

    This is intentionally narrow: current-point facts and grounded cross-
    sectional comparisons remain untouched.  Only sentences that themselves
    claim the requested multi-period horizon are withheld.
    """
    if not requirement.minimum_distinct_periods or not any(
        gap.startswith("동일 지표 시계열") for gap in gaps
    ):
        return summary
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    kept = [sentence for sentence in sentences if not _SPAN_RE.search(sentence)]
    current = max(
        (
            int(match.group(1))
            for gap in gaps
            if (match := _CURRENT_MAX_RE.search(gap))
        ),
        default=0,
    )
    if current >= minimum_drawable_periods(requirement.minimum_distinct_periods):
        limitation = (
            f"확보된 동일 지표 {current}개 시점의 추이는 제시하되, "
            f"요청한 {requirement.minimum_distinct_periods}개 시점 전체로 확대 해석할 수 없습니다."
        )
    else:
        limitation = (
            f"동일 지표 {requirement.minimum_distinct_periods}개 시점이 확보되지 않아 "
            "기간 전체 추이는 확정할 수 없습니다."
        )
    return " ".join([limitation, *kept]).strip()
