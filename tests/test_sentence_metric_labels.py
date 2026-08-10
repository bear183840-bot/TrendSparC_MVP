"""Sentence-path label and subject extraction.

Fixtures are the literal malformed output the 2026-08-10 live runs put on
the dashboard, plus the source sentences that produced them.
"""
from sectors.sk_broadband.adapter import analyzer as analyzer_module

_complete = analyzer_module._semantically_complete_label


# ------------------------------------------------- A. malformed is rejected
def test_dangling_connective_is_not_a_label():
    """"…늘어난 것으로 전년 대비" left `으로 전년 대비` as the subject."""
    assert not _complete("으로 전년 대비")
    assert not _complete("으로 전년 대비 증감률")


def test_parenthetical_tail_is_not_a_label():
    """The split landed inside "(9,008억 원)" and kept its far end."""
    for fragment in ("008억 원) 대비", "009억 원) 대비", "910억 원) 대비"):
        assert not _complete(fragment)


def test_mid_number_fragment_is_not_a_label():
    assert not _complete("006가구 내")
    assert not _complete("609")
    assert not _complete("251 증감률")


def test_bare_clause_tail_is_not_a_label():
    assert not _complete("대비")
    assert not _complete("전년 대비")
    assert not _complete("증감률")


# ---------------------------------------------------- B. real names survive
def test_real_metric_names_are_accepted():
    for name in (
        "IPTV 가입자 수", "유료방송시장 전체 가입자 수", "IPTV ARPU",
        "SK브로드밴드", "KT", "LGU+", "2022년도 방송광고시장", "외주제작비 총규모",
    ):
        assert _complete(name), name


# ----------------------------------- C. the number itself must be preserved
def test_thousands_separators_are_not_clause_boundaries():
    """`9,008억 원` must stay whole; splitting it made `008억 원) 대비`."""
    text = "전체 채널제공 매출액은 9,008억 원 대비 5.1% 증가했다."
    position = text.index("5.1%")

    label = analyzer_module._metric_label_before(text, position, "수치")

    # The number may appear inside the label, but never cut open: the old
    # split produced the bare tail "008억 원) 대비".
    assert not label.startswith("008")
    assert "9,008억" in label or "008억" not in label
    assert analyzer_module._semantically_complete_label(label)


def test_comma_grouped_number_before_a_percentage_keeps_the_entity():
    text = "사업자별 가입자 수는 케이티(KT) 9,028,900(24.92%)"
    position = text.index("24.92%")

    label = analyzer_module._metric_label_before(text, position, "수치")

    assert label not in ("900", "028", "9")
    assert analyzer_module._semantically_complete_label(label)


def test_the_figure_itself_still_parses_out_of_a_grouped_number():
    """Protecting the span must not stop the value being read."""
    claim = {
        "claim_id": "c1", "claim_type": "metric",
        "claim": "2022년 방송광고시장 규모는 9,008억 원이다.",
        "evidence_quote": "2022년 방송광고시장 규모는 9,008억 원이다.",
        "evidence_passage_id": "P001",
    }
    points = analyzer_module._recovered_metric_points([claim], [])

    assert 9008 in [p["value"] for p in points]


# ------------------------------------------------ D. nothing malformed ships
def test_recovered_points_never_carry_a_fragment_subject():
    sentences = [
        "2022년도 전체 채널제공 매출액은 9,008억 원) 대비 5.1% 증가했다.",
        "전체 방송사업자의 외주제작비 총규모는 9,009억 원으로 전년 대비 7.3% 늘었다.",
        "2022년도 방송광고시장은 3,910억 원) 대비 3.2% 감소했다.",
    ]
    claims = [
        {"claim_id": f"c{i}", "claim_type": "metric", "claim": s,
         "evidence_quote": s, "evidence_passage_id": "P001"}
        for i, s in enumerate(sentences)
    ]

    points = analyzer_module._recovered_metric_points(claims, [])

    for point in points:
        assert analyzer_module._semantically_complete_label(str(point["label"])), point["label"]
        if point.get("subject") is not None:
            assert analyzer_module._semantically_complete_label(str(point["subject"])), point["subject"]
