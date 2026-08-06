"""The --synthesis-fixture development entrypoint.

Re-running the report half of the pipeline used to require paying for
collection and analysis again. These tests pin the contract of the free path:
it starts at report_planner, it never touches the collection stages, and the
audience it is given changes tone and detail but not the report's structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.errors import StageStatus
from core.request_pipeline.pipeline import _FIXTURE_SKIPPED_STAGES, run_pipeline_from_synthesis
from core.request_pipeline.synthesis_fixture import load_synthesis_fixture

_FIXTURES = Path(__file__).parent / "fixtures"
_REVENUE = _FIXTURES / "synthesis_revenue_trend.json"
_IPTV = _FIXTURES / "synthesis_iptv_competition.json"
_FUTURE = _FIXTURES / "synthesis_future_business.json"


def _run(path: Path, audience: str | None = None):
    synthesis, question, audience_id, purpose = load_synthesis_fixture(path)
    return run_pipeline_from_synthesis(question, synthesis, audience or audience_id, purpose)


def _block_types(result) -> list[str]:
    return [block.block_type for block in result.layout.blocks]


def test_fixture_loads_the_run_settings_alongside_the_synthesis():
    synthesis, question, audience_id, purpose = load_synthesis_fixture(_IPTV)

    assert synthesis.sector_id == "sk_broadband"
    assert audience_id == "executive"
    assert purpose.purpose_id == "issue_response"
    # The purpose's own recipe, not a list hand-copied into the fixture.
    assert purpose.recommended_sections
    assert question.startswith("IPTV")


def test_bare_string_corroborated_point_is_promoted_without_inventing_sources():
    synthesis, *_ = load_synthesis_fixture(_REVENUE)
    point = synthesis.corroborated_points[0]

    assert point.claim
    assert point.supporting_doc_ids == []
    assert point.supporting_source_ids == []


def test_collection_stages_are_skipped_not_silently_absent():
    result = _run(_REVENUE)
    by_stage = {trace.stage: trace.status for trace in result.trace}

    for stage in _FIXTURE_SKIPPED_STAGES:
        assert by_stage[stage] is StageStatus.SKIPPED
    for stage in ("report_planner", "report_generator", "audience_adapter", "layout_generator"):
        assert by_stage[stage] is StageStatus.OK
    assert result.halted_at_stage is None
    # Nothing was collected or analyzed on this path.
    assert result.collected_source_documents == []
    assert result.document_analyses == []


@pytest.mark.parametrize(
    "path, expected_sections, expected_blocks",
    [
        (_REVENUE, {"key_metrics", "timeline", "near_term_outlook"}, {"chart", "timeline"}),
        (_IPTV, {"issue", "impact", "response_actions"}, {"matrix", "list"}),
        (
            _FUTURE,
            {"trend", "opportunity", "investment_signal", "strategic_recommendation"},
            {"matrix", "metrics", "list"},
        ),
    ],
)
def test_each_purpose_produces_its_own_sections_and_blocks(path, expected_sections, expected_blocks):
    result = _run(path)

    assert expected_sections <= set(result.report_plan.sections)
    assert expected_blocks <= set(_block_types(result))


def test_the_three_purposes_do_not_share_a_section_list():
    plans = [tuple(_run(path).report_plan.sections) for path in (_REVENUE, _IPTV, _FUTURE)]
    assert len(set(plans)) == 3


def test_one_off_metrics_in_different_units_are_kpis_not_a_chart():
    """future_business carries 12%, 2개 지역 and 1건 - three unrelated numbers.

    Plotting them on shared axes would invent a comparison that doesn't exist,
    so the section must land on the KPI block instead.
    """
    result = _run(_FUTURE)
    by_section = {block.section: block.block_type for block in result.layout.blocks}

    assert by_section["investment_signal"] == "metrics"
    assert "chart" not in by_section.values()


def test_narrative_section_is_text_not_an_unclassified_auto_block():
    """"trend" is statically mapped to chart, but holds only prose here.

    Withdrawing the chart used to drop it all the way to "auto", which means
    "no idea what this is" and requests a new block type - plain text was the
    right answer.
    """
    result = _run(_FUTURE)
    by_section = {block.section: block.block_type for block in result.layout.blocks}

    assert by_section["trend"] == "text"
    assert "auto" not in by_section.values()


def test_metric_rich_fixture_keeps_its_key_metrics_section():
    """A section is judged on its data, not on whether an internal id is set.

    The fixture's MetricPoints carry no metric_id (the synthesizer assigns
    those during a live run), and key_metrics used to be omitted for exactly
    that reason - with eight metric points sitting right there.
    """
    result = _run(_REVENUE)

    assert "key_metrics" not in result.report_plan.omitted_sections
    assert "recommended_action" not in result.report_plan.omitted_sections


def test_audience_changes_tone_and_detail_but_not_structure():
    practitioner = _run(_REVENUE, "practitioner")
    executive = _run(_REVENUE, "executive")

    assert practitioner.report_plan.sections == executive.report_plan.sections
    assert _block_types(practitioner) == _block_types(executive)

    assert practitioner.audience_adaptation.tone != executive.audience_adaptation.tone
    # Executive is the more compressed profile, so at least one section must
    # actually carry fewer items - otherwise "detail level" means nothing.
    practitioner_items = sum(len(s.key_points) for s in practitioner.generated_report.sections)
    executive_items = sum(len(s.key_points) for s in executive.generated_report.sections)
    assert executive_items < practitioner_items
