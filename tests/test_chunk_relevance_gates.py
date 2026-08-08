"""A collected document can be a whole magazine issue.

One live run scraped a 100-page KOCCA periodical: seven chunks analysed,
seven model calls spent, and the single claim returned was about a dancer in
a survival show - which then travelled through synthesis into the report as
an "opportunity". Two gates, one before the call and one after it.
"""

from __future__ import annotations

from common.contracts import DocumentAnalysis, GroundedClaim, MetricPoint, SourceDocument
from sectors.sk_broadband.adapter import analyzer


_QUESTION = "롱폼과 숏폼 미디어 소비 트렌드는? 연령대별 이용률 차이도"


def _terms():
    return analyzer._question_terms(_QUESTION, [])


# --- before the call: don't pay to read what can't answer ----------------


def test_prose_with_neither_a_question_term_nor_a_figure_is_skipped():
    interview = (
        "라디오 PD 인터뷰. 청취자가 마치 자신에게 직접 말하는 것처럼 느끼게 만드는 것이 "
        "이 매체의 매력이라고 그는 말했다."
    )

    assert analyzer._chunk_can_answer(interview, _terms()) is False


def test_a_figure_alone_is_enough_to_keep_a_chunk():
    """"전체의 62.5%" in a paragraph phrased in other words is exactly the
    figure a block needs, so a number keeps a chunk on its own."""
    other_words = "공연건수 4.0%, 티켓예매수 2.8% 수준으로 대체로 낮다."

    assert analyzer._chunk_can_answer(other_words, _terms()) is True


def test_a_question_term_alone_is_enough():
    assert analyzer._chunk_can_answer("숏폼 시청 행태가 달라지고 있다.", _terms()) is True


def test_a_particle_does_not_hide_a_matching_term():
    """The question says "근거를", the document says "근거가" - the same word,
    and a literal match would have missed it."""
    terms = analyzer._question_terms("핵심 근거를 구조화하라", [])

    assert analyzer._chunk_can_answer("첫 번째 본문 근거가 있다.", terms) is True


def test_no_question_terms_keeps_everything():
    assert analyzer._chunk_can_answer("아무 내용", []) is True


# --- after the call: an irrelevant chunk contributes nothing --------------


def _analysis(doc_id: str, relevance: str, claim_text: str) -> DocumentAnalysis:
    return DocumentAnalysis(
        doc_id=doc_id, source_id="src", summary="요약",
        relevance_level=relevance, relevant_to_question=relevance != "irrelevant",
        grounded_claims=[GroundedClaim(
            claim_id="c1", claim_type="key_point", claim=claim_text,
            evidence_quote=claim_text, confidence="high",
        )],
        metric_points=[MetricPoint(
            label="이용률", period="2024년", value=93.2, unit="%",
            evidence_claim_id="c1",
        )],
    )


def _document() -> SourceDocument:
    return SourceDocument(
        doc_id="kocca:issue", source_id="KOCCA", title="정기간행물",
        url="https://example.com/issue.pdf", content="본문",
    )


def test_a_chunk_judged_irrelevant_contributes_neither_claims_nor_metrics():
    merged = analyzer._merge_chunk_analyses(
        _document(),
        [
            _analysis("kocca:issue", "direct", "숏폼 이용률은 93.2%였다"),
            _analysis("kocca:issue", "irrelevant", "무용수가 플로어 테크닉을 소화했다"),
        ],
        [],
        incomplete=False,
    )

    claims = [claim.claim for claim in merged.grounded_claims]
    assert claims == ["숏폼 이용률은 93.2%였다"]
    assert len(merged.metric_points) == 1


def test_every_chunk_being_irrelevant_keeps_them_all():
    """Then the judgement is about the document as a whole, and that one is
    made once, downstream - dropping everything here would hide it."""
    merged = analyzer._merge_chunk_analyses(
        _document(),
        [
            _analysis("kocca:issue", "irrelevant", "무용수 이야기"),
            _analysis("kocca:issue", "irrelevant", "드라마 칼럼"),
        ],
        [],
        incomplete=False,
    )

    assert len(merged.grounded_claims) == 2
    assert merged.relevant_to_question is False


# --- a periodical is many articles, only some of them on topic ------------


def test_a_bound_volume_keeps_the_articles_about_the_question():
    """Measured on a live 100-page KOCCA issue: the chunks carrying the actual
    숏폼/롱폼 analysis matched question terms 125 and 104 times, the PD
    interviews and drama columns 27, 21, 19 and 15. Distinct terms didn't
    separate them at all - the whole magazine is about broadcasting."""
    terms = ["숏폼", "이용률"]
    candidates = [
        (1, "숏폼 " * 60 + "이용률 " * 60),   # the analysis
        (2, "숏폼 " * 50 + "이용률 " * 50),
        (3, "숏폼 " * 30),
        (4, "무용수 인터뷰. " * 40 + "숏폼"),  # a column that mentions it once
        (5, "드라마 칼럼. " * 40),
    ]

    kept = [index for index, _ in analyzer._periodical_chunks(candidates, terms)]

    assert kept == [1, 2, 3]


def test_a_short_document_keeps_every_chunk():
    """The rule is about volumes, not about prose quality - an ordinary
    article or report is never thinned."""
    candidates = [(1, "숏폼 이용률 93.2%"), (2, "본문 이어짐"), (3, "결론")]

    assert analyzer._periodical_chunks(candidates, ["숏폼"]) == candidates


def test_a_volume_no_chunk_matches_is_left_alone():
    """No match anywhere means the terms are unusual, not that the document is
    off topic - thinning on a zero signal would be guessing."""
    candidates = [(index, "본문") for index in range(1, 6)]

    assert analyzer._periodical_chunks(candidates, ["숏폼"]) == candidates
