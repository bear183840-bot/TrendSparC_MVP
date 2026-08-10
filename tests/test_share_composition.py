"""Composition eligibility and the derived remainder.

The exact-100 groups here are the 방송미디어통신위원회 유료방송 splits the
live run produced once share_of recovery landed.
"""
from common.block_shapes import (
    derived_share_remainder,
    has_share_split,
    latest_share_group,
    share_groups,
)
from common.contracts import MetricPoint

WHOLE = "유료방송 가입자 전체"


def _slice(subject, value, period="2025년 상반기", whole=WHOLE, **kwargs):
    base = dict(label=f"{subject} 점유율", subject=subject, period=period,
                value=value, unit="%", share_of=whole,
                evidence_claim_id=f"c-{subject}", doc_id="d1")
    base.update(kwargs)
    return MetricPoint(**base)


EXACT = [_slice("IPTV", 59.11), _slice("SO", 33.38), _slice("위성", 7.51)]
PREVIOUS = [_slice("IPTV", 58.60, "2024년 하반기"),
            _slice("SO", 33.75, "2024년 하반기"),
            _slice("위성", 7.65, "2024년 하반기")]


# ------------------------------------------------------- A/B. exact stays exact
def test_an_exact_hundred_group_is_composition_eligible():
    assert has_share_split(EXACT)
    groups = share_groups(EXACT)

    assert len(groups) == 1
    assert abs(sum(p.value for p in groups[0][1]) - 100.0) < 0.05


def test_an_exact_group_gets_no_remainder():
    assert derived_share_remainder(WHOLE, EXACT) is None


def test_a_rounding_gap_is_not_a_slice():
    """99.4 is rounding; a 0.6% "기타" wedge would be noise, not evidence."""
    almost = [_slice("IPTV", 59.0), _slice("SO", 33.0), _slice("위성", 7.4)]

    assert derived_share_remainder(WHOLE, almost) is None


# ------------------------------------------------------- C. partial gets one
def test_a_partial_share_yields_the_unnamed_rest():
    partial = [_slice("A", 40.0), _slice("B", 30.0)]

    other = derived_share_remainder(WHOLE, partial)

    assert other is not None
    assert other.value == 30.0
    assert other.subject == "기타"
    assert other.unit == "%"
    assert other.share_of == WHOLE
    assert other.period == "2025년 상반기"


def test_the_remainder_is_marked_as_calculated_not_read():
    other = derived_share_remainder(WHOLE, [_slice("A", 40.0), _slice("B", 30.0)])

    assert other.derived is True
    assert other.derivation == "100 - sum(known shares)"
    assert other.evidence_claim_id is None, "it must not look like a stated figure"


# ------------------------------------------------------- D~G. refusals
def test_no_named_whole_means_no_remainder():
    loose = [_slice("A", 40.0, whole=None), _slice("B", 30.0, whole=None)]

    assert derived_share_remainder("", loose) is None


def test_periods_must_agree():
    mixed = [_slice("A", 40.0, "2024년 하반기"), _slice("B", 30.0, "2025년 상반기")]

    assert derived_share_remainder(WHOLE, mixed) is None


def test_a_sum_over_one_hundred_is_not_a_composition():
    over = [_slice("A", 60.0), _slice("B", 50.0)]

    assert derived_share_remainder(WHOLE, over) is None
    assert share_groups(over) == []


def test_a_rest_the_source_already_named_is_not_recomputed():
    named = [_slice("A", 40.0), _slice("기타", 60.0)]

    assert derived_share_remainder(WHOLE, named) is None


def test_a_derived_slice_never_feeds_another_derivation():
    first = derived_share_remainder(WHOLE, [_slice("A", 40.0), _slice("B", 30.0)])

    assert derived_share_remainder(WHOLE, [_slice("A", 40.0), first]) is None


def test_non_percentage_slices_are_not_a_composition():
    counts = [_slice("A", 40.0, unit="명"), _slice("B", 30.0, unit="명")]

    assert derived_share_remainder(WHOLE, counts) is None


# ---------------------------------------------------------- H. provenance
def test_the_remainder_names_every_slice_it_was_subtracted_from():
    partial = [_slice("A", 40.0, doc_id="d1"), _slice("B", 30.0, doc_id="d2")]

    other = derived_share_remainder(WHOLE, partial)

    assert other.source_claim_ids == ["c-A", "c-B"]
    assert other.supporting_doc_ids == ["d1", "d2"]


# --------------------------------------------------------- I/J. period rank
def test_the_latest_composition_is_identifiable():
    groups = share_groups([*EXACT, *PREVIOUS])
    latest = latest_share_group(groups)

    assert latest is not None
    # share_groups() keys periods at year level, so the group is named by
    # its year - the ordering is what this asserts.
    assert latest[1][0].period.startswith("2025년")


def test_the_earlier_composition_is_not_discarded():
    """A 변화/추이 question needs both halves; only ordering is imposed."""
    groups = share_groups([*EXACT, *PREVIOUS])

    assert len(groups) == 2
    years = {g[1][0].period[:5] for g in groups}
    assert years == {"2024년", "2025년"}
