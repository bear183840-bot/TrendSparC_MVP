import json

from common.contracts import SourceDocument
from core.request_pipeline.pipeline import PipelineResult
from main import _save_source_documents


def test_save_source_documents_writes_markdown_and_index(tmp_path):
    result = PipelineResult(
        request_id="req_test",
        collected_source_documents=[
            SourceDocument(
                doc_id="doc1",
                source_id="공식/출처",
                title="테스트 원문",
                url="https://example.com/article",
                content="# 스크랩 본문\n\n원문 내용",
                reliability_tier="official",
            )
        ],
    )

    saved_dir = _save_source_documents(result, tmp_path)

    markdown_path = saved_dir / "01_공식_출처.md"
    assert markdown_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "https://example.com/article" in markdown
    assert "# 스크랩 본문" in markdown
    index = json.loads((saved_dir / "index.json").read_text(encoding="utf-8"))
    assert index[0]["file"] == markdown_path.name
    assert index[0]["doc_id"] == "doc1"


def test_pipeline_result_keeps_the_actual_question_in_full_json():
    result = PipelineResult(request_id="req_question", question="실제 사용자 질문")

    assert PipelineResult.model_validate_json(result.model_dump_json()).question == "실제 사용자 질문"
