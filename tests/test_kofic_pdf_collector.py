from sources.collectors.kofic_pdf import (
    KOFIC_DOWNLOAD_ENDPOINT,
    KoficAttachment,
    download_pdf_bytes,
    extract_pdf_attachments,
)


def test_extract_pdf_attachments_from_kofic_download_call():
    html = """
    <a onclick="fn_fileDownload('1' ,'/kofic/uploadFile/attachFile/202507' , 'dc60a211d6e8457693038bb735222a14.pdf',  '2025년 상반기 한국 영화산업 결산 보고서.pdf')">
      다운로드
    </a>
    """

    attachments = extract_pdf_attachments(html)

    assert len(attachments) == 1
    assert attachments[0].attach_seq_number == "1"
    assert attachments[0].file_url == "/kofic/uploadFile/attachFile/202507"
    assert attachments[0].file_name == "dc60a211d6e8457693038bb735222a14.pdf"
    assert attachments[0].download_name == "2025년 상반기 한국 영화산업 결산 보고서.pdf"


def test_extract_pdf_attachments_ignores_non_pdf_files():
    html = """
    <a onclick="fn_fileDownload('2' ,'/kofic/uploadFile/attachFile/202507' , 'image.png',  'preview.png')">
      다운로드
    </a>
    """

    assert extract_pdf_attachments(html) == []


def test_download_pdf_bytes_posts_to_kofic_download_endpoint(monkeypatch):
    calls = []

    class FakeResponse:
        content = b"%PDF-1.7 fake pdf"

        def raise_for_status(self):
            return None

    def fake_post(url, data, headers, timeout):
        calls.append(
            {
                "url": url,
                "data": data,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr("sources.collectors.kofic_pdf.requests.post", fake_post)
    attachment = KoficAttachment(
        attach_seq_number="1",
        file_url="/kofic/uploadFile/attachFile/202507",
        file_name="dc60a211d6e8457693038bb735222a14.pdf",
        download_name="2025년 상반기 한국 영화산업 결산 보고서.pdf",
    )

    pdf_bytes = download_pdf_bytes(
        attachment,
        referer_url="https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=69184",
        timeout_seconds=12,
    )

    assert pdf_bytes.startswith(b"%PDF-")
    assert calls == [
        {
            "url": KOFIC_DOWNLOAD_ENDPOINT,
            "data": {
                "fileUrl": "/kofic/uploadFile/attachFile/202507",
                "fileNm": "dc60a211d6e8457693038bb735222a14.pdf",
                "dnFileName": "2025년 상반기 한국 영화산업 결산 보고서.pdf",
            },
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.kofic.or.kr/kofic/business/board/selectBoardDetail.do?boardNumber=2&boardSeqNumber=69184",
            },
            "timeout": 12,
        }
    ]


def test_download_pdf_bytes_rejects_non_pdf_response(monkeypatch):
    class FakeResponse:
        content = b"<html>not pdf</html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "sources.collectors.kofic_pdf.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )
    attachment = KoficAttachment(
        attach_seq_number="1",
        file_url="/kofic/uploadFile/attachFile/202507",
        file_name="dc60a211d6e8457693038bb735222a14.pdf",
        download_name="2025년 상반기 한국 영화산업 결산 보고서.pdf",
    )

    try:
        download_pdf_bytes(attachment)
    except ValueError as exc:
        assert "not a PDF" in str(exc)
    else:
        raise AssertionError("download_pdf_bytes should reject non-PDF responses")
