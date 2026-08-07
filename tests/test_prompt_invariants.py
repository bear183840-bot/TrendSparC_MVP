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
    SWOT_COMPLETENESS_INSTRUCTION,
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
    text = path.read_text(encoding="utf-8")
    if "SWOT_COMPLETENESS_INSTRUCTION" not in text:
        pytest.skip("sector analyzer is still a stub")
    assert "COMPARISON_COMPLETENESS_INSTRUCTION" in text


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
