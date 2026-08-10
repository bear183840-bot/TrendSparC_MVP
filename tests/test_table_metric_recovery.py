"""Deterministic recovery over table-shaped evidence.

Every fixture here is the literal text of the 방송미디어통신위원회 유료방송
가입자 보도자료 that the 2026-08-10 live run collected, because that run is
what exposed the defect: 184 recovered metric points, of which none carried
both a usable label and a real period, and 0 comparison points despite the
tables comparing three operators on one shared 점유율 column.
"""
import re

from sectors.sk_broadband.adapter import analyzer as analyzer_module

# The '최근 3년간' table: one period header split over two lines, subscriber
# counts whose unit lives only in the caption, and a parenthesised delta.
TREND_PASSAGE = """< 최근 3년간 가입자 수 및 전기 대비 증감률 > (단위: 단말장치・단자)

| 구 분 | 구 분 | 2022년 | 2023년 | 2023년 | 2024년 | 2024년 | 2025년 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 구 분 | 구 분 | 하반기 | 상반기 | 하반기 | 상반기 | 하반기 | 상반기 |
| 전체 가입자 | 전체 가입자 | 36,248,397 | 36,347,495 | 36,390,365 | 36,384,610 | 36,364,646 | 36,226,100 |
|  | IPTV (증감률) | 20,565,609 (1.79%) | 20,814,402 (1.21%) | 21,003,615 (0.91%) | 21,149,096 (0.69%) | 21,310,251 (0.76%) | 21,414,521 (0.49%) |"""

TREND_ROW = (
    "|  | IPTV (증감률) | 20,565,609 (1.79%) | 20,814,402 (1.21%) | 21,003,615 (0.91%) "
    "| 21,149,096 (0.69%) | 21,310,251 (0.76%) | 21,414,521 (0.49%) |"
)

# The '25년도 상반기' table: period on one header line, criterion on the next,
# one row per operator - the shape a comparison block needs.
SHARE_PASSAGE = """< ’25년도 상반기 가입자 수 및 시장점유율 > (단위: 단말장치・단자)

| 구 분 | '24년 하반기 | '24년 하반기 | '25년 상반기 | '25년 상반기 | 증감 | 증감 |
| --- | --- | --- | --- | --- | --- | --- |
| 구 분 | 가입자 수 | 점유율(B) | 가입자 수 | 점유율(B) | 가입자 수 | 점유율(B-A) |
| KT | 8,998,120 | 24.74% | 9,028,900 | 24.92% | 30,780 | 0.18%p |
| SKB | 6,742,300 | 18.54% | 6,768,835 | 18.68% | 26,535 | 0.14%p |
| LGU+ | 5,590,410 | 15.37% | 5,616,786 | 15.50% | 26,376 | 0.13%p |"""

SHARE_ROWS = {
    "KT": "| KT | 8,998,120 | 24.74% | 9,028,900 | 24.92% | 30,780 | 0.18%p |",
    "SKB": "| SKB | 6,742,300 | 18.54% | 6,768,835 | 18.68% | 26,535 | 0.14%p |",
    "LGU+": "| LGU+ | 5,590,410 | 15.37% | 5,616,786 | 15.50% | 26,376 | 0.13%p |",
}


def _claim(claim_id: str, quote: str, passage_id: str = "P001") -> dict:
    return {
        "claim_id": claim_id,
        "claim_type": "metric",
        "claim": quote,
        "evidence_quote": quote,
        "evidence_passage_id": passage_id,
        "evidence_location": passage_id,
        "confidence": "high",
    }


def _passages(text: str, passage_id: str = "P001") -> list[dict]:
    return [{"passage_id": passage_id, "text": text}]


def _recover(claims, passages):
    return analyzer_module._recovered_metric_points(claims, passages)


