"""Expected Impact: filled only where a source said what would follow.

The column was blank because nothing linked an action to an outcome. Before
that it was filled by pairing the Nth action with the Nth business_impact -
two independent lists lined up by position, which read as a finding while
carrying none. That was removed rather than replaced; this is the replacement.
"""

from __future__ import annotations

from common.contracts import ActionImpact, GeneratedReport, TrendSynthesis
from core.report_generator.generator import _verified_action_impacts
from reporting.dashboard_streamlit.components import action_impact_lookup

_ACTION = "AI 추천 서비스를 고도화한다 [doc_id=a:1]"
_SENTENCE = "AI 추천 고도화 시 이탈률이 5%p 낮아질 것으로 분석됐다."


def _synthesis(**overrides) -> TrendSynthesis:
    data = dict(
        request_id="r",
        sector_id="sk_broadband",
        recommended_actions=[_ACTION],
        evidence=[_SENTENCE],
    )
    data.update(overrides)
    return TrendSynthesis(**data)


def _raw(**overrides) -> dict:
    raw = {
        "action": "AI 추천 서비스를 고도화한다",
        "expected_impact": "이탈률 5%p 개선",
        "source_sentence": _SENTENCE,
    }
    raw.update(overrides)
    return raw


def test_an_impact_the_evidence_states_is_kept():
    impacts = _verified_action_impacts([_raw()], _synthesis())

    assert len(impacts) == 1
    assert impacts[0].expected_impact == "이탈률 5%p 개선"
    # The stored action keeps its doc_id marker so the row can still resolve
    # an evidence link.
    assert impacts[0].action == _ACTION
    assert impacts[0].evidence_quote == _SENTENCE


def test_an_impact_whose_sentence_is_not_in_the_evidence_is_dropped():
    """The single guard that keeps this from becoming invention."""
    raw = _raw(source_sentence="이탈률이 절반으로 줄어든다는 분석이 있다.")
    assert _verified_action_impacts([raw], _synthesis()) == []


def test_an_action_we_never_recommended_is_dropped():
    raw = _raw(action="요금제를 인하한다")
    assert _verified_action_impacts([raw], _synthesis()) == []


def test_restating_the_action_as_its_own_impact_is_dropped():
    """"AI 추천을 고도화한다" -> "AI 추천 고도화" says nothing about outcome."""
    raw = _raw(expected_impact="AI 추천 서비스를 고도화한다")
    assert _verified_action_impacts([raw], _synthesis()) == []


def test_one_impact_per_action():
    impacts = _verified_action_impacts([_raw(), _raw(expected_impact="다른 효과")], _synthesis())
    assert len(impacts) == 1


def test_no_impacts_is_the_normal_case():
    """Most sources recommend without saying what follows."""
    assert _verified_action_impacts([], _synthesis()) == []


def test_lookup_matches_the_action_with_or_without_its_marker():
    report = GeneratedReport(
        request_id="r", sector_id="sk_broadband", audience_id="practitioner",
        purpose_id="issue_response", title="t",
        action_impacts=[
            ActionImpact(action=_ACTION, expected_impact="이탈률 5%p 개선", evidence_quote=_SENTENCE)
        ],
    )

    lookup = action_impact_lookup(report)

    assert lookup["AI 추천 서비스를 고도화한다"] == "이탈률 5%p 개선"


def test_lookup_is_empty_when_the_report_has_no_links():
    report = GeneratedReport(
        request_id="r", sector_id="sk_broadband", audience_id="practitioner",
        purpose_id="issue_response", title="t",
    )
    assert action_impact_lookup(report) == {}
    assert action_impact_lookup(None) == {}
