from common.contracts import DocumentAnalysis
from core.synthesis.synthesizer import synthesize


def _analysis(doc_id, source_id, key_points=None):
    return DocumentAnalysis(doc_id=doc_id, source_id=source_id, key_points=key_points or [])


def test_synthesize_populates_doc_source_map():
    analyses = [
        _analysis("doc1", "전자신문"),
        _analysis("doc2", "SK브로드밴드 뉴스룸"),
    ]

    result = synthesize("req1", "sk_broadband", analyses)

    assert result.doc_source_map == {"doc1": "전자신문", "doc2": "SK브로드밴드 뉴스룸"}


def test_synthesize_falls_back_to_doc_id_prefix_when_source_id_missing():
    analyses = [DocumentAnalysis(doc_id="전자신문:abc123", source_id=None, key_points=["점"])]

    result = synthesize("req1", "sk_broadband", analyses)

    assert result.doc_source_map == {"전자신문:abc123": "전자신문"}


def test_synthesize_new_synthesis_fields_default_empty():
    result = synthesize("req1", "sk_broadband", [_analysis("doc1", "전자신문", ["점"])])

    assert result.corroborated_points == []
    assert result.uncorroborated_points == []
    assert result.contradictions == []
