"""No two sections of a report may say the same thing.

The live "브랜드 이미지 개선" run put one identical opportunities list under
개요 / 트렌드 / 기회 / 투자신호, and the same watch-list under three more.
Four differently-titled cards repeating one sentence is not four findings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.report_generator.generator import generate_report
from core.report_planner.planner import plan_report
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture
from reporting.dashboard_streamlit.components import headline_stats

_FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("synthesis_*.json"))
_NARRATIVE_FIELDS = ("key_points", "risks", "opportunities", "actions", "monitoring_indicators")


def _report(path: Path):
    synthesis, question, audience_id, purpose = load_synthesis_fixture(path)
    plan = plan_report(synthesis, audience_id, purpose)
    return synthesis, purpose, generate_report(question, synthesis, plan, audience_id)


@pytest.mark.parametrize("path", _FIXTURES, ids=lambda p: p.stem.replace("synthesis_", ""))
def test_no_narrative_item_appears_in_two_sections(path):
    _, _, report = _report(path)

    owners: dict[tuple[str, str], set[str]] = {}
    for section in report.sections:
        for field in _NARRATIVE_FIELDS:
            for value in getattr(section, field, None) or []:
                owners.setdefault((field, value), set()).add(section.section_id)

    repeated = {key: sorted(sections) for key, sections in owners.items() if len(sections) > 1}
    assert repeated == {}, repeated


@pytest.mark.parametrize("path", _FIXTURES, ids=lambda p: p.stem.replace("synthesis_", ""))
def test_deduplication_never_empties_a_section_that_had_content(path):
    """A section stripped to nothing is dropped from the report entirely, so
    over-eager deduplication silently deleted whole sections. Repeating a
    sentence would have been the lesser fault."""
    synthesis, _, report = _report(path)

    for section in report.sections:
        if section.section_id == "sources":
            continue
        has_anything = any(
            getattr(section, field, None)
            for field in (*_NARRATIVE_FIELDS, "evidence", "metric_points", "comparison_points",
                          "strengths", "weaknesses")
        )
        assert has_anything or not synthesis.evidence, section.section_id


def test_timeline_evidence_is_dated_and_not_a_copy_of_market_status():
    from common.content_quality_validator import dated_items

    _, _, report = _report(_FIXTURES[0].parent / "synthesis_revenue_trend.json")
    by_id = {section.section_id: section for section in report.sections}
    timeline = by_id["timeline"]

    assert timeline.evidence
    assert timeline.evidence == dated_items(timeline.evidence)
    assert timeline.evidence != by_id["market_status"].evidence


# --- the summary card follows the purpose, not one fixed pair -----------


@pytest.mark.parametrize(
    "purpose_id, expected_labels",
    [
        ("issue_response", ["Risk Signals", "Opportunity Signals"]),
        ("future_business", ["기회 신호", "실행 과제"]),
        ("root_cause", ["확인된 원인", "개선 과제"]),
        ("current_status", ["확인된 지표", "주의 신호"]),
    ],
)
def test_headline_stats_differ_by_purpose(purpose_id, expected_labels):
    """A 미래사업 report led with "RISK SIGNALS 0건" - the one number that
    question never asked about. PURPOSE_HEADLINE_STYLE declared this and
    nothing read it."""
    synthesis, _, _ = _report(_FIXTURES[0])

    assert [label for label, _, _ in headline_stats(synthesis, purpose_id)] == expected_labels


def test_headline_stats_are_counts_of_real_statements():
    """Never a synthesized severity word - a count is evidence-backed."""
    synthesis, purpose, _ = _report(_FIXTURES[0])

    for _, count, _ in headline_stats(synthesis, purpose.purpose_id):
        assert isinstance(count, int)


def test_unknown_purpose_still_gets_a_summary_card():
    synthesis, _, _ = _report(_FIXTURES[0])
    assert len(headline_stats(synthesis, "not_a_purpose")) == 2
