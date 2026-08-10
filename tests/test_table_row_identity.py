"""Which column names the row, when a table leads with two of them.

유료방송 사업자별 rows read `| IPTV (3개) | KT | 9,123,463 | 25.24% |`. The
first column groups operators by delivery type; the second is the operator.
Taking the first made KT, SK브로드밴드 and LG유플러스 all come back as
`subject="IPTV"` - five distinct operators as one entity - so the ranking
had no two entities to compare, `comparison_points` came back empty, and the
경쟁구도 card showed a sentence where a bar chart belonged.

The rule is not "take the second column". It is "take the last leading
column the table's own header names", so a table with one label column is
read exactly as before.
"""
from __future__ import annotations

from sectors.sk_broadband.adapter.analyzer import (
    _split_table_cells,
    _table_row_label,
    _table_row_points,
)

# The real 보도자료 table, headers and all.
OPERATOR_TABLE = "\n".join([
    "< 유료방송 사업자별 가입자 수 및 시장점유율 > (단위: 단말장치・단자)",
    "",
    "| 구 분 | 유료방송 사업자 | '25년 상반기 | '25년 상반기 | '25년 하반기 | '25년 하반기 |",
    "| --- | --- | --- | --- | --- | --- |",
    "| 구 분 | 유료방송 사업자 | 가입자수 | 점유율 (A) | 가입자수 | 점유율 (B) |",
    "| IPTV (3개) | KT | 9,028,900 | 24.92% | 9,123,463 | 25.24% |",
    "| IPTV (3개) | SK브로드밴드 | 6,768,835 | 18.68% | 6,691,354 | 18.51% |",
    "| IPTV (3개) | LG유플러스 | 5,616,786 | 15.50% | 5,720,439 | 15.82% |",
])

MEDIA_TABLE = "\n".join([
    "< '25년도 하반기 가입자 수 및 시장점유율 > (단위: 단말장치・단자)",
    "",
    "| 구 분 | '25년 상반기 | '25년 상반기 | '25년 하반기 | '25년 하반기 |",
    "| --- | --- | --- | --- | --- |",
    "| 구 분 | 가입자 수 | 점유율(A) | 가입자 수 | 점유율(B) |",
    "| IPTV | 21,414,521 | 59.11% | 21,535,256 | 59.57% |",
    "| SO | 12,091,056 | 33.38% | 11,935,236 | 33.01% |",
    "| 합계 | 36,226,100 | - | 36,150,070 | - |",
])


def _row(table: str, needle: str) -> str:
    return next(line for line in table.splitlines() if needle in line and line.startswith("|"))


def _points(table: str, needle: str):
    claim = {"claim_id": "c1", "claim_type": "metric", "evidence_quote": _row(table, needle)}
    return _table_row_points(claim, table, table)


# --- the label column itself --------------------------------------------


def test_the_header_decides_which_leading_column_is_the_row():
    cells = _split_table_cells(_row(OPERATOR_TABLE, "KT |"))
    criteria = ["", "유료방송 사업자", "가입자수", "점유율 (A)", "가입자수", "점유율 (B)"]

    assert _table_row_label(cells, criteria)[0] == "KT"


def test_a_grouping_column_with_only_filler_above_it_never_wins():
    """`구 분` names no column, so the column under it is not the row."""
    cells = _split_table_cells(_row(OPERATOR_TABLE, "SK브로드밴드"))
    criteria = ["구 분", "유료방송 사업자", "가입자수", "점유율 (A)", "", ""]

    assert _table_row_label(cells, criteria)[0] == "SK브로드밴드"


def test_one_label_column_is_read_exactly_as_before():
    cells = _split_table_cells(_row(MEDIA_TABLE, "| IPTV |"))

    assert _table_row_label(cells, ["구 분", "가입자 수", "점유율(A)", "", ""])[0] == "IPTV"


def test_without_headers_the_first_column_still_names_the_row():
    """A serialized or header-less row must not change meaning."""
    cells = _split_table_cells(_row(OPERATOR_TABLE, "LG유플러스"))

    assert _table_row_label(cells, None)[0] == "IPTV"
    assert _table_row_label(cells, [])[0] == "IPTV"


def test_a_wrapped_merged_cell_is_not_an_entity():
    """`-0.10%p<br>-` stopped reading as digits once the markup survived."""
    cells = _split_table_cells("| -0.10%p<br>- | 2,720,523 | 7.51% |")

    assert _table_row_label(cells, ["구 분", "가입자수", "점유율"]) is None


# --- what that changes downstream ---------------------------------------


def test_each_operator_row_carries_its_own_subject():
    subjects = {
        _points(OPERATOR_TABLE, needle)[0][0]["subject"]
        for needle in ("KT |", "SK브로드밴드", "LG유플러스")
    }

    assert subjects == {"KT", "SK브로드밴드", "LG유플러스"}


def test_the_ranking_becomes_comparable_points():
    """Three entities on one shared criterion - the shape a bar block needs."""
    comparisons = [
        point
        for needle in ("KT |", "SK브로드밴드", "LG유플러스")
        for point in _points(OPERATOR_TABLE, needle)[1]
    ]
    latest = [c for c in comparisons if "점유율 (B)" in c["criterion"]]

    assert {c["entity"] for c in latest} == {"KT", "SK브로드밴드", "LG유플러스"}
    assert {c["value"] for c in latest} == {"25.24%", "18.51%", "15.82%"}


def test_the_period_stays_the_one_the_column_stated():
    comparisons = _points(OPERATOR_TABLE, "KT |")[1]

    assert all("'25년" in point["criterion"] for point in comparisons)


def test_a_single_label_table_still_compares_its_media_types():
    comparisons = [
        point for needle in ("| IPTV |", "| SO |")
        for point in _points(MEDIA_TABLE, needle)[1]
    ]

    assert {point["entity"] for point in comparisons} == {"IPTV", "SO"}
