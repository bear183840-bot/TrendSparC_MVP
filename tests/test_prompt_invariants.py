"""Properties the shipped prompts must keep.

Prompts are as much a part of behaviour as code here, but nothing failed when
one of them contradicted another - these were all found by reading, after the
output had been wrong for several runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.content_quality_validator import (
    COMPARISON_COMPLETENESS_INSTRUCTION,
    QUALITATIVE_LEVEL_EXTRACTION_INSTRUCTION,
    RELATIVE_METRIC_EXTRACTION_INSTRUCTION,
    SWOT_COMPLETENESS_INSTRUCTION,
    TABLE_COMPLETENESS_INSTRUCTION,
)

_ROOT = Path(__file__).resolve().parent.parent
_PURPOSE_PROMPTS = sorted((_ROOT / "prompts" / "report_purposes").glob("*.md"))
_ANALYZERS = sorted((_ROOT / "sectors").glob("*/adapter/analyzer/__init__.py"))


@pytest.mark.parametrize("path", _PURPOSE_PROMPTS, ids=lambda p: p.stem)
def test_purpose_prompt_does_not_tell_the_model_it_is_unused(path):
    """These files are sent to the report writer as "authoritative style and
    structure rules", so a header saying they are an unwired draft undercuts
    the very instructions being given."""
    text = path.read_text(encoding="utf-8")

    assert "쓰지는 않음" not in text
    assert "Status: drafted" not in text


def test_purpose_prompts_are_actually_loaded():
    """Guards the assumption the test above rests on."""
    from core.report_planner.planner import _load_intent_emphasis

    for path in _PURPOSE_PROMPTS:
        if path.stem == "README":
            continue
        loaded = _load_intent_emphasis(path.stem)
        assert loaded and len(loaded) > 500, path.stem


def test_swot_instruction_permits_an_empty_quadrant():
    """The old wording ("반드시 채우세요", "매번 비는 경우가 없도록") read as a
    quota and contradicted global principle 1, which forbids filling a gap
    with a guess."""
    assert "비워 두세요" in SWOT_COMPLETENESS_INSTRUCTION
    assert "모두 채우라는 뜻이 아닙니다" in SWOT_COMPLETENESS_INSTRUCTION
    assert "반드시 채우세요" not in SWOT_COMPLETENESS_INSTRUCTION


def test_comparison_instruction_asks_for_every_mentioned_item():
    """Live-observed: "TV는 31.7%를 기록해 유튜브(25.6%)를 앞서며 1위" kept
    only 25.6% and dropped the first-place figure the sentence was about."""
    assert "빠뜨리지 말고" in COMPARISON_COMPLETENESS_INSTRUCTION
    assert "1위" in COMPARISON_COMPLETENESS_INSTRUCTION


@pytest.mark.parametrize("path", _ANALYZERS, ids=lambda p: p.parts[-4])
def test_every_sector_analyzer_gets_both_completeness_instructions(path):
    """Both rules, in every analyzer that calls a model.

    This used to skip when `SWOT_COMPLETENESS_INSTRUCTION` was absent, on the
    theory that such an analyzer was still a stub. That made the check
    self-defeating: removing the import removed the test with it, and both
    rules were once dropped from the live analyzer without a single failure.
    A stub is now identified by having no model call at all.
    """
    text = path.read_text(encoding="utf-8")
    # `general` is the deliberately unimplemented fallback (see CLAUDE.md); it
    # answers without a sector prompt at all. Everything that loads one is a
    # real analyzer and has to carry both rules.
    if "_SECTOR_PROMPT_PATH" not in text:
        pytest.skip("fallback analyzer: no sector prompt to attach the rules to")
    assert "SWOT_COMPLETENESS_INSTRUCTION" in text, (
        "the analyzer sends a sector prompt but not the SWOT completeness rule"
    )
    assert "COMPARISON_COMPLETENESS_INSTRUCTION" in text


@pytest.mark.parametrize("path", _ANALYZERS, ids=lambda p: p.parts[-4])
def test_every_sector_analyzer_keeps_table_rows_as_separate_points(path):
    """A table printed with several period columns has to arrive as several
    metric points, and a per-age/per-company list as several comparisons.

    Without this, a results table came back as one representative figure and
    the trend it described could never be charted - the loss happens at
    extraction, where no later stage can recover it.
    """
    text = path.read_text(encoding="utf-8")
    if "_SECTOR_PROMPT_PATH" not in text:
        pytest.skip("fallback analyzer: no sector prompt to attach the rules to")
    assert "TABLE_COMPLETENESS_INSTRUCTION" in text


def test_sector_prompt_accepts_research_that_never_names_the_company():
    """The generic_topic_round deliberately fetches industry research with no
    company mention; the analyzer must not then discard it as off-topic."""
    text = (_ROOT / "sectors" / "sk_broadband" / "prompts" / "system_prompt.md").read_text(
        encoding="utf-8"
    )

    assert "회사명이 등장하지 않는 일반 산업 리서치" in text
    assert "irrelevant` 처리하면 안 된다" in text


def test_key_points_cap_is_not_below_the_number_of_required_angles():
    """The prompt asked for 7 analysis angles but capped key_points at 5."""
    text = (_ROOT / "sectors" / "sk_broadband" / "prompts" / "system_prompt.md").read_text(
        encoding="utf-8"
    )
    assert "최대 8개" in text


def test_global_output_order_does_not_claim_to_set_section_order():
    """Analysis thinking order and report section order are different things;
    the global prompt used to state its 4-step order as the report's shape,
    which competes with each purpose's own skeleton."""
    text = (_ROOT / "prompts" / "global_system_prompt.md").read_text(encoding="utf-8")

    assert "보고 목적(purpose)" in text
    assert "섹션 순서를 4단으로 되돌리지 마세요" in text


