"""Causal links and importance scores are judgements, so they are verified.

The analyzer may propose a parent claim or an importance score; neither is
something a document states outright, so each survives only where it resolves
and arrives with its reason attached.
"""

from __future__ import annotations

from common.block_shapes import cause_tree, has_cause_tree, has_importance_ranking, importance_ranked
from common.contracts import SynthesisClaim
from sectors.sk_broadband.adapter.analyzer import _verified_relations


def _claim(claim_id: str, **extra) -> dict:
    return {"claim_id": claim_id, "claim_type": "risk", "claim": f"주장 {claim_id}",
            "evidence_quote": "q", "confidence": "high", **extra}


def test_a_parent_that_did_not_survive_verification_is_dropped_not_the_claim():
    claims = [_claim("c1", parent_claim_id="c9")]

    resolved = _verified_relations(claims)

    assert len(resolved) == 1
    assert resolved[0]["parent_claim_id"] is None


def test_a_claim_cannot_be_its_own_cause():
    assert _verified_relations([_claim("c1", parent_claim_id="c1")])[0]["parent_claim_id"] is None


def test_a_cycle_is_broken_because_a_looped_tree_has_no_root():
    claims = [_claim("c1", parent_claim_id="c2"), _claim("c2", parent_claim_id="c1")]

    resolved = _verified_relations(claims)

    assert [claim["parent_claim_id"] for claim in resolved] == [None, None]


def test_a_real_chain_is_kept():
    claims = [_claim("c1"), _claim("c2", parent_claim_id="c1"), _claim("c3", parent_claim_id="c2")]

    assert [claim["parent_claim_id"] for claim in _verified_relations(claims)] == [None, "c1", "c2"]


def test_an_importance_with_no_stated_reason_is_discarded():
    """A number with no reason renders as a measurement while carrying an
    opinion - the requirement was that the judgement arrive with its context."""
    resolved = _verified_relations([
        _claim("c1", importance=80),
        _claim("c2", importance=80, importance_basis="  "),
        _claim("c3", importance=80, importance_basis="가입자 이탈에 직접 연결됨"),
        _claim("c4", importance=140, importance_basis="이유 있음"),
    ])

    assert [claim["importance"] for claim in resolved] == [None, None, 80, None]
    assert resolved[0]["importance_basis"] is None


def _synthesis_claim(
    claim_id: str, parent: str | None = None, importance: int | None = None,
    claim_type: str = "risk",
) -> SynthesisClaim:
    return SynthesisClaim(
        synthesis_claim_id=claim_id, claim_id=claim_id, claim_type=claim_type,
        claim=f"주장 {claim_id}", evidence_quote="q", confidence="high",
        doc_id="d1", source_id="s1",
        parent_synthesis_claim_id=parent,
        importance=importance,
        importance_basis="이유" if importance is not None else None,
    )


def test_a_tree_needs_a_root_something_actually_derives_from():
    """A claim nobody derives from is a finding, not a root."""
    assert has_cause_tree([_synthesis_claim("a"), _synthesis_claim("b")]) is False

    tree = cause_tree([_synthesis_claim("a"), _synthesis_claim("b", parent="a")])

    assert [(root.synthesis_claim_id, [child.synthesis_claim_id for child in children])
            for root, children in tree] == [("a", ["b"])]


def test_one_scored_claim_is_not_a_ranking():
    assert has_importance_ranking(
        [_synthesis_claim("a", importance=90, claim_type="factor")]
    ) is False
    assert has_importance_ranking(
        [_synthesis_claim("a", importance=40, claim_type="factor"),
         _synthesis_claim("b", importance=90, claim_type="factor")]
    ) is True
    assert [claim.synthesis_claim_id for claim in importance_ranked(
        [_synthesis_claim("a", importance=40, claim_type="factor"),
         _synthesis_claim("b", importance=90, claim_type="factor")]
    )] == ["b", "a"]


def test_importance_ranking_is_restricted_to_driver_claims():
    """Key Drivers ranks causes ("factor"), not every scored claim type.

    Live-verified 2026-08-11: an `opportunity`/`risk`/`business_impact`
    claim the model happened to score still isn't a *driver* of anything -
    it answers "what" or "so what", not "why". Ranking it under a heading
    that promises causes was the actual bug behind Key Drivers showing plain
    narrative sentences.
    """
    claims = [
        _synthesis_claim("a", importance=90, claim_type="opportunity"),
        _synthesis_claim("b", importance=40, claim_type="risk"),
    ]
    assert importance_ranked(claims) == []
    assert has_importance_ranking(claims) is False


def test_importance_bars_always_say_they_are_an_ai_judgement(monkeypatch):
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_importance_bars(
        [_synthesis_claim("a", importance=90, claim_type="factor"),
         _synthesis_claim("b", importance=40, claim_type="factor")]
    )
    body = "".join(captured)

    assert "AI 판단" in body
    # Scaled against 100, not against the top row: a set of middling scores
    # must not render as one dominant driver.
    assert "width:90%" in body and "width:40%" in body


def test_no_relations_means_no_block_rather_than_an_empty_frame(monkeypatch):
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_cause_tree([_synthesis_claim("a")])
    components.render_importance_bars([_synthesis_claim("a")])

    assert captured == []