# --------------------------------------------------------------- A. reject
def test_comma_grouped_number_never_becomes_a_label():
    """`20,565,609 (1.79%)` used to yield label '609 증감률', subject '609'.

    _METRIC_LABEL_BOUNDARY_RE splits on commas, so the sentence parser read
    the last comma group of the count as the name of the percentage.
    """
    points = _recover([_claim("c1", TREND_ROW)], _passages(TREND_PASSAGE))

    labels = {str(point["label"]) for point in points}
    subjects = {str(point.get("subject")) for point in points}
    for fragment in ("609", "402", "615", "096", "251", "521"):
        assert fragment not in labels
        assert f"{fragment} 증감률" not in labels
        assert fragment not in subjects


def test_no_metric_label_is_a_bare_number():
    points = _recover([_claim("c1", TREND_ROW)], _passages(TREND_PASSAGE))

    for point in points:
        assert not str(point["label"]).strip().replace(".", "").isdigit()
        assert any(character.isalpha() for character in str(point["label"]))


def test_header_only_row_produces_nothing():
    """'구 분 | 가입자 수 | 점유율(B)' names no subject of its own."""
    header = "| 구 분 | 가입자 수 | 점유율(B) | 가입자 수 | 점유율(B) | 가입자 수 | 점유율(B-A) |"

    assert _recover([_claim("c1", header)], _passages(SHARE_PASSAGE)) == []


def test_row_whose_label_cell_is_numeric_is_rejected():
    passage = "| 구 분 | 2025년 |\n| --- | --- |\n| 12,345 | 6,789 |"
    row = "| 12,345 | 6,789 |"

    assert _recover([_claim("c1", row)], _passages(passage)) == []


# ------------------------------------------------------------- B. preserve
def test_subscriber_counts_survive_with_the_sources_own_unit():
    """The count is the answer; its unit is stated only in the caption.

    "단말장치・단자" is kept verbatim - turning it into "명" would invent a
    unit the document never used.
    """
    points = _recover([_claim("c1", TREND_ROW)], _passages(TREND_PASSAGE))
    counts = [p for p in points if p["value"] == 21414521]

    assert counts, "the latest IPTV subscriber count must be recovered"
    assert counts[0]["unit"] == "단말장치・단자"
    assert counts[0]["subject"] == "IPTV"
    assert counts[0]["period"] == "2025년 상반기"


def test_every_period_of_the_series_is_recovered_from_stacked_headers():
    """chart's contract needs 3+ real periods; the row supplies six."""
    points = _recover([_claim("c1", TREND_ROW)], _passages(TREND_PASSAGE))
    counts = [p for p in points if not p["is_relative"]]
    periods = [p["period"] for p in counts]

    assert periods == [
        "2022년 하반기", "2023년 상반기", "2023년 하반기",
        "2024년 상반기", "2024년 하반기", "2025년 상반기",
    ]
    assert [p["value"] for p in counts] == [
        20565609, 20814402, 21003615, 21149096, 21310251, 21414521,
    ]
    assert {p["label"] for p in counts} == {"IPTV"}
    assert "시점 미상" not in periods


def test_parenthesised_delta_is_kept_as_its_own_relative_metric():
    points = _recover([_claim("c1", TREND_ROW)], _passages(TREND_PASSAGE))
    deltas = [p for p in points if p["is_relative"]]

    assert {p["label"] for p in deltas} == {"IPTV 증감률"}
    assert deltas[0]["unit"] == "%"
    assert deltas[-1]["value"] == 0.49


def test_operator_share_row_keeps_criterion_and_period():
    points = _recover([_claim("c1", SHARE_ROWS["KT"])], _passages(SHARE_PASSAGE))
    shares = [p for p in points if p["unit"] == "%"]

    assert {"KT 점유율(B)"} == {p["label"] for p in shares}
    assert 24.92 in [p["value"] for p in shares]
    assert "'25년 상반기" in [p["period"] for p in shares]


