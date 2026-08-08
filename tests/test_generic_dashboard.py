from types import SimpleNamespace

from common.contracts import DocumentAnalysis
from reporting.dashboard_streamlit.generic_dashboard import _item_markup, clean_citation, evidence_url


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


def test_item_markup_shows_the_single_source_badge_only_for_flagged_doc_ids():
    result = SimpleNamespace(document_analyses=[])

    flagged = _item_markup("단일 출처 주장 [doc_id=news:1]", result, 1, frozenset({"news:1"}))
    unflagged = _item_markup("교차검증된 주장 [doc_id=news:2]", result, 2, frozenset({"news:1"}))
    default = _item_markup("배지 인자 없이 호출", result, 3)

    assert "ts-badge-uncorroborated" in flagged
    assert "단일 출처" in flagged
    assert "ts-badge-uncorroborated" not in unflagged
    assert "ts-badge-uncorroborated" not in default
