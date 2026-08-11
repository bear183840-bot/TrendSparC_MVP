import json
import types

from common.contracts import SourceDocument
from sectors.sk_hynix.adapter import analyzer as analyzer_module


def _document(content="HBM demand reached 100 units in 2026."):
    return SourceDocument(doc_id="doc-1", source_id="hynix", title="Memory update", url="https://example.com/a", content=content)


def _analysis_response(claims, *, metrics=None, comparisons=None):
    payload = {"summary": "summary", "relevance_level": "direct", "grounded_claims": claims, "metric_points": metrics or [], "comparison_points": comparisons or [], "analysis_confidence": "high"}
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(payload), refusal=None))])


def _repair_response(repairs):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({"repairs": repairs}), refusal=None))])


class _FakeOpenAI:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        return next(self.responses)


def _claim(quote, claim_id="c1", claim_type="key_point"):
    return {"claim_id": claim_id, "claim_type": claim_type, "claim": "grounded claim", "evidence_passage_id": None, "evidence_quote": quote, "evidence_location": None, "as_of_date": None, "confidence": "high"}


def _wire(monkeypatch, responses):
    monkeypatch.setenv("TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY", "test-key")
    monkeypatch.setattr(analyzer_module, "OpenAI", lambda **_: _FakeOpenAI(responses))
    monkeypatch.setattr(analyzer_module, "_load_system_prompt", lambda: "prompt")
    monkeypatch.setattr(analyzer_module, "call_with_truncation_retry", lambda call, _: (call(4500), False))


def test_analyzer_keeps_first_pass_verbatim_quote(monkeypatch):
    quote = "HBM demand reached 100 units in 2026."
    _wire(monkeypatch, [_analysis_response([_claim(quote)])])

    result = analyzer_module.analyze([_document(quote)], "HBM demand?")[0]

    assert [claim.evidence_quote for claim in result.grounded_claims] == [quote]
    assert result.analysis_validation_status == "verified"


def test_analyzer_repairs_one_failed_quote(monkeypatch):
    quote = "HBM demand reached 100 units in 2026."
    _wire(monkeypatch, [_analysis_response([_claim("incorrect quote")]), _repair_response([{"claim_id": "c1", "evidence_passage_id": "P001", "evidence_quote": quote}])])

    result = analyzer_module.analyze([_document(quote)], "HBM demand?")[0]

    assert result.grounded_claims[0].evidence_quote == quote


def test_analyzer_drops_quote_when_repair_is_not_grounded(monkeypatch):
    _wire(monkeypatch, [_analysis_response([_claim("incorrect quote")]), _repair_response([{"claim_id": "c1", "evidence_passage_id": None, "evidence_quote": None}])])

    result = analyzer_module.analyze([_document()], "HBM demand?")[0]

    assert result.grounded_claims == []
    assert result.usable_for_synthesis is False


def test_analyzer_chunks_and_merges_long_document(monkeypatch):
    first = "HBM demand reached 100 units in 2026."
    second = "Capacity investment reached 200 units in 2026."
    content = first + "x" * 12_100 + "\n\n" + second
    _wire(monkeypatch, [_analysis_response([_claim(first, "first")]), _analysis_response([_claim(second, "second", "metric")], metrics=[{"label": "capacity", "period": "2026", "value": 200, "unit": "units", "subject": None, "is_relative": False, "comparison_period": None, "evidence_claim_id": "second"}])])

    result = analyzer_module.analyze([_document(content)], "HBM capacity?")[0]

    assert len(result.grounded_claims) == 2
    assert result.metric_points[0].evidence_claim_id == "second"
