"""현황파악 questions answer with lists as often as with charts.

Three of four target questions ("인기 순위", "가입 고려 요인", "불만 키워드")
asked for a set of items, and the skeleton had nowhere to put one - they fell
into the summary card's four-bullet prose fallback, which answers a different
question. These slots exist for that, and every one of them disappears rather
than showing an empty frame.
"""

from __future__ import annotations

from common.block_shapes import recurring_terms
from common.contracts import MetricPoint, SynthesisClaim, TrendSynthesis
from common.purpose_slots import PURPOSE_SLOTS, resolve_slots


def _claim(doc_id: str, text: str) -> SynthesisClaim:
    return SynthesisClaim(
        synthesis_claim_id=f"{doc_id}:c1", claim_id="c1", claim_type="risk", claim=text,
        evidence_quote=text, confidence="high", doc_id=doc_id, source_id=doc_id,
    )


def _synthesis(**kwargs) -> TrendSynthesis:
    return TrendSynthesis(request_id="r", sector_id="sk_broadband", **kwargs)


def test_a_word_needs_two_separate_documents_to_count():
    """One article repeating its own vocabulary says nothing about a market."""
    one_document = [_claim("d1", "요금 부담이 크다"), _claim("d1", "요금 부담 반복")]

    assert recurring_terms(one_document) == []

    two_documents = [_claim("d1", "요금 부담이 크다"), _claim("d2", "요금 부담과 속도 불만")]

    assert [term for term, _, _ in recurring_terms(two_documents)] == ["부담", "요금"]


def test_a_particle_does_not_split_one_noun_into_two_terms():
    """"요금"과 "요금과" counted separately never reached the threshold."""
    terms = dict((term, count) for term, count, _ in recurring_terms(
        [_claim("d1", "속도 저하가 문제"), _claim("d2", "속도를 지적")]
    ))

    assert terms.get("속도") == 2


def test_every_term_carries_a_claim_the_reader_can_check(monkeypatch):
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_recurring_terms(
        [_claim("d1", "설치 지연 불만"), _claim("d2", "설치 지연이 반복"), _claim("d3", "설치 대기 불만")]
    )
    body = "".join(captured)

    assert "설치" in body
    # The number is a document count, and the card has to say so - a bare
    # number beside a word reads as a score.
    assert "서로 다른 출처 문서의 수" in body


def test_a_ranking_question_gets_the_comparison_bars_not_the_market_card():
    """Both slots read metric_series; slot order is what decides. A question
    about ranking must not have its bars claimed by 시장 상황 first."""
    synthesis = _synthesis(metric_series=[
        MetricPoint(label="이용률", subject=name, period="2025년", value=value, unit="%")
        for name, value in (("숏폼", 62), ("롱폼", 38))
    ])

    by_id = {slot.slot.slot_id: slot for slot in resolve_slots("current_status", synthesis, None)}

    assert by_id["ranking"].block_type == "item_bar"
    # And 시장 상황 must not have taken them on its way past.
    assert by_id["market"].block_type != "item_bar"


def test_a_status_report_with_no_recommendation_shows_no_recommendation_card():
    """현황파악 asks what is happening. Four of five tested questions want no
    action at all, and the card was appearing regardless."""
    synthesis = _synthesis(key_points=["시장이 성장 중"], recommended_actions=[])

    slot_ids = {slot.slot.slot_id for slot in resolve_slots("current_status", synthesis, None)}

    assert "response" not in slot_ids


def test_the_recommendation_card_still_appears_when_there_are_actions():
    synthesis = _synthesis(recommended_actions=["요금제를 재설계한다"])

    by_id = {slot.slot.slot_id: slot for slot in resolve_slots("current_status", synthesis, None)}

    assert by_id["response"].block_type == "action_list"


def test_a_short_list_stays_prose_rather_than_claiming_a_card():
    """Two bullets are a sentence, not a list worth its own block."""
    synthesis = _synthesis(risks=["요금 부담", "속도 불만"])

    by_id = {slot.slot.slot_id: slot for slot in resolve_slots("current_status", synthesis, None)}

    assert by_id["factors"].block_type == "narrative_list"


def test_factor_claims_reach_the_factor_block_without_audience_item_limits():
    factors = [f"근거로 확인된 요인 {index}" for index in range(1, 7)]
    synthesis = _synthesis(factors=factors)

    by_id = {slot.slot.slot_id: slot for slot in resolve_slots("current_status", synthesis, None)}

    assert by_id["factors"].block_type == "factor_list"
    assert by_id["factors"].items == factors


def test_the_factor_card_keeps_every_item_not_the_first_four(monkeypatch):
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_factor_list([(f"요인 {index}", None) for index in range(1, 7)])
    body = "".join(captured)

    assert "요인 6" in body
    assert "순서는 우열이 아닙니다" in body


def test_factor_slot_renderer_does_not_reintroduce_a_display_cap(monkeypatch):
    from reporting.dashboard_streamlit.blocks import slot_blocks

    captured: list[list[tuple[str, str | None]]] = []
    monkeypatch.setattr(slot_blocks, "render_factor_list", lambda rows: captured.append(rows))
    synthesis = _synthesis(factors=[f"요인 {index}" for index in range(1, 13)])
    context = slot_blocks.SlotContext(
        result=type("Result", (), {"synthesis": synthesis})(),
        synthesis=synthesis,
        items=synthesis.factors,
        risks=[],
        opportunities=[],
        strengths=[],
        weaknesses=[],
    )

    renderer = slot_blocks._factor_list(context)
    assert renderer is not None
    renderer()
    assert [value for value, _ in captured[0]] == synthesis.factors


def test_the_new_slots_are_all_optional():
    """A 현황파악 report without them must look exactly as it did before."""
    optional = {
        slot.slot_id for slot in PURPOSE_SLOTS["current_status"] if slot.optional
    }

    assert optional == {"ranking", "factors", "segments", "keywords", "response"}
