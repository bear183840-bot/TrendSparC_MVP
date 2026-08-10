"""Which metrics reach a KPI card, and in what order."""
from common.block_shapes import rank_kpi_candidates
from common.contracts import MetricPoint

QUESTION = "IPTV 가입자 수 현황은?".split()


def _m(label, value, period, subject=None, unit="명", doc_id="d1"):
    return MetricPoint(label=label, value=value, period=period, unit=unit,
                       subject=subject, doc_id=doc_id)


# ------------------------------------------------------- 1. recency in-metric
def test_the_latest_reading_of_one_metric_wins():
    points = [_m("IPTV 가입자 수", 20565609, "2023년 상반기"),
              _m("IPTV 가입자 수", 21414521, "2025년 상반기")]

    ranked = rank_kpi_candidates(points, QUESTION)

    assert len(ranked) == 1
    assert ranked[0].value == 21414521


# --------------------------------------------- 2. relevance outranks recency
def test_a_newer_unrelated_metric_does_not_displace_the_asked_about_one():
    points = [_m("방송광고시장 규모", 39000, "2025년", unit="억원"),
              _m("IPTV 가입자 수", 21149096, "2024년 상반기")]

    ranked = rank_kpi_candidates(points, QUESTION)

    assert ranked[0].label == "IPTV 가입자 수", [p.label for p in ranked]


# --------------------------------------------------------- 3/4. diversity
def test_one_metrics_three_periods_do_not_fill_the_grid():
    points = [_m("IPTV 가입자 수", 1.0, "2023년 상반기"),
              _m("IPTV 가입자 수", 2.0, "2024년 상반기"),
              _m("IPTV 가입자 수", 3.0, "2025년 상반기")]

    ranked = rank_kpi_candidates(points, QUESTION)

    assert len(ranked) == 1, "the series belongs to a chart, not three cards"


def test_metrics_that_mean_different_things_all_stay():
    points = [_m("IPTV 가입자 수", 21414521, "2025년 상반기"),
              _m("IPTV 비중", 59.11, "2025년 상반기", unit="%"),
              _m("유료방송 전체 가입자", 36226100, "2025년 상반기")]

    ranked = rank_kpi_candidates(points, QUESTION)

    assert len(ranked) == 3
    assert len({p.label for p in ranked}) == 3


# ------------------------------------------------------------- 5. conflict
def test_a_metric_two_sources_disagree_about_is_left_out():
    points = [_m("IPTV 가입자 수", 21414521, "2025년 상반기", doc_id="a"),
              _m("IPTV 가입자 수", 21310000, "2025년 상반기", doc_id="b"),
              _m("IPTV 비중", 59.11, "2025년 상반기", unit="%")]

    ranked = rank_kpi_candidates(points, QUESTION)
    labels = {p.label for p in ranked}

    assert "IPTV 가입자 수" not in labels, "no first/latest/average winner"
    assert "IPTV 비중" in labels, "the untouched metric still shows"


def test_a_conflict_does_not_empty_the_row_of_everything_else():
    points = [_m("A", 1.0, "2025년 상반기", doc_id="a"),
              _m("A", 2.0, "2025년 상반기", doc_id="b"),
              _m("IPTV 가입자 수", 21414521, "2025년 상반기")]

    ranked = rank_kpi_candidates(points, QUESTION)

    assert [p.label for p in ranked] == ["IPTV 가입자 수"]


# ------------------------------------------------------ 6. DIRECT preserved
def test_the_asked_about_metric_is_never_dropped_by_the_limit():
    filler = [_m(f"기타 지표 {i}", float(i), "2025년 상반기") for i in range(10)]
    points = [*filler, _m("IPTV 가입자 수", 21414521, "2025년 상반기")]

    ranked = rank_kpi_candidates(points, QUESTION, limit=3)

    assert "IPTV 가입자 수" in {p.label for p in ranked}
    assert len(ranked) == 3


def test_no_question_still_returns_candidates():
    points = [_m("IPTV 가입자 수", 1.0, "2025년 상반기"), _m("IPTV 비중", 2.0, "2025년 상반기")]

    assert len(rank_kpi_candidates(points, [])) == 2


def test_an_empty_series_is_handled():
    assert rank_kpi_candidates([], QUESTION) == []


def test_a_broader_metric_does_not_outrank_the_one_actually_asked_about():
    """Both match "가입자 수"; only one is about IPTV.

    Live-verified 2026-08-10: "유료방송시장 전체 가입자 수 3,629만 (2023년)"
    led the row for the question "IPTV 가입자 수 현황은?" because relevance
    was a yes/no test and list order settled the tie.
    """
    points = [_m("유료방송시장 전체 가입자 수", 36290000, "2022년"),
              _m("IPTV 가입자 수", 20670000, "2022년"),
              _m("SO 가입자 수", 12680000, "2022년")]

    ranked = rank_kpi_candidates(points, QUESTION)

    assert ranked[0].label == "IPTV 가입자 수", [p.label for p in ranked]
    assert {p.label for p in ranked} == {p.label for p in points}, "nothing is dropped"