def test_the_table_rule_says_every_row_not_a_representative_one():
    """The wording matters: "대표값 하나로 요약하지 말고" is the whole rule.
    A table arriving as one figure is a loss no later stage can undo."""
    assert "시점 수만큼" in TABLE_COMPLETENESS_INSTRUCTION
    assert "대표값 하나로 요약하지 말고" in TABLE_COMPLETENESS_INSTRUCTION
    assert "각 행·항목을 개별" in TABLE_COMPLETENESS_INSTRUCTION


def test_relative_and_qualitative_rules_preserve_explicit_evidence_only():
    assert "is_relative=true" in RELATIVE_METRIC_EXTRACTION_INSTRUCTION
    assert "100→200" in RELATIVE_METRIC_EXTRACTION_INSTRUCTION
    assert "직접 평가한 경우에만" in QUALITATIVE_LEVEL_EXTRACTION_INSTRUCTION
    assert "수치가 크거나" in QUALITATIVE_LEVEL_EXTRACTION_INSTRUCTION


@pytest.mark.parametrize("path", _ANALYZERS, ids=lambda p: p.parts[-4])
def test_every_analyzer_schema_carries_relative_metric_provenance(path):
    text = path.read_text(encoding="utf-8")
    assert '"is_relative"' in text
    assert '"comparison_period"' in text
    assert '"value_origin"' in text


def test_entity_runtime_prompt_is_compact_without_losing_search_guards():
    """The entity call runs for every question, so repeated prose is TPM too.

    Pin the collector-facing safeguards rather than the old wording: short
    headline terms, one language form, no invented competitor, and general
    routing must survive future attempts to shorten this prompt again.
    """
    from core.entity.ai_based import _COMPACT_SYSTEM_PROMPT

    assert len(_COMPACT_SYSTEM_PROMPT) < 5_000
    assert "Do not invent a named competitor" in _COMPACT_SYSTEM_PROMPT
    assert 'sector_id="general"' in _COMPACT_SYSTEM_PROMPT
    assert "3-6 short canonical topic terms" in _COMPACT_SYSTEM_PROMPT
    assert "both Korean and English forms" in _COMPACT_SYSTEM_PROMPT