# ----------------------------------------------------------- C. comparison
def test_three_operators_on_one_shared_column_become_comparison_points():
    claims = [_claim(f"c{i}", row) for i, row in enumerate(SHARE_ROWS.values())]

    comparisons = analyzer_module._recovered_comparison_points(
        claims, _passages(SHARE_PASSAGE)
    )
    latest = [c for c in comparisons if "'25년 상반기" in c["criterion"] and "%" in c["value"]]

    assert {c["entity"] for c in latest} == {"KT", "SKB", "LGU+"}
    assert {c["criterion"] for c in latest} == {"점유율(B) '25년 상반기"}
    assert {c["value"] for c in latest} == {"24.92%", "18.68%", "15.50%"}


def test_a_single_row_never_invents_a_comparison():
    """One entity is not a comparison, however well-formed the table is."""
    claims = [_claim("c1", SHARE_ROWS["KT"])]

    assert analyzer_module._recovered_comparison_points(
        claims, _passages(SHARE_PASSAGE)
    ) == []


def test_comparison_recovery_needs_a_named_criterion():
    """The trend table's columns are periods only - nothing to compare on."""
    claims = [_claim("c1", TREND_ROW)]

    assert analyzer_module._recovered_comparison_points(
        claims, _passages(TREND_PASSAGE)
    ) == []


# ---------------------------------------------------------------- D. dedup
def test_the_same_table_row_seen_twice_is_not_counted_twice():
    """Both PDF chunks of one 보도자료 restate the same table."""
    claims = [_claim("c1", TREND_ROW), _claim("c2", TREND_ROW)]

    points = _recover(claims, _passages(TREND_PASSAGE))
    identities = {
        (p["label"], p["subject"], p["period"], p["unit"], p["value"]) for p in points
    }

    assert len(points) == len(identities)


def test_distinct_periods_of_one_series_are_never_deduped_away():
    points = _recover([_claim("c1", TREND_ROW)], _passages(TREND_PASSAGE))
    counts = [p for p in points if not p["is_relative"]]

    assert len({p["period"] for p in counts}) == 6


# ----------------------------------------------------------- E. provenance
def test_every_recovered_point_still_names_its_claim():
    points = _recover([_claim("c9", TREND_ROW)], _passages(TREND_PASSAGE))

    assert points
    assert {p["evidence_claim_id"] for p in points} == {"c9"}


def test_recovered_comparisons_still_name_their_claim():
    claims = [_claim(f"c{i}", row) for i, row in enumerate(SHARE_ROWS.values())]

    comparisons = analyzer_module._recovered_comparison_points(
        claims, _passages(SHARE_PASSAGE)
    )

    assert comparisons
    assert all(c["evidence_claim_id"] for c in comparisons)


# ------------------------------------------------------------- fallbacks
def test_prose_claims_still_go_through_the_sentence_parser():
    """The model's own well-formed sentences must not regress."""
    quote = "SK브로드밴드의 IPTV 시장 점유율은 2025년 상반기 기준 7.69%로 집계됐다."

    points = _recover([_claim("c1", quote)], _passages(quote))

    assert [p["value"] for p in points] == [7.69]
    assert points[0]["unit"] == "%"


def test_table_row_without_its_passage_loses_the_period_not_the_label():
    """No passage means no headers, so no period and no caption unit.

    The row's own structure still holds, which matters: falling back to the
    sentence parser here is precisely what produced '609 증감률'.
    """
    points = _recover([_claim("c1", TREND_ROW)], [])

    assert {p["subject"] for p in points} == {"IPTV"}
    assert {p["period"] for p in points} == {"시점 미상"}
    assert 21414521 in [p["value"] for p in points]
    assert [p for p in points if p["unit"] is None]


def test_row_is_matched_with_whitespace_collapsed():
    """A stored quote has been normalised; the passage line has not.

    Live-verified 2026-08-10: the quote read `| | IPTV (증감률) | …` where
    the passage still had `|  | IPTV …`, so an exact line match found no
    table, dropped the header rows, and every point of the six-period series
    came back as 시점 미상 - which is what the chart contract fails on.
    """
    collapsed = re.sub(r"\s+", " ", TREND_ROW)
    assert collapsed != TREND_ROW

    points = _recover([_claim("c1", collapsed)], _passages(TREND_PASSAGE))
    counts = [p for p in points if not p["is_relative"]]

    assert len({p["period"] for p in counts}) == 6
    assert "시점 미상" not in {p["period"] for p in counts}


