import base64

import sectors.sk_hynix.adapter.analyzer as analyzer
import sectors.sk_hynix.adapter.collector as collector
import sectors.sk_hynix.adapter.processor as processor
import sectors.sk_hynix.adapter.validator as validator
from common.contracts import Attachment, DocumentAnalysis, UserRequest
from common.errors import PipelineStageError
from core.request_pipeline.pipeline import run_pipeline


def test_attachment_is_analyzed_beside_web_documents_and_can_continue_without_collector(monkeypatch):
    monkeypatch.setattr(
        collector,
        "collect",
        lambda plan: (_ for _ in ()).throw(
            PipelineStageError(stage="collector", reason="template_only: FIRECRAWL_API_KEY is not configured")
        ),
    )
    monkeypatch.setattr(processor, "process", lambda documents: documents)
    monkeypatch.setattr(validator, "validate", lambda documents: documents)

    def fake_analyze(documents, question):
        assert len(documents) == 1
        assert documents[0].doc_id.startswith("attachment:")
        assert "첨부의 핵심 사실" in question
        return [
            DocumentAnalysis(
                doc_id=documents[0].doc_id,
                summary="첨부 요약",
                key_points=["첨부 근거"],
                evidence=["첨부의 핵심 사실"],
                relevant_to_question=True,
            )
        ]

    monkeypatch.setattr(analyzer, "analyze", fake_analyze)
    attachment = Attachment(
        attachment_id="a-pipeline",
        filename="evidence.txt",
        content_type="text/plain",
        content_base64=base64.b64encode("첨부의 핵심 사실".encode()).decode(),
    )
    request = UserRequest(
        request_id="req_attachment_pipeline",
        question="이 자료를 분석해줘",
        requested_sector_id="sk_hynix",
        attachments=[attachment],
    )

    result = run_pipeline(request, dry_run=False)

    assert result.halted_at_stage is None
    assert result.attachment_extractions[0].status == "extracted"
    assert result.synthesis.source_count == 1
    assert result.generated_report.source_count == 1