def test_entity_routing_choices_do_not_send_downstream_analysis_dimensions():
    """Entity needs aliases/topics to route and search; report metrics and
    strategic dimensions belong downstream and used to be repeated unused."""
    import json

    from common.contracts import SectorProfile
    from core.entity.ai_based import _sector_choices

    profile = SectorProfile(
        sector_id="test_sector",
        display_name="Test",
        status="active",
        aliases=["테스트"],
        keywords=["테스트 시장"],
        key_metrics=["매출"],
        strategic_dimensions=["성장성"],
    )
    choices, _ = _sector_choices({profile.sector_id: profile})
    payload = json.loads(choices)[0]

    assert payload["routing_aliases"] == ["테스트"]
    assert payload["business_topics"] == ["테스트 시장"]
    assert "key_metrics" not in payload
    assert "strategic_dimensions" not in payload


def test_sk_broadband_analyzer_sends_table_completeness_once_per_call():
    text = (
        _ROOT / "sectors" / "sk_broadband" / "adapter" / "analyzer" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert text.count('f"{TABLE_COMPLETENESS_INSTRUCTION} "') == 1


def test_broadband_analyzer_requests_block_ready_generic_axes():
    text = (
        _ROOT / "sectors" / "sk_broadband" / "adapter" / "analyzer" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert "공통 지표명은 같은 label" in text
    assert "각 항목명은 subject" in text
    assert "share_of는 원문이 하나의 전체" in text
    assert "여러 기업·국가·기술을 공통 기준" in text
    assert "같이 증가하거나 순서대로 언급" in text
    assert "'~에 따르면'은 인과가 아니다" in text
    assert "시장 규모나 숫자가 크다는 이유로 level을 만들지 마라" in text


def test_solar_stages_choose_provider_appropriate_defaults(monkeypatch):
    from core.entity import ai_based as entity_ai
    from core.synthesis import ai_based as synthesis_ai
    from sectors.sk_broadband.adapter import analyzer as broadband_analyzer

    stages = (
        (entity_ai, "TRENDSPARC_ENTITY_AI_MODEL", "TRENDSPARC_ENTITY_AI_BASE_URL", "gpt-4o"),
        (synthesis_ai, "TRENDSPARC_SYNTHESIS_AI_MODEL", "TRENDSPARC_SYNTHESIS_AI_BASE_URL", "gpt-4o-mini"),
        (
            broadband_analyzer,
            "TRENDSPARC_SK_BROADBAND_ANALYZER_MODEL",
            "TRENDSPARC_SK_BROADBAND_ANALYZER_BASE_URL",
            "gpt-4o",
        ),
    )
    for module, model_env, base_env, openai_default in stages:
        monkeypatch.delenv(model_env, raising=False)
        monkeypatch.setenv(base_env, "https://api.upstage.ai/v1")
        assert module._model() == "solar-pro3"
        monkeypatch.delenv(base_env, raising=False)
        assert module._model() == openai_default
        monkeypatch.setenv(model_env, "explicit-model")
        assert module._model() == "explicit-model"


def test_report_writer_keeps_action_owner_distinct_from_source_organisations():
    text = (_ROOT / "core" / "report_generator" / "generator.py").read_text(
        encoding="utf-8"
    )
    assert "payload.target_company is the accountable actor" in text
    assert "third-party " in text
    assert "plans only as evidence or benchmarks" in text


def test_all_report_purposes_share_question_first_planning_without_fixed_issue_rows():
    prompt_dir = _ROOT / "prompts" / "report_purposes"
    common = (prompt_dir / "common_planning.md").read_text(encoding="utf-8")

    assert "QUESTION FIRST" in common
    assert "question_answered" in common
    assert "why_here" in common
    assert "AI judgement" in common
    for filename in ("current_status.md", "root_cause.md", "issue_response.md", "future_business.md"):
        assert "Narrative contract" in (prompt_dir / filename).read_text(encoding="utf-8")
    issue = (prompt_dir / "issue_response.md").read_text(encoding="utf-8")
    assert "고정 행으로 만들지 말고" in issue
