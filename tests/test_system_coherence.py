"""Rules that keep the layers honest with each other.

Each of these was a real drift found by reading the whole tree at once, not by
any failing test: two section-title tables that disagreed on three ids, two
different default audiences, and a shape predicate that lived in the rendering
module so anything wanting to ask a data question had to import Streamlit.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LAYERS_THAT_MUST_NOT_RENDER = ("core", "common", "sources", "sectors")


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _python_files(*roots: str):
    for root in roots:
        for path in (_ROOT / root).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path


def test_the_analysis_layers_never_import_the_rendering_layer():
    """core/ decides what is true; reporting/ decides how it looks. A core
    module that imports a view can't be reasoned about without the UI."""
    offenders = [
        f"{path.relative_to(_ROOT)} -> {name}"
        for path in _python_files(*_LAYERS_THAT_MUST_NOT_RENDER)
        for name in _module_imports(path)
        if name.startswith("reporting")
    ]
    assert offenders == [], offenders


def test_slot_resolution_does_not_need_streamlit():
    """purpose_slots decides which block a slot earns - a data question. It
    used to import components (and Streamlit with it) for seven predicates.

    Runs in a subprocess: reimporting modules in-process to observe a fresh
    import leaves a second copy of them in sys.modules, which then breaks
    every `is`-identity assertion in the rest of this file.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            "import reporting.dashboard_streamlit.purpose_slots;"
            "print('streamlit' in sys.modules)",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", result.stdout


def test_one_default_audience():
    from core.request_pipeline.pipeline import DEFAULT_AUDIENCE_ID
    from core.request_pipeline.synthesis_fixture import _DEFAULT_AUDIENCE_ID

    assert _DEFAULT_AUDIENCE_ID == DEFAULT_AUDIENCE_ID


def test_one_section_title_table():
    """Two tables disagreed on market_status / recommended_action /
    risk_and_opportunity, and 18 ids had no Korean title at all."""
    from common.section_titles import SECTION_TITLES

    generator = importlib.import_module("core.report_generator.generator")
    components = importlib.import_module("reporting.dashboard_streamlit.components")

    assert not hasattr(generator, "_SECTION_TITLES")
    assert not hasattr(components, "_SECTION_TITLES")
    assert generator.section_title is components.section_title
    assert SECTION_TITLES["market_status"] == "시장 현황"


def test_every_planned_section_has_a_registered_title():
    """Otherwise a real section renders as a raw id like `investment_signal`
    in an otherwise Korean report."""
    from common.section_titles import SECTION_TITLES
    from core.report_purpose.classifier import recommended_sections_for

    planned = {"overview", "sources", "executive_summary"}
    for purpose in ("current_status", "issue_response", "future_business", "root_cause"):
        planned |= set(recommended_sections_for(purpose))

    assert planned <= set(SECTION_TITLES), sorted(planned - set(SECTION_TITLES))


def test_every_slot_section_reference_resolves_to_a_title():
    from common.section_titles import SECTION_TITLES
    from reporting.dashboard_streamlit.purpose_slots import PURPOSE_SLOTS

    referenced = {
        section
        for slots in PURPOSE_SLOTS.values()
        for slot in slots
        for section in slot.sections
    }
    assert referenced <= set(SECTION_TITLES), sorted(referenced - set(SECTION_TITLES))


def test_every_slot_synthesis_field_exists_on_the_contract():
    """A slot's fallback field name is a string; a typo would silently mean
    "no evidence" forever."""
    from common.contracts import TrendSynthesis
    from reporting.dashboard_streamlit.purpose_slots import PURPOSE_SLOTS

    valid = set(TrendSynthesis.model_fields)
    for slots in PURPOSE_SLOTS.values():
        for slot in slots:
            assert set(slot.fields) <= valid, (slot.slot_id, slot.fields)


def test_the_radar_scale_is_shared_between_predicate_and_renderers():
    from common.block_shapes import LEVEL_RADIUS_FRACTION
    from reporting.dashboard_streamlit.blocks import radar

    assert radar._LEVEL_RADIUS_FRACTION is LEVEL_RADIUS_FRACTION


@pytest.mark.parametrize(
    "name",
    ["has_timeseries", "bar_metric_groups", "has_comparison", "has_radar",
     "has_timeline", "has_cause_map", "metric_comparison_groups"],
)
def test_components_still_exposes_the_moved_predicates(name):
    """They were re-exported rather than relocated silently, so every existing
    caller and test keeps working."""
    from common import block_shapes
    from reporting.dashboard_streamlit import components

    assert getattr(components, name) is getattr(block_shapes, name)
