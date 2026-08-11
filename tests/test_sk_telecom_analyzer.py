import json
import types

from common.contracts import SourceDocument
from sectors.sk_telecom.adapter import analyzer as analyzer_module


def _document(content="SK Telecom 5G subscribers reached 100 units in 2026."):
    return SourceDocument(doc_id="doc-1", source_id="telecom", title="Telecom update", url="https://example.com/a", content=content)


def _response(payload):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(payload), refusal=None))])


class _FakeOpenAI:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        return next(self.responses)


def _claim(quote):
    return {"claim_id": "c1", "claim_type": "key_point", "claim": "grounded claim", "evidence_passage_id": None, "evidence_quote": quote, "evidence_location": None, "as_of_date": None, "confidence": "high"}


def _analysis(claims):
    return _response({"summary": "summary", "relevance_level": "direct", "grounded_claims": claims, "metric_points": [], "comparison_points": [], "analysis_confidence": "high"})


def _wire(monkeypatch, responses):
    monkeypatch.setenv("TRENDSPARC_SK_TELECOM_ANALYZER_API_KEY", "test-key")
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda **_: _FakeOpenAI(responses))
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "prompt")
    monkeypatch.setattr(analyzer_module, "call_with_truncation_retry", lambda call, _: (call(4_500), False))


def test_analyzer_keeps_verbatim_quote(monkeypatch):
    quote = "SK Telecom 5G subscribers reached 100 units in 2026."
    _wire(monkeypatch, [_analysis([_claim(quote)])])
    result = analyzer_module.analyze([_document(quote)], "5G 가입자는?")[0]
    assert [claim.evidence_quote for claim in result.grounded_claims] == [quote]


def test_analyzer_repairs_one_failed_quote(monkeypatch):
    quote = "SK Telecom 5G subscribers reached 100 units in 2026."
    repair = _response({"repairs": [{"claim_id": "c1", "evidence_passage_id": "P001", "evidence_quote": quote}]})
    _wire(monkeypatch, [_analysis([_claim("incorrect quote")]), repair])
    result = analyzer_module.analyze([_document(quote)], "5G 가입자는?")[0]
    assert result.grounded_claims[0].evidence_quote == quote


def test_analyzer_drops_unrepairable_quote(monkeypatch):
    repair = _response({"repairs": [{"claim_id": "c1", "evidence_passage_id": None, "evidence_quote": None}]})
    _wire(monkeypatch, [_analysis([_claim("incorrect quote")]), repair])
    result = analyzer_module.analyze([_document()], "5G 가입자는?")[0]
    assert result.grounded_claims == []
    assert result.usable_for_synthesis is False
