from types import SimpleNamespace

from common.contracts import DocumentAnalysis
from reporting.dashboard_streamlit.generic_dashboard import clean_citation, evidence_url


def test_clean_citation_removes_internal_doc_id_from_user_facing_text():
    assert clean_citation("HBM 수요가 증가했습니다. [doc_id=news:1]") == "HBM 수요가 증가했습니다."


def test_evidence_url_uses_exact_document_url_only_when_doc_id_is_present():
    result = SimpleNamespace(
        document_analyses=[
            DocumentAnalysis(
                doc_id="news:1",
                source_id="네이버 뉴스",
                source_url="https://example.com/article/1",
            )
        ]
    )

    assert evidence_url("근거 문장 [doc_id=news:1]", result) == "https://example.com/article/1"
    assert evidence_url("근거 표시가 없는 문장", result) is None
