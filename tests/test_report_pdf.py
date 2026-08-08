"""The PDF has to carry Korean, or it is worse than no PDF at all."""

from __future__ import annotations

import pytest

from common.contracts import UserRequest
from core.request_pipeline.pipeline import run_pipeline
from reporting.export.report_pdf import build_report_pdf, pdf_font_available


@pytest.mark.skipif(not pdf_font_available(), reason="no Hangul-capable font on this host")
def test_the_report_exports_with_korean_text_intact():
    """An unregistered font renders every Hangul character as a black box,
    which looks like a broken export rather than a missing font."""
    pypdf = pytest.importorskip("pypdf")
    result = run_pipeline(
        UserRequest(request_id="pdf_export", question="유료방송 가입자 추이는?",
                    target_audience="practitioner"),
        dry_run=True, archive=False,
    )

    data = build_report_pdf(result, "유료방송 가입자 추이는?")

    assert data[:5] == b"%PDF-"
    import io

    text = pypdf.PdfReader(io.BytesIO(data)).pages[0].extract_text()
    assert "유료방송 가입자 추이는?" in text
    assert "이 리포트의 모든 수치와 주장은" in text
