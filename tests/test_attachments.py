import base64

from common.contracts import Attachment
from core.attachments.extractor import build_question_context, extract_attachments


def test_text_attachment_becomes_first_class_source_document():
    body = "첨부 보고서의 핵심 근거입니다. " * 30
    attachment = Attachment(
        attachment_id="a1",
        filename="briefing.txt",
        content_type="text/plain",
        content_base64=base64.b64encode(body.encode()).decode(),
    )

    documents, results = extract_attachments([attachment])

    assert results[0].status == "extracted"
    assert documents[0].source_id == "attachment:briefing.txt"
    assert documents[0].content == body.strip()
    assert "briefing.txt" in build_question_context("무엇이 중요한가?", documents)


def test_unsupported_attachment_is_reported_without_fabricating_document():
    attachment = Attachment(
        attachment_id="a2",
        filename="archive.zip",
        content_base64=base64.b64encode(b"not a document").decode(),
    )

    documents, results = extract_attachments([attachment])

    assert documents == []
    assert results[0].status == "unsupported"