# ------------------------------------------- serialized (non-pipe) table row
SERIALIZED_ROW = (
    "표 원문 행: 구 분=IPTV (증감률); 2022년=20,565,609 (1.79%); "
    "2023년=20,814,402 (1.21%); 2023년=21,003,615 (0.91%); "
    "2024년=21,149,096 (0.69%); 2024년=21,310,251 (0.76%); "
    "2025년=21,414,521 (0.49%)."
)


def test_serialized_table_row_is_read_as_a_table_not_a_sentence():
    """`표 원문 행: k=v; k=v` is the same row without its pipes.

    Live-verified 2026-08-10: with no leading `|` it fell to the sentence
    parser, which made one label out of the whole run of data cells -
    `1,149,096 (0.69%); 2024년=21,310,251 …`.
    """
    points = _recover([_claim("c1", SERIALIZED_ROW)], _passages(TREND_PASSAGE))
    counts = [p for p in points if not p["is_relative"]]

    assert [p["value"] for p in counts] == [
        20565609, 20814402, 21003615, 21149096, 21310251, 21414521,
    ]
    assert {p["subject"] for p in counts} == {"IPTV"}
    for point in points:
        assert ";" not in str(point["label"])
        assert not str(point["label"]).lstrip().startswith("1,149")


def test_serialized_row_takes_its_periods_from_its_own_headers():
    points = _recover([_claim("c1", SERIALIZED_ROW)], _passages(TREND_PASSAGE))
    counts = [p for p in points if not p["is_relative"]]

    assert [p["period"] for p in counts] == [
        "2022년", "2023년", "2023년", "2024년", "2024년", "2025년",
    ]


def test_a_data_run_never_becomes_a_criterion():
    """Numeric cells must not be promoted into a column name."""
    points = _recover([_claim("c1", SERIALIZED_ROW)], _passages(TREND_PASSAGE))

    for point in points:
        label = str(point["label"])
        assert not re.match(r"^[\d,]", label), label
        assert analyzer_module._semantically_complete_label(label, context="table")


# ----------------------------------------- 증감폭 is a row name in a table
DELTA_PASSAGE = """< 최근 3년간 가입자 수 및 전기 대비 증감률 > (단위: 단말장치・단자)

| 구 분 | 2022년 | 2023년 | 2024년 |
| --- | --- | --- | --- |
| 구 분 | 하반기 | 상반기 | 하반기 |
| 증감폭 (증감률) | 242,585 (0.67%) | 99,098 (0.27%) | 42,870 (0.12%) |"""

DELTA_ROW = "| 증감폭 (증감률) | 242,585 (0.67%) | 99,098 (0.27%) | 42,870 (0.12%) |"


def test_delta_row_name_survives_in_table_context():
    """"증감폭" is a dangling tail in prose and a row name in a table."""
    points = _recover([_claim("c1", DELTA_ROW)], _passages(DELTA_PASSAGE))

    assert points, "the 증감폭 row is real evidence and must not be dropped"
    assert {p["subject"] for p in points} == {"증감폭"}
    assert 242585 in [p["value"] for p in points]


def test_the_same_word_is_still_rejected_in_sentence_context():
    assert analyzer_module._semantically_complete_label("증감폭", context="table")
    assert not analyzer_module._semantically_complete_label("증감폭")
    assert not analyzer_module._semantically_complete_label("증감폭", context="sentence")


def test_table_context_never_rescues_a_real_fragment():
    """Widening for row names must not readmit the sentence-path failures."""
    for fragment in ("으로 전년 대비", "008억 원) 대비", "006가구 내", "609"):
        assert not analyzer_module._semantically_complete_label(fragment, context="table")
