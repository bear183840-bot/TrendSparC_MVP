"""The report writer's request has to fit the account's per-minute allowance.

Live-observed on a 롱폼/숏폼 run: 30,881 tokens against a 30,000 TPM limit,
a 429, and a silent fall back to the rule-based path - which also meant none
of the figures sitting in the evidence were ever structured. The request was
42,770 characters, half of it claims carrying evidence quotes that were
already in `evidence` verbatim.
"""

from __future__ import annotations

import json

from common.contracts import ReportPlan, SectionEvidenceRefs
from core.report_generator.generator import _fit_payload


def _payload(claims: int = 20, evidence: int = 20) -> dict:
    return {
        "question": "질문",
        "synthesis": {
            "grounded_claims": [
                {
                    "synthesis_claim_id": f"d1:c{index}", "claim_id": f"c{index}",
                    "claim_type": "key_point", "claim": f"주장 {index}",
                    "evidence_quote": "원문 인용 " * 30, "evidence_location": "문단 3",
                    "source_url": "https://example.com/very/long/path", "doc_id": "d1",
                    "source_id": "example.com", "confidence": "high",
                }
                for index in range(claims)
            ],
            "conclusions": [
                {"conclusion_id": f"rule:{index}", "conclusion": f"결론 {index}"}
                for index in range(5)
            ],
            "highlights": [f"하이라이트 {index} " + "내용 " * 20 for index in range(10)],
            "key_points": [f"핵심 {index} " + "내용 " * 20 for index in range(10)],
            "evidence": [f"근거 {index}: 이용률은 {index}0.5%였다." for index in range(evidence)],
            "metric_series": [
                {
                    "metric_id": f"m{index}", "label": "플랫폼 이용률",
                    "subject": f"플랫폼 {index}", "period": "2025년",
                    "value": index + 0.5, "unit": "%", "is_forecast": False,
                    "evidence_claim_id": f"c{index}",
                    "evidence_synthesis_claim_id": f"d1:c{index}",
                    "evidence_quote": "같은 근거 문장이 각 수치마다 반복된다. " * 20,
                    "doc_id": "d1", "source_id": "example.com",
                    "source_url": "https://example.com/very/long/path",
                }
                for index in range(evidence)
            ],
        },
    }


def _plan(referenced: list[str]) -> ReportPlan:
    return ReportPlan(
        request_id="r", audience_id="practitioner", primary_intent="current_status",
        sections=["overview"],
        section_evidence_map={"overview": SectionEvidenceRefs(claim_ids=referenced)},
    )


def test_a_claim_is_reduced_to_what_the_writer_reads():
    """Quotes, locations and urls are provenance the writer never uses - and
    the quote is already in `evidence` word for word."""
    payload = _payload()

    fitted = _fit_payload(payload, _plan([]), budget=10_000)
    claim = fitted["synthesis"]["grounded_claims"][0]

    assert set(claim) == {"synthesis_claim_id", "claim_type", "claim", "source_id"}


def test_rule_based_conclusions_are_dropped_because_they_restate_the_claims():
    payload = _payload()

    fitted = _fit_payload(payload, _plan([]), budget=10_000)

    assert fitted["synthesis"]["conclusions"] == []


def test_metrics_keep_chart_axes_but_do_not_repeat_evidence_and_urls():
    fitted = _fit_payload(_payload(evidence=20), _plan([]), budget=20_000)
    metric = fitted["synthesis"]["metric_series"][0]

    assert set(metric) == {
        "metric_id", "label", "subject", "period", "value", "unit",
        "is_forecast", "value_type", "evidence_synthesis_claim_id",
    }
    assert metric["label"] == "플랫폼 이용률"
    assert metric["subject"] == "플랫폼 0"


def test_relative_metric_keeps_only_its_small_provenance_extension():
    payload = _payload(evidence=1)
    payload["synthesis"]["metric_series"][0].update({
        "is_relative": True,
        "comparison_period": "전년 대비",
        "value_origin": "source",
    })

    metric = _fit_payload(payload, _plan([]), budget=20_000)["synthesis"]["metric_series"][0]

    assert metric["is_relative"] is True
    assert metric["comparison_period"] == "전년 대비"
    assert metric["value_origin"] == "source"


def test_evidence_survives_when_something_has_to_go():
    """Evidence is the text every figure is extracted from - a report that
    loses it loses its charts with it."""
    payload = _payload(claims=40, evidence=20)

    fitted = _fit_payload(payload, _plan([]), budget=4_000)
    synthesis = fitted["synthesis"]

    assert len(synthesis["evidence"]) >= 8
    assert synthesis["highlights"] == []
    assert len(json.dumps(fitted, ensure_ascii=False)) <= 4_200


def test_claims_the_section_map_names_are_the_last_to_be_dropped():
    payload = _payload(claims=20)
    referenced = ["d1:c17", "d1:c18", "d1:c19"]

    fitted = _fit_payload(payload, _plan(referenced), budget=3_000)
    kept = {claim["synthesis_claim_id"] for claim in fitted["synthesis"]["grounded_claims"]}

    assert set(referenced) <= kept or not kept


def test_nothing_is_cut_mid_sentence():
    """A truncated figure ("78.8" from "78.8%") is worse than an absent one:
    the verifier would reject it as unsupported, and the failure would read as
    a data problem rather than a size one."""
    payload = _payload(evidence=20)

    fitted = _fit_payload(payload, _plan([]), budget=3_000)

    for sentence in fitted["synthesis"]["evidence"]:
        assert sentence.endswith("였다.")
