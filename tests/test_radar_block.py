import re

import streamlit

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit.blocks import purpose_templates, radar, registry

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _comparison_points():
    return [
        {"entity": "자사", "criterion": "가격 경쟁력", "value": "High", "level": "high"},
        {"entity": "자사", "criterion": "콘텐츠", "value": "Medium", "level": "medium"},
        {"entity": "자사", "criterion": "기술력", "value": "High", "level": "high"},
        {"entity": "경쟁사 A", "criterion": "가격 경쟁력", "value": "Medium", "level": "medium"},
        {"entity": "경쟁사 A", "criterion": "콘텐츠", "value": "High", "level": "high"},
        {"entity": "경쟁사 A", "criterion": "기술력", "value": "Low", "level": "low"},
    ]


def test_importing_radar_module_registers_radar_type():
    assert "radar" in registry.known_types()
    definition = registry.get("radar")
    assert definition is not None
    assert definition.render is radar.render
    assert definition.schema is radar.RadarContent


def test_purpose_template_reference_to_radar_resolves_via_registry():
    referencing_sections = [
        template
        for templates in purpose_templates.PURPOSE_TEMPLATES.values()
        for template in templates
        if "radar" in template["blocks"]
    ]
    assert referencing_sections, "expected at least one purpose template section to reference 'radar'"

    definition = registry.get("radar")
    assert definition is not None
    assert callable(definition.render)


def test_radar_renders_svg_using_only_css_variables_no_hardcoded_hex(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(streamlit, "markdown", lambda body, **kwargs: captured.append(body))

    block = DashboardBlock(
        block_id="radar_smoke",
        section="capability_comparison",
        block_type="radar",
        content={"comparison_points": _comparison_points()},
    )
    registry.get("radar").render(block)

    output = "\n".join(captured)
    assert "<svg" in output
    assert "var(--ts-accent)" in output or "var(--ts-teal)" in output
    svg_markup = output[output.index("<svg"):output.index("</svg>") + len("</svg>")]
    assert not _HEX_COLOR.search(svg_markup)


def test_radar_falls_back_to_caption_when_too_few_shared_axes(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(streamlit, "caption", lambda text, **kwargs: captured.append(text))
    monkeypatch.setattr(streamlit, "markdown", lambda *a, **k: None)

    block = DashboardBlock(
        block_id="radar_insufficient",
        section="capability_comparison",
        block_type="radar",
        content={
            "comparison_points": [
                {"entity": "자사", "criterion": "가격 경쟁력", "value": "High", "level": "high"},
                {"entity": "경쟁사 A", "criterion": "가격 경쟁력", "value": "Medium", "level": "medium"},
            ]
        },
    )
    registry.get("radar").render(block)

    assert captured
    assert "레이더" in captured[0]
