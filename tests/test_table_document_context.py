"""A table row finds its headers even when they were cut into another passage.

Evidence passages are split for retrieval, not along table boundaries.
Live-verified 2026-08-10 on the 방송미디어통신위원회 보도자료: the caption
(line 37) and both header rows (39, 41) landed in a different passage from
the IPTV row (42), so every figure in that table came back with
`period="시점 미상"` and no criterion.
"""
from sectors.sk_broadband.adapter import analyzer as analyzer_module

DOCUMENT = """앞선 산문 문단이 여기에 있다.

< ’24년도 하반기 가입자 수 및 시장점유율 > (단위: 단말장치・단자)

| 구 분 | '24년 하반기 |
| --- | --- |
| 구 분 | 점유율 |
| IPTV | 58.60% |

이 사이에 다른 산문이 들어간다.

< ’25년 상반기 가입자 수 및 시장점유율 > (단위: 단말장치・단자)

| 구 분 | '25년 상반기 | '25년 상반기 | '25년 하반기 | '25년 하반기 |
| --- | --- | --- | --- | --- |
| 구 분 | 가입자 수 | 점유율(A) | 가입자 수 | 점유율(B) |
| IPTV | 21,414,521 | 59.11% | 21,535,256 | 59.57% |
| SO | 12,091,056 | 33.38% | 11,935,236 | 33.01% |
| 위성 | 2,720,523 | 7.51% | 2,679,578 | 7.41% |"""

TARGET = "| IPTV | 21,414,521 | 59.11% | 21,535,256 | 59.57% |"
SO_ROW = "| SO | 12,091,056 | 33.38% | 11,935,236 | 33.01% |"
SAT_ROW = "| 위성 | 2,720,523 | 7.51% | 2,679,578 | 7.41% |"

# What retrieval actually handed the analyzer: the row, without its headers.
ROW_ONLY_PASSAGE = [{"passage_id": "P012", "text": TARGET}]


def _claim(quote, claim_id="c1", passage_id="P012"):
    return {"claim_id": claim_id, "claim_type": "metric", "claim": quote,
            "evidence_quote": quote, "evidence_passage_id": passage_id}


def _recover(quote, passages, document=DOCUMENT, claim_id="c1"):
    return analyzer_module._recovered_metric_points(
        [_claim(quote, claim_id)], passages, document
    )


# ------------------------------------------- B. cross-passage context works
def test_headers_in_another_passage_are_still_found():
    points = _recover(TARGET, ROW_ONLY_PASSAGE)
    counts = [p for p in points if p["unit"] == "단말장치・단자"]

    assert counts, "the subscriber counts must survive"
    assert "시점 미상" not in {p["period"] for p in points}


def test_period_comes_from_the_rows_own_table(): # F
    points = _recover(TARGET, ROW_ONLY_PASSAGE)

    assert {p["period"] for p in points} == {"'25년 상반기", "'25년 하반기"}


def test_criterion_is_column_aligned(): # G
    points = _recover(TARGET, ROW_ONLY_PASSAGE)
    by_value = {p["value"]: p for p in points}

    assert by_value[21414521]["label"] == "IPTV 가입자 수"
    assert by_value[21414521]["period"] == "'25년 상반기"
    assert by_value[59.11]["label"] == "IPTV 점유율(A)"
    assert by_value[21535256]["period"] == "'25년 하반기"
    assert by_value[59.57]["label"] == "IPTV 점유율(B)"


# ------------------------------------------------ A. same-passage unchanged
def test_a_passage_that_does_contain_the_headers_still_wins():
    whole_table = DOCUMENT.split("이 사이에 다른 산문이 들어간다.")[1]
    points = _recover(TARGET, [{"passage_id": "P012", "text": whole_table}])

    assert {p["period"] for p in points} == {"'25년 상반기", "'25년 하반기"}


# ------------------------------------- C/D/E. the wrong table is never used
def test_the_earlier_tables_headers_are_not_borrowed():
    """The '24 table sits above, separated by prose - it is a different table."""
    points = _recover(TARGET, ROW_ONLY_PASSAGE)

    assert "'24년 하반기" not in {p["period"] for p in points}


def test_a_row_from_another_document_finds_nothing():
    points = _recover(TARGET, ROW_ONLY_PASSAGE, document="전혀 다른 문서 본문.")

    assert {p["period"] for p in points} == {"시점 미상"}
    assert all(p.get("share_of") is None for p in points)


def test_no_document_and_no_headers_stays_unknown(): # I
    points = _recover(TARGET, ROW_ONLY_PASSAGE, document="")

    assert {p["period"] for p in points} == {"시점 미상"}


# --------------------------------------------- comparison recovery revives
def test_operator_rows_now_yield_comparisons():
    """Phase 5's recovery is unchanged - it simply has criteria to work with."""
    claims = [_claim(row, f"c{i}") for i, row in enumerate((TARGET, SO_ROW, SAT_ROW))]
    passages = [{"passage_id": "P012", "text": TARGET}]

    recovered = analyzer_module._recovered_comparison_points(claims, passages, DOCUMENT)
    latest = [c for c in recovered if "'25년 하반기" in c["criterion"] and "%" in c["value"]]

    assert {c["entity"] for c in latest} == {"IPTV", "SO", "위성"}
    assert {c["value"] for c in latest} == {"59.57%", "33.01%", "7.41%"}


# ------------------------------------------- 9. share_of policy unchanged
def test_a_table_without_a_total_row_still_gets_no_denominator():
    """Recovering headers must not loosen Phase 3: this table has no 합계."""
    points = _recover(TARGET, ROW_ONLY_PASSAGE)

    assert all(p.get("share_of") is None for p in points)


# ----------------------------------------------------------- J. provenance
def test_provenance_survives_the_wider_lookup():
    points = _recover(TARGET, ROW_ONLY_PASSAGE, claim_id="c9")

    assert points
    assert {p["evidence_claim_id"] for p in points} == {"c9"}


# --------------------------------------- H. serialized row keeps its own
def test_a_serialized_rows_own_headers_win_over_the_document():
    quote = "표 원문 행: 구 분=IPTV; 2022년=20,565,609; 2023년=20,814,402."
    points = analyzer_module._recovered_metric_points(
        [_claim(quote)], ROW_ONLY_PASSAGE, DOCUMENT
    )

    assert {p["period"] for p in points} == {"2022년", "2023년"}
