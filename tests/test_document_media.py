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

    monkeypatch.setattr(document_media.requests, "head", lambda *args, **kwargs: _Response())

    assert detect_document_media_type(
        "https://www.kmcc.go.kr/download.do?fileSeq=70246",
        "방송시장 보고서",
    ) == "application/pdf"
