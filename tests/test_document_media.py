import types

from sources.collectors import document_media
from sources.collectors.document_media import (
    detect_document_media_type,
    response_media_type,
)


def test_reads_pdf_media_type_from_firecrawl_metadata():
    response = types.SimpleNamespace(
        metadata=types.SimpleNamespace(contentType="application/pdf; charset=binary")
    )

    assert response_media_type(response) == "application/pdf"


def test_extensionless_download_url_uses_response_headers(monkeypatch):
    class _Response:
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": 'attachment; filename="policy-report.pdf"',
        }
        url = "https://www.kmcc.go.kr/download.do?fileSeq=70246"

    def _no_body_fetch(*args, **kwargs):
        raise AssertionError("a header probe must not download the file body")

    monkeypatch.setattr(document_media.requests, "head", lambda *args, **kwargs: _Response())
    # The HEAD headers already answer the question. Any GET here means the
    # probe fell through and is fetching the whole document to re-learn it -
    # which is also how this test used to reach the live site and pass only
    # because that site really does serve a PDF.
    monkeypatch.setattr(document_media.requests, "get", _no_body_fetch)

    assert detect_document_media_type(
        "https://www.kmcc.go.kr/download.do?fileSeq=70246",
        "방송시장 보고서",
    ) == "application/pdf"


def test_quoted_pdf_filename_in_content_disposition_is_recognised():
    """RFC 6266's usual form quotes the filename; the URL suffix pattern does
    not match it, and treating that miss as "not a PDF" costs a full download."""
    assert document_media._pdf_from_headers({
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="policy-report.pdf"',
    }) == "application/pdf"
    assert document_media._pdf_from_headers({
        "Content-Type": "application/octet-stream",
        "Content-Disposition": "attachment; filename=policy-report.pdf",
    }) == "application/pdf"
    # A name that merely contains "pdf" is still not a PDF.
    assert document_media._pdf_from_headers({
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="pdf-guide.hwp"',
    }) == "application/octet-stream"
