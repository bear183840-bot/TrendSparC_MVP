from __future__ import annotations

from common.contracts import UserRequest
from core.request_pipeline.pipeline import run_pipeline
from reporting.export.artifacts import artifact_path, ensure_artifact


def test_exports_use_request_id_directories_and_reuse_written_json(tmp_path):
    result = run_pipeline(
        UserRequest(request_id="req_export_1", question="테스트 질문"),
        dry_run=True, archive=False,
    )

    path = ensure_artifact("result_json", result, "테스트 질문", tmp_path)
    first = path.read_bytes()
    second_path = ensure_artifact("result_json", result, "다른 표시 제목", tmp_path)

    assert path == tmp_path / "result_json" / "req_export_1.json"
    assert second_path == path
    assert second_path.read_bytes() == first


def test_unsafe_request_id_cannot_escape_output_directory(tmp_path):
    try:
        artifact_path("result_json", "../escape", tmp_path)
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("unsafe request id was accepted")
