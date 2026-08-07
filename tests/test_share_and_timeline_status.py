"""The last two contract gaps: a share of a whole, and where a step stands.

Both were left unbuilt because the honest version needs a condition the data
didn't carry. A donut asserts its slices are the whole, and a plain
percentage never says whether it is one; a timeline that marks a row 완료 is
asserting something no date alone proves.
"""

from __future__ import annotations

from common.block_shapes import (
    has_share_split,
    share_groups,
    timeline_entries_with_status,
    timeline_status,
)
from common.contracts import MetricPoint


def _share(subject: str, value: float, whole: str | None, unit: str = "%") -> MetricPoint:
    return MetricPoint(label="시청 비중", subject=subject, period="2025년", value=value,
                       unit=unit, share_of=whole)


def test_percentages_of_one_stated_whole_are_a_split():
    points = [_share("IPTV", 45, "스포츠 시청자"), _share("OTT", 31, "스포츠 시청자")]

    (whole, slices), = share_groups(points)

    assert whole == "스포츠 시청자"
    assert [point.subject for point in slices] == ["IPTV", "OTT"]


def test_overlapping_survey_answers_are_not_a_split():
    """"62%가 유튜브, 55%가 넷플릭스" is two overlapping groups. Summing past
    100 is the arithmetic that catches it."""
    assert has_share_split(
        [_share("유튜브", 62, "이용자"), _share("넷플릭스", 55, "이용자")]
    ) is False


def test_percentages_with_no_stated_whole_stay_bars():
    """Without the framing, two percentages could be measured over different
    bases - so nothing may be drawn as one circle."""
    assert has_share_split([_share("IPTV", 45, None), _share("OTT", 31, None)]) is False


def test_a_non_percentage_is_never_a_slice():
    assert has_share_split(
        [_share("IPTV", 45, "스포츠 시청자", unit="만명"),
         _share("OTT", 31, "스포츠 시청자", unit="만명")]
    ) is False


def test_an_incomplete_split_says_so_instead_of_inventing_a_remainder(monkeypatch):
    from reporting.dashboard_streamlit import components

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))

    components.render_share_split([_share("IPTV", 45, "스포츠 시청자"), _share("OTT", 31, "스포츠 시청자")])
    body = "".join(captured)

    assert "24%는 출처에 명시되지 않았습니다" in body
    assert "기타" not in body


def test_a_stated_word_decides_the_state_whatever_the_date_says():
    as_of = "2026-08-01"

    assert timeline_status("2024년부터 제휴를 추진 중이다", "2024년", as_of) == "active"
    assert timeline_status("2025년 하반기 출시 예정", "2025년", as_of) == "todo"
    assert timeline_status("2024년 서비스를 출시했다", "2024년", as_of) == "done"


def test_the_date_only_decides_when_the_sentence_says_nothing():
    as_of = "2026-08-01"

    assert timeline_status("가입자가 682만명을 기록", "2027년", as_of) == "todo"
    assert timeline_status("가입자가 682만명을 기록", "2024년", as_of) == "done"


def test_an_undated_unmarked_row_is_never_called_finished():
    """A dated statement with no completion word is something that was
    reported. Marking it 완료 is the one reading nothing supports."""
    assert timeline_status("가입자가 682만명을 기록", "2026년", None) == "active"


def test_rows_carry_their_state_through_to_the_renderer(monkeypatch):
    from reporting.dashboard_streamlit import components

    evidence = ["2025년 3분기 프로야구 중계권을 확보했다.", "2027년 1분기 신규 요금제를 출시할 예정이다."]
    entries = timeline_entries_with_status(evidence, [], 2026, "2026-08-01")

    assert [status for _, _, status in entries] == ["done", "todo"]

    captured: list[str] = []
    monkeypatch.setattr(components.st, "markdown", lambda body, **_: captured.append(body))
    components.render_timeline(evidence, [], 2026, as_of_date="2026-08-01")
    body = "".join(captured)

    assert "예정" in body and "완료" in body
