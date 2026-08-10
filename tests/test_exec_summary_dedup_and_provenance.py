"""Checklist items L, N, O, P from the teammate's dashboard spec (§20).

L. A different metric (different label) must never be swept up in the
   Executive Summary <-> Key Metrics dedup just because it shares a report
   with the headline figure.
N. Composition (a stated whole split into parts, `share_of`) and competitor
   comparison (`comparison_points.entity`) come from two structurally
   separate synthesis fields and must never be read as one another.
O. The "AI Insight" badge/label stays visible even though its content is
   collapsed by default.
P. citation/provenance (a claim's source link) survives through
   render_metric_insight.
"""
from __future__ import annotations

from unittest.mock import patch

from common.block_shapes import has_metric_comparison, share_groups
from common.contracts import ComparisonPoint, MetricPoint, SynthesisClaim
from common.purpose_slots import kpi_evidence_key
from reporting.dashboard_streamlit import components
from reporting.dashboard_streamlit.blocks.base import SlotContext
from reporting.dashboard_streamlit.blocks.slot_blocks import _undrawn_kpi_points


def _point(label: str, value: float, **kwargs) -> MetricPoint:
    base = dict(label=label, period="2025년", value=value, unit="억원")
    base.update(kwargs)
    return MetricPoint(**base)


# --- L: dedup keys on identity, not on "something already happened" -------


def test_a_different_metric_survives_the_headline_seed():
    headline = _point("가입자 수", 21_535_256, unit="명")
    other = _point("영업이익", 3_741)
    context = SlotContext(
        result=None, synthesis=type("S", (), {"metric_series": [headline, other]})(),
        items=[], risks=[], opportunities=[], strengths=[], weaknesses=[],
        drawn_before=frozenset({kpi_evidence_key(headline)}),
    )

    remaining = _undrawn_kpi_points(context)

    assert other in remaining
    assert len(remaining) == 1


def test_the_same_label_at_a_different_period_is_still_one_kpi_identity():
    """rank_kpi_candidates already folds every period of one label into a
    single latest-plus-delta card (see common/block_shapes.py) - so keying
    the cross-section dedup on label alone does not create a second,
    unintended exclusion for a different period of the *same* metric; it
    reproduces exactly what the KPI card already does with it."""
    early = _point("가입자 수", 20_000_000, unit="명", period="2024년")
    late = _point("가입자 수", 21_535_256, unit="명", period="2025년")

    assert kpi_evidence_key(early) == kpi_evidence_key(late)


# --- N: composition and competitor comparison never cross-read ------------


def test_a_composition_group_is_never_read_as_an_item_comparison():
    shares = [
        MetricPoint(label="KT", subject="KT", period="2025년", value=25, unit="%",
                    share_of="유료방송 가입자"),
        MetricPoint(label="SKB", subject="SKB", period="2025년", value=19, unit="%",
                    share_of="유료방송 가입자"),
    ]

    assert share_groups(shares)
    assert has_metric_comparison(shares) is False


def test_composition_and_comparison_are_different_contracts_entirely():
    """share_groups() reads `MetricPoint.share_of`; a competitor comparison
    reads `ComparisonPoint.entity`/`.criterion` - two distinct Pydantic
    models, not two readings of one shape, so a resolver cannot confuse them
    by construction."""
    comparison = ComparisonPoint(entity="KT", criterion="점유율", value="25%")

    assert not hasattr(comparison, "share_of")
    assert not hasattr(_point("KT", 25), "criterion")


# --- O: the AI Insight badge, and P: its citation link ---------------------


def _claim(**kwargs) -> SynthesisClaim:
    base = dict(
        synthesis_claim_id="s1", claim_id="c1", claim_type="metric",
        claim="가입자 증가세가 최근 반기에도 지속됨",
        evidence_quote="가입자 수가 전기 대비 증가했다", confidence="high",
        doc_id="d1", source_id="src1", source_url="https://example.com/report",
    )
    base.update(kwargs)
    return SynthesisClaim(**base)


def test_the_ai_insight_badge_is_always_visible():
    point = _point("가입자 수", 100, evidence_synthesis_claim_id="s1")
    captured: list[str] = []
    with patch.object(components.st, "markdown", lambda body, **_: captured.append(body)):
        # st.expander is a context manager in real Streamlit; patch it the
        # same way so the label passed to it is observable.
        labels: list[str] = []

        class _FakeExpander:
            def __init__(self, label):
                labels.append(label)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with patch.object(components.st, "expander", _FakeExpander):
            components.render_metric_insight([point], [_claim()])

    assert "AI Insight" in labels


def test_the_citation_link_survives_into_the_insight_panel():
    point = _point("가입자 수", 100, evidence_synthesis_claim_id="s1")
    captured: list[str] = []
    with patch.object(components.st, "markdown", lambda body, **_: captured.append(body)):
        with patch.object(components.st, "expander", lambda label: _NullContext()):
            components.render_metric_insight([point], [_claim()])
    body = "".join(captured)

    assert "https://example.com/report" in body
    assert "출처 원문" in body


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
