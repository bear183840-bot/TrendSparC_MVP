"""Comparisons the model stated and comparisons a table proves, together."""
from common.contracts import ComparisonPoint
from common.metric_identity import (
    comparison_identity,
    conflicting_comparison_groups,
    normalize_comparison_points,
)
from sectors.sk_broadband.adapter import analyzer as analyzer_module

SHARE_PASSAGE = """< 사업자별 시장점유율 > (단위: 단말장치・단자)

| 구 분 | '25년 상반기 | '25년 상반기 |
| --- | --- | --- |
| 구 분 | 가입자 수 | 점유율 |
| KT | 9,028,900 | 25.24% |
| SKB | 6,768,835 | 26.11% |
| LGU+ | 5,616,786 | 15.82% |"""

ROWS = {
    "KT": "| KT | 9,028,900 | 25.24% |",
    "SKB": "| SKB | 6,768,835 | 26.11% |",
    "LGU+": "| LGU+ | 5,616,786 | 15.82% |",
}


def _claim(quote, claim_id):
    return {"claim_id": claim_id, "claim_type": "comparison", "claim": quote,
            "evidence_quote": quote, "evidence_passage_id": "P001"}


def _cmp(entity, criterion, value, **kwargs):
    base = dict(entity=entity, criterion=criterion, value=value, doc_id="d1")
    base.update(kwargs)
    return ComparisonPoint(**base)


# ------------------------------------------------------------- A. additive
def test_a_model_comparison_no_longer_suppresses_the_tables_own():
    """One ARPU row used to hide the whole three-operator 점유율 table."""
    model = [_cmp("SO", "ARPU", "8,799원")]
    recovered = analyzer_module._recovered_comparison_points(
        [_claim(row, f"c{i}") for i, row in enumerate(ROWS.values())],
        [{"passage_id": "P001", "text": SHARE_PASSAGE}],
    )

    final = normalize_comparison_points([*model, *recovered])
    entities = {c["entity"] if isinstance(c, dict) else c.entity for c in final}

    assert len(recovered) >= 3
    assert {"KT", "SKB", "LGU+"} <= entities
    assert "SO" in entities, "the model's own comparison must survive"
    assert len(final) >= 4


# --------------------------------------------------------- B/C. dedup vs conflict
def test_the_same_row_from_both_sources_becomes_one():
    both = [_cmp("KT", "IPTV 점유율", "25.24%", doc_id="ai"),
            _cmp("KT", "IPTV 점유율", "25.24%", doc_id="table")]

    final = normalize_comparison_points(both)

    assert len(final) == 1
    assert final[0].supporting_doc_ids == ["ai", "table"]


def test_a_disagreement_is_never_silently_resolved():
    both = [_cmp("KT", "IPTV 점유율", "25.24%", doc_id="ai"),
            _cmp("KT", "IPTV 점유율", "24.90%", doc_id="table")]

    final = normalize_comparison_points(both)

    assert len(final) == 2
    assert len(conflicting_comparison_groups(both)) == 1


# ------------------------------------------------------- D/E/F. separate rows
def test_a_different_period_is_a_different_criterion():
    """Table recovery bakes the period into `criterion`."""
    rows = [_cmp("KT", "점유율 '24년 하반기", "24.74%"),
            _cmp("KT", "점유율 '25년 상반기", "25.24%")]

    assert comparison_identity(rows[0]) != comparison_identity(rows[1])
    assert len(normalize_comparison_points(rows)) == 2


def test_different_criteria_stay_separate():
    rows = [_cmp("KT", "IPTV 점유율", "25.24%"), _cmp("KT", "ARPU", "29,202원")]

    assert len(normalize_comparison_points(rows)) == 2


def test_different_entities_stay_separate():
    rows = [_cmp("KT", "IPTV 점유율", "25.24%"), _cmp("SKB", "IPTV 점유율", "26.11%")]

    assert len(normalize_comparison_points(rows)) == 2


# ------------------------------------------------------ G. mismatch refused
def test_a_single_row_table_yields_no_comparison():
    single = "| KT | 9,028,900 | 25.24% |"
    passage = "< 점유율 >\n\n| 구 분 | '25년 상반기 |\n| --- | --- |\n| 구 분 | 점유율 |\n" + single

    assert analyzer_module._recovered_comparison_points(
        [_claim(single, "c1")], [{"passage_id": "P001", "text": passage}]
    ) == []


# --------------------------------------------------------- J. levels survive
def test_a_qualitative_level_comparison_is_preserved():
    rows = [_cmp("SKB", "브랜드 적합성", "높음", level="high"),
            _cmp("KT", "브랜드 적합성", "보통", level="medium")]

    final = normalize_comparison_points(rows)

    assert len(final) == 2
    assert {c.level for c in final} == {"high", "medium"}


def test_the_same_criterion_at_two_levels_is_a_conflict_not_a_merge():
    rows = [_cmp("SKB", "브랜드 적합성", "높음", level="high", doc_id="a"),
            _cmp("SKB", "브랜드 적합성", "보통", level="medium", doc_id="b")]

    assert len(normalize_comparison_points(rows)) == 2


# ------------------------------------------------------------ L. provenance
def test_recovered_comparisons_keep_their_claim():
    recovered = analyzer_module._recovered_comparison_points(
        [_claim(row, f"c{i}") for i, row in enumerate(ROWS.values())],
        [{"passage_id": "P001", "text": SHARE_PASSAGE}],
    )

    assert recovered
    assert all(c["evidence_claim_id"] for c in recovered)


def test_merging_never_drops_a_source():
    rows = [_cmp("KT", "점유율", "25.24%", doc_id="d1", source_url="u1"),
            _cmp("KT", "점유율", "25.24%", doc_id="d2", source_url="u2")]

    merged = normalize_comparison_points(rows)[0]

    assert merged.supporting_doc_ids == ["d1", "d2"]
    assert merged.supporting_source_urls == ["u1", "u2"]
    assert merged.doc_id == "d1"


# --------------------------------------------- K. composition left untouched
def test_additive_recovery_does_not_touch_share_semantics():
    """A share group is metric-side; comparisons must not duplicate it."""
    from common.block_shapes import share_groups
    from common.contracts import MetricPoint

    slices = [
        MetricPoint(label="IPTV 점유율", subject="IPTV", period="2025년 상반기",
                    value=59.11, unit="%", share_of="유료방송 전체"),
        MetricPoint(label="SO 점유율", subject="SO", period="2025년 상반기",
                    value=33.38, unit="%", share_of="유료방송 전체"),
    ]

    assert len(share_groups(slices)) == 1
