"""One unusable document must not cost the report the other four.

Live-observed on a 롱폼/숏폼 run: five good sources were collected - a KOCCA
trend report, a 숏폼 이용률 ranking article, a survey piece - and the run
halted at the analyzer because one page's response came back off schema.
"""

from __future__ import annotations

import pytest

from common.contracts import SourceDocument
from common.errors import PipelineStageError
from sectors.sk_broadband.adapter import analyzer


def _document(doc_id: str) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id, source_id="example.com", url=f"https://example.com/{doc_id}",
        title=doc_id, content="본문", collected_at="2026-08-08",
    )


def _analysis(doc_id: str):
    from common.contracts import DocumentAnalysis

    return DocumentAnalysis(
        doc_id=doc_id, source_id="example.com", summary="요약", key_points=["핵심"],
        relevant_to_question=True,
    )


def test_a_document_that_fails_is_skipped_not_fatal(monkeypatch):
    monkeypatch.setattr(analyzer, "_api_key", lambda: "test-key")
    monkeypatch.setattr(analyzer, "OpenAI", lambda **_: object())
    monkeypatch.setattr(analyzer, "_load_system_prompt", lambda: "prompt")

    def fake_analyze(client, prompt, document, *args, **kwargs):
        if document.doc_id == "bad":
            raise PipelineStageError(stage="analyzer", reason="did not match the expected schema")
        return _analysis(document.doc_id)

    monkeypatch.setattr(analyzer, "_analyze_document", fake_analyze)

    analyses = analyzer.analyze(
        [_document("good1"), _document("bad"), _document("good2")], "질문"
    )

    assert [item.doc_id for item in analyses] == ["good1", "good2"]


def test_every_document_failing_is_still_a_stage_failure(monkeypatch):
    """Whether what survived is enough is decided downstream against the
    sector's minimum - but nothing surviving is this stage's own failure."""
    monkeypatch.setattr(analyzer, "_api_key", lambda: "test-key")
    monkeypatch.setattr(analyzer, "OpenAI", lambda **_: object())
    monkeypatch.setattr(analyzer, "_load_system_prompt", lambda: "prompt")

    def always_fail(client, prompt, document, *args, **kwargs):
        raise PipelineStageError(stage="analyzer", reason=f"{document.doc_id} broke")

    monkeypatch.setattr(analyzer, "_analyze_document", always_fail)

    with pytest.raises(PipelineStageError) as caught:
        analyzer.analyze([_document("a"), _document("b")], "질문")

    assert "no document could be analysed" in caught.value.reason
    # Every document's own error is carried, not only the first.
    assert "a broke" in caught.value.detail and "b broke" in caught.value.detail
