"""share_of is filled only when the source structurally proves a whole.

Fixtures are the 방송미디어통신위원회 유료방송 tables the live runs collected.
"""
import re

from sectors.sk_broadband.adapter import analyzer as analyzer_module

# Has an explicit 합계 row and a title - the two structural facts that prove
# the percentage column partitions a named whole.
SHARE_PASSAGE = """< ’25년도 상반기 가입자 수 및 시장점유율 > (단위: 단말장치・단자)

| 구 분 | '24년 하반기 | '24년 하반기 | '25년 상반기 | '25년 상반기 | 증감 |
| --- | --- | --- | --- | --- | --- |
| 구 분 | 가입자 수 | 점유율(B) | 가입자 수 | 점유율(B) | 점유율(B-A) |
| IPTV | 21,310,251 | 58.60% | 21,414,521 | 59.11% | 0.51%p |
| SO | 12,273,100 | 33.75% | 12,091,056 | 33.38% | -0.37%p |
| 위성 | 2,781,295 | 7.65% | 2,720,523 | 7.51% | -0.14%p |
| 합계 | 36,364,646 | - | 36,226,100 | - | - |"""

ROWS = {
    "IPTV": "| IPTV | 21,310,251 | 58.60% | 21,414,521 | 59.11% | 0.51%p |",
    "SO": "| SO | 12,273,100 | 33.75% | 12,091,056 | 33.38% | -0.37%p |",
    "위성": "| 위성 | 2,781,295 | 7.65% | 2,720,523 | 7.51% | -0.14%p |",
}

# Same shape, but no total row: nothing states what these add up to.
NO_TOTAL_PASSAGE = """< 사업자별 시장점유율 >

| 구 분 | '25년 상반기 |
| --- | --- |
| 구 분 | 점유율 |
| KT | 25.24% |
| SKB | 18.68% |
| LGU+ | 15.82% |"""

NO_TOTAL_ROW = "| KT | 25.24% |"

# A total row, but the column is a growth rate, not a composition.
RATE_PASSAGE = """< 최근 가입자 증감률 >

| 구 분 | 2025년 |
| --- | --- |
| 구 분 | 증감률 |
| IPTV | 1.79% |
| SO | -0.74% |
| 합계 | 0.5% |"""

RATE_ROW = "| IPTV | 1.79% |"


def _claim(quote: str, claim_id: str = "c1") -> dict:
    return {"claim_id": claim_id, "claim_type": "metric", "claim": quote,
            "evidence_quote": quote, "evidence_passage_id": "P001"}


def _recover(quote, passage, claim_id="c1"):
    return analyzer_module._recovered_metric_points(
        [_claim(quote, claim_id)], [{"passage_id": "P001", "text": passage}]
    )


def _shares(points):
    return [p for p in points if p.get("share_of")]


# ------------------------------------------- A/B/H. share is recovered
def test_composition_column_gets_the_tables_own_whole():
    points = _recover(ROWS["IPTV"], SHARE_PASSAGE)
    shares = _shares(points)

    assert shares, "the 점유율 column of a table with a 합계 row is a share"
    assert all(s["unit"] == "%" for s in shares)
    assert {s["share_of"] for s in shares} == {"’25년도 상반기 가입자 수 및 시장점유율"}


def test_every_slice_of_one_table_names_the_same_whole():
    wholes = set()
    for i, row in enumerate(ROWS.values()):
        wholes |= {s["share_of"] for s in _shares(_recover(row, SHARE_PASSAGE, f"c{i}"))}

    assert len(wholes) == 1


def test_slices_of_one_period_sum_to_the_whole():
    """Corroboration, not the trigger - but it must actually hold here."""
    latest = []
    for i, row in enumerate(ROWS.values()):
        latest += [
            s for s in _shares(_recover(row, SHARE_PASSAGE, f"c{i}"))
            if s["period"] == "'25년 상반기"
        ]

    assert len(latest) == 3
    assert abs(sum(s["value"] for s in latest) - 100.0) < 0.05


# ----------------------------------------------- C/D. rates never get one
def test_a_growth_column_never_becomes_a_share():
    points = _recover(RATE_ROW, RATE_PASSAGE)

    assert _shares(points) == []


def test_the_parenthesised_change_beside_a_count_is_not_a_share():
    points = _recover(ROWS["IPTV"], SHARE_PASSAGE)

    assert all(not p.get("share_of") for p in points if p["is_relative"])
    assert all(not p.get("share_of") for p in points if p["unit"] == "%p")


# ------------------------------------ E/G. no proof of a whole -> None
def test_without_a_total_row_no_denominator_is_invented():
    """The three add to 59.74, not 100 - and nothing names the whole."""
    points = _recover(NO_TOTAL_ROW, NO_TOTAL_PASSAGE)

    assert _shares(points) == []
    assert all(p.get("share_of") is None for p in points)


def test_a_serialized_row_has_no_table_body_to_prove_a_whole():
    quote = "표 원문 행: 구 분=IPTV; '25년 상반기=59.11%."
    points = analyzer_module._recovered_metric_points(
        [_claim(quote)], [{"passage_id": "P001", "text": SHARE_PASSAGE}]
    )

    assert all(p.get("share_of") is None for p in points)


def test_prose_percentages_never_get_a_denominator():
    quote = "IPTV 가입률은 60.7%, 케이블TV는 36.7%로 나타났다."
    points = analyzer_module._recovered_metric_points([_claim(quote)], [])

    assert all(p.get("share_of") is None for p in points)


# ------------------------------------------------ F. period keeps groups apart
def test_the_two_periods_of_one_table_are_separate_groups():
    points = _shares(_recover(ROWS["IPTV"], SHARE_PASSAGE))
    periods = {p["period"] for p in points}

    assert periods == {"'24년 하반기", "'25년 상반기"}
    assert len({(p["share_of"], p["period"]) for p in points}) == 2


# -------------------------------------------------------- I. provenance
def test_share_metrics_keep_their_claim():
    points = _shares(_recover(ROWS["SO"], SHARE_PASSAGE, "c9"))

    assert points
    assert {p["evidence_claim_id"] for p in points} == {"c9"}


# ------------------------------------------ K. identity/conflict untouched
def test_share_of_participates_in_identity_without_forcing_merges():
    from common.metric_identity import metric_identity, normalize_metric_points

    a = {"label": "IPTV 점유율", "subject": "IPTV", "period": "2025년 상반기",
         "unit": "%", "share_of": "유료방송 전체", "value": 59.11, "doc_id": "d1"}
    b = dict(a, share_of=None)

    assert metric_identity(a) != metric_identity(b)
    assert len(normalize_metric_points([a, b])) == 2
