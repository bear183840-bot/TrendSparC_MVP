import streamlit
from pydantic import BaseModel

from common.contracts import DashboardBlock
from reporting.dashboard_streamlit import renderer
from reporting.dashboard_streamlit.blocks import registry

# The 9 blocks named in the block-registry spec, plus "bar" (a genuinely new
# 10th type added this session) and the 4 backward-compat types ("auto",
# "text", "metric", "custom") that pre-date the registry but must keep working.
_CORE_NINE = {"metrics", "chart", "matrix", "timeline", "table", "graph", "list", "evidence", "bar"}
_COMPAT_TYPES = {"auto", "text", "metric", "custom"}

_SMOKE_CONTENT = {
    "metrics": {"key_points": ["핵심 포인트"], "risks": ["위험 신호"], "opportunities": ["기회 신호"]},
    "chart": {"opportunities": ["기회 신호"], "key_points": ["포인트"]},
    "bar": {"key_points": ["1위 항목", "2위 항목"]},
    "matrix": {"risks": ["위험"], "opportunities": ["기회"]},
    "timeline": {"monitoring_indicators": ["지표 1", "지표 2"]},
    "table": [{"항목": "A", "값": "1"}, {"항목": "B", "값": "2"}],
    "graph": {"summary": "문제 요약", "risks": ["원인"], "evidence": ["영향"], "actions": ["개선"]},
    "list": {"actions": ["과제 1", "과제 2"]},
    "evidence": {"evidence": ["근거 1"]},
    "auto": {"key_points": ["필드"]},
    "text": {"summary": "요약문", "key_points": ["포인트"]},
    "metric": {"label": "지표", "value": 10},
    "custom": {"anything": True},
}


def test_default_blocks_are_registered_with_valid_definitions():
    known = registry.known_types()
    assert _CORE_NINE <= known
    assert _COMPAT_TYPES <= known

    for block_type in _CORE_NINE | _COMPAT_TYPES:
        definition = registry.get(block_type)
        assert definition is not None, block_type
        assert definition.block_type == block_type
        assert isinstance(definition.description, str) and definition.description
        assert isinstance(definition.schema, type) and issubclass(definition.schema, BaseModel)
        assert callable(definition.render)


def test_each_default_block_smoke_renders_without_raising(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(streamlit, "markdown", lambda body, **kwargs: captured.append(body))

    for block_type, content in _SMOKE_CONTENT.items():
        captured.clear()
        block = DashboardBlock(
            block_id=f"smoke_{block_type}",
            section="smoke_section",
            block_type=block_type,
            content=content if isinstance(content, dict) else {},
            data=content if isinstance(content, list) else None,
        )
        definition = registry.get(block_type)
        definition.render(block)  # must not raise


def test_normalized_block_type_recognizes_newly_registered_types_dynamically():
    # BLOCK_REGISTRY is process-global, so this must not leak into other
    # tests (e.g. test_dashboard_skeleton.py's "unknown type stays custom"
    # case) - register a throwaway type and always remove it again.
    probe_type = "test_only_design_component_v2"
    renderer.register_renderer(probe_type, lambda block: None)
    try:
        probe = DashboardBlock(block_id="probe", section="s", block_type=probe_type)
        assert renderer.normalized_block_type(probe) == probe_type

        still_unknown = DashboardBlock(block_id="unknown", section="s", block_type="totally_unregistered_type")
        assert renderer.normalized_block_type(still_unknown) == "custom"
    finally:
        registry.BLOCK_REGISTRY.pop(probe_type, None)


def test_render_block_uses_registry_for_dispatch(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(streamlit, "markdown", lambda body, **kwargs: captured.append(body))
    monkeypatch.setattr(streamlit, "caption", lambda *a, **k: None)
    monkeypatch.setattr(streamlit, "subheader", lambda *a, **k: None)

    block = DashboardBlock(
        block_id="01_evidence",
        section="sources",
        block_type="evidence",
        content={"evidence": ["근거 A [doc_id=x:1]"]},
    )
    renderer.render_block(block)

    output = "\n".join(captured)
    assert "근거 A" in output
