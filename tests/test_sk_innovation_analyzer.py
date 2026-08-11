"""Grounding behaviour shared by the SK Innovation analyzer's API boundary."""

import json
import types

from common.contracts import SourceDocument
from sectors.sk_innovation.adapter import analyzer as analyzer_module


def _document(content="SK On battery demand reached 100 units in 2026."):
    return SourceDocument(
        doc_id="doc-1",
        source_id="innovation",
        title="Battery update",
        url="https://example.com/a",
        content=content,
    )


def _analysis_response(claims, *, metrics=None):
    payload = {
        "summary": "summary",
        "relevance_level": "direct",
        "grounded_claims": claims,
        "metric_points": metrics or [],
        "comparison_points": [],
        "analysis_confidence": "high",
    }
    message = types.SimpleNamespace(content=json.dumps(payload), refusal=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _repair_response(repairs):
    message = types.SimpleNamespace(
        content=json.dumps({"repairs": repairs}), refusal=None
    )
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FakeOpenAI:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        return next(self.responses)


def _claim(quote, claim_id="c1", claim_type="key_point"):
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "claim": "grounded claim",
        "evidence_passage_id": None,
        "evidence_quote": quote,
        "evidence_location": None,
        "as_of_date": None,
        "confidence": "high",
    }


def _wire(monkeypatch, responses):
    monkeypatch.setenv("TRENDSPARC_SK_INNOVATION_ANALYZER_API_KEY", "test-key")
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda **_: _FakeOpenAI(responses))
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "prompt")
    monkeypatch.setattr(
        analyzer_module,
        "call_with_truncation_retry",
        lambda call, _: (call(4_500), False),
    )


def test_analyzer_keeps_verbatim_quote(monkeypatch):
    quote = "SK On battery demand reached 100 units in 2026."
    _wire(monkeypatch, [_analysis_response([_claim(quote)])])

    result = analyzer_module.analyze([_document(quote)], "배터리 수요는?")[0]

    assert [claim.evidence_quote for claim in result.grounded_claims] == [quote]
    assert result.analysis_validation_status == "verified"


def test_analyzer_repairs_one_failed_quote(monkeypatch):
    quote = "SK On battery demand reached 100 units in 2026."
    _wire(
        monkeypatch,
        [
            _analysis_response([_claim("incorrect quote")]),
            _repair_response(
                [
                    {
                        "claim_id": "c1",
                        "evidence_passage_id": "P001",
                        "evidence_quote": quote,
                    }
                ]
            ),
        ],
    )

    result = analyzer_module.analyze([_document(quote)], "배터리 수요는?")[0]

    assert result.grounded_claims[0].evidence_quote == quote


def test_analyzer_drops_unrepairable_quote(monkeypatch):
    _wire(
        monkeypatch,
        [
            _analysis_response([_claim("incorrect quote")]),
            _repair_response(
                [
                    {
                        "claim_id": "c1",
                        "evidence_passage_id": None,
                        "evidence_quote": None,
                    }
                ]
            ),
        ],
    )

    result = analyzer_module.analyze([_document()], "배터리 수요는?")[0]

    assert result.grounded_claims == []
    assert result.usable_for_synthesis is False
